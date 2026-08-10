"""
tests/test_demo_perf_budgets.py — Focused tests for benchmarks/demo_perf_budgets.py.

Pure-logic, schema, and boundary tests only. The real mine/search/read/
maintenance pipeline against the deterministic fixture is proven by REG-2
(`python benchmarks/demo_perf_budgets.py --check --ci`), not by slow real
mining inside pytest.
"""

from __future__ import annotations

import importlib.util
import json
import socket
from pathlib import Path

import pytest

_BENCH_FILE = Path(__file__).resolve().parent.parent / "benchmarks" / "demo_perf_budgets.py"
_spec = importlib.util.spec_from_file_location("demo_perf_budgets", _BENCH_FILE)
assert _spec is not None
assert _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def _write_artifact(path: Path, **overrides) -> dict:
    baselines = {
        "mine_full": 1.0,
        "mine_incremental_noop": 0.05,
        "search_p95": 5.0,
        "read_p95": 5.0,
        "maintenance": 0.05,
    }
    metrics = {}
    for name, rules in _mod.DEFAULT_RULES.items():
        metrics[name] = {**rules, "baseline": baselines[name], "before": None}
    artifact = {
        "schema_version": _mod.SCHEMA_VERSION,
        "budget_changed_because": "test baseline",
        "fixture": {"files": ["a.py"], "file_count": 1, "total_bytes": 10},
        "metrics": metrics,
    }
    artifact.update(overrides)
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return artifact


_FAKE_MEASUREMENTS_BREACH = {
    "fixture": {"files": ["a.py"], "file_count": 1, "total_bytes": 10},
    "mine_full": {"elapsed_secs": 999.0, "drawers_filed": 1, "files_processed": 1},
    "mine_incremental_noop": {"elapsed_secs": 0.01, "drawers_filed": 0, "files_skipped": 1},
    "search": {"samples": 1, "median_ms": 1.0, "p95_ms": 1.0, "max_ms": 1.0},
    "read": {"samples": 1, "median_ms": 1.0, "p95_ms": 1.0, "max_ms": 1.0},
    "maintenance": {"elapsed_secs": 0.01, "ok": True, "supported": True},
}


# ── AC-1: fixture generation + offline network guard ───────────────────────


def test_fixture_is_generated_locally_and_network_guarded(tmp_path):
    project_dir = tmp_path / "project"
    fixture = _mod.build_fixture(project_dir)

    assert fixture["files"] == sorted(_mod.FIXTURE_FILES)
    assert fixture["file_count"] == len(_mod.FIXTURE_FILES)
    assert fixture["total_bytes"] > 0

    for name, content in _mod.FIXTURE_FILES.items():
        assert (project_dir / name).read_text(encoding="utf-8") == content
    assert (project_dir / "mempalace.yaml").exists()

    # No CLI surface accepts an external project/repo path — argparse rejects any
    # stray positional argument outright, so only the fixed in-repo fixture is
    # ever mined.
    with pytest.raises(SystemExit) as exc:
        _mod.main(["/some/external/repo"])
    assert exc.value.code == 2

    with pytest.raises(_mod.NetworkBlockedError):
        with _mod._socket_guard():
            socket.create_connection(("example.invalid", 80))

    with pytest.raises(_mod.NetworkBlockedError):
        with _mod._socket_guard():
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("example.invalid", 80))

    # The guard is scoped to the context manager — the real function is restored
    # afterward so unrelated socket use elsewhere is unaffected.
    original = socket.create_connection
    with _mod._socket_guard():
        assert socket.create_connection is not original
    assert socket.create_connection is original


# ── AC-2/AC-3: measurement schema + comparison rules ────────────────────────


