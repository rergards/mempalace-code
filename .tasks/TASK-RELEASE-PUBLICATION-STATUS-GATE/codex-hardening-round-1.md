## New Findings

1. **P1 / High - Workflow gate can pass on stale successful runs after a newer failure.**  
   `scripts/release_status_gate.py:174` filters all completed runs from the `gh run list` response and `scripts/release_status_gate.py:175-179` returns OK if any completed run in the last 10 succeeded. The release skill promises the "most recent completed run" must be green for both Tests and Publish to PyPI, so a newer failed completed run followed by an older successful run will still mark the surface OK. Reproducer against the current helper returned `ok workflow 'Tests' has a successful completed run` for `[failure, success]`. This can falsely allow "shipped" status after a red hosted workflow.

## Known Issues Map Status

- Previous round report `docs/audits/RELEASE-PUBLICATION-STATUS-GATE-round-0.md`: not present in this snapshot.
- Matching task/backlog context reviewed: `docs/plans/RELEASE-PUBLICATION-STATUS-GATE.md`.
- No duplicate known issue suppressed; the workflow freshness problem is current and directly conflicts with the touched release-skill wording.

## Evidence Reviewed

- Scoped diff: `.tasks/TASK-RELEASE-PUBLICATION-STATUS-GATE/codex-hardening-round-1.diff`.
- Scoped file manifest: `.tasks/TASK-RELEASE-PUBLICATION-STATUS-GATE/codex-hardening-round-1-files.txt`.
- Touched implementation: `scripts/release_status_gate.py`.
- Touched tests: `tests/test_release_status_gate.py`.
- Touched release workflow docs: `.claude/skills/release/SKILL.md`.
- Relevant plan/backlog context: `docs/plans/RELEASE-PUBLICATION-STATUS-GATE.md`.
- Verification run: `python -m pytest tests/test_release_status_gate.py -q` passed locally (`8 passed in 0.27s`).
- Targeted probe: `check_workflow_run(...)` returned OK for a completed failed run followed by a completed successful run.

## Residual Risks

- I did not perform live GitHub, PyPI, or pip-install publication checks; this was a scoped implementation review.
- The focused tests pass, but they do not cover completed-run ordering or stale-success masking.

## Convergence Recommendation

Do not converge yet. Fix `check_workflow_run` so it evaluates the most recent completed run, not any successful completed run in the result window, and add a regression test where the newest completed run fails while an older completed run succeeds.

## Suggested Claude Follow-Up

- Update workflow parsing to select the first/latest completed run from the `gh run list` result, or request/sort by a stable timestamp/id field before evaluating conclusion.
- Add tests for `[completed failure, completed success]` returning `fail` for both `SURFACE_TESTS` and `SURFACE_PUBLISH`.
- Rerun `python -m pytest tests/test_release_status_gate.py -q` and the release-skill `rg` acceptance check.
