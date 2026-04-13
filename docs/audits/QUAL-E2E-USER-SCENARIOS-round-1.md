slug: QUAL-E2E-USER-SCENARIOS
round: 1
date: "2026-04-12"
commit_range: a1a4db3..49ea492
findings:
  - id: F-1
    title: "AC-1 only_manual filter assertion too weak — >= 1 passes even if filter is broken"
    severity: low
    location: "tests/test_e2e.py:114"
    claim: >
      The assertion `assert result["drawer_count"] >= 1` does not verify that
      `write_jsonl(only_manual=True)` correctly excludes mined drawers. The palace
      contains multiple mined drawers plus exactly 1 manually added drawer (chunker_strategy
      "manual_v1"). If the only_manual filter were silently broken and exported all drawers,
      the count would be > 1, but the assertion >= 1 would still pass — giving a false green.
      The import assertion `imported_drawers >= 1` has the same weakness. The correctness of
      the filter is the core thing AC-1 is meant to verify.
    decision: fixed
    fix: >
      Changed `assert result["drawer_count"] >= 1` to `== 1` and
      `assert import_result["imported_drawers"] >= 1` to `== 1`.
      With exactly 1 manual drawer in the palace, an exact count assertion verifies
      that only_manual correctly excludes the multiple mined drawers.

  - id: F-2
    title: "Coverage gap — convo_miner, layers, palace_graph have no e2e scenario tests"
    severity: low
    location: "tests/test_e2e.py (missing scenarios)"
    claim: >
      tests/test_e2e.py covers 7 of 9 key modules listed in CLAUDE.md. Three significant
      modules are untouched by any e2e scenario: convo_miner.py (conversation mining from
      Claude/ChatGPT/Slack exports), layers.py (tiered context loading L0–L3 for local
      models), and palace_graph.py (graph traversal and tunnel detection across wings/rooms).
      These modules have only unit tests. A regression in cross-module integration paths
      (e.g. mine → graph → traverse) would not be caught by the current test suite.
    decision: backlogged
    backlog_slug: QUAL-E2E-REMAINING-MODULES

  - id: F-3
    title: "CI runs @pytest.mark.slow tests on every push across 4 matrix jobs"
    severity: info
    location: ".github/workflows/ci.yml:22"
    claim: >
      The CI pytest command deselects needs_network but not slow:
      `pytest tests/ -v -m "not needs_network"`. The slow marker is documented as
      "skippable in fast CI runs" in pyproject.toml, but the CI doesn't skip it.
      test_large_palace_search_latency (AC-9) mines 500 files and runs 4 times per push
      (3 Python versions + chroma-compat). Locally the full suite takes 47s, which is
      acceptable, but on slower CI hardware or with future slow tests this could compound.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 1
  dismissed: 1

fixes_applied:
  - "tests/test_e2e.py: tighten AC-1 only_manual assertions from >= 1 to == 1 for both export and import counts"

new_backlog:
  - slug: QUAL-E2E-REMAINING-MODULES
    summary: "Add e2e scenario tests (AC-10/11/12) for convo_miner, layers, and palace_graph modules"