def test_measurement_schema_has_expected_shape():
    stats = _mod._latency_stats([0.001, 0.003, 0.002])
    assert set(stats) == {"samples", "median_ms", "p95_ms", "max_ms"}
    assert stats["samples"] == 3
    assert stats["median_ms"] == pytest.approx(2.0)
    assert stats["max_ms"] == pytest.approx(3.0)
    assert stats["p95_ms"] >= stats["median_ms"]

    measurements = {
        "mine_full": {"elapsed_secs": 1.5, "drawers_filed": 4, "files_processed": 4},
        "mine_incremental_noop": {"elapsed_secs": 0.02, "drawers_filed": 0, "files_skipped": 4},
        "search": {"samples": 20, "median_ms": 1.1, "p95_ms": 2.2, "max_ms": 3.3},
        "read": {"samples": 20, "median_ms": 0.5, "p95_ms": 1.0, "max_ms": 1.5},
        "maintenance": {"elapsed_secs": 0.03, "ok": True, "supported": True},
    }
    assert _mod._actual_values(measurements) == {
        "mine_full": 1.5,
        "mine_incremental_noop": 0.02,
        "search_p95": 2.2,
        "read_p95": 1.0,
        "maintenance": 0.03,
    }


def test_budget_comparison_rules_pass_and_fail():
    assert _mod.budget_for(baseline=1.0, floor=0.1, ratio=2.0) == 2.0
    assert _mod.budget_for(baseline=0.0, floor=0.5, ratio=3.0) == 0.5

    passing = _mod.evaluate_metric("x", actual=1.5, baseline=1.0, floor=0.1, ratio=2.0)
    assert passing["passed"] is True
    assert passing["budget"] == 2.0

    failing = _mod.evaluate_metric("x", actual=2.5, baseline=1.0, floor=0.1, ratio=2.0)
    assert failing["passed"] is False
    assert failing["budget"] == 2.0


def test_missing_or_malformed_budget_artifact_fails_closed(tmp_path):
    missing = tmp_path / "missing.json"
    data, errors = _mod.load_and_validate_artifact(missing)
    assert data is None
    assert len(errors) == 1
    assert "missing" in errors[0]

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not valid json", encoding="utf-8")
    data, errors = _mod.load_and_validate_artifact(malformed)
    assert data is None
    assert len(errors) == 1
    assert "malformed" in errors[0].lower()

    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(
        json.dumps(
            {
                "schema_version": _mod.SCHEMA_VERSION,
                "budget_changed_because": "x",
                "fixture": {"files": ["a"], "file_count": 1, "total_bytes": 1},
                "metrics": {},
            }
        ),
        encoding="utf-8",
    )
    data, errors = _mod.load_and_validate_artifact(incomplete)
    assert data is None
    assert any("mine_full" in e for e in errors)

    breached_shape = tmp_path / "bad_ratio.json"
    _write_artifact(breached_shape)
    bad = json.loads(breached_shape.read_text(encoding="utf-8"))
    bad["metrics"]["mine_full"]["ratio"] = 0.5  # ratio < 1 is rejected
    breached_shape.write_text(json.dumps(bad), encoding="utf-8")
    data, errors = _mod.load_and_validate_artifact(breached_shape)
    assert data is None
    assert any("ratio" in e for e in errors)


# ── AC-4/AC-5: hard CI gate vs informational local output ───────────────────


def test_ci_check_uses_hard_budgets_and_default_output_is_informational(
    tmp_path, monkeypatch, capsys
):
    artifact_path = tmp_path / "budget.json"
    _write_artifact(artifact_path)

    monkeypatch.setattr(_mod, "ARTIFACT_PATH", artifact_path)
    monkeypatch.setattr(_mod, "run_measurements", lambda: _FAKE_MEASUREMENTS_BREACH)

    # --check without --ci is rejected before any measurement runs.
    with pytest.raises(SystemExit) as exc:
        _mod.main(["--check"])
    assert exc.value.code == 2

    # --check --ci enforces the hard budget and fails on a real breach
    # (mine_full actual=999s vs budget=max(20.0, 1.0*3.0)=20.0s).
    assert _mod.main(["--check", "--ci"]) == 1

    # Default informational output shows the same breach but never gates on it.
    capsys.readouterr()
    assert _mod.main([]) == 0
    out = capsys.readouterr().out
    assert "[FAIL] mine_full" in out

    assert _mod.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["measurements"]["mine_full"]["elapsed_secs"] == 999.0


