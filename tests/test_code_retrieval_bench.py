import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

_BENCH_FILE = Path(__file__).resolve().parent.parent / "benchmarks" / "code_retrieval_bench.py"
_spec = importlib.util.spec_from_file_location("code_retrieval_bench", _BENCH_FILE)
assert _spec is not None
assert _spec.loader is not None
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


class FakeStore:
    def __init__(self, query_metas=None):
        self.upserts = []
        self.query_metas = query_metas or []

    def upsert(self, ids, documents, metadatas):
        self.upserts.append((ids, documents, metadatas))
        self.metadatas = metadatas

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        return {"ids": [], "metadatas": getattr(self, "metadatas", [])}

    def query(self, query_texts, n_results=5, where=None, include=None):
        return {"metadatas": [self.query_metas[:n_results]], "documents": [[]], "distances": [[]]}


def test_hit_and_rank_match_basename_and_suffix():
    metas = [
        {"source_file": "/repo/mempalace/convo_miner.py"},
        {"source_file": "/repo/mempalace/miner.py"},
    ]

    assert bench.rank_of_first_hit(metas, ["mempalace/miner.py"]) == 2
    assert bench.hit_at_k(metas, ["miner.py"], 5) is True
    assert bench.hit_at_k(metas, ["mempalace/miner.py"], 1) is False


def test_validate_dataset_reports_missing_expected_file(tmp_path, capsys, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "present.py"
    source.write_text("def present():\n    return True\n" * 20, encoding="utf-8")
    monkeypatch.setattr(bench.miner, "scan_project", lambda _repo: [source])
    records = [
        {"id": "ok", "query": "present", "expected_files": ["present.py"], "category": "x"},
        {"id": "bad", "query": "absent", "expected_files": ["absent.py"], "category": "x"},
    ]

    assert bench.validate_dataset(repo.resolve(), records) == 1
    out = capsys.readouterr().out
    assert "PASS ok: present.py" in out
    assert "FAIL bad: missing absent.py" in out


def test_normalize_modes_rejects_unknown_with_supported_modes():
    try:
        bench.normalize_modes("smart,unknown")
    except bench.BenchError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected BenchError")

    assert "unknown" in message
    assert "naive, smart, treesitter" in message


def test_limit_must_be_positive(tmp_path):
    dataset = tmp_path / "queries.json"
    dataset.write_text("[]", encoding="utf-8")

    try:
        bench.load_dataset(dataset, limit=0)
    except bench.BenchError as exc:
        assert "--limit must be positive" in str(exc)
    else:
        raise AssertionError("expected BenchError")


def test_load_dataset_rejects_empty_dataset(tmp_path):
    dataset = tmp_path / "queries.json"
    dataset.write_text("[]", encoding="utf-8")

    try:
        bench.load_dataset(dataset)
    except bench.BenchError as exc:
        assert "dataset must contain at least one record" in str(exc)
    else:
        raise AssertionError("expected BenchError")


def test_load_dataset_rejects_malformed_expected_files(tmp_path):
    dataset = tmp_path / "queries.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "id": "q1",
                    "query": "find miner",
                    "expected_files": "miner.py",
                    "category": "function_lookup",
                }
            ]
        ),
        encoding="utf-8",
    )

    try:
        bench.load_dataset(dataset)
    except bench.BenchError as exc:
        assert "expected_files must be a non-empty list of strings" in str(exc)
    else:
        raise AssertionError("expected BenchError")


def test_aggregate_results_computes_r_at_k_mrr_and_categories():
    rows = [
        {"category": "function_lookup", "rank": 1, "hit_at_5": True, "hit_at_10": True},
        {"category": "function_lookup", "rank": 6, "hit_at_5": False, "hit_at_10": True},
        {"category": "module_overview", "rank": None, "hit_at_5": False, "hit_at_10": False},
    ]

    result = bench.aggregate_results(rows, [10.0, 20.0, 30.0])

    assert result["R@5"] == 1 / 3
    assert result["R@10"] == 2 / 3
    assert result["MRR"] == (1 + 1 / 6) / 3
    assert result["query_latency_avg_ms"] == 20.0
    assert result["per_category"]["function_lookup"]["R@10"] == 1.0


