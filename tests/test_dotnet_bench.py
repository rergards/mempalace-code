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


def _make_compare_results():
    """Minimal stub matching run_compare_bench's return structure.

    All categories keep the same R@5 for vector and hybrid EXCEPT
    project_dependency, which improves by 0.200 under hybrid. The
    comparison.per_category deltas are derived from the mode data to
    keep the stub internally consistent.
    """
    vec_cat = {
        "symbol_lookup": {"R@5": 0.800, "R@10": 1.000},
        "cross_project": {"R@5": 0.600, "R@10": 0.800},
        "interface_impl": {"R@5": 0.600, "R@10": 0.800},
        "project_dependency": {"R@5": 0.400, "R@10": 0.600},
    }
    hyb_cat = {
        "symbol_lookup": {"R@5": 0.800, "R@10": 1.000},  # unchanged → delta = 0.000
        "cross_project": {"R@5": 0.600, "R@10": 0.800},  # unchanged → delta = 0.000
        "interface_impl": {"R@5": 0.600, "R@10": 0.800},  # unchanged → delta = 0.000
        "project_dependency": {"R@5": 0.600, "R@10": 0.800},  # improved → delta = 0.200
    }

    return {
        "code_retrieval": {
            "modes": {
                "vector": {
                    "R@5": 0.600,
                    "R@10": 0.850,
                    "per_category": vec_cat,
                    "per_query": [],
                },
                "hybrid": {
                    "R@5": 0.650,
                    "R@10": 0.850,
                    "per_category": hyb_cat,
                    "per_query": [],
                },
            }
        },
        "comparison": {
            "per_category": {
                "project_dependency": {"delta_R@5": 0.200},
                "symbol_lookup": {"delta_R@5": 0.000},
                "cross_project": {"delta_R@5": 0.000},
                "interface_impl": {"delta_R@5": 0.000},
            }
        },
        "performance": {
            "embed_time_s": 5.0,
            "chunk_count": 271,
            "query_latency_avg_ms": 15.0,
            "query_latency_p95_ms": 20.0,
            "index_size_mb": 5.0,
        },
    }


def _run_main(monkeypatch, tmp_path, r5, extra_args=None):
    out_path = tmp_path / "result.json"
    # Use **_kw to accept rerank_mode kwarg added to run_bench signature
    monkeypatch.setattr(bench, "run_bench", lambda _repo, **_kw: _make_bench_results(r5))
    monkeypatch.setattr(bench, "get_repo_commit", lambda _repo: "abc123")
    sys.argv = [
        "dotnet_bench.py",
        "--repo-dir",
        str(tmp_path),
        "--out",
        str(out_path),
    ] + (extra_args or [])
    return out_path


def _run_compare_main(monkeypatch, tmp_path, extra_args=None):
    out_path = tmp_path / "result.json"
    monkeypatch.setattr(bench, "run_compare_bench", lambda _repo: _make_compare_results())
    monkeypatch.setattr(bench, "get_repo_commit", lambda _repo: "abc123")
    sys.argv = [
        "dotnet_bench.py",
        "--repo-dir",
        str(tmp_path),
        "--compare-rerank",
        "--out",
        str(out_path),
    ] + (extra_args or [])
    return out_path


# =============================================================================
# Pre-existing threshold tests (stubs updated to accept **_kw)
# =============================================================================


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
    monkeypatch.setattr(bench, "run_bench", lambda _repo, **_kw: _make_bench_results(1.0))
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


# =============================================================================
# Default mode backwards-compatibility (Codex review gap)
# =============================================================================


def test_default_mode_json_shape_backwards_compatible(monkeypatch, tmp_path):
    """Default run (no --rerank-mode, no --compare-rerank) preserves existing CI schema.

    CI reads code_retrieval.R@5, code_retrieval.R@10, code_retrieval.per_category,
    code_retrieval.per_query, performance, and meta from the output JSON.
    """
    out_path = _run_main(monkeypatch, tmp_path, 0.700)

    bench.main()

    data = json.loads(out_path.read_text())
    # Top-level keys must include code_retrieval (not nested under modes)
    assert "code_retrieval" in data
    assert "R@5" in data["code_retrieval"], "CI reads code_retrieval.R@5 directly"
    assert "R@10" in data["code_retrieval"]
    assert "per_category" in data["code_retrieval"]
    assert "per_query" in data["code_retrieval"]
    assert "performance" in data
    assert "meta" in data
    # rerank_mode is added but does not break existing shape
    assert data["meta"]["rerank_mode"] == "vector"


# =============================================================================
# --rerank-mode tests (AC-7, AC-8)
# =============================================================================


def test_rerank_mode_invalid_exits_before_mining(monkeypatch, tmp_path):
    """AC-7: --rerank-mode with an invalid value must exit non-zero before mining."""
    mining_called = []
    monkeypatch.setattr(bench, "mine_project", lambda *_args, **_kw: mining_called.append(True))

    sys.argv = [
        "dotnet_bench.py",
        "--repo-dir",
        str(tmp_path),
        "--rerank-mode",
        "invalid_mode",
    ]

    with pytest.raises(SystemExit) as exc:
        bench.main()

    assert exc.value.code != 0
    assert not mining_called, "mine_project must not be called for an invalid --rerank-mode"