def test_zero_duration_floor_boundary():
    # A zero baseline must not collapse the budget to zero (ratio * 0 == 0) —
    # the floor is what keeps a near-instant metric passable.
    assert _mod.budget_for(baseline=0.0, floor=0.25, ratio=10.0) == 0.25

    at_zero = _mod.evaluate_metric("x", actual=0.0, baseline=0.0, floor=0.25, ratio=10.0)
    assert at_zero["passed"] is True

    at_floor = _mod.evaluate_metric("x", actual=0.25, baseline=0.0, floor=0.25, ratio=10.0)
    assert at_floor["passed"] is True

    over_floor = _mod.evaluate_metric("x", actual=0.250001, baseline=0.0, floor=0.25, ratio=10.0)
    assert over_floor["passed"] is False


def test_budget_changed_because_is_required(tmp_path):
    artifact = _write_artifact(tmp_path / "a.json")
    assert _mod.validate_artifact(artifact) == []

    missing_field = dict(artifact)
    del missing_field["budget_changed_because"]
    errors = _mod.validate_artifact(missing_field)
    assert any("budget_changed_because" in e for e in errors)

    empty_field = dict(artifact)
    empty_field["budget_changed_because"] = "   "
    errors = _mod.validate_artifact(empty_field)
    assert any("budget_changed_because" in e for e in errors)


# ── Socket guard covers connect_ex ──────────────────────────────────────────


def test_socket_guard_also_blocks_connect_ex():
    with _mod._socket_guard():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(_mod.NetworkBlockedError):
                s.connect_ex(("example.invalid", 80))
        finally:
            s.close()

    # Guard is restored after the context exits.
    original_connect_ex = socket.socket.connect_ex
    with _mod._socket_guard():
        assert socket.socket.connect_ex is not original_connect_ex
    assert socket.socket.connect_ex is original_connect_ex


# ── _run_update_baseline falls back to DEFAULT_RULES on partial prev artifact ─


def test_update_baseline_falls_back_on_partial_prev_artifact(tmp_path, monkeypatch):
    # Simulate a previous artifact whose metric dict is missing floor/ratio/baseline.
    partial_artifact = {
        "schema_version": _mod.SCHEMA_VERSION,
        "budget_changed_because": "first run",
        "fixture": {"files": ["a.py"], "file_count": 1, "total_bytes": 10},
        "metrics": {name: {} for name in _mod.METRIC_NAMES},  # all fields missing
    }
    artifact_path = tmp_path / "budget.json"
    artifact_path.write_text(__import__("json").dumps(partial_artifact), encoding="utf-8")
    monkeypatch.setattr(_mod, "ARTIFACT_PATH", artifact_path)
    # ROOT must match ARTIFACT_PATH's parent so relative_to() inside the module doesn't raise.
    monkeypatch.setattr(_mod, "ROOT", tmp_path)

    # Monkeypatch run_measurements so this test stays fast.
    fake_measurements = {
        "fixture": {"files": ["a.py"], "file_count": 1, "total_bytes": 10},
        "mine_full": {"elapsed_secs": 0.5, "drawers_filed": 1, "files_processed": 1},
        "mine_incremental_noop": {"elapsed_secs": 0.01, "drawers_filed": 0, "files_skipped": 1},
        "search": {"samples": 5, "median_ms": 1.0, "p95_ms": 1.5, "max_ms": 2.0},
        "read": {"samples": 5, "median_ms": 0.5, "p95_ms": 1.0, "max_ms": 1.5},
        "maintenance": {"elapsed_secs": 0.01, "ok": True, "supported": True},
    }
    monkeypatch.setattr(_mod, "run_measurements", lambda: fake_measurements)

    # Must not raise KeyError; must use DEFAULT_RULES fallbacks.
    rc = _mod.main(["--update-baseline", "--reason", "test partial fallback"])
    assert rc == 0
    written = __import__("json").loads(artifact_path.read_text(encoding="utf-8"))
    assert written["metrics"]["mine_full"]["floor"] == _mod.DEFAULT_RULES["mine_full"]["floor"]
    assert written["metrics"]["mine_full"]["ratio"] == _mod.DEFAULT_RULES["mine_full"]["ratio"]


# ── Committed artifact sanity (fast — reads only) ───────────────────────────


def test_committed_artifact_is_valid():
    """The real committed benchmarks/demo_perf_budgets.json passes validation."""
    data, errors = _mod.load_and_validate_artifact(_mod.ARTIFACT_PATH)
    assert errors == []
    assert data is not None
    assert data["budget_changed_because"].strip() != ""