def test_smart_mode_suppresses_treesitter_parser(monkeypatch, tmp_path):
    calls = []
    fake_store = FakeStore()
    source = tmp_path / "sample.py"
    source.write_text("def sample():\n    return 1\n" * 20, encoding="utf-8")

    monkeypatch.setattr(bench, "open_store", lambda *_a, **_kw: fake_store)
    monkeypatch.setattr(bench, "scan_corpus_files", lambda _repo: [source])
    monkeypatch.setattr(bench.miner, "get_parser", lambda language: object())

    def fake_process_file(**kwargs):
        calls.append(bench.miner.get_parser("python"))
        kwargs["collection"].metadatas = [{"chunker_strategy": "regex_structural_v1"}]
        return 1

    monkeypatch.setattr(bench.miner, "process_file", fake_process_file)

    _store, count, meta = bench.mine_with_miner(tmp_path, tmp_path / "palace", "smart")

    assert count == 1
    assert calls == [None]
    assert bench.miner.get_parser("python") is not None
    assert meta["mode_degraded"] is False
    assert meta["tree_sitter_available"] is False


def test_treesitter_mode_reports_available_or_degraded(monkeypatch, tmp_path):
    fake_store = FakeStore()
    source = tmp_path / "sample.py"
    source.write_text("def sample():\n    return 1\n" * 20, encoding="utf-8")

    monkeypatch.setattr(bench, "open_store", lambda *_a, **_kw: fake_store)
    monkeypatch.setattr(bench, "scan_corpus_files", lambda _repo: [source])

    def fake_process_file(**kwargs):
        kwargs["collection"].metadatas = [{"chunker_strategy": "treesitter_v1"}]
        return 1

    monkeypatch.setattr(bench.miner, "process_file", fake_process_file)

    _store, count, meta = bench.mine_with_miner(tmp_path, tmp_path / "palace", "treesitter")

    assert count == 1
    assert meta["tree_sitter_available"] is True
    assert meta["mode_degraded"] is False
    assert meta["chunker_strategies"] == ["treesitter_v1"]


def test_run_benchmark_json_shape_without_embeddings(monkeypatch, tmp_path):
    dataset = tmp_path / "queries.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "id": "q1",
                    "query": "find miner",
                    "expected_files": ["miner.py"],
                    "category": "function_lookup",
                }
            ]
        ),
        encoding="utf-8",
    )

    def fake_run_mode(_repo_dir, mode, records):
        return {
            "chunk_count": 2,
            "embed_time_s": 0.1,
            "index_size_mb": 0.0,
            "query_latency_avg_ms": 1.5,
            "R@5": 1.0,
            "R@10": 1.0,
            "MRR": 1.0,
            "per_category": {
                "function_lookup": {"query_count": 1, "R@5": 1.0, "R@10": 1.0, "MRR": 1.0}
            },
            "per_query": [{"id": records[0]["id"], "top5_files": ["/repo/miner.py"]}],
            "tree_sitter_available": mode == "treesitter",
            "mode_degraded": False,
        }

    monkeypatch.setattr(bench, "run_mode", fake_run_mode)
    monkeypatch.setattr(bench, "_repo_commit", lambda _repo: "abc123")

    report = bench.run_benchmark(tmp_path, dataset, ["smart", "treesitter"], None)

    assert report["meta"]["query_count"] == 1
    assert set(report["modes"]) == {"smart", "treesitter"}
    assert report["modes"]["smart"]["per_query"][0]["top5_files"] == ["/repo/miner.py"]
    assert report["comparison"]["treesitter"]["chunk_count"] == 2


