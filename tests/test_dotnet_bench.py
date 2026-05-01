import importlib.util
import json
import sys
from pathlib import Path

import pytest

_BENCH_FILE = Path(__file__).resolve().parent.parent / "benchmarks" / "dotnet_bench.py"
_spec = importlib.util.spec_from_file_location("dotnet_bench", _BENCH_FILE)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def _make_bench_results(r5, r10=0.900):
    """Minimal stub matching run_bench's return structure."""
    n = 20
    hits = round(r5 * n)
    per_query = [
        {
            "hit_at_5": i < hits,
            "hit_at_10": True,
            "category": "symbol_lookup",
            "query": f"q{i}",
            "expected_files": ["x.cs"],
            "top5_files": [],
        }
        for i in range(n)
    ]
    return {
        "code_retrieval": {
            "R@5": r5,
            "R@10": r10,
            "per_category": {"symbol_lookup": {"R@5": r5, "R@10": r10}},
            "per_query": per_query,
        },
        "performance": {
            "embed_time_s": 1.0,
            "chunk_count": 100,
            "query_latency_avg_ms": 15.0,
            "query_latency_p95_ms": 20.0,
            "index_size_mb": 5.0,
        },
    }


def _run_main(monkeypatch, tmp_path, r5, extra_args=None):
    out_path = tmp_path / "result.json"
    monkeypatch.setattr(bench, "run_bench", lambda _repo: _make_bench_results(r5))
    monkeypatch.setattr(bench, "get_repo_commit", lambda _repo: "abc123")
    sys.argv = [
        "dotnet_bench.py",
        "--repo-dir",
        str(tmp_path),
        "--out",
        str(out_path),
    ] + (extra_args or [])
    return out_path


def test_threshold_pass(monkeypatch, tmp_path):
    """R@5 == threshold must exit 0 and write the JSON report."""
    out_path = _run_main(monkeypatch, tmp_path, 0.800, ["--fail-under-r5", "0.800"])

    bench.main()  # must not raise SystemExit

    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert data["code_retrieval"]["R@5"] == pytest.approx(0.800)


def test_threshold_fail(monkeypatch, tmp_path):
    """R@5 = 0.799 with enforcement must exit 1 after writing the JSON report."""
    out_path = _run_main(monkeypatch, tmp_path, 0.799, ["--fail-under-r5", "0.800"])

    with pytest.raises(SystemExit) as exc:
        bench.main()

    assert exc.value.code == 1
    assert out_path.exists(), "JSON must be written before the gate raises SystemExit"
    data = json.loads(out_path.read_text())
    assert data["code_retrieval"]["R@5"] == pytest.approx(0.799, rel=1e-2)


def test_threshold_not_enforced_by_default(monkeypatch, tmp_path):
    """Without --fail-under-r5, low R@5 exits 0 (warning-only behavior preserved)."""
    out_path = _run_main(monkeypatch, tmp_path, 0.500)

    bench.main()  # must not raise SystemExit

    assert out_path.exists()


def test_threshold_invalid_rejects_non_float(monkeypatch, tmp_path):
    """Non-numeric --fail-under-r5 value must produce a non-zero exit via argparse."""
    monkeypatch.setattr(bench, "run_bench", lambda _repo: _make_bench_results(1.0))
    monkeypatch.setattr(bench, "get_repo_commit", lambda _repo: "abc123")
    sys.argv = [
        "dotnet_bench.py",
        "--repo-dir",
        str(tmp_path),
        "--fail-under-r5",
        "not_a_float",
    ]

    with pytest.raises(SystemExit) as exc:
        bench.main()

    assert exc.value.code != 0


def test_report_includes_commit_metadata(monkeypatch, tmp_path):
    """Output JSON must include repo_commit and expected_repo_commit in meta."""
    out_path = _run_main(monkeypatch, tmp_path, 0.900)
    monkeypatch.setattr(bench, "get_repo_commit", lambda _repo: "deadbeef")
    sys.argv = [
        "dotnet_bench.py",
        "--repo-dir",
        str(tmp_path),
        "--out",
        str(out_path),
    ]

    bench.main()

    data = json.loads(out_path.read_text())
    assert data["meta"]["repo_commit"] == "deadbeef"
    assert data["meta"]["expected_repo_commit"] == "5a600ab8749c110384bc3bd436b9c67f3067b489"


def test_failure_message_names_observed_r5_and_threshold(monkeypatch, tmp_path, capsys):
    """Failure message must name the observed R@5 value and the configured threshold."""
    _run_main(monkeypatch, tmp_path, 0.650, ["--fail-under-r5", "0.800"])

    with pytest.raises(SystemExit) as exc:
        bench.main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "0.650" in output or "0.65" in output
    assert "0.800" in output or "0.8" in output
