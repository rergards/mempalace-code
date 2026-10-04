"""UAT regressions for model-cache recovery, install hints, and installer UX."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from mempalace_code import storage
from mempalace_code.cli_commands import model
from mempalace_code.storage import (
    CANONICAL_EMBED_MODEL_REVISION,
    DEFAULT_EMBED_MODEL,
    CanonicalModelCacheError,
    _FastEmbedder,
    canonical_fastembed_cache_owned,
    canonical_fastembed_cache_root,
    canonical_fastembed_cache_status,
    canonical_fastembed_provenance,
    quarantine_unowned_canonical_fastembed_cache,
)

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "models--qdrant--all-MiniLM-L6-v2-onnx"
ARTIFACTS = (
    "config.json",
    "model.onnx",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)


def _write_cache(root: Path, *, provenance: bool = True, metadata: bool = False) -> Path:
    """Write a structurally owned cache whose snapshot entries link into blobs/ like HF."""
    repository = root / REPOSITORY
    snapshot = repository / "snapshots" / CANONICAL_EMBED_MODEL_REVISION
    snapshot.mkdir(parents=True)
    blobs = repository / "blobs"
    blobs.mkdir()
    (repository / "refs").mkdir()
    (repository / "refs" / "main").write_text(CANONICAL_EMBED_MODEL_REVISION, encoding="utf-8")
    sizes = {}
    for name in ARTIFACTS:
        if name == "tokenizer_config.json":
            (snapshot / name).write_text(
                json.dumps({"max_length": 256, "model_max_length": 512}), encoding="utf-8"
            )
            continue
        blob = blobs / f"blob-{name}"
        blob.write_bytes(b"x" * 64)
        (snapshot / name).symlink_to(Path("..") / ".." / "blobs" / blob.name)
        sizes[f"snapshots/{CANONICAL_EMBED_MODEL_REVISION}/{name}"] = {"size": 64, "blob_id": "b"}
    if metadata:
        (repository / "files_metadata.json").write_text(json.dumps(sizes), encoding="utf-8")
    if provenance:
        (root / ".mempalace-model.json").write_text(
            json.dumps(canonical_fastembed_provenance()), encoding="utf-8"
        )
    return root


class _FakeTokenizer:
    def __init__(self):
        self.padding = {
            "length": 128,
            "direction": "right",
            "pad_id": 0,
            "pad_type_id": 0,
            "pad_token": "[PAD]",
            "pad_to_multiple_of": None,
        }

    def enable_padding(self, **kwargs):
        self.padding = kwargs


def _install_fake_fastembed(monkeypatch, calls, *, fail_local=False, fail_download=False):
    """Fake FastEmbed local loads and the pinned download that may fail.

    A download is recorded in *calls* as ``{"local_files_only": False}`` so call
    sequences read as load, download, load.
    """

    class FakeTextEmbedding:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            cache = Path(kwargs["cache_dir"])
            if fail_local and not (cache / "fresh-download").exists():
                raise RuntimeError("[ONNXRuntimeError] : 7 : INVALID_PROTOBUF")
            self.model = types.SimpleNamespace(tokenizer=_FakeTokenizer())

    def fake_download():
        calls.append({"local_files_only": False})
        cache = canonical_fastembed_cache_root()
        cache.mkdir(parents=True, exist_ok=True)
        if fail_download:
            (cache / "models--qdrant--all-MiniLM-L6-v2-onnx").mkdir(exist_ok=True)
            raise RuntimeError("Could not load model from any source")
        _write_cache(cache, provenance=False)
        (cache / "fresh-download").write_text("new", encoding="utf-8")

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding)
    )
    monkeypatch.setattr(storage, "_download_pinned_canonical_snapshot", fake_download)


def _go_online(monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)


def _siblings(root: Path) -> list[str]:
    return sorted(path.name for path in root.parent.iterdir() if path != root)


@pytest.fixture
def cache_root(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    return canonical_fastembed_cache_root()


# ── install-1: --force must never delete a working cache before a replacement exists ──


def test_force_while_offline_refuses_and_keeps_owned_cache(cache_root, monkeypatch):
    _write_cache(cache_root)
    calls: list = []
    _install_fake_fastembed(monkeypatch, calls)
    _go_online(monkeypatch)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    with pytest.raises(model.ModelFetchError) as excinfo:
        model.fetch_model(DEFAULT_EMBED_MODEL, force=True)

    message = str(excinfo.value)
    assert "Refusing to replace the cached embedding model" in message
    assert "is unchanged" in message
    assert "`env -u HF_HUB_OFFLINE mempalace-code fetch-model" in message
    assert "--force`" in message
    assert calls == []
    assert canonical_fastembed_cache_owned()
    assert _siblings(cache_root) == []


def test_force_download_failure_restores_the_previous_cache(cache_root, monkeypatch, capsys):
    _write_cache(cache_root)
    _go_online(monkeypatch)
    _install_fake_fastembed(monkeypatch, [], fail_download=True)

    with pytest.raises(model.ModelFetchError) as excinfo:
        model.fetch_model(DEFAULT_EMBED_MODEL, force=True)

    assert "The previous cache was restored" in str(excinfo.value)
    assert "Retry exactly: `mempalace-code fetch-model --model all-MiniLM-L6-v2 --force`" in str(
        excinfo.value
    )
    assert canonical_fastembed_cache_owned()
    assert _siblings(cache_root) == []
    assert "Removing cached model" not in capsys.readouterr().out


def test_force_replaces_cache_only_after_the_download_validates(cache_root, monkeypatch):
    _write_cache(cache_root)
    _go_online(monkeypatch)
    _install_fake_fastembed(monkeypatch, [])

    model.fetch_model(DEFAULT_EMBED_MODEL, force=True)

    assert canonical_fastembed_cache_owned()
    assert (cache_root / "fresh-download").exists()
    assert _siblings(cache_root) == []


def test_interrupted_force_download_puts_the_cache_back(cache_root, monkeypatch):
    _write_cache(cache_root)
    _go_online(monkeypatch)

    def interrupted(model_name, *, local_files_only):
        if not local_files_only:
            cache_root.mkdir(parents=True, exist_ok=True)
            raise KeyboardInterrupt
        return object()

    monkeypatch.setattr(model, "_load_model", interrupted)

    with pytest.raises(KeyboardInterrupt):
        model.fetch_model(DEFAULT_EMBED_MODEL, force=True)

    assert canonical_fastembed_cache_owned()
    assert _siblings(cache_root) == []


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def _orphan(cache_root: Path) -> Path:
    """Leave the working cache set aside as a killed ``fetch-model --force`` would."""
    orphan = cache_root.with_name(f".{cache_root.name}.replace-{_dead_pid()}-{'a' * 32}")
    _write_cache(orphan)
    return orphan


def test_search_error_names_a_cache_left_aside_by_a_killed_fetch(cache_root, monkeypatch):
    _orphan(cache_root)
    cache_root.mkdir()  # the killed download's empty skeleton

    with pytest.raises(CanonicalModelCacheError) as excinfo:
        _FastEmbedder(local_files_only=True)

    assert "left the previous cache set aside" in str(excinfo.value)
    assert "Run `mempalace-code fetch-model` to put it back" in str(excinfo.value)


def test_fetch_model_restores_a_cache_left_aside_by_a_killed_fetch_offline(
    cache_root, monkeypatch, capsys
):
    orphan = _orphan(cache_root)
    cache_root.mkdir()
    calls: list = []
    _install_fake_fastembed(monkeypatch, calls)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    model.fetch_model(DEFAULT_EMBED_MODEL)

    out = capsys.readouterr().out
    assert f"Restored the cache an interrupted fetch-model set aside: {orphan}" in out
    assert "is already available locally" in out
    assert canonical_fastembed_cache_owned()
    assert _siblings(cache_root) == []
    assert all(call.get("local_files_only") for call in calls)


def test_fetch_model_discards_a_redundant_orphan_and_keeps_a_live_one(cache_root, monkeypatch):
    _write_cache(cache_root)
    _orphan(cache_root)
    live = cache_root.with_name(f".{cache_root.name}.replace-{os.getpid()}-{'b' * 32}")
    _write_cache(live)
    _install_fake_fastembed(monkeypatch, [])
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    model.fetch_model(DEFAULT_EMBED_MODEL)

    assert _siblings(cache_root) == [live.name]


# ── install-5 / ops-9: corrupt caches name the model cache and are recoverable ──


def test_truncated_artifact_is_not_owned(cache_root):
    _write_cache(cache_root, metadata=True)
    assert canonical_fastembed_cache_owned()
    blob = cache_root / REPOSITORY / "blobs" / "blob-model.onnx"
    blob.write_bytes(b"x" * 10)

    status = canonical_fastembed_cache_status()

    assert status["owned"] is False
    assert (
        status["error"] == "runtime artifact size does not match its download metadata: model.onnx"
    )


def test_owned_cache_that_fails_to_load_is_a_model_cache_error(cache_root, monkeypatch):
    _write_cache(cache_root)
    _install_fake_fastembed(monkeypatch, [], fail_local=True)

    with pytest.raises(CanonicalModelCacheError) as excinfo:
        _FastEmbedder(local_files_only=True)

    message = str(excinfo.value)
    assert "model cache failed to load: [ONNXRuntimeError]" in message
    assert "Run `mempalace-code fetch-model` while online" in message
    assert "repair" not in message


def test_fetch_model_replaces_an_unloadable_owned_cache_instead_of_looping(
    cache_root, monkeypatch, capsys
):
    _write_cache(cache_root)
    _go_online(monkeypatch)
    calls: list = []
    _install_fake_fastembed(monkeypatch, calls, fail_local=True)

    model.fetch_model(DEFAULT_EMBED_MODEL)

    output = capsys.readouterr().out
    assert "Cached model is not usable (it failed to load: [ONNXRuntimeError]" in output
    assert (cache_root / "fresh-download").exists()
    assert canonical_fastembed_cache_owned()
    assert _siblings(cache_root) == []
    assert [call["local_files_only"] for call in calls] == [True, False, True]


def test_fetch_model_quarantines_a_truncated_cache_and_downloads(cache_root, monkeypatch, capsys):
    _write_cache(cache_root, metadata=True)
    (cache_root / REPOSITORY / "blobs" / "blob-model.onnx").write_bytes(b"x")
    _go_online(monkeypatch)
    _install_fake_fastembed(monkeypatch, [])

    model.fetch_model(DEFAULT_EMBED_MODEL)

    assert "Preserved partial cache at:" in capsys.readouterr().out
    assert canonical_fastembed_cache_owned()
    assert len(list(cache_root.parent.glob(f"{cache_root.name}.quarantine-*"))) == 1


# ── install-6: a dangling link inside the cache is a partial cache, not a hostile one ──


def test_dangling_in_cache_link_is_quarantined_as_partial(cache_root):
    _write_cache(cache_root)
    (cache_root / REPOSITORY / "blobs" / "blob-model.onnx").unlink()
    assert not canonical_fastembed_cache_owned()

    preserved = quarantine_unowned_canonical_fastembed_cache()

    assert preserved is not None
    assert not cache_root.exists()
    assert (preserved / REPOSITORY / "snapshots" / CANONICAL_EMBED_MODEL_REVISION).is_dir()


def test_link_escaping_the_cache_is_still_refused(cache_root, tmp_path):
    _write_cache(cache_root)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"secret")
    (cache_root / "escape.bin").symlink_to(outside)
    (cache_root / ".mempalace-model.json").unlink()

    with pytest.raises(RuntimeError, match="Refusing to quarantine hostile"):
        quarantine_unowned_canonical_fastembed_cache()
    assert cache_root.is_dir()


def test_force_with_dangling_link_downloads_without_claiming_removal(
    cache_root, monkeypatch, capsys
):
    _write_cache(cache_root)
    (cache_root / REPOSITORY / "blobs" / "blob-model.onnx").unlink()
    _go_online(monkeypatch)
    _install_fake_fastembed(monkeypatch, [])

    model.fetch_model(DEFAULT_EMBED_MODEL, force=True)

    output = capsys.readouterr().out
    assert "Removing cached model" not in output
    assert "Preserved partial cache at:" in output
    assert canonical_fastembed_cache_owned()


# ── install-7 / ops-22: offline attempts never move caches or leave empty directories ──


def test_offline_fetch_leaves_a_provenance_less_cache_in_place(cache_root, monkeypatch):
    _write_cache(cache_root, provenance=False)
    calls: list = []
    _install_fake_fastembed(monkeypatch, calls)
    _go_online(monkeypatch)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    with pytest.raises(model.ModelFetchError) as excinfo:
        model.fetch_model(DEFAULT_EMBED_MODEL)

    message = str(excinfo.value)
    assert "is not usable (cache provenance is missing" in message
    assert "it was left unchanged" in message
    assert "Offline mode is on (HF_HUB_OFFLINE)" in message
    assert calls == []
    assert (cache_root / REPOSITORY / "blobs" / "blob-model.onnx").exists()
    assert _siblings(cache_root) == []


def test_repeated_offline_fetch_without_cache_leaves_nothing_behind(cache_root, monkeypatch):
    _install_fake_fastembed(monkeypatch, [])
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    for _ in range(3):
        with pytest.raises(model.ModelFetchError) as excinfo:
            model.fetch_model(DEFAULT_EMBED_MODEL)
        assert "The embedding model is not cached at" in str(excinfo.value)
        assert "`env -u HF_HUB_OFFLINE -u TRANSFORMERS_OFFLINE mempalace-code fetch-model" in str(
            excinfo.value
        )

    assert not cache_root.parent.exists() or list(cache_root.parent.iterdir()) == []


def test_failed_download_removes_its_empty_skeleton(cache_root, monkeypatch):
    _go_online(monkeypatch)
    _install_fake_fastembed(monkeypatch, [], fail_download=True)

    for _ in range(2):
        with pytest.raises(model.ModelFetchError, match="Retry exactly"):
            model.fetch_model(DEFAULT_EMBED_MODEL)

    assert not cache_root.exists()
    assert list(cache_root.parent.iterdir()) == []


def test_empty_cache_root_is_removed_not_quarantined(cache_root):
    (cache_root / REPOSITORY / "refs").mkdir(parents=True)

    assert quarantine_unowned_canonical_fastembed_cache() is None
    assert not cache_root.exists()
    assert list(cache_root.parent.iterdir()) == []


# ── install-8: captured output stays ordered and FastEmbed log noise is silenced ──


def _fake_fastembed_package(packages: Path) -> None:
    package = packages / "fastembed"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        textwrap.dedent(
            """\
            from loguru import logger

            class TextEmbedding:
                def __init__(self, **kwargs):
                    logger.error("fastembed download noise")
                    raise RuntimeError("Could not load model from any source")
            """
        ),
        encoding="utf-8",
    )


def test_captured_fetch_output_is_ordered_and_quiet(tmp_path):
    pytest.importorskip("loguru")
    packages = tmp_path / "packages"
    _fake_fastembed_package(packages)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"}
    }
    env.update(
        PYTHONPATH=os.pathsep.join([str(packages), str(ROOT)]),
        HF_HOME=str(tmp_path / "hf"),
        MEMPALACE_VERSION_CHECK="0",
    )

    completed = subprocess.run(
        [sys.executable, "-m", "mempalace_code.cli", "fetch-model"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        timeout=60,
    )

    assert completed.returncode == 1
    output = completed.stdout
    assert "fastembed download noise" not in output
    assert output.index("Waiting for model download") < output.index("Error preparing model")
    assert output.rstrip().endswith(
        "Retry exactly: `mempalace-code fetch-model --model all-MiniLM-L6-v2`"
    )


# ── install-18 / hint-1: extra hints change a pipx venv only through pipx ──


def _fake_pipx_venv(tmp_path: Path, monkeypatch) -> Path:
    from mempalace_code import storage

    venv = tmp_path / "pipx home" / "venvs" / "mempalace-code"
    (venv / "bin").mkdir(parents=True)
    (venv / "pipx_metadata.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setattr(sys, "executable", str(venv / "bin" / "python"))
    monkeypatch.setattr(storage, "find_spec", lambda name: None)
    requirements = {
        "watch": ["watchfiles>=1.0"],
        "custom-models": ["sentence-transformers>=5.6.0"],
    }
    monkeypatch.setattr(storage, "_extra_requirements", lambda extra: requirements[extra])
    return venv


def test_pipx_venv_gets_pipx_inject_for_its_own_home(tmp_path, monkeypatch):
    from mempalace_code.storage import extra_install_command, preflight_embed_model

    venv = _fake_pipx_venv(tmp_path, monkeypatch)
    home = venv.parent.parent
    monkeypatch.delenv("PIPX_HOME", raising=False)

    assert extra_install_command("watch") == (
        f"PIPX_HOME='{home}' pipx inject mempalace-code 'watchfiles>=1.0'"
    )

    monkeypatch.setenv("PIPX_HOME", str(home))
    assert extra_install_command("custom-models") == (
        "pipx inject mempalace-code 'sentence-transformers>=5.6.0'"
    )

    original_import = __import__("importlib").import_module

    def missing_sentence_transformers(name, package=None):
        if name == "sentence_transformers":
            raise ImportError("not installed")
        return original_import(name, package)

    monkeypatch.setattr(
        "mempalace_code.storage.importlib.import_module", missing_sentence_transformers
    )
    with pytest.raises(RuntimeError) as excinfo:
        preflight_embed_model("all-mpnet-base-v2")
    assert "pipx inject mempalace-code 'sentence-transformers>=5.6.0'" in str(excinfo.value)
    assert "uv pip" not in str(excinfo.value)


def test_extra_requirements_come_from_installed_metadata():
    from mempalace_code.storage import _extra_requirements

    assert _extra_requirements("watch") == ["watchfiles>=1.0"]
    assert _extra_requirements("custom-models") == ["sentence-transformers>=5.6.0"]
    assert _extra_requirements("no-such-extra") == []


# ── ops-26: custom-model output reports the real footprint and no premature progress ──


def _block_sentence_transformers(monkeypatch):
    original_import = __import__("importlib").import_module

    def guarded(name, package=None):
        if name == "sentence_transformers":
            raise ImportError("not installed")
        return original_import(name, package)

    monkeypatch.setattr("mempalace_code.storage.importlib.import_module", guarded)
    monkeypatch.setattr("mempalace_code.cli_commands.model.importlib.import_module", guarded)


def test_custom_model_refusal_prints_no_download_progress(monkeypatch, capsys):
    _block_sentence_transformers(monkeypatch)

    with pytest.raises(RuntimeError, match="Custom embedding model support is not installed"):
        model.fetch_model("all-mpnet-base-v2")

    assert "Downloading" not in capsys.readouterr().out


def test_custom_model_force_refusal_does_not_claim_removal(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    cache = tmp_path / "hf" / "hub" / "models--sentence-transformers--all-mpnet-base-v2"
    cache.mkdir(parents=True)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=lambda *args, **kwargs: object()),
    )

    with pytest.raises(model.ModelFetchError, match="Refusing to delete a custom-model cache"):
        model.fetch_model("all-mpnet-base-v2", force=True)

    assert "Removing cached model" not in capsys.readouterr().out
    assert cache.is_dir()


def test_custom_model_size_counts_weights_in_the_shared_blob_store(tmp_path, monkeypatch, capsys):
    hub = tmp_path / "hf" / "hub"
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    model_dir = hub / "models--sentence-transformers--paraphrase-MiniLM-L3-v2"
    snapshot = model_dir / "snapshots" / "rev"
    snapshot.mkdir(parents=True)
    (model_dir / "blobs").mkdir()
    (model_dir / "blobs" / "config").write_bytes(b"c" * 1024)
    (snapshot / "config.json").symlink_to(model_dir / "blobs" / "config")
    shared = hub / "blobs" / "b2" / "weights"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(b"w" * (3 * 1024 * 1024))
    (snapshot / "model.safetensors").symlink_to(shared)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=lambda *args, **kwargs: object()),
    )

    model.fetch_model("sentence-transformers/paraphrase-MiniLM-L3-v2")

    output = capsys.readouterr().out
    assert "already available locally" in output
    assert "Size on disk: 3.0 MB" in output
    assert (
        f"Includes 3.0 MB in the shared Hugging Face blob store; to move this model, copy all of {hub}."
        in output
    )


# ── ops-10: a palace records its embedding model; CLI/MCP honour it or refuse clearly ──


class _NamedEmbedder:
    """Deterministic embedder whose vectors identify the model that produced them."""

    def __init__(self, name: str, dim: int):
        self.name = name
        self.dim = dim

    def ndims(self) -> int:
        return self.dim

    def compute_source_embeddings(self, texts):
        vector = [0.0] * self.dim
        vector[sum(map(ord, self.name)) % self.dim] = 1.0
        return [list(vector) for _ in texts]


def _install_model_embedders(monkeypatch, dims: dict[str, int], loaded: list[str]):
    from mempalace_code.storage import LanceStore, is_canonical_embed_model

    def get_embedder(store):
        name = store._model_name
        loaded.append(name)
        if is_canonical_embed_model(name):
            return _NamedEmbedder("minilm", 384)
        if name not in dims:
            raise RuntimeError(
                "Custom embedding model support is not installed. Run exactly: "
                "pipx inject mempalace-code 'sentence-transformers>=5.6.0'"
            )
        return _NamedEmbedder(name, dims[name])

    monkeypatch.setattr(LanceStore, "_get_embedder", get_embedder)
    monkeypatch.setattr("mempalace_code.storage.preflight_embed_model", lambda name: None)


def _vector_record(palace: Path) -> bytes | None:
    import lancedb

    table = lancedb.connect(str(palace / "lance")).open_table("mempalace_drawers")
    return (table.schema.field("vector").metadata or {}).get(b"mempalace.embed_model")


def test_new_palace_records_its_model_and_reopens_with_it(tmp_path, monkeypatch):
    from mempalace_code.storage import CANONICAL_EMBED_MODEL, LanceStore, open_store

    loaded: list[str] = []
    _install_model_embedders(monkeypatch, {"org/custom-384": 384}, loaded)
    default_palace = tmp_path / "default"
    LanceStore(str(default_palace))
    assert _vector_record(default_palace) == CANONICAL_EMBED_MODEL.encode()

    palace = tmp_path / "custom"
    LanceStore(str(palace), embed_model="org/custom-384").add(
        ["d1"], ["invoice database decision"], [{"wing": "w", "room": "r"}]
    )
    assert _vector_record(palace) == b"org/custom-384"

    loaded.clear()
    reopened = open_store(str(palace), create=False)
    result = reopened.query(query_texts=["invoice"], n_results=1)

    assert reopened.embed_model == "org/custom-384"
    assert loaded == ["org/custom-384"]
    assert result["ids"][0] == ["d1"]


def test_opening_a_palace_with_another_model_is_refused(tmp_path, monkeypatch):
    from mempalace_code.storage import LanceStore, PalaceEmbeddingModelError

    _install_model_embedders(monkeypatch, {"org/custom-384": 384, "org/other": 384}, [])
    palace = tmp_path / "custom"
    LanceStore(str(palace), embed_model="org/custom-384")

    with pytest.raises(PalaceEmbeddingModelError) as excinfo:
        LanceStore(str(palace), embed_model="org/other")
    assert "was built with embedding model 'org/custom-384'" in str(excinfo.value)
    assert "embed_model='org/custom-384'" in str(excinfo.value)
    with pytest.raises(PalaceEmbeddingModelError):
        LanceStore(str(palace), embed_model=DEFAULT_EMBED_MODEL)


def _legacy_palace(palace: Path, dim: int) -> None:
    """Create a drawers table the way releases before model recording did."""
    import lancedb

    from mempalace_code.storage import _META_DEFAULTS, _target_drawer_schema

    table = lancedb.connect(str(palace / "lance")).create_table(
        "mempalace_drawers", schema=_target_drawer_schema(dim)
    )
    row = dict(_META_DEFAULTS)
    row.update(id="d1", text="PostgreSQL for invoices", vector=[1.0] + [0.0] * (dim - 1))
    table.add([row])


def test_unrecorded_palace_with_other_dimensions_fails_clearly(tmp_path, monkeypatch):
    from mempalace_code.storage import PalaceEmbeddingModelError, open_store

    _install_model_embedders(monkeypatch, {}, [])
    palace = tmp_path / "legacy768"
    _legacy_palace(palace, 768)
    store = open_store(str(palace), create=False)

    with pytest.raises(PalaceEmbeddingModelError) as excinfo:
        store.query(query_texts=["database"], n_results=1)
    message = str(excinfo.value)
    assert "stores 768-dimensional vectors" in message
    assert "produces 384" in message
    assert ".record_embed_model()" in message
    with pytest.raises(PalaceEmbeddingModelError):
        store.add(["d2"], ["more"], [{"wing": "w", "room": "r"}])
    assert store.count() == 1


def test_record_embed_model_upgrades_an_unrecorded_custom_palace(tmp_path, monkeypatch):
    from mempalace_code.storage import LanceStore, PalaceEmbeddingModelError, open_store

    loaded: list[str] = []
    _install_model_embedders(monkeypatch, {"org/custom-768": 768, "org/wrong-512": 512}, loaded)
    palace = tmp_path / "legacy768"
    _legacy_palace(palace, 768)

    with pytest.raises(PalaceEmbeddingModelError, match="produces 512"):
        LanceStore(str(palace), embed_model="org/wrong-512").record_embed_model()
    assert _vector_record(palace) is None

    assert LanceStore(str(palace), embed_model="org/custom-768").record_embed_model() == (
        "org/custom-768"
    )
    assert _vector_record(palace) == b"org/custom-768"

    loaded.clear()
    store = open_store(str(palace), create=False)
    assert store.query(query_texts=["database"], n_results=1)["ids"][0] == ["d1"]
    assert loaded == ["org/custom-768"]


def test_cli_search_of_a_custom_palace_without_the_extra_names_the_model(
    tmp_path, monkeypatch, capsys
):
    from mempalace_code.cli import main
    from mempalace_code.storage import LanceStore

    _install_model_embedders(monkeypatch, {"org/custom-384": 384}, [])
    palace = tmp_path / "custom"
    LanceStore(str(palace), embed_model="org/custom-384").add(
        ["d1"], ["invoice database decision"], [{"wing": "w", "room": "r"}]
    )
    _install_model_embedders(monkeypatch, {}, [])
    monkeypatch.setenv("MEMPALACE_VERSION_CHECK", "0")
    monkeypatch.setattr(sys, "argv", ["mempalace-code", "--palace", str(palace), "search", "db"])

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    stderr = capsys.readouterr().err
    assert "records embedding model 'org/custom-384', which could not be loaded" in stderr
    assert "pipx inject mempalace-code 'sentence-transformers>=5.6.0'" in stderr
    assert "repair" not in stderr


from mempalace_code.storage import LanceStore as _LanceStore  # noqa: E402

# Captured at import, before the autouse fixture replaces it with the test embedder.
_REAL_GET_EMBEDDER = _LanceStore._get_embedder


class _FakeVectors(list):
    def tolist(self):
        return list(self)


def _install_logging_sentence_transformer(monkeypatch, calls, *, cached: set[str]):
    """A sentence_transformers stand-in that logs kwargs and knows which models are cached."""

    class FakeSentenceTransformer:
        def __init__(self, model_name, **kwargs):
            calls.append((model_name, kwargs))
            if kwargs.get("local_files_only") and model_name not in cached:
                raise OSError(f"{model_name} is not in the local cache")

        def encode(self, texts, **kwargs):
            return _FakeVectors([[1.0] + [0.0] * 383 for _ in texts])

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    monkeypatch.setattr(_LanceStore, "_get_embedder", _REAL_GET_EMBEDDER)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)


def test_explicit_custom_model_keeps_remote_code_and_online_fallback(tmp_path, monkeypatch):
    from mempalace_code.storage import LanceStore

    calls: list = []
    _install_logging_sentence_transformer(monkeypatch, calls, cached=set())
    LanceStore(str(tmp_path / "p"), embed_model="someorg/remote-code-model")

    assert calls == [
        (
            "someorg/remote-code-model",
            {"local_files_only": True, "device": "cpu", "trust_remote_code": True},
        ),
        ("someorg/remote-code-model", {"device": "cpu", "trust_remote_code": True}),
    ]


def test_recorded_model_loads_locally_without_remote_code(tmp_path, monkeypatch):
    from mempalace_code.storage import open_store

    calls: list = []
    model_id = "someorg/remote-code-model"
    _install_logging_sentence_transformer(monkeypatch, calls, cached={model_id})
    palace = str(tmp_path / "p")
    open_store(palace, create=True, embed_model=model_id).add(
        ["d1"], ["invoice database"], [{"wing": "w", "room": "r"}]
    )

    calls.clear()
    store = open_store(palace, create=False)
    assert store.query(query_texts=["invoice"], n_results=1)["ids"][0] == ["d1"]
    assert calls == [
        (model_id, {"local_files_only": True, "device": "cpu", "trust_remote_code": False})
    ]


def test_uncached_recorded_model_is_never_downloaded(tmp_path, monkeypatch, capsys):
    from mempalace_code.cli import main
    from mempalace_code.storage import open_store

    calls: list = []
    model_id = "someorg/remote-code-model"
    _install_logging_sentence_transformer(monkeypatch, calls, cached={model_id})
    palace = str(tmp_path / "p")
    open_store(palace, create=True, embed_model=model_id).add(
        ["d1"], ["invoice database"], [{"wing": "w", "room": "r"}]
    )

    _install_logging_sentence_transformer(monkeypatch, calls, cached=set())
    calls.clear()
    monkeypatch.setenv("MEMPALACE_VERSION_CHECK", "0")
    monkeypatch.setattr(sys, "argv", ["mempalace-code", "--palace", palace, "search", "db"])
    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert calls == [
        (model_id, {"local_files_only": True, "device": "cpu", "trust_remote_code": False})
    ]
    stderr = capsys.readouterr().err
    assert f"records embedding model '{model_id}'" in stderr
    assert f"mempalace-code fetch-model --model {model_id}" in stderr
    assert "never downloaded" in stderr
    assert "Traceback" not in stderr


# ── install-13 / ops-27: onboarding states what it saves and promises nothing more ──


def test_onboarding_output_and_notes_match_what_is_saved(tmp_path, monkeypatch, capsys):
    from mempalace_code.onboarding import run_onboarding

    project = tmp_path / "notes"
    project.mkdir()
    (project / "n.md").write_text("n\n", encoding="utf-8")
    config_dir = tmp_path / "config"
    answers = iter(["1", "Alice, tech lead", "Bob, SRE", "done", "Apollo", "done", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    registry = run_onboarding(directory=str(project), config_dir=config_dir)

    assert registry is not None
    output = capsys.readouterr().out
    summary = output[output.index("Setup Complete") :]
    assert "  Mode: work\n  People: 2 (Alice, Bob)\n  Projects: Apollo\n" in summary
    assert "Wiki cache" not in summary
    assert "know your world" not in summary
    assert f"AAAK entity codes: {config_dir / 'aaak_entities.md'}" in summary
    assert "the wings above are notes only" in summary
    assert sorted(path.name for path in project.iterdir()) == ["n.md"]
    facts = (config_dir / "critical_facts.md").read_text(encoding="utf-8")
    codes = (config_dir / "aaak_entities.md").read_text(encoding="utf-8")
    assert "palace_facts" not in facts
    assert "does not read or update this file automatically" in facts
    assert "mempalace-code init" not in codes
    assert "Generated by mempalace-code onboarding" in codes


def test_registry_summary_shows_wiki_cache_only_for_legacy_entries(tmp_path):
    from mempalace_code.entity_registry import EntityRegistry

    registry = EntityRegistry.load(tmp_path)
    assert "Wiki cache" not in registry.summary()
    registry._data["wiki_cache"] = {"Sam": {"inferred_type": "person"}}
    assert registry.summary().splitlines()[-1] == "Wiki cache: 1 entries"


# ── install-23 / install-15: alias targets must exist; the alias script never acts bare ──


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_install_alias_refuses_a_missing_target_dir(tmp_path, monkeypatch, capsys):
    from mempalace_code.cli_commands.alias import cmd_install_alias

    canonical = _executable(tmp_path / "bin" / "mempalace-code")
    monkeypatch.setenv("PATH", str(canonical.parent))
    missing = tmp_path / "nope" / "dir"

    with pytest.raises(SystemExit) as excinfo:
        cmd_install_alias(types.SimpleNamespace(target_dir=str(missing)))

    assert excinfo.value.code == 1
    assert f"target directory does not exist: {missing}" in capsys.readouterr().err
    assert not (tmp_path / "nope").exists()


def test_install_alias_reports_the_real_link_target_and_path_note(tmp_path, monkeypatch, capsys):
    from mempalace_code.cli_commands.alias import cmd_install_alias

    canonical = _executable(tmp_path / "bin" / "mempalace-code")
    target = tmp_path / "elsewhere"
    target.mkdir()
    monkeypatch.setenv("PATH", str(canonical.parent))

    cmd_install_alias(types.SimpleNamespace(target_dir=str(target)))

    out = capsys.readouterr().out
    assert out.splitlines() == [
        f"  Alias ready: {target / 'mempalace'} -> {os.readlink(target / 'mempalace')}",
        f"  Note: {target} is not on PATH; add it to PATH to run `mempalace` by name.",
    ]
    assert Path(os.readlink(target / "mempalace")).name == "mempalace-code"
    assert os.path.isabs(os.readlink(target / "mempalace"))


def test_bare_alias_console_script_prints_help_without_creating_files(
    tmp_path, monkeypatch, capsys
):
    from mempalace_code.cli_commands.alias import main_alias

    installer = _executable(tmp_path / "bin" / "mempalace-code-alias")
    _executable(tmp_path / "bin" / "mempalace-code")
    monkeypatch.setenv("PATH", str(installer.parent))
    monkeypatch.setattr(sys, "argv", [str(installer)])

    with pytest.raises(SystemExit) as excinfo:
        main_alias()

    assert excinfo.value.code == 2
    assert "same as `mempalace-code install-alias`" in " ".join(capsys.readouterr().out.split())
    assert not (installer.parent / "mempalace").exists()

    monkeypatch.setattr(sys, "argv", [str(installer), "--yes"])
    main_alias()
    assert (installer.parent / "mempalace").is_symlink()
    assert "Alias ready:" in capsys.readouterr().out


# ── install-24: bootstrap checks collisions first, recognizes its alias, and upgrades ──


def _bootstrap(tmp_path: Path, venv: Path, *, extra_path: str = "") -> subprocess.CompletedProcess:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    host_bin = tmp_path / "host-bin"
    if not host_bin.exists():
        host_bin.mkdir()
        (host_bin / "python3").symlink_to(sys.executable)
    path = os.pathsep.join(filter(None, [str(host_bin), extra_path, os.environ["PATH"]]))
    env = {**os.environ, "HOME": str(home), "MEMPALACE_VENV": str(venv), "PATH": path}
    return subprocess.run(
        ["/bin/bash", str(ROOT / "scripts" / "bootstrap.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _logging_fake_venv(tmp_path: Path) -> tuple[Path, Path]:
    """A reusable venv whose python stub logs every pip call instead of installing."""
    venv = tmp_path / "venv"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    log = tmp_path / "pip.log"
    prefix = os.path.realpath(venv)
    stubs = {
        "python": (
            f"#!/bin/sh\n[ \"$1\" = -c ] && printf '%s\\n' '{prefix}' && exit 0\n"
            f"printf '%s\\n' \"$*\" >> '{log}'\nexit 0\n"
        ),
        "mempalace-code": "#!/bin/sh\necho 'mempalace-code 0.0.0'\n",
        "mempalace-code-mcp": "#!/bin/sh\nexit 0\n",
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    return venv, log


def test_bootstrap_refuses_launcher_collision_before_creating_a_venv(tmp_path):
    local_bin = tmp_path / "home" / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "mempalace-code").symlink_to(tmp_path / "other-venv" / "bin" / "mempalace-code")
    venv = tmp_path / "venvs" / "bootcustom"

    result = _bootstrap(tmp_path, venv)

    assert result.returncode != 0
    assert f"Refusing to replace existing launcher {local_bin / 'mempalace-code'}" in result.stdout
    assert "Creating venv" not in result.stdout
    assert not venv.exists()


def test_bootstrap_rerun_recognizes_its_alias_and_upgrades(tmp_path):
    venv, log = _logging_fake_venv(tmp_path)
    local_bin = tmp_path / "home" / ".local" / "bin"

    first = _bootstrap(tmp_path, venv, extra_path=str(local_bin))
    second = _bootstrap(tmp_path, venv, extra_path=str(local_bin))

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    assert os.readlink(local_bin / "mempalace") == str(local_bin / "mempalace-code")
    assert f"Symlink already correct: {local_bin / 'mempalace'}" in second.stdout
    assert "Leaving existing" not in second.stdout
    installs = [
        line for line in log.read_text(encoding="utf-8").splitlines() if "mempalace" in line
    ]
    assert installs == ["-m pip install --upgrade mempalace-code --quiet"] * 2


# ── install-14: entity detection never samples its own output; its threshold is documented ──


def test_entity_scan_skips_files_init_generates(tmp_path):
    from mempalace_code.entity_detector import scan_for_detection

    (tmp_path / "meeting.md").write_text("Alice said hello.\n", encoding="utf-8")
    (tmp_path / "entities.json").write_text('{"people": ["Alice"]}', encoding="utf-8")
    (tmp_path / "mempalace.yaml").write_text("wing: notes\n", encoding="utf-8")

    assert [path.name for path in scan_for_detection(str(tmp_path))] == ["meeting.md"]


def test_entity_threshold_is_the_documented_one():
    from mempalace_code.entity_detector import MIN_CANDIDATE_MENTIONS, extract_candidates

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert MIN_CANDIDATE_MENTIONS == 3
    assert "appear at least 3 times" in " ".join(readme.split())
    assert extract_candidates("Alice met Alice.") == {}
    assert extract_candidates("Alice met Alice. Alice left.") == {"Alice": 3}


# ── install-11 / install-17 / install-26: install docs wire MCP to the palace the CLI uses ──


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end, text.index(start))]


def test_agent_install_persists_a_custom_palace_before_mcp_wiring():
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    step_4a = _section(runbook, "### Step 4a", "### Step 4b")
    section_5 = _section(runbook, "## Section 5", "### Step 5.0")

    assert "To make it permanent" not in step_4a
    assert "**Required for a custom path:**" in step_4a
    assert "do not wire\nMCP (Section 5) until this block succeeds" in step_4a
    assert "Clients start it without your shell's environment" in section_5
    assert "`mempalace_status`" in section_5


def test_troubleshooting_reinstalls_keep_extras_and_use_the_owning_interpreter():
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    stale = _section(runbook, "### Stale installed metadata", "## Validation Log")

    assert 'python3 -c "import mempalace_code' not in stale
    assert '"$MEMPALACE_PYTHON" -c "import mempalace_code' in stale
    assert "installation.extras" in stale
    for line in stale.splitlines():
        if line.startswith(("uv tool install", '"$MEMPALACE_PYTHON" -m pip install')):
            assert "mempalace-code[" in line, line


def test_readme_json_mcp_snippet_uses_the_launcher_profile_and_palace_env():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = _section(readme, "### Supported MCP Clients", "## How It Actually Works")
    block = section[
        section.index("```json") + len("```json") : section.index(
            "```\n", section.index("```json") + 7
        )
    ]
    server = json.loads(block)["mcpServers"]["mempalace-code"]

    assert server["command"].startswith("/")
    assert server["command"].endswith("mempalace-code-mcp")
    assert server["args"] == ["--profile=minimal"]
    assert server["env"]["MEMPALACE_PALACE_PATH"].startswith("/")
    assert "add as MCP server in settings" not in section


def test_gemini_guide_matches_the_install_runbook():
    guide = (ROOT / "examples" / "gemini_cli_setup.md").read_text(encoding="utf-8")
    block = guide[
        guide.index("```json") + len("```json") : guide.index("```\n", guide.index("```json") + 7)
    ]
    server = json.loads(block)["mcpServers"]["mempalace-code"]

    assert server["command"].endswith("/bin/mempalace-code-mcp")
    assert server["args"] == ["--profile=minimal"]
    assert "mempalace_code.mcp_server" not in guide
    assert '"$MPALACE" init ~/projects/my-project --skip-model-download' in guide
    assert '"$MPALACE" fetch-model' in guide


def test_first_mine_without_the_model_leaves_no_lance_directory(tmp_path, monkeypatch):
    """install-9: a failed first mine must not leave a bookkeeping-only lance/ behind."""
    import yaml

    from mempalace_code.mining.orchestrator import mine
    from mempalace_code.storage import LanceStore

    def missing_model(store):
        raise CanonicalModelCacheError("model missing; run mempalace-code fetch-model")

    monkeypatch.setattr(LanceStore, "_get_embedder", missing_model)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (project / "mempalace.yaml").write_text(
        yaml.safe_dump({"wing": "proj", "rooms": [{"name": "general", "description": "All"}]}),
        encoding="utf-8",
    )
    palace = tmp_path / "palace"

    with pytest.raises(CanonicalModelCacheError):
        mine(str(project), str(palace), skip_optimize=True)

    assert not (palace / "lance").exists()


def _run_cli(monkeypatch, capsys, *argv: str) -> tuple[int, str, str]:
    from mempalace_code.cli import main

    monkeypatch.setenv("MEMPALACE_VERSION_CHECK", "0")
    monkeypatch.setattr(sys, "argv", ["mempalace-code", *argv])
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _stored_vectors(palace: Path) -> dict[str, list[float]]:
    from mempalace_code.storage import open_store

    store = open_store(str(palace), create=False, read_only=True)
    return {
        row["id"]: list(row["vector"])
        for batch in store.iter_all(include_vectors=True)
        for row in batch
    }


def test_repair_keeps_a_custom_palace_model_and_its_vectors(tmp_path, monkeypatch, capsys):
    from mempalace_code.storage import LanceStore, open_store

    loaded: list[str] = []
    _install_model_embedders(monkeypatch, {"org/custom-768": 768}, loaded)
    palace = tmp_path / "custom"
    LanceStore(str(palace), embed_model="org/custom-768").add(
        ["d1", "d2"], ["invoice database decision", "refund flow"], [{"wing": "w", "room": "r"}] * 2
    )
    before = _stored_vectors(palace)
    loaded.clear()

    code, out, err = _run_cli(monkeypatch, capsys, "--palace", str(palace), "repair")

    assert code == 0, out + err
    assert _vector_record(palace) == b"org/custom-768"
    assert loaded == []  # stored vectors are reused; no model is loaded
    store = open_store(str(palace), create=False)
    assert store.embed_model == "org/custom-768"
    assert _stored_vectors(palace) == before


def test_rebuild_embeds_rows_without_vectors_with_the_palace_model(tmp_path, monkeypatch):
    import lancedb

    from mempalace_code.storage import LanceStore, open_store

    loaded: list[str] = []
    _install_model_embedders(monkeypatch, {"org/custom-768": 768}, loaded)
    palace = tmp_path / "custom"
    LanceStore(str(palace), embed_model="org/custom-768").add(
        ["d1"], ["invoice database decision"], [{"wing": "w", "room": "r"}]
    )
    store = open_store(str(palace), create=False)
    rows = store.read_all_for_rebuild()["rows"]
    rows[0]["vector"] = None
    loaded.clear()

    staging = tmp_path / "staging"
    assert store.write_rebuilt_table(str(staging), rows) == 1

    assert loaded == ["org/custom-768"]
    assert _vector_record(staging) == b"org/custom-768"
    rebuilt = lancedb.connect(str(staging / "lance")).open_table("mempalace_drawers")
    [row] = rebuilt.to_arrow().to_pylist()
    assert (
        row["vector"] == _NamedEmbedder("org/custom-768", 768).compute_source_embeddings(["x"])[0]
    )


def test_rebuild_of_an_unrecorded_palace_does_not_invent_a_model_record(tmp_path, monkeypatch):
    from mempalace_code.storage import open_store

    _install_model_embedders(monkeypatch, {}, [])
    palace = tmp_path / "legacy"
    _legacy_palace(palace, 384)
    store = open_store(str(palace), create=False)
    staging = tmp_path / "staging"

    assert store.write_rebuilt_table(str(staging), store.read_all_for_rebuild()["rows"]) == 1
    assert _vector_record(staging) is None


def test_health_reports_the_palace_model_and_flags_a_dimension_mismatch(
    tmp_path, monkeypatch, capsys
):
    from mempalace_code.storage import LanceStore

    _install_model_embedders(monkeypatch, {"org/custom-768": 768}, [])
    custom = tmp_path / "custom"
    LanceStore(str(custom), embed_model="org/custom-768").add(
        ["d1"], ["invoice database decision"], [{"wing": "w", "room": "r"}]
    )
    code, out, err = _run_cli(monkeypatch, capsys, "--palace", str(custom), "health", "--json")
    report = json.loads(out)
    assert code == 0, err
    assert report["embedding"] == {
        "model": "org/custom-768",
        "recorded": True,
        "vector_dim": 768,
        "model_dim": None,  # unknown without loading the model: never flagged
        "dimension_mismatch": False,
    }

    legacy = tmp_path / "legacy768"
    _legacy_palace(legacy, 768)
    code, out, err = _run_cli(monkeypatch, capsys, "--palace", str(legacy), "health", "--json")
    report = json.loads(out)
    assert code == 1
    assert report["ok"] is False
    assert report["embedding"]["recorded"] is False
    assert report["embedding"]["vector_dim"] == 768
    assert report["embedding"]["model_dim"] == 384
    [error] = report["errors"]
    assert error["kind"] == "embedding_mismatch"
    assert ".record_embed_model()" in error["message"]
    assert "rollback" not in report["next"]

    code, out, err = _run_cli(monkeypatch, capsys, "--palace", str(legacy), "health")
    assert code == 1
    assert "Status: DEGRADED" in out
    assert "vector dimension: 768" in out
