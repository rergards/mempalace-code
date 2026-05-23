## 1. New Findings

1. **P1 / High - Bulk invalidation helpers still accept invalid and inverted `ended` values.**  
   `mempalace_code/knowledge_graph.py:265` validates only the primary `invalidate()` path; the related helpers at `invalidate_by_source_file()`, `invalidate_by_predicates()`, `invalidate_arch_by_project_root()`, and `invalidate_legacy_arch_ns_project_for_wing()` still assign `ended` directly to `valid_to` before any parser/window check. This violates the task contract that KG `ended` inputs reject invalid temporal strings and that invalidations reject inverted windows before mutation. Reproduction in this snapshot: each helper accepted `ended="last month"` without raising.

2. **P2 / Medium - Date-only `valid_to` rows are excluded for same-day UTC datetime `as_of` queries.**  
   `mempalace_code/knowledge_graph.py:83` normalizes a date to midnight UTC, then `_in_window()` compares `as_of > valid_to` at `mempalace_code/knowledge_graph.py:119`. A row with `valid_from="2026-05-10", valid_to="2026-05-10"` is visible for `as_of="2026-05-10"` but not for `as_of="2026-05-10T12:00:00Z"`. That is a likely contract drift for the feature's mixed date/datetime support and inclusive valid-to boundary behavior for legacy date rows.

3. **P2 / High - Scoped verification cannot run because required pytest fixtures are outside the manifest.**  
   `tests/test_knowledge_graph.py:147` and `tests/test_mcp_server.py:614` depend on fixtures such as `kg`, `seeded_kg`, `config`, and `palace_path`, but the scoped files manifest contains only the two implementation files and two test files, and this isolated snapshot has no `conftest.py`. Running the plan's targeted pytest command produced six setup errors for missing fixtures, so Claude cannot prove the acceptance checks from the scoped artifact as-is.

## 2. Known Issues Map Status

- Previous audit report `docs/audits/UPSTREAM-KG-TEMPORAL-VALIDATION-round-0.md` was not present.
- Matching backlog context found only in `docs/plans/UPSTREAM-KG-TEMPORAL-VALIDATION.md`.
- No duplicate findings were suppressed from a prior audit.

## 3. Evidence Reviewed

- Scoped diff: `.tasks/TASK-UPSTREAM-KG-TEMPORAL-VALIDATION/codex-hardening-round-1.diff`
- Scoped files manifest: `.tasks/TASK-UPSTREAM-KG-TEMPORAL-VALIDATION/codex-hardening-round-1-files.txt`
- Matching plan/backlog context: `docs/plans/UPSTREAM-KG-TEMPORAL-VALIDATION.md`
- Touched files inspected: `mempalace_code/knowledge_graph.py`, `mempalace_code/mcp/tools/kg.py`, `tests/test_knowledge_graph.py`, `tests/test_mcp_server.py`
- Targeted verification attempted:
  - `python -m pytest tests/test_knowledge_graph.py::TestTemporalValidation tests/test_mcp_server.py::TestKGTools::test_kg_add_stores_full_window_and_source_metadata tests/test_mcp_server.py::TestKGTools::test_kg_tools_reject_invalid_temporal_arguments_before_write -q`
  - Result: failed at setup with missing fixtures (`kg`, `config`, etc.) in this scoped snapshot.
- Targeted reproductions:
  - Bulk invalidation helpers accepted `ended="last month"`.
  - Date-only same-day window returned count `1` for date `as_of` and count `0` for same-day datetime `as_of`.

## 4. Residual Risks

- I did not scan unrelated repo areas or non-scoped implementation paths.
- The full regression suite could not be evaluated in this isolated snapshot because the fixture provider is absent.
- The date-vs-datetime boundary finding depends on intended date-only semantics; the current tests do not specify same-day datetime behavior for date-only `valid_to`.

## 5. Convergence Recommendation

Do not converge yet. Fix the bulk invalidation validation gap and make the scoped verification artifact runnable. Clarify or test same-day datetime behavior for date-only `valid_to` before closing the mixed date/datetime risk.

## 6. Suggested Claude Follow-Up

- Route all KG invalidation helpers that accept `ended` through the same temporal parser, and compare `ended` against each affected active row's `valid_from` before update.
- Add regression tests for invalid and inverted `ended` on bulk invalidation helpers.
- Decide whether date-only `valid_to` means midnight or end-of-day when queried with a UTC datetime, then encode that behavior in `_as_comparable()` or `_in_window()` tests.
- Include the pytest fixture provider in the scoped files manifest, or make the targeted tests self-contained for isolated verification.