def test_minilm_compatibility_fixture_is_the_single_strict_contract():
    facts = json.loads(bench.RETRIEVAL_QUALITY_FACTS.read_text(encoding="utf-8"))
    assert "public_reproducible_compatibility" not in facts["code_minilm"]
    assert {key: facts["code_minilm"][key] for key in ("chunk_count", "r_at_5", "r_at_10")} == {
        "chunk_count": 469,
        "r_at_5": 0.95,
        "r_at_10": 1.0,
    }
    fixture = bench._load_minilm_compatibility_fixture()
    assert fixture["model"] == {
        "alias": "all-MiniLM-L6-v2",
        "identifier": "sentence-transformers/all-MiniLM-L6-v2",
        "max_sequence_length": 256,
        "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    }
    assert fixture["dimensions"] == 384
    assert len(fixture["texts"]) == len(fixture["former_vectors"]) == 5
    assert all(isinstance(text, str) and text.strip() for text in fixture["texts"])
    assert isinstance(fixture["generation_command"], str)
    assert fixture["generation_command"].strip()


def _write_mutated_fixture(tmp_path, mutate):
    fixture = json.loads(bench.MINILM_COMPATIBILITY_FIXTURE.read_text(encoding="utf-8"))
    mutate(fixture)
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "mutate",
    [
        lambda fixture: fixture.update(extra=True),
        lambda fixture: fixture.update(schema_version=True),
        lambda fixture: fixture["model"].update(alias="other"),
        lambda fixture: fixture.update(dimensions=383),
        lambda fixture: fixture.update(generation_command=""),
        lambda fixture: fixture["texts"].append("extra"),
        lambda fixture: fixture["former_vectors"][0].__setitem__(0, float("nan")),
        lambda fixture: fixture["former_vectors"][0].pop(),
        lambda fixture: fixture["compatibility"].update(minimum_paired_cosine=True),
        lambda fixture: fixture["compatibility"]["neighbor_order"][0].__setitem__(0, 1),
    ],
)
def test_minilm_compatibility_fixture_rejects_schema_and_bound_fact_drift(tmp_path, mutate):
    path = _write_mutated_fixture(tmp_path, mutate)

    with pytest.raises(bench.BenchError, match="fixture_schema failed"):
        bench._load_minilm_compatibility_fixture(path)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version": 1, "schema_version": 1}',
        b'{"model": {"alias": "first", "alias": "second"}}',
    ],
)
def test_minilm_compatibility_fixture_rejects_duplicate_keys(tmp_path, raw):
    path = tmp_path / "fixture.json"
    path.write_bytes(raw)

    with pytest.raises(bench.BenchError, match="fixture_schema failed"):
        bench._load_minilm_compatibility_fixture(path)


def test_minilm_generation_command_is_bound_inert_provenance(tmp_path):
    marker = tmp_path / "generation-command-ran"
    path = _write_mutated_fixture(
        tmp_path,
        lambda fixture: fixture.update(generation_command=f"touch {marker}"),
    )

    with pytest.raises(bench.BenchError, match="fixture_hash failed"):
        bench._load_minilm_compatibility_fixture(path)

    assert not marker.exists()


def test_minilm_compatibility_vectors_pass_and_fail_closed_on_metric_drift():
    fixture = bench._load_minilm_compatibility_fixture()
    result = bench._validate_current_vectors(fixture, deepcopy(fixture["former_vectors"]))

    assert result == {
        "fixture": "minilm_runtime_compatibility_fixture.json",
        "model": "all-MiniLM-L6-v2",
        "texts": 5,
        "dimensions": 384,
    }
    drifted = deepcopy(fixture["former_vectors"])
    drifted[0][0], drifted[0][1] = drifted[0][1], drifted[0][0]
    norm = sum(value * value for value in drifted[0]) ** 0.5
    drifted[0] = [value / norm for value in drifted[0]]
    with pytest.raises(bench.BenchError, match="minimum_paired_cosine failed"):
        bench._validate_current_vectors(fixture, drifted)


