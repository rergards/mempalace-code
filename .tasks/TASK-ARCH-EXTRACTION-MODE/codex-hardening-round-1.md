## 1. New Findings

### P1 / High - Disabling architecture mode leaves old architecture facts active

`mempalace_code/miner.py:3586`

The architecture cleanup is gated behind `if arch_cfg.get("enabled", True)`, so when a project is mined once with architecture enabled/defaults and later mined with `architecture.enabled: false`, the miner skips both `kg.invalidate_by_predicates(...)` and `run_arch_pass(...)`. Existing active `is_pattern`, `is_layer`, `in_namespace`, and `in_project` triples therefore remain queryable even though the config now disables the feature. This is user-visible stale KG data and contradicts the documented/plan behavior that `enabled: false` disables the pass.

Suggested fix: still expire `ARCH_PREDICATES` when KG is available and `limit == 0`, then only re-emit when enabled. Add a regression that mines a service with default config, changes `mempalace.yaml` to `architecture: {enabled: false}`, re-mines, and asserts incoming `Service` no longer returns current architecture facts.

## 2. Known Issues Map Status

No previous round report was present at `docs/audits/ARCH-EXTRACTION-MODE-round-0.md`, so no duplicate findings were suppressed from an earlier audit. The matching task plan was reviewed; the finding above is not listed as an accepted limitation.

## 3. Evidence Reviewed

- Scoped diff: `.tasks/TASK-ARCH-EXTRACTION-MODE/codex-hardening-round-1.diff`
- Scoped files manifest: `.tasks/TASK-ARCH-EXTRACTION-MODE/codex-hardening-round-1-files.txt`
- Implementation files: `mempalace_code/architecture.py`, `mempalace_code/knowledge_graph.py`, `mempalace_code/miner.py`
- Tests/docs in scope: `tests/test_architecture_extraction.py`, `tests/test_mcp_server.py`, `docs/plans/ARCH-EXTRACTION-MODE.md`, `README.md`, `CHANGELOG.md`
- Test attempt: `pytest` was not on PATH; `python -m pytest -q tests/test_architecture_extraction.py tests/test_mcp_server.py::TestKGTools::test_kg_query_arch_facts_queryable` failed during collection because this isolated snapshot resolves `mempalace_code` to an installed package outside the scoped snapshot, which does not contain the new `architecture` module.

## 4. Residual Risks

- Full runtime verification was blocked by the isolated snapshot import-path issue above.
- I did not scan unrelated repo areas or unscoped CLI packaging paths.

## 5. Convergence Recommendation

Do not converge yet. Fix the stale-fact behavior for `architecture.enabled: false` and add the regression described above; then rerun the targeted architecture tests in a full repo checkout where the local package import path is intact.

## 6. Suggested Claude Follow-Up

Move architecture predicate invalidation outside the enabled guard in `mine()` while keeping emission behind the guard. Add a mining integration test that toggles `architecture.enabled` from omitted/default to `false` and verifies no current architecture facts remain.
