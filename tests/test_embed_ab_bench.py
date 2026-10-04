"""
Tests for benchmarks/embed_ab_bench.py — the --out mkdir fix, the shared query set, and the
LongMemEval no-regression gate.
"""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_BENCH_FILE = Path(__file__).resolve().parent.parent / "benchmarks" / "embed_ab_bench.py"
_spec = importlib.util.spec_from_file_location("embed_ab_bench", _BENCH_FILE)
assert _spec is not None
assert _spec.loader is not None
_embed_ab_bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_embed_ab_bench)

_STUB_CODE_RESULT = {
    "code_retrieval": {"R@5": 1.0, "R@10": 1.0, "per_category": {}},
    "performance": {"embed_time_s": 0.1, "query_latency_avg_ms": 1.0, "index_size_mb": 0.1},
}


def test_out_mkdir_creates_parent_dirs(monkeypatch, tmp_path):
    """--out with a non-existent nested path auto-creates parents and writes the report (AC-1, AC-3)."""
    out_file = tmp_path / "nested" / "deep" / "report.json"

    monkeypatch.setattr(_embed_ab_bench, "run_code_bench", _stub_code_bench)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "embed_ab_bench",
            "--models",
            "minilm",
            "--skip-longmemeval",
            "--out",
            str(out_file),
        ],
    )

    _embed_ab_bench.main()

    assert out_file.exists(), "report file was not created"
    data = json.loads(out_file.read_text())
    assert "models" in data
    assert "minilm" in data["models"]


_ROOT = Path(__file__).resolve().parent.parent


def _stub_code_bench(*_args, **_kwargs):
    return copy.deepcopy(_STUB_CODE_RESULT)


def test_queries_use_the_shared_dataset_with_current_owners():
    """The A/B ground truth is the maintained dataset, not inline pre-refactor module names."""
    dataset = _ROOT / "benchmarks" / "data" / "code_retrieval_queries.json"
    queries = _embed_ab_bench.QUERIES

    assert queries == json.loads(dataset.read_text(encoding="utf-8"))
    assert all((_ROOT / path).is_file() for q in queries for path in q["expected_files"])
    assert not any("chroma" in q["query"].lower() for q in queries)


def test_longmemeval_gate_reports_a_harness_that_cannot_run(monkeypatch, capsys):
    crashed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="ModuleNotFoundError: No module named 'chromadb'\n"
    )
    monkeypatch.setattr(_embed_ab_bench.subprocess, "run", lambda *_a, **_kw: crashed)

    result = _embed_ab_bench.run_longmemeval_gate("mpnet", "longmemeval.json")

    assert result["R@5"] is None
    assert "exited 1" in result["error"]
    assert "chromadb" in result["error"]
    assert "LongMemEval gate could not run" in capsys.readouterr().err


def test_longmemeval_gate_requires_match_or_beat():
    results: dict[str, dict[str, dict[str, float | None]]] = {
        "minilm": {"text_retrieval": {"R@5": 0.96}},
        "mpnet": {"text_retrieval": {"R@5": 0.95}},
        "nomic": {"text_retrieval": {"R@5": 0.96}},
    }
    keys = ["minilm", "mpnet", "nomic"]

    assert _embed_ab_bench.longmemeval_verdicts(results, keys) == {
        "minilm": "BASE",
        "mpnet": "FAIL",
        "nomic": "PASS",
    }

    results["minilm"]["text_retrieval"]["R@5"] = None
    assert set(_embed_ab_bench.longmemeval_verdicts(results, keys).values()) == {"ERROR"}