def _runtime_contract(*, minimum=0.9, maximum=0.1, neighbor_order=None):
    diagonal = 2**-0.5
    return {
        "dimensions": 2,
        "texts": ["first", "second", "third"],
        "former_vectors": [[1.0, 0.0], [0.0, 1.0], [diagonal, diagonal]],
        "model": {"alias": "all-MiniLM-L6-v2"},
        "compatibility": {
            "minimum_paired_cosine": minimum,
            "maximum_similarity_matrix_delta": maximum,
            "neighbor_order": neighbor_order or [[2, 1], [2, 0], [0, 1]],
        },
    }


@pytest.mark.parametrize(
    ("fixture", "current", "expected"),
    [
        (
            _runtime_contract(),
            [[1.0, 0.0], [0.0, 1.0]],
            "current_vector_shape failed: observed_vector_count=2 expected_vector_count=3",
        ),
        (
            _runtime_contract(),
            ([1.0, 0.0], [0.0, 1.0], [2**-0.5, 2**-0.5]),
            "current_vector_shape failed: observed_vector_count=not-a-list expected_vector_count=3",
        ),
        (
            _runtime_contract(),
            [[1.0], [0.0, 1.0], [2**-0.5, 2**-0.5]],
            "current_vector_shape failed: vector_index=0 observed_dimensions=1 "
            "expected_dimensions=2",
        ),
        (
            _runtime_contract(),
            [[2.0, 0.0], [0.0, 1.0], [2**-0.5, 2**-0.5]],
            "current_vector_norm failed: vector_index=0 observed_norm=2 "
            "expected_norm=1 absolute_tolerance=1e-06",
        ),
        (
            _runtime_contract(),
            [[float("nan"), 0.0], [0.0, 1.0], [2**-0.5, 2**-0.5]],
            "current_vector_norm failed: vector_index=0 observed_norm=non-finite "
            "expected_norm=1 absolute_tolerance=1e-06",
        ),
        (
            _runtime_contract(),
            [[-1.0, 0.0], [0.0, 1.0], [2**-0.5, 2**-0.5]],
            "minimum_paired_cosine failed: observed=-1 expected_minimum=0.90000000000000002",
        ),
        (
            _runtime_contract(minimum=-1.0),
            [[0.0, 1.0], [0.0, 1.0], [2**-0.5, 2**-0.5]],
            "maximum_similarity_matrix_delta failed: observed=1 "
            "expected_maximum=0.10000000000000001",
        ),
        (
            _runtime_contract(minimum=-1.0, maximum=2.0, neighbor_order=[[1, 2], [2, 0], [0, 1]]),
            [[1.0, 0.0], [0.0, 1.0], [2**-0.5, 2**-0.5]],
            "neighbor_order failed: row_index=0 observed=[2, 1] expected=[1, 2]",
        ),
    ],
)
def test_runtime_predicate_cli_diagnostics_are_stable_and_bounded(
    monkeypatch, tmp_path, capsys, fixture, current, expected
):
    class FakeEmbedder:
        def __init__(self, *, local_files_only):
            assert local_files_only is True

        def compute_source_embeddings(self, texts):
            assert texts == fixture["texts"]
            return deepcopy(current)

    monkeypatch.setattr(bench, "_load_minilm_compatibility_fixture", lambda: deepcopy(fixture))
    monkeypatch.setattr(
        bench,
        "_import_installed_storage",
        lambda: SimpleNamespace(_FastEmbedder=FakeEmbedder),
    )
    outputs = []
    for _ in range(2):
        assert (
            bench.main(["--repo-dir", str(tmp_path), "--check-minilm-runtime-compatibility"]) == 2
        )
        captured = capsys.readouterr()
        assert captured.out == ""
        outputs.append(captured.err)

    assert outputs[0] == outputs[1]
    assert outputs[0] == (
        f"ERROR: MiniLM compatibility {expected}; "
        "cache refresh-and-retry: "
        "mempalace-code fetch-model --model all-MiniLM-L6-v2 --force; "
        "persistent failure is a runtime/dependency compatibility blocker\n"
    )
    assert len(outputs[0].splitlines()) == 1
    assert len(outputs[0]) < 512
    assert outputs[0].count(bench.MINILM_CACHE_RECOVERY) == 1
    assert str(tmp_path) not in outputs[0]
    assert str(fixture["former_vectors"][0][0]) not in outputs[0]
    assert "Traceback" not in outputs[0]
    assert "will repair" not in outputs[0]


