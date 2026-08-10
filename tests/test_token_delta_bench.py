"""Fast unit coverage for benchmarks/token_delta_bench.py fixture-facts machinery.

Covers fixture-fact extraction, retrieval precision, sanitized metadata output, and
drift-warning boundary behavior (BENCHMARK-FIXTURE-FRESHNESS-FACTS AC-1, AC-3, AC-4).
None of these tests mine a project or run the embedding model — mine_project() and
mempalace_search_tokens() are stubbed where the CLI wiring is exercised.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from mempalace_code.language_catalog import searchable_languages

_BENCH_FILE = Path(__file__).resolve().parent.parent / "benchmarks" / "token_delta_bench.py"
_spec = importlib.util.spec_from_file_location("token_delta_bench", _BENCH_FILE)
assert _spec is not None
assert _spec.loader is not None
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def _init_git_repo(root: Path, file_count: int) -> str:
    """Create a small git checkout with `file_count` tracked files. Returns HEAD sha."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    for i in range(file_count):
        (root / f"file_{i}.py").write_text(f"# file {i}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


# ── anonymized_fixture_ref ──────────────────────────────────────────────────


def test_anonymized_fixture_ref_is_stable_and_hides_the_path(tmp_path: Path):
    project = tmp_path / "some-private-customer-repo"
    project.mkdir()

    ref1 = bench.anonymized_fixture_ref(str(project))
    ref2 = bench.anonymized_fixture_ref(str(project))

    assert ref1 == ref2
    assert len(ref1) == 16
    assert "some-private-customer-repo" not in ref1
    assert str(project) not in ref1


def test_anonymized_fixture_ref_differs_across_paths(tmp_path: Path):
    project_a = tmp_path / "repo-a"
    project_b = tmp_path / "repo-b"
    project_a.mkdir()
    project_b.mkdir()

    assert bench.anonymized_fixture_ref(str(project_a)) != bench.anonymized_fixture_ref(
        str(project_b)
    )


# ── git_commit_ref / git_tracked_file_count ─────────────────────────────────


def test_git_helpers_read_real_checkout_facts(tmp_path: Path):
    repo = tmp_path / "checkout"
    sha = _init_git_repo(repo, file_count=3)

    assert bench.git_commit_ref(str(repo)) == sha
    assert bench.git_tracked_file_count(str(repo)) == 3


def test_git_helpers_return_none_for_non_git_directory(tmp_path: Path):
    plain_dir = tmp_path / "not-a-repo"
    plain_dir.mkdir()

    assert bench.git_commit_ref(str(plain_dir)) is None
    assert bench.git_tracked_file_count(str(plain_dir)) is None


# ── retrieval_precision_at_k ─────────────────────────────────────────────────


def test_retrieval_precision_at_k_counts_hits_and_misses():
    query_results = [
        {"expected_files": ["miner.py"], "mempalace_sources": ["/repo/mempalace_code/miner.py"]},
        {"expected_files": ["storage.py"], "mempalace_sources": ["/repo/mempalace_code/other.py"]},
        {
            "expected_files": ["searcher.py"],
            "mempalace_sources": ["/repo/mempalace_code/searcher.py"],
        },
    ]

    assert bench.retrieval_precision_at_k(query_results) == 2 / 3


def test_retrieval_precision_at_k_excludes_queries_without_expected_files():
    query_results = [
        {"expected_files": ["miner.py"], "mempalace_sources": ["/repo/miner.py"]},
        {"expected_files": [], "mempalace_sources": ["/repo/unrelated.py"]},
    ]

    assert bench.retrieval_precision_at_k(query_results) == 1.0


def test_retrieval_precision_at_k_empty_input_is_zero():
    assert bench.retrieval_precision_at_k([]) == 0.0


# ── build_fixture_facts ──────────────────────────────────────────────────────


def test_build_fixture_facts_is_sanitized_and_matches_measured_values(tmp_path: Path):
    repo = tmp_path / "customer-private-checkout"
    sha = _init_git_repo(repo, file_count=5)

    query_results = [
        {
            "expected_files": ["miner.py"],
            "mempalace_sources": ["/repo/miner.py"],
            "mempalace_languages": ["python"],
        },
        {
            "expected_files": ["storage.py"],
            "mempalace_sources": ["/repo/storage.py"],
            "mempalace_languages": ["python", "markdown"],
        },
    ]
    summary = {"median_ratio": 12.5, "mean_ratio": 15.0, "peak_ratio": 30.0}

    facts = bench.build_fixture_facts(str(repo), query_results, 42, 5, summary, 5)

    assert facts["commit"] == sha
    assert facts["tracked_file_count"] == 5
    assert facts["mined_drawer_count"] == 42
    assert facts["supported_language_count"] == len(searchable_languages())
    assert facts["fixture_language_count"] == 2  # {"python", "markdown"}
    assert facts["query_count"] == 2
    assert facts["results_per_query"] == 5
    assert facts["median_ratio"] == 12.5
    assert facts["mean_ratio"] == 15.0
    assert facts["peak_ratio"] == 30.0
    assert facts["retrieval_precision_at_5"] == 1.0
    assert facts["drift_warnings"] == []

    # Sanitization (INV-3): no identifying repo name or local path in the output.
    serialized = json.dumps(facts)
    assert "customer-private-checkout" not in serialized
    assert str(repo) not in serialized


def test_build_fixture_facts_falls_back_to_provided_count_for_non_git_dir(tmp_path: Path):
    plain_dir = tmp_path / "synthetic-fixture"
    plain_dir.mkdir()
    summary = {"median_ratio": 1.0, "mean_ratio": 1.0, "peak_ratio": 1.0}

    facts = bench.build_fixture_facts(str(plain_dir), [], 7, 99, summary, 5)

    assert facts["commit"] is None
    assert facts["tracked_file_count"] == 99  # fallback, since not a git checkout
    assert facts["mined_drawer_count"] == 7


# ── check_fixture_drift ───────────────────────────────────────────────────────


def test_check_fixture_drift_warns_above_threshold():
    current = {"tracked_file_count": 111, "mined_drawer_count": 500}
    baseline = {"tracked_file_count": 100, "mined_drawer_count": 500}

    warnings = bench.check_fixture_drift(current, baseline, threshold_pct=10.0)

    assert len(warnings) == 1
    assert "tracked_file_count" in warnings[0]
    assert "111" in warnings[0]


def test_check_fixture_drift_exact_threshold_is_not_a_warning():
    current = {"tracked_file_count": 110, "mined_drawer_count": 500}
    baseline = {"tracked_file_count": 100, "mined_drawer_count": 500}

    warnings = bench.check_fixture_drift(current, baseline, threshold_pct=10.0)

    assert warnings == []


def test_check_fixture_drift_skips_missing_or_zero_baseline_fields():
    current = {"tracked_file_count": 500, "mined_drawer_count": 10}
    baseline = {"tracked_file_count": 0}  # mined_drawer_count missing entirely

    warnings = bench.check_fixture_drift(current, baseline, threshold_pct=10.0)

    assert warnings == []


# ── CLI wiring: --fixture-facts-out / --baseline-facts (AC-1, AC-3, AC-4) ────


def test_cli_writes_fixture_facts_and_warns_on_drift(monkeypatch, tmp_path: Path):
    repo = tmp_path / "fixture-repo"
    _init_git_repo(repo, file_count=20)
    (repo / "file_0.py").write_text("widget widget widget\n" * 50, encoding="utf-8")

    queries_path = tmp_path / "queries.json"
    queries_path.write_text(
        json.dumps(
            [{"query": "find the widget", "expected_files": ["file_0.py"], "category": "test"}]
        ),
        encoding="utf-8",
    )

    baseline_path = tmp_path / "baseline_facts.json"
    baseline_path.write_text(
        json.dumps({"tracked_file_count": 2, "mined_drawer_count": 5}), encoding="utf-8"
    )

    facts_out_path = tmp_path / "facts_out.json"
    report_out_path = tmp_path / "report.json"

    monkeypatch.setattr(bench, "count_tokens", lambda text: len(text.split()))
    monkeypatch.setattr(bench, "mine_project", lambda *_a, **_kw: (object(), 50))
    monkeypatch.setattr(
        bench,
        "mempalace_search_tokens",
        lambda *_a, **_kw: (10, 1, [str(repo / "file_0.py")], ["python"]),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "token_delta_bench",
            "--project",
            str(repo),
            "--queries",
            str(queries_path),
            "--out",
            str(report_out_path),
            "--fixture-facts-out",
            str(facts_out_path),
            "--baseline-facts",
            str(baseline_path),
            "--drift-threshold-pct",
            "10",
        ],
    )

    bench.main()

    assert facts_out_path.exists()
    facts = json.loads(facts_out_path.read_text())
    assert facts["tracked_file_count"] == 20
    assert facts["mined_drawer_count"] == 50
    assert facts["retrieval_precision_at_5"] == 1.0
    assert len(facts["drift_warnings"]) == 2  # both tracked_file_count and mined_drawer_count

    report = json.loads(report_out_path.read_text())
    assert report["fixture_facts"]["tracked_file_count"] == 20
    assert report["summary"]["peak_ratio"] > 0


def test_cli_omits_fixture_facts_when_flags_absent(monkeypatch, tmp_path: Path):
    """INV-1: default runs (no fixture-facts flags) keep prior output shape."""
    repo = tmp_path / "plain-repo"
    _init_git_repo(repo, file_count=2)

    queries_path = tmp_path / "queries.json"
    queries_path.write_text(
        json.dumps([{"query": "find it", "expected_files": ["file_0.py"], "category": "test"}]),
        encoding="utf-8",
    )
    report_out_path = tmp_path / "report.json"

    monkeypatch.setattr(bench, "mine_project", lambda *_a, **_kw: (object(), 12))
    monkeypatch.setattr(
        bench,
        "mempalace_search_tokens",
        lambda *_a, **_kw: (10, 1, [str(repo / "file_0.py")], ["python"]),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "token_delta_bench",
            "--project",
            str(repo),
            "--queries",
            str(queries_path),
            "--out",
            str(report_out_path),
        ],
    )

    bench.main()

    report = json.loads(report_out_path.read_text())
    assert "fixture_facts" not in report
    assert "peak_ratio" in report["summary"]
