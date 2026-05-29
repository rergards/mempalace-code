verdict: NEEDS_CHANGES

# Plan Review — WATCH-INITIALIZED-ROOT-UX

## Summary

The plan file is empty (0 bytes). There is no reviewable content: no YAML front matter,
no `task_contract:` canvas, no requirements, no file list, no acceptance criteria, no
`verification:` rows, no `regression_plan:`, and no `contract_policy:`. A plan review
cannot pass when the plan document does not exist.

Note: commit `7d43465 docs(WATCH-INITIALIZED-ROOT-UX): plan root watch support` purports to
add this plan, but the working-tree file `docs/plans/WATCH-INITIALIZED-ROOT-UX.md` is empty
on this branch. The plan content is missing or was truncated.

## Verification of emptiness
- `Read docs/plans/WATCH-INITIALIZED-ROOT-UX.md` → harness reported "points to an empty file".
- `Grep` for any character (`.`) in the file → no matches.
- `Grep` for `task_contract|acceptance|verification|regression_plan` in `docs/plans/` → no matches.

gaps:
  - severity: critical
    claim: "The plan file is empty — there is no plan to implement or review."
    evidence: "docs/plans/WATCH-INITIALIZED-ROOT-UX.md (0 bytes; Read reports empty file, Grep returns no content)"
    suggested_fix: "Author the plan document. It must restore/define the full SPDD structure for this task: a clear problem statement (watching an initialized root such as `/srv` works for child `/srv/dev`, but `watch /srv/dev` on the initialized directory itself finds no child projects), the chosen approach (either support watching an initialized root directly, or emit a clear diagnostic naming the correct command), requirements, and the affected file list."
  - severity: high
    claim: "No `task_contract:` canvas present (required for standard plans)."
    evidence: "docs/plans/WATCH-INITIALIZED-ROOT-UX.md front matter — file is empty"
    suggested_fix: "Add the `task_contract:` block to the YAML front matter, listing provider-owned/touched files (e.g. mempalace_code/watcher.py, mempalace_code/cli.py and their tests) and surfaces. Do not list docs/BACKLOG.yaml or archive files as touched/provider-owned files."
  - severity: high
    claim: "No `acceptance:` criteria — nothing observable or testable is defined."
    evidence: "docs/plans/WATCH-INITIALIZED-ROOT-UX.md — file is empty"
    suggested_fix: "Define acceptance criteria as observable behaviors, e.g.: (1) `mempalace-code watch <initialized-root>` either watches that root directly or exits with a clear diagnostic naming the exact correct command; (2) the diagnostic distinguishes 'directory is itself an initialized project' from 'no child projects found'. Each criterion needs a stable `acceptance_ids` handle."
  - severity: high
    claim: "No `verification:` rows linked to acceptance criteria."
    evidence: "docs/plans/WATCH-INITIALIZED-ROOT-UX.md — file is empty"
    suggested_fix: "Add runnable `verification:` rows (pytest invocations against tests/test_watcher.py / CLI tests, and/or real `mempalace-code watch` CLI executions) each linked via `acceptance_ids`. No prose-only or 'check manually' commands for automated/mixed paths."
  - severity: high
    claim: "No `regression_plan:` present despite a behavior-changing requirement (watch on an initialized root changes CLI/watcher behavior)."
    evidence: "docs/plans/WATCH-INITIALIZED-ROOT-UX.md — file is empty; task description changes watch behavior"
    suggested_fix: "Add a `regression_plan:` with runnable `checks` rows linked to every acceptance id, covering the existing behavior (`watch /srv` still discovers child `/srv/dev`) so the new root-handling does not regress child discovery. `applies: false` is not valid here because the task implies a behavior change."
  - severity: high
    claim: "No `contract_policy:` present (required; for full SPDD `sync_gate` must be `required`)."
    evidence: "docs/plans/WATCH-INITIALIZED-ROOT-UX.md — file is empty"
    suggested_fix: "Add `contract_policy:` to the front matter. For a full SPDD plan set `flow: full_spdd` and `sync_gate: required`; for a lite compact plan include an explicit, specific `contract_policy.reason`."
  - severity: high
    claim: "Affected-files list is absent — implementation scope is undefined."
    evidence: "docs/plans/WATCH-INITIALIZED-ROOT-UX.md — file is empty"
    suggested_fix: "Identify the files to change. Based on the codebase guide these are likely `mempalace_code/watcher.py` (watch_and_mine / watch_all discovery logic), `mempalace_code/cli.py` (the `watch` command + diagnostic output), and corresponding tests under `tests/`. Confirm by inspecting the watcher's project-discovery code path before finalizing."