def test_minilm_compatibility_uses_local_only_storage_owner(monkeypatch, tmp_path):
    fixture = bench._load_minilm_compatibility_fixture()
    calls = []

    class FakeEmbedder:
        def __init__(self, *, local_files_only):
            calls.append(local_files_only)

        def compute_source_embeddings(self, texts):
            assert texts == fixture["texts"]
            return deepcopy(fixture["former_vectors"])

    monkeypatch.setattr(
        bench,
        "_import_installed_storage",
        lambda: SimpleNamespace(_FastEmbedder=FakeEmbedder),
    )

    result = bench.run_minilm_runtime_compatibility(tmp_path)

    assert result["dimensions"] == 384
    assert calls == [True]
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_installed_storage_import_rejects_an_already_shadowed_checkout_module(
    monkeypatch, tmp_path
):
    installed = tmp_path / "installed" / "mempalace_code"
    installed.mkdir(parents=True)
    shadowed = tmp_path / "checkout" / "mempalace_code" / "storage.py"
    shadowed.parent.mkdir(parents=True)
    shadowed.write_text("", encoding="utf-8")
    monkeypatch.setattr(bench, "_active_distribution_package_root", lambda: installed)
    monkeypatch.setattr(
        bench.importlib, "import_module", lambda _name: SimpleNamespace(__file__=str(shadowed))
    )

    with pytest.raises(bench.BenchError, match="installed MiniLM runtime is shadowed"):
        bench._import_installed_storage()


