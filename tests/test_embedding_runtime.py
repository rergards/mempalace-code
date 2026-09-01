"""Focused contract tests for the canonical FastEmbed runtime and cache owner."""

import json
import math
import os
import sys
import types
from array import array
from pathlib import Path

import pytest

from mempalace_code.storage import (
    CANONICAL_EMBED_COMPATIBILITY_REVISION,
    CANONICAL_EMBED_MAX_LENGTH,
    CANONICAL_EMBED_MODEL,
    CANONICAL_EMBED_MODEL_REVISION,
    CUSTOM_MODELS_INSTALL_COMMAND,
    DEFAULT_EMBED_MODEL,
    LanceStore,
    _FastEmbedder,
    _write_canonical_provenance,
    canonical_fastembed_cache_owned,
    canonical_fastembed_cache_root,
    canonical_fastembed_provenance,
    canonical_fastembed_provenance_path,
    is_canonical_embed_model,
    quarantine_unowned_canonical_fastembed_cache,
    remove_owned_canonical_fastembed_cache,
)


def _write_owned_provenance(root: Path) -> None:
    root.mkdir(parents=True)
    repository = root / "models--qdrant--all-MiniLM-L6-v2-onnx"
    snapshot = repository / "snapshots" / CANONICAL_EMBED_MODEL_REVISION
    snapshot.mkdir(parents=True)
    refs = repository / "refs"
    refs.mkdir()
    (refs / "main").write_text(CANONICAL_EMBED_MODEL_REVISION, encoding="utf-8")
    for name in (
        "config.json",
        "model.onnx",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ):
        (snapshot / name).write_bytes(b"fixture")
    (snapshot / "tokenizer_config.json").write_text(
        json.dumps({"max_length": 256, "model_max_length": 512}), encoding="utf-8"
    )
    canonical_fastembed_provenance_path().write_text(
        json.dumps(canonical_fastembed_provenance()), encoding="utf-8"
    )


def test_canonical_aliases_have_one_owner():
    assert is_canonical_embed_model(DEFAULT_EMBED_MODEL)
    assert is_canonical_embed_model(CANONICAL_EMBED_MODEL)
    assert not is_canonical_embed_model("all-mpnet-base-v2")


