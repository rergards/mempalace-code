## 1. New Findings

1. **P2 - High confidence - `mempalace_code/cli.py:393`**
   `mine-all` treats uninitialized projects as fatal duplicate-wing collisions. `project_entries` includes every detected project, but the duplicate guard builds `wing_to_paths` before the later `if not entry["initialized"]` skip at `mempalace_code/cli.py:423`. A parent directory with one initialized project and one uninitialized folder/clone resolving to the same wing now exits 1 before mining anything, even though the uninitialized project would never be mined and cannot corrupt the palace. This regresses the documented "sync initialized repos" behavior and can block a whole batch because of a skipped project. Restrict the fatal duplicate check to initialized entries, or apply the uninitialized skip before collision fatality.

2. **P3 - Medium confidence - `tests/test_cli.py:1314` / `tests/test_miner.py:2822`**
   AC-5 is not actually covered. The plan says the same-relative-filename case should prove resulting search/code-search output has two hits with distinct wing names and full `source_file` paths, but the CLI test only verifies two mocked `mine()` calls with different `wing_override` values, and the miner test only compares two manually constructed path strings. A regression in drawer IDs, stored metadata, or search filtering for `src/settings.py` across repos would still pass. Add an integration-level regression that mines both repos into a temp palace and asserts stored/searchable metadata contains both wings and distinct source files.

## 2. Known Issues Map Status

- No previous report found at `docs/audits/FUT-MULTI-REPO-round-0.md`.
- Matching backlog/context found only in `docs/plans/FUT-MULTI-REPO.md`.
- No findings were suppressed as duplicates.

## 3. Evidence Reviewed

- Scoped diff: `.tasks/TASK-FUT-MULTI-REPO/codex-hardening-round-1.diff`
- Scoped file manifest: `.tasks/TASK-FUT-MULTI-REPO/codex-hardening-round-1-files.txt`
- Feature plan: `docs/plans/FUT-MULTI-REPO.md`
- Touched implementation files: `mempalace_code/cli.py`, `mempalace_code/miner.py`, `mempalace_code/watcher.py`
- Touched tests: `tests/test_cli.py`, `tests/test_miner.py`, `tests/test_watcher.py`
- Docs: `README.md`

Targeted pytest was attempted with and without `PYTHONPATH="$PWD"`, but collection imported an installed package copy from `/Users/rerg/dev/mempalace` instead of the isolated snapshot, so the run was not usable as verification evidence for this diff.

## 4. Residual Risks

- I did not expand into storage/search implementation beyond the touched-path acceptance context.
- `mine-all --dry-run` still returns success before duplicate-wing validation, so dry-run can differ from real execution on duplicate batches. I did not elevate this because it does not mine or corrupt data, but it is worth considering while touching the duplicate guard.

## 5. Convergence Recommendation

Do not converge yet. Fix the initialized-only duplicate handling in `cmd_mine_all`, then add the AC-5 integration regression if the feature gate requires proof of cross-repo stored/searchable separation.

## 6. Suggested Claude Follow-Up

- Move `mine-all` duplicate-wing validation to operate only on entries that will be mined, while preserving fatal duplicate handling for initialized projects before any `mine()` call.
- Add a regression with one initialized duplicate and one uninitialized duplicate to prove the initialized project still mines and the uninitialized project is skipped.
- Replace or supplement the AC-5 tests with a temp-palace mine/search assertion over two repos containing the same relative filename.