def test_main_compatibility_mode_prints_one_bounded_status(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        bench,
        "run_minilm_runtime_compatibility",
        lambda _repo: {
            "fixture": "minilm_runtime_compatibility_fixture.json",
            "model": "all-MiniLM-L6-v2",
            "texts": 5,
            "dimensions": 384,
        },
    )

    assert (
        bench.main(
            [
                "--repo-dir",
                str(tmp_path),
                "--dataset",
                str(tmp_path / "missing.json"),
                "--check-minilm-runtime-compatibility",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "PASS MiniLM runtime compatibility: "
        "fixture=minilm_runtime_compatibility_fixture.json "
        "model=all-MiniLM-L6-v2 texts=5 dimensions=384"
    ]


@pytest.mark.parametrize(
    "message",
    [
        "MiniLM compatibility minimum_paired_cosine failed: observed=0.1",
        "MiniLM runtime cache is unavailable; recovery: "
        "mempalace-code fetch-model --model all-MiniLM-L6-v2 --force",
        "MiniLM runtime cache is unavailable; recovery: retry",
    ],
)
def test_hosted_compatibility_failure_preserves_stderr_and_emits_one_annotation(
    monkeypatch, tmp_path, capsys, message
):
    def fail(_repo):
        raise bench.BenchError(message)

    monkeypatch.setattr(bench, "run_minilm_runtime_compatibility", fail)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert bench.main(["--repo-dir", str(tmp_path), "--check-minilm-runtime-compatibility"]) == 2
    captured = capsys.readouterr()

    assert captured.err == f"ERROR: {message}\n"
    assert captured.out == f"::error title=MiniLM runtime compatibility::ERROR: {message}\n"
    assert len(captured.out.splitlines()) == 1


@pytest.mark.parametrize("github_actions", [None, "True", "1", "false"])
def test_local_compatibility_failure_has_exact_existing_output(
    monkeypatch, tmp_path, capsys, github_actions
):
    message = "MiniLM runtime cache is unavailable; recovery: retry"
    monkeypatch.setattr(
        bench,
        "run_minilm_runtime_compatibility",
        lambda _repo: (_ for _ in ()).throw(bench.BenchError(message)),
    )
    if github_actions is None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", github_actions)

    assert bench.main(["--check-minilm-runtime-compatibility"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"ERROR: {message}\n"


def test_hosted_other_mode_failure_and_compatibility_success_emit_no_annotation(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(
        bench,
        "load_dataset",
        lambda *_args: (_ for _ in ()).throw(bench.BenchError("ordinary failure")),
    )
    assert bench.main(["--repo-dir", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ERROR: ordinary failure\n"

    monkeypatch.setattr(
        bench,
        "run_minilm_runtime_compatibility",
        lambda _repo: {
            "fixture": "fixture.json",
            "model": "all-MiniLM-L6-v2",
            "texts": 5,
            "dimensions": 384,
        },
    )
    assert bench.main(["--check-minilm-runtime-compatibility"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "::" not in captured.out


def test_compatibility_annotation_escapes_workflow_command_data_in_order():
    error = bench.BenchError("MiniLM 100%\r\n::warning::secret")

    assert bench._github_compatibility_annotation(error) == (
        "::error title=MiniLM runtime compatibility::ERROR: MiniLM 100%25%0D%0A::warning::secret"
    )


@pytest.mark.parametrize(
    "message",
    [
        "MiniLM compatibility fixture_schema failed; recovery: "
        "git restore benchmarks/minilm_runtime_compatibility_fixture.json",
        "MiniLM compatibility fixture_hash failed; recovery: "
        "git restore benchmarks/minilm_runtime_compatibility_fixture.json",
        "active mempalace-code distribution is not installed; recovery: "
        "python -m pip install dist/*.whl",
        "active mempalace-code distribution metadata is malformed; recovery: "
        "python -m pip install dist/*.whl",
        "active mempalace-code package root is unavailable; recovery: "
        "python -m pip install dist/*.whl",
        "installed MiniLM runtime is unavailable; recovery: python -m pip install dist/*.whl",
        "installed MiniLM runtime is shadowed; recovery: python -m pip install dist/*.whl",
        "MiniLM runtime cache is unavailable; recovery: "
        "mempalace-code fetch-model --model all-MiniLM-L6-v2 --force",
        "MiniLM compatibility current_vector_shape failed: observed_vector_count=5 "
        "expected_vector_count=5; cache refresh-and-retry: mempalace-code fetch-model "
        "--model all-MiniLM-L6-v2 --force; persistent failure is a runtime/dependency "
        "compatibility blocker",
        "MiniLM compatibility current_vector_shape failed: vector_index=4 "
        "observed_dimensions=384 expected_dimensions=384; cache refresh-and-retry: "
        "mempalace-code fetch-model --model all-MiniLM-L6-v2 --force; persistent failure "
        "is a runtime/dependency compatibility blocker",
        "MiniLM compatibility current_vector_norm failed: vector_index=4 "
        "observed_norm=0.99999999999999989 expected_norm=1 absolute_tolerance=1e-06; "
        "cache refresh-and-retry: mempalace-code fetch-model --model all-MiniLM-L6-v2 "
        "--force; persistent failure is a runtime/dependency compatibility blocker",
        "MiniLM compatibility minimum_paired_cosine failed: "
        "observed=-0.99999999999999989 expected_minimum=0.99999999999999989; "
        "cache refresh-and-retry: mempalace-code fetch-model --model all-MiniLM-L6-v2 "
        "--force; persistent failure is a runtime/dependency compatibility blocker",
        "MiniLM compatibility maximum_similarity_matrix_delta failed: "
        "observed=1.9999999999999998 expected_maximum=0.99999999999999989; "
        "cache refresh-and-retry: mempalace-code fetch-model --model all-MiniLM-L6-v2 "
        "--force; persistent failure is a runtime/dependency compatibility blocker",
        "MiniLM compatibility neighbor_order failed: row_index=4 observed=[3, 2, 1, 0] "
        "expected=[0, 1, 2, 3]; cache refresh-and-retry: mempalace-code fetch-model "
        "--model all-MiniLM-L6-v2 --force; persistent failure is a runtime/dependency "
        "compatibility blocker",
    ],
)
def test_current_production_compatibility_annotation_messages_are_below_bound(message):
    error = bench.BenchError(message)
    data = f"ERROR: {message}"

    assert len(data) < 640
    assert bench._github_compatibility_annotation(error).endswith(data)


def _write_fake_installed_runtime(root, *, fail=False):
    package = root / "mempalace_code"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    body = (
        "raise RuntimeError('cache missing')"
        if fail
        else (
            "import json, os\n"
            "return json.load(open(os.environ['MINILM_TEST_FIXTURE']))['former_vectors']"
        )
    )
    (package / "storage.py").write_text(
        "class _FastEmbedder:\n"
        "    def __init__(self, *, local_files_only):\n"
        "        assert local_files_only is True\n"
        "    def compute_source_embeddings(self, texts):\n"
        f"        {body.replace(chr(10), chr(10) + '        ')}\n",
        encoding="utf-8",
    )
    metadata = root / "mempalace_code-99.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: mempalace-code\nVersion: 99.0\n", encoding="utf-8"
    )


def _run_compatibility_script(tmp_path, *, fail=False, malformed=False, drifted_hash=False):
    checkout = tmp_path / "checkout"
    benchmarks = checkout / "benchmarks"
    benchmarks.mkdir(parents=True)
    script = benchmarks / "code_retrieval_bench.py"
    script.write_bytes(_BENCH_FILE.read_bytes())
    fixture = benchmarks / "minilm_runtime_compatibility_fixture.json"
    fixture.write_bytes(bench.MINILM_COMPATIBILITY_FIXTURE.read_bytes())
    if malformed:
        value = json.loads(fixture.read_text(encoding="utf-8"))
        value["dimensions"] = 383
        fixture.write_text(json.dumps(value), encoding="utf-8")
    if drifted_hash:
        value = json.loads(fixture.read_text(encoding="utf-8"))
        value["generation_command"] += " "
        fixture.write_text(json.dumps(value), encoding="utf-8")
    checkout_package = checkout / "mempalace_code"
    checkout_package.mkdir()
    (checkout_package / "__init__.py").write_text("", encoding="utf-8")
    (checkout_package / "storage.py").write_text(
        "raise RuntimeError('checkout source shadowed installed package')\n", encoding="utf-8"
    )
    installed = tmp_path / "installed"
    _write_fake_installed_runtime(installed, fail=fail)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(checkout), str(installed)])
    env["MINILM_TEST_FIXTURE"] = str(fixture)
    return subprocess.run(
        [sys.executable, str(script), "--check-minilm-runtime-compatibility"],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_compatibility_subprocess_prefers_installed_root_over_checkout_source(tmp_path):
    result = _run_compatibility_script(tmp_path)

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.count("PASS MiniLM runtime compatibility") == 1
    assert "checkout source shadowed" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("kwargs", "recovery"),
    [
        ({"fail": True}, "mempalace-code fetch-model --model all-MiniLM-L6-v2 --force"),
        ({"malformed": True}, "fixture_schema failed"),
        ({"drifted_hash": True}, "fixture_hash failed"),
    ],
)
def test_compatibility_subprocess_failures_are_bounded_and_actionable(tmp_path, kwargs, recovery):
    result = _run_compatibility_script(tmp_path, **kwargs)

    assert result.returncode == 2
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert result.stderr.startswith("ERROR: MiniLM")
    assert result.stderr.count(recovery) == 1
    assert "Traceback" not in result.stderr


def test_compatibility_implementation_has_no_git_history_or_generated_result_owner():
    source = _BENCH_FILE.read_text(encoding="utf-8")
    compatibility_source = source[
        source.index("def _fixture_error") : source.index("def load_dataset")
    ]

    assert "git archive" not in compatibility_source
    assert "git fetch" not in compatibility_source
    assert "TemporaryDirectory" not in compatibility_source
    assert "write_text" not in compatibility_source