def test_rerank_mode_invalid_does_not_write_json(monkeypatch, tmp_path):
    """AC-7: Invalid --rerank-mode must not write an output JSON file."""
    out_path = tmp_path / "should_not_exist.json"
    monkeypatch.setattr(bench, "run_bench", lambda _repo, **_kw: _make_bench_results(0.7))
    sys.argv = [
        "dotnet_bench.py",
        "--repo-dir",
        str(tmp_path),
        "--rerank-mode",
        "notamode",
        "--out",
        str(out_path),
    ]

    with pytest.raises(SystemExit):
        bench.main()

    assert not out_path.exists(), "JSON must not be written for invalid --rerank-mode"


def test_rerank_mode_hybrid_records_meta_field(monkeypatch, tmp_path):
    """AC-8: --rerank-mode hybrid writes meta.rerank_mode = 'hybrid' to the JSON report."""
    out_path = _run_main(monkeypatch, tmp_path, 0.700, ["--rerank-mode", "hybrid"])

    bench.main()

    data = json.loads(out_path.read_text())
    assert data["meta"]["rerank_mode"] == "hybrid"


def test_rerank_mode_hybrid_writes_json_before_threshold_fail(monkeypatch, tmp_path):
    """AC-8: --rerank-mode hybrid writes JSON before threshold gate exits non-zero."""
    out_path = _run_main(
        monkeypatch,
        tmp_path,
        0.700,
        ["--rerank-mode", "hybrid", "--fail-under-r5", "1.000"],
    )

    with pytest.raises(SystemExit) as exc:
        bench.main()

    assert exc.value.code == 1
    assert out_path.exists(), "JSON must be written before --fail-under-r5 raises SystemExit"
    data = json.loads(out_path.read_text())
    assert data["meta"]["rerank_mode"] == "hybrid"


def test_rerank_mode_vector_explicit_matches_default_shape(monkeypatch, tmp_path):
    """--rerank-mode vector produces the same JSON shape as the default (no --rerank-mode)."""
    out_path = _run_main(monkeypatch, tmp_path, 0.700, ["--rerank-mode", "vector"])

    bench.main()

    data = json.loads(out_path.read_text())
    assert "R@5" in data["code_retrieval"]
    assert data["meta"]["rerank_mode"] == "vector"


# =============================================================================
# --compare-rerank tests (AC-1)
# =============================================================================


def test_compare_rerank_report_shape(monkeypatch, tmp_path):
    """AC-1: --compare-rerank output contains code_retrieval.modes.{vector,hybrid}."""
    out_path = _run_compare_main(monkeypatch, tmp_path)

    bench.main()

    assert out_path.exists()
    data = json.loads(out_path.read_text())

    # code_retrieval must have a modes sub-key, not a flat R@5
    assert "modes" in data["code_retrieval"], (
        "Compare mode must nest results under code_retrieval.modes"
    )
    for mode in ("vector", "hybrid"):
        assert mode in data["code_retrieval"]["modes"], f"Missing mode: {mode}"
        mode_data = data["code_retrieval"]["modes"][mode]
        assert "R@5" in mode_data, f"{mode} mode missing R@5"
        assert "R@10" in mode_data, f"{mode} mode missing R@10"
        assert "per_category" in mode_data, f"{mode} mode missing per_category"
        assert "per_query" in mode_data, f"{mode} mode missing per_query"


def test_compare_rerank_comparison_delta_present(monkeypatch, tmp_path):
    """AC-1: comparison.per_category.project_dependency.delta_R@5 is in the output."""
    out_path = _run_compare_main(monkeypatch, tmp_path)

    bench.main()

    data = json.loads(out_path.read_text())
    assert "comparison" in data
    assert "per_category" in data["comparison"]
    assert "project_dependency" in data["comparison"]["per_category"], (
        "project_dependency category must appear in comparison.per_category"
    )
    assert "delta_R@5" in data["comparison"]["per_category"]["project_dependency"]


def test_compare_rerank_meta_has_compare_flag(monkeypatch, tmp_path):
    """--compare-rerank sets meta.compare_rerank = True in the output JSON."""
    out_path = _run_compare_main(monkeypatch, tmp_path)

    bench.main()

    data = json.loads(out_path.read_text())
    assert data["meta"].get("compare_rerank") is True


def test_compare_rerank_delta_value_matches_modes(monkeypatch, tmp_path):
    """delta_R@5 equals hybrid R@5 minus vector R@5 for each category."""
    out_path = _run_compare_main(monkeypatch, tmp_path)

    bench.main()

    data = json.loads(out_path.read_text())
    comp = data["comparison"]["per_category"]
    modes = data["code_retrieval"]["modes"]

    for cat, cat_delta in comp.items():
        v = modes["vector"]["per_category"].get(cat, {}).get("R@5", 0)
        h = modes["hybrid"]["per_category"].get(cat, {}).get("R@5", 0)
        expected_delta = round(h - v, 3)
        assert cat_delta["delta_R@5"] == pytest.approx(expected_delta, abs=1e-3), (
            f"delta_R@5 for {cat} should be {expected_delta}, got {cat_delta['delta_R@5']}"
        )