def test_canonical_runtime_is_cpu_only_and_never_enables_remote_code(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    _write_owned_provenance(canonical_fastembed_cache_root())
    calls = []

    class FakeTextEmbedding:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def embed(self, texts):
            return [[3.0, 4.0] + [0.0] * 382 for _ in texts]

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding)
    )
    vectors = _FastEmbedder(local_files_only=True).compute_source_embeddings(["one", "two"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 384
    assert sum(value * value for value in vectors[0]) == pytest.approx(1.0)
    assert calls == [
        {
            "model_name": CANONICAL_EMBED_MODEL,
            "cache_dir": str(canonical_fastembed_cache_root()),
            "providers": ["CPUExecutionProvider"],
            "cuda": False,
            "local_files_only": True,
        }
    ]
    assert "trust_remote_code" not in calls[0]


def test_missing_custom_extra_fails_before_lance_creation(tmp_path, monkeypatch):
    original_import = __import__("importlib").import_module

    def guarded_import(name, package=None):
        if name == "sentence_transformers":
            raise ImportError("optional dependency unavailable")
        return original_import(name, package)

    monkeypatch.setattr("mempalace_code.storage.importlib.import_module", guarded_import)
    palace = tmp_path / "palace"

    with pytest.raises(RuntimeError, match=r"custom-models") as exc_info:
        LanceStore(str(palace), embed_model="example/custom-model")

    assert CUSTOM_MODELS_INSTALL_COMMAND in str(exc_info.value)
    assert not palace.exists()


def test_force_cleanup_refuses_symlink_and_foreign_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    root = canonical_fastembed_cache_root()
    target = tmp_path / "foreign"
    target.mkdir()
    root.parent.mkdir(parents=True)
    root.symlink_to(target, target_is_directory=True)

    with pytest.raises(RuntimeError, match="Refusing to remove unowned"):
        remove_owned_canonical_fastembed_cache()
    assert target.exists()

    root.unlink()
    root.mkdir()
    canonical_fastembed_provenance_path().write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Refusing to remove unowned"):
        remove_owned_canonical_fastembed_cache()
    assert root.exists()


@pytest.mark.parametrize("hostile_component", ["provenance", "refs", "artifact"])
def test_owned_cache_rejects_hostile_nested_symlinks(tmp_path, monkeypatch, hostile_component):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    root = canonical_fastembed_cache_root()
    _write_owned_provenance(root)
    foreign = tmp_path / "foreign"
    foreign.mkdir()

    if hostile_component == "provenance":
        path = canonical_fastembed_provenance_path()
        replacement = foreign / "provenance.json"
        replacement.write_text(json.dumps(canonical_fastembed_provenance()), encoding="utf-8")
    elif hostile_component == "refs":
        path = root / "models--qdrant--all-MiniLM-L6-v2-onnx" / "refs"
        replacement = foreign / "refs"
        replacement.mkdir()
        (replacement / "main").write_text(CANONICAL_EMBED_MODEL_REVISION, encoding="utf-8")
    else:
        path = (
            root
            / "models--qdrant--all-MiniLM-L6-v2-onnx"
            / "snapshots"
            / CANONICAL_EMBED_MODEL_REVISION
            / "model.onnx"
        )
        replacement = foreign / "model.onnx"
        replacement.write_bytes(b"foreign")
    if path.is_dir():
        (path / "main").unlink()
        path.rmdir()
    else:
        path.unlink()
    path.symlink_to(replacement, target_is_directory=replacement.is_dir())

    assert not canonical_fastembed_cache_owned()
    with pytest.raises(RuntimeError, match="not owned"):
        _FastEmbedder(local_files_only=True)
    with pytest.raises(RuntimeError, match="not owned"):
        _FastEmbedder(local_files_only=False)
    with pytest.raises(RuntimeError, match="Refusing to remove unowned"):
        remove_owned_canonical_fastembed_cache()
    assert replacement.exists()


def test_provenance_write_refuses_hostile_temporary_symlink(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    root = canonical_fastembed_cache_root()
    _write_owned_provenance(root)
    canonical_fastembed_provenance_path().unlink()
    sentinel = tmp_path / "external-sentinel"
    expected = b"external\x00\xffsentinel"
    sentinel.write_bytes(expected)
    temporary = canonical_fastembed_provenance_path().with_suffix(".tmp")
    temporary.symlink_to(sentinel)

    with pytest.raises(FileExistsError):
        _write_canonical_provenance()

    assert sentinel.read_bytes() == expected
    assert not canonical_fastembed_provenance_path().exists()
    assert not canonical_fastembed_cache_owned()


def test_owned_cache_rejects_unpinned_refs_main(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    root = canonical_fastembed_cache_root()
    _write_owned_provenance(root)
    (root / "models--qdrant--all-MiniLM-L6-v2-onnx" / "refs" / "main").write_text(
        "0" * 40, encoding="utf-8"
    )

    assert not canonical_fastembed_cache_owned()
    with pytest.raises(RuntimeError, match="not owned"):
        _FastEmbedder(local_files_only=True)
    with pytest.raises(RuntimeError, match="Refusing to remove unowned"):
        remove_owned_canonical_fastembed_cache()


def test_owned_cache_rejects_tokenizer_length_drift_offline_and_force(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    root = canonical_fastembed_cache_root()
    _write_owned_provenance(root)
    tokenizer_config = (
        root
        / "models--qdrant--all-MiniLM-L6-v2-onnx"
        / "snapshots"
        / CANONICAL_EMBED_MODEL_REVISION
        / "tokenizer_config.json"
    )
    tokenizer_config.write_text(
        json.dumps({"max_length": 128, "model_max_length": 512}), encoding="utf-8"
    )

    assert not canonical_fastembed_cache_owned()
    with pytest.raises(RuntimeError, match="not owned"):
        _FastEmbedder(local_files_only=True)
    with pytest.raises(RuntimeError, match="Refusing to remove unowned"):
        remove_owned_canonical_fastembed_cache()


def test_online_download_normalizes_then_reloads_before_embedding(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    calls = []
    embedded_by = []

    class FakeTextEmbedding:
        def __init__(self, **kwargs):
            self.call_index = len(calls)
            calls.append(kwargs)
            if not kwargs["local_files_only"]:
                root = canonical_fastembed_cache_root()
                _write_owned_provenance(root)
                tokenizer_config = (
                    root
                    / "models--qdrant--all-MiniLM-L6-v2-onnx"
                    / "snapshots"
                    / CANONICAL_EMBED_MODEL_REVISION
                    / "tokenizer_config.json"
                )
                tokenizer_config.write_text(
                    json.dumps({"max_length": 128, "model_max_length": 512}), encoding="utf-8"
                )

        def embed(self, texts):
            embedded_by.append(self.call_index)
            return [[1.0] + [0.0] * 383 for _ in texts]

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding)
    )
    vector = _FastEmbedder(local_files_only=False).compute_source_embeddings(["fixture"])[0]

    assert calls[0]["local_files_only"] is False
    assert calls[1]["local_files_only"] is True
    assert embedded_by == [1]
    assert vector[0] == 1.0
    tokenizer_config = (
        canonical_fastembed_cache_root()
        / "models--qdrant--all-MiniLM-L6-v2-onnx"
        / "snapshots"
        / CANONICAL_EMBED_MODEL_REVISION
        / "tokenizer_config.json"
    )
    assert json.loads(tokenizer_config.read_text(encoding="utf-8"))["max_length"] == 256
    assert canonical_fastembed_cache_owned()


def test_sequence_length_contract_is_sourced_from_former_runtime_fixture():
    fixture_path = (
        Path(__file__).resolve().parent.parent
        / "benchmarks"
        / "minilm_runtime_compatibility_fixture.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture["model"]["max_sequence_length"] == CANONICAL_EMBED_MAX_LENGTH
    assert fixture["model"]["revision"] == CANONICAL_EMBED_COMPATIBILITY_REVISION


def test_force_cleanup_atomically_removes_only_owned_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    root = canonical_fastembed_cache_root()
    _write_owned_provenance(root)

    assert remove_owned_canonical_fastembed_cache() is True
    assert not root.exists()
    assert not list(root.parent.glob(f".{root.name}.delete-*"))


def test_partial_cache_is_atomically_quarantined_without_deletion(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    root = canonical_fastembed_cache_root()
    root.mkdir(parents=True)
    marker = root / "interrupted-download.bin"
    marker.write_bytes(b"preserve me")

    quarantine = quarantine_unowned_canonical_fastembed_cache()

    assert quarantine is not None
    assert not root.exists()
    assert quarantine.parent == root.parent
    assert (quarantine / marker.name).read_bytes() == b"preserve me"
    assert quarantine_unowned_canonical_fastembed_cache() is None


def test_real_default_fastembed_runtime_from_prepared_cache(monkeypatch):
    """Direct evidence: execute FastEmbed itself when the qualification cache is supplied."""
    cache = os.environ.get("MEMPALACE_TEST_HF_HOME")
    if not cache:
        pytest.skip("set MEMPALACE_TEST_HF_HOME after mempalace-code fetch-model")
    monkeypatch.setenv("HF_HOME", cache)
    assert canonical_fastembed_cache_owned()

    vector = _FastEmbedder(local_files_only=True).compute_source_embeddings(
        ["MemPalace stores exact project context."]
    )[0]
    assert len(vector) == 384
    assert sum(value * value for value in vector) == pytest.approx(1.0, abs=1e-6)


def test_real_fastembed_matches_former_runtime_fixture(monkeypatch):
    """Compatibility evidence is derived from the committed former-runtime vectors."""
    cache = os.environ.get("MEMPALACE_TEST_HF_HOME")
    if not cache:
        pytest.skip("set MEMPALACE_TEST_HF_HOME after mempalace-code fetch-model")
    monkeypatch.setenv("HF_HOME", cache)
    fixture_path = (
        Path(__file__).resolve().parent.parent
        / "benchmarks"
        / "minilm_runtime_compatibility_fixture.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    former = fixture["former_vectors"]
    current = _FastEmbedder(local_files_only=True).compute_source_embeddings(fixture["texts"])

    def cosine(left, right):
        return sum(a * b for a, b in zip(left, right)) / (
            math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
        )

    paired = [cosine(left, right) for left, right in zip(former, current)]
    assert min(paired) >= fixture["compatibility"]["minimum_paired_cosine"]
    maximum_delta = max(
        abs(cosine(former[i], former[j]) - cosine(current[i], current[j]))
        for i in range(len(current))
        for j in range(len(current))
    )
    assert maximum_delta <= fixture["compatibility"]["maximum_similarity_matrix_delta"]
    current_order = [
        [
            j
            for j in sorted(range(len(current)), key=lambda j: (-cosine(current[i], current[j]), j))
            if j != i
        ]
        for i in range(len(current))
    ]
    assert current_order == fixture["compatibility"]["neighbor_order"]


def test_real_cache_searches_and_appends_to_former_vector_palace_without_reindex(
    tmp_path, monkeypatch
):
    """An existing 384d former-runtime row remains byte-stable across search and append."""
    cache = os.environ.get("MEMPALACE_TEST_HF_HOME")
    if not cache:
        pytest.skip("set MEMPALACE_TEST_HF_HOME after mempalace-code fetch-model")
    monkeypatch.setenv("HF_HOME", cache)
    fixture_path = (
        Path(__file__).resolve().parent.parent
        / "benchmarks"
        / "minilm_runtime_compatibility_fixture.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    former_vector = fixture["former_vectors"][0]
    former_bytes = array("f", former_vector).tobytes()

    palace = tmp_path / "old-palace"
    initial = LanceStore(str(palace))
    table = initial._require_table()
    row = initial._meta_defaults({"wing": "decisions", "room": "compatibility"})
    row.update({"id": "former-row", "text": fixture["texts"][0], "vector": former_vector})
    table.add([row])

    reopened = LanceStore(str(palace))
    real = _FastEmbedder(local_files_only=True)
    embedded_texts: list[str] = []

    class CountingEmbedder:
        def ndims(self):
            return real.ndims()

        def compute_source_embeddings(self, texts):
            embedded_texts.extend(texts)
            return real.compute_source_embeddings(texts)

    reopened._embedder = CountingEmbedder()
    results = reopened.query([fixture["texts"][0]], n_results=1, include=["documents"])
    assert results["ids"] == [["former-row"]]
    reopened.add(
        ["current-row"],
        [fixture["texts"][1]],
        [{"wing": "decisions", "room": "compatibility"}],
    )

    rows = {row["id"]: row for batch in reopened.iter_all(include_vectors=True) for row in batch}
    assert set(rows) == {"former-row", "current-row"}
    assert array("f", rows["former-row"]["vector"]).tobytes() == former_bytes
    assert reopened._require_table().schema.field("vector").type.list_size == 384
    assert embedded_texts == [fixture["texts"][0], fixture["texts"][1]]
