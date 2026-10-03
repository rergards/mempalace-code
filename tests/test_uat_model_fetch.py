"""UAT round-2 regressions: the canonical model download is pinned and never piles up copies."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from mempalace_code import storage
from mempalace_code.cli_commands import model
from mempalace_code.storage import (
    CANONICAL_EMBED_MODEL_REVISION,
    DEFAULT_EMBED_MODEL,
    canonical_fastembed_cache_owned,
    canonical_fastembed_cache_root,
    canonical_fastembed_provenance,
)

REPOSITORY = "models--qdrant--all-MiniLM-L6-v2-onnx"
UPSTREAM_HEAD = "8f518e882455312b086101e60691f5e6e2f05c3c"


def _content(name: str, revision: str) -> bytes:
    if name == "tokenizer_config.json":
        max_length = 256 if revision == UPSTREAM_HEAD else 128
        return json.dumps({"max_length": max_length, "model_max_length": 512}).encode()
    return f"{name} at {revision}".encode()


def _pin_fake_artifacts(monkeypatch) -> None:
    """Point the reviewed manifest at the fake pinned files the fake hub serves."""
    manifest = {}
    for name in storage._FASTEMBED_PINNED_ARTIFACTS:
        data = _content(name, CANONICAL_EMBED_MODEL_REVISION)
        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        sha256 = hashlib.sha256(data).hexdigest() if name == "model.onnx" else None
        manifest[name] = (len(data), blob, sha256)
    monkeypatch.setattr(storage, "_FASTEMBED_PINNED_ARTIFACTS", manifest)


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


def _install_fake_hub(monkeypatch, calls, *, missing_revision=False, corrupt=None):
    """Fake a hub whose ``main`` moved past the pinned revision, and a FastEmbed on top.

    Like the real FastEmbed, the fake downloads ``main`` when it may go online.
    """

    def snapshot_download(*, repo_id, revision=None, cache_dir, allow_patterns=None, **kwargs):
        calls.append({"revision": revision, "local_files_only": kwargs.get("local_files_only")})
        assert repo_id == "qdrant/all-MiniLM-L6-v2-onnx"
        repository = Path(cache_dir) / REPOSITORY
        if kwargs.get("local_files_only"):
            head = (repository / "refs" / "main").read_text(encoding="utf-8").strip()
            return str(repository / "snapshots" / head)
        if missing_revision:
            raise _revision_not_found()
        resolved = revision or UPSTREAM_HEAD
        snapshot = repository / "snapshots" / resolved
        snapshot.mkdir(parents=True, exist_ok=True)
        for name in allow_patterns or storage._FASTEMBED_PINNED_ARTIFACTS:
            if name in storage._FASTEMBED_PINNED_ARTIFACTS:
                data = _content(name, resolved)
                if name == corrupt:
                    data = data[:-1]
                (snapshot / name).write_bytes(data)
        if revision is None:
            (repository / "refs").mkdir(exist_ok=True)
            (repository / "refs" / "main").write_text(resolved, encoding="utf-8")
        return str(snapshot)

    class FakeTextEmbedding:
        def __init__(self, **kwargs):
            calls.append({"fastembed_local_files_only": kwargs["local_files_only"]})
            snapshot_download(
                repo_id="qdrant/all-MiniLM-L6-v2-onnx",
                cache_dir=kwargs["cache_dir"],
                local_files_only=kwargs["local_files_only"],
            )
            self.model = types.SimpleNamespace(tokenizer=_FakeTokenizer())

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot_download)
    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding)
    )
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)


def _revision_not_found() -> Exception:
    from huggingface_hub.errors import RevisionNotFoundError

    error = RevisionNotFoundError.__new__(RevisionNotFoundError)
    Exception.__init__(error, "404 Client Error. Revision Not Found for url")
    return error


def _siblings(root: Path) -> list[str]:
    return sorted(path.name for path in root.parent.iterdir() if path != root)


@pytest.fixture
def cache_root(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    return canonical_fastembed_cache_root()


# ── ops-1: a new upstream commit on main can no longer break the install ──


def test_fetch_downloads_the_pinned_revision_after_upstream_main_moved(cache_root, monkeypatch):
    calls: list = []
    _pin_fake_artifacts(monkeypatch)
    _install_fake_hub(monkeypatch, calls)

    model.fetch_model(DEFAULT_EMBED_MODEL)

    assert canonical_fastembed_cache_owned()
    downloads = [call for call in calls if "revision" in call and not call["local_files_only"]]
    assert downloads == [{"revision": CANONICAL_EMBED_MODEL_REVISION, "local_files_only": None}]
    loads = [call["fastembed_local_files_only"] for call in calls if "revision" not in call]
    assert loads
    assert all(loads)
    repository = cache_root / REPOSITORY
    assert (repository / "refs" / "main").read_text() == CANONICAL_EMBED_MODEL_REVISION
    assert not (repository / "snapshots" / UPSTREAM_HEAD).exists()
    metadata = json.loads((repository / "files_metadata.json").read_text())
    assert metadata[f"snapshots/{CANONICAL_EMBED_MODEL_REVISION}/model.onnx"]["size"] == len(
        _content("model.onnx", CANONICAL_EMBED_MODEL_REVISION)
    )
    assert json.loads((cache_root / ".mempalace-model.json").read_text()) == (
        canonical_fastembed_provenance()
    )
    assert _siblings(cache_root) == []


def test_unavailable_pinned_revision_is_named_and_retries_leave_nothing(cache_root, monkeypatch):
    _pin_fake_artifacts(monkeypatch)
    _install_fake_hub(monkeypatch, [], missing_revision=True)

    for _ in range(3):
        with pytest.raises(model.ModelFetchError) as excinfo:
            model.fetch_model(DEFAULT_EMBED_MODEL)
        message = str(excinfo.value)
        assert f"reviewed model revision {CANONICAL_EMBED_MODEL_REVISION}" in message
        assert "retrying will not help" in message
        assert "Retry exactly" not in message
        assert "Check network" not in message

    assert not cache_root.exists()
    assert list(cache_root.parent.iterdir()) == []


def test_download_that_differs_from_the_review_is_deleted(cache_root, monkeypatch):
    _pin_fake_artifacts(monkeypatch)
    _install_fake_hub(monkeypatch, [], corrupt="model.onnx")

    for _ in range(2):
        with pytest.raises(model.ModelFetchError) as excinfo:
            model.fetch_model(DEFAULT_EMBED_MODEL)
        assert "does not match reviewed revision" in str(excinfo.value)
        assert "model.onnx has" in str(excinfo.value)

    assert not cache_root.exists()
    assert list(cache_root.parent.iterdir()) == []


def test_force_on_a_good_cache_with_a_failed_download_leaves_no_quarantine(cache_root, monkeypatch):
    _pin_fake_artifacts(monkeypatch)
    _install_fake_hub(monkeypatch, [])
    model.fetch_model(DEFAULT_EMBED_MODEL)
    _install_fake_hub(monkeypatch, [], corrupt="tokenizer.json")

    with pytest.raises(model.ModelFetchError) as excinfo:
        model.fetch_model(DEFAULT_EMBED_MODEL, force=True)

    assert "The previous cache was restored" in str(excinfo.value)
    assert canonical_fastembed_cache_owned()
    assert _siblings(cache_root) == []


def test_truncated_cache_is_repaired_online_once(cache_root, monkeypatch, capsys):
    _pin_fake_artifacts(monkeypatch)
    _install_fake_hub(monkeypatch, [])
    model.fetch_model(DEFAULT_EMBED_MODEL)
    onnx = cache_root / REPOSITORY / "snapshots" / CANONICAL_EMBED_MODEL_REVISION / "model.onnx"
    onnx.write_bytes(b"x")
    assert not canonical_fastembed_cache_owned()

    model.fetch_model(DEFAULT_EMBED_MODEL)
    model.fetch_model(DEFAULT_EMBED_MODEL)

    output = capsys.readouterr().out
    assert output.count("Preserved partial cache at:") == 1
    assert "is already available locally" in output
    assert canonical_fastembed_cache_owned()
    assert len(_siblings(cache_root)) == 1


# ── install-r2-3: interrupted --force runs report the restore and leave no copies ──


def test_ctrl_c_during_force_reports_the_restore_and_deletes_the_partial(
    cache_root, monkeypatch, capsys
):
    _pin_fake_artifacts(monkeypatch)
    _install_fake_hub(monkeypatch, [])
    model.fetch_model(DEFAULT_EMBED_MODEL)
    capsys.readouterr()

    def interrupted():
        cache_root.mkdir(parents=True)
        (cache_root / "partial.bin").write_bytes(b"x" * 1024)
        raise KeyboardInterrupt

    monkeypatch.setattr(storage, "_download_pinned_canonical_snapshot", interrupted)

    with pytest.raises(KeyboardInterrupt):
        model.fetch_model(DEFAULT_EMBED_MODEL, force=True)

    assert f"The previous cache was restored at {cache_root}." in capsys.readouterr().err
    assert canonical_fastembed_cache_owned()
    assert _siblings(cache_root) == []


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_offline_orphan_restore_deletes_the_killed_download_and_sweeps_trash(
    cache_root, monkeypatch, capsys
):
    _pin_fake_artifacts(monkeypatch)
    _install_fake_hub(monkeypatch, [])
    model.fetch_model(DEFAULT_EMBED_MODEL)
    pid = _dead_pid()
    orphan = cache_root.with_name(f".{cache_root.name}.replace-{pid}-{'a' * 32}")
    cache_root.rename(orphan)
    cache_root.mkdir()
    (cache_root / "partial.bin").write_bytes(b"x" * 1024)
    trash = cache_root.with_name(f".{cache_root.name}.delete-{pid}-{'b' * 32}")
    trash.mkdir()
    (trash / "left.bin").write_bytes(b"x")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    capsys.readouterr()

    model.fetch_model(DEFAULT_EMBED_MODEL)

    output = capsys.readouterr().out
    assert f"Restored the cache an interrupted fetch-model set aside: {orphan}" in output
    assert canonical_fastembed_cache_owned()
    assert _siblings(cache_root) == []


# ── review: a lazy first-use download fails with one message, not a traceback ──


def _run_cli(monkeypatch, capsys, *argv: str) -> tuple[int, str]:
    from mempalace_code.cli import main

    monkeypatch.setenv("MEMPALACE_VERSION_CHECK", "0")
    monkeypatch.setattr(sys, "argv", ["mempalace-code", *argv])
    with pytest.raises(SystemExit) as excinfo:
        main()
    return int(excinfo.value.code or 0), capsys.readouterr().err


def _use_real_embedder(monkeypatch) -> None:
    from mempalace_code.storage import LanceStore

    monkeypatch.setattr(LanceStore, "_get_embedder", _REAL_GET_EMBEDDER)


from mempalace_code.storage import LanceStore as _LanceStore  # noqa: E402

# Captured at import, before the autouse fixture replaces it with the test embedder.
_REAL_GET_EMBEDDER = _LanceStore._get_embedder


def test_first_use_mine_reports_an_unavailable_revision_without_traceback(
    cache_root, tmp_path, monkeypatch, capsys
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "notes.md").write_text("# Notes\n\nThe invoice database moved to Postgres.\n")
    (corpus / "mempalace.yaml").write_text("wing: notes\nrooms:\n  - name: general\n")
    _pin_fake_artifacts(monkeypatch)
    _install_fake_hub(monkeypatch, [], missing_revision=True)
    _use_real_embedder(monkeypatch)

    for _ in range(2):
        code, stderr = _run_cli(
            monkeypatch, capsys, "--palace", str(tmp_path / "p"), "mine", str(corpus)
        )
        assert code == 1
        assert "Traceback" not in stderr
        assert f"reviewed model revision {CANONICAL_EMBED_MODEL_REVISION}" in stderr
        assert "retrying will not help" in stderr
        assert "docs/OFFLINE_USAGE.md, Option A" in stderr
        # The failed first-use download is deleted, so the next run does not say "not owned".
        assert "not owned" not in stderr
        assert not cache_root.exists()


def test_first_use_search_reports_a_network_failure_with_fetch_model(
    cache_root, tmp_path, monkeypatch, capsys
):
    from mempalace_code.storage import open_store

    palace = str(tmp_path / "p")
    open_store(palace, create=True).add(["d1"], ["invoice database"], [{"wing": "w", "room": "r"}])
    _pin_fake_artifacts(monkeypatch)
    _install_fake_hub(monkeypatch, [])
    import huggingface_hub

    def offline_hub(**kwargs):
        Path(kwargs["cache_dir"], REPOSITORY, "blobs").mkdir(parents=True)
        raise ConnectionError("Failed to resolve huggingface.co")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", offline_hub)
    _use_real_embedder(monkeypatch)

    code, stderr = _run_cli(monkeypatch, capsys, "--palace", palace, "search", "invoice")

    assert code == 1
    assert "Traceback" not in stderr
    assert "Could not download the embedding model" in stderr
    assert "Failed to resolve huggingface.co" in stderr
    assert "Run `mempalace-code fetch-model` while online" in stderr
    assert "repair" not in stderr
    assert not cache_root.exists()