def test_main_exits_nonzero_when_the_text_gate_cannot_run(monkeypatch, tmp_path, capsys):
    data = tmp_path / "longmemeval.json"
    data.write_text("[]", encoding="utf-8")
    out_file = tmp_path / "report.json"
    monkeypatch.setattr(_embed_ab_bench, "run_code_bench", _stub_code_bench)
    monkeypatch.setattr(
        _embed_ab_bench,
        "run_longmemeval_gate",
        lambda *_a: {"R@5": None, "R@10": None, "NDCG@10": None, "error": "no chromadb"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["embed_ab_bench", "--models", "minilm,mpnet", "--longmemeval-data", str(data)]
        + ["--out", str(out_file)],
    )

    with pytest.raises(SystemExit) as caught:
        _embed_ab_bench.main()

    assert caught.value.code == 1
    report = json.loads(out_file.read_text(encoding="utf-8"))
    assert report["models"]["mpnet"]["text_retrieval"]["error"] == "no chromadb"
    assert "did not pass for: minilm, mpnet" in capsys.readouterr().err


def test_main_rejects_missing_longmemeval_data_before_mining(monkeypatch, tmp_path):
    monkeypatch.setattr(_embed_ab_bench, "run_code_bench", pytest.fail)
    monkeypatch.setattr(
        sys,
        "argv",
        ["embed_ab_bench", "--models", "minilm", "--longmemeval-data", str(tmp_path / "none")],
    )

    with pytest.raises(SystemExit) as caught:
        _embed_ab_bench.main()

    assert caught.value.code == 1


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("valid", 0),
        ("equal", 0),
        ("nonzero", 1),
        ("missing", 1),
        ("baseline_missing", 1),
        ("regression", 1),
        ("nan", 1),
        ("inf", 1),
        ("baseline_nan", 1),
        ("baseline_inf", 1),
        ("ndcg_nan", 1),
        ("r10_inf", 1),
    ],
)
def test_text_gate_cli_with_synthetic_harness_reports(tmp_path, scenario, expected_code):
    """Execute real CLI parsing/report/exit behavior; replace mining and the legacy harness."""
    data = tmp_path / "data.json"
    data.write_text("[]", encoding="utf-8")
    output = tmp_path / "report.json"
    driver = """
import copy, importlib.util, subprocess, sys
spec = importlib.util.spec_from_file_location("embed_ab", sys.argv.pop(1))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
scenario = sys.argv.pop(1)
bench.run_code_bench = lambda *args: copy.deepcopy({
    "code_retrieval": {"R@5": 1.0, "R@10": 1.0, "per_category": {}},
    "performance": {},
})
def synthetic_harness(cmd, **kwargs):
    baseline = cmd[cmd.index("--embed-model") + 1] == "default"
    r5 = "0.8" if baseline or scenario == "equal" else "0.9"
    if scenario == "regression" and not baseline:
        r5 = "0.7"
    if scenario in ("nan", "inf") and not baseline:
        r5 = scenario
    if scenario in ("baseline_nan", "baseline_inf") and baseline:
        r5 = scenario.removeprefix("baseline_")
    r10 = "inf" if scenario == "r10_inf" and not baseline else "0.9"
    ndcg = "nan" if scenario == "ndcg_nan" and not baseline else "0.8"
    label = "Recall@ 5" if scenario in ("valid", "equal") else "Recall@5"
    stdout = f"{label}: {r5}    NDCG@ 5: 0.7\\nRecall@10: {r10}    NDCG@10: {ndcg}\\n"
    if (scenario == "missing" and not baseline) or (scenario == "baseline_missing" and baseline):
        stdout = "Recall@10: 0.9\\n"
    return subprocess.CompletedProcess(cmd, 3 if scenario == "nonzero" else 0, stdout, "")
bench.subprocess.run = synthetic_harness
bench.main()
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            driver,
            str(_BENCH_FILE),
            scenario,
            "--models",
            "minilm,mpnet",
            "--longmemeval-data",
            str(data),
            "--out",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == expected_code, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert set(report["models"]) == {"minilm", "mpnet"}
    if expected_code == 0:
        assert report["models"]["minilm"]["text_retrieval"]["R@5"] == 0.8
        assert report["models"]["mpnet"]["text_retrieval"]["NDCG@10"] == 0.8


@pytest.mark.parametrize("invalid", [float("inf"), float("-inf"), float("nan"), True])
def test_longmemeval_verdicts_reject_invalid_baseline(invalid):
    results = {
        "minilm": {"text_retrieval": {"R@5": invalid}},
        "mpnet": {"text_retrieval": {"R@5": 0.9}},
    }
    assert _embed_ab_bench.longmemeval_verdicts(results, ["minilm", "mpnet"]) == {
        "minilm": "ERROR",
        "mpnet": "ERROR",
    }
