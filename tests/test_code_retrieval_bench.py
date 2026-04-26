import importlib.util
import json
from pathlib import Path

_BENCH_FILE = Path(__file__).resolve().parent.parent / "benchmarks" / "code_retrieval_bench.py"
_spec = importlib.util.spec_from_file_location("code_retrieval_bench", _BENCH_FILE)
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
