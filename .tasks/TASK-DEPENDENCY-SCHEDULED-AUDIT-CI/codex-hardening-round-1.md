## 1. New Findings

1. **P1 / High - Workflow swallows audit failures, so issue creation and final failure never run.**  
   File: `.github/workflows/dependency-audit.yml:30`  
   The audit step runs `python scripts/dependency_upgrade_gate.py current-audit`, then immediately runs `echo "audit_exit=$?" >> "$GITHUB_OUTPUT"`. Because `echo` is the last command and normally exits 0, the step outcome is success even when `current-audit` returns 1. The downstream notification and fail steps both check `steps.audit.outcome == 'failure'` at lines 44 and 78, so actionable findings will upload artifacts but will not create/update the issue and will not fail the scheduled workflow. This directly violates the task plan's required workflow execution pattern in `docs/plans/DEPENDENCY-SCHEDULED-AUDIT-CI.md:215`.

2. **P1 / High - `permissions` removes `contents: read`, so checkout can fail before the audit starts.**  
   File: `.github/workflows/dependency-audit.yml:8`  
   The workflow sets only `issues: write`. In GitHub Actions, declaring `permissions` makes unspecified token scopes unavailable, while `actions/checkout` at line 15 needs repository contents access when using the default token. On private repos, and commonly under least-privilege token settings, this prevents checkout from reading the repository, so the scheduled audit never reaches the script. Add explicit `contents: read` alongside `issues: write`.

3. **P2 / High - Declared-range drift is only test-injected; the real CLI path never checks it.**  
   File: `scripts/dependency_upgrade_gate.py:770`  
   `_default_range_drift_querier()` returns `[[] for _ in queries]`, and `cmd_current_audit()` uses that default whenever the CLI is run without injection at lines 802-803. The scheduled workflow invokes the CLI directly, so production runs can never report the "newly affected declared range" class promised by the docs (`docs/DEPENDENCY_UPGRADE_GATE.md:186`) and the task contract (`docs/plans/DEPENDENCY-SCHEDULED-AUDIT-CI.md:78`). The unit test at `tests/test_dependency_upgrade_gate.py:1153` only proves injected mock handling, not the hosted/default behavior.

## 2. Known Issues Map Status

- Previous round report `docs/audits/DEPENDENCY-SCHEDULED-AUDIT-CI-round-0.md` is absent in this isolated snapshot, so there were no prior findings to suppress.
- Matching task/backlog context is `docs/plans/DEPENDENCY-SCHEDULED-AUDIT-CI.md`; the findings above map to unsatisfied plan requirements rather than known accepted issues.

## 3. Evidence Reviewed

- Scoped diff: `.tasks/TASK-DEPENDENCY-SCHEDULED-AUDIT-CI/codex-hardening-round-1.diff`
- Scoped files manifest: `.tasks/TASK-DEPENDENCY-SCHEDULED-AUDIT-CI/codex-hardening-round-1-files.txt`
- Task/backlog context: `docs/plans/DEPENDENCY-SCHEDULED-AUDIT-CI.md`
- Touched implementation files: `.github/workflows/dependency-audit.yml`, `scripts/dependency_upgrade_gate.py`, `tests/test_dependency_upgrade_gate.py`, `docs/DEPENDENCY_UPGRADE_GATE.md`, `docs/dependency-audit-allowlist.json`

## 4. Residual Risks

- Hosted GitHub Actions behavior was reviewed statically only; no live `workflow_dispatch` run was available in this snapshot.
- The snapshot omits `pyproject.toml` and `uv.lock`, so dependency group shape and actual resolver surfaces could not be verified against the live project metadata.

## 5. Convergence Recommendation

Do not converge yet. Fix the workflow status propagation and token permissions first, then replace the range-drift stub with a real default implementation or remove the production claim and acceptance coverage for that class.

## 6. Suggested Claude Follow-Up

- In the workflow, capture the audit exit code into an output and preserve it as a failure signal, for example `set +e`, run the audit, save `rc=$?`, write `audit_exit=$rc`, then `exit "$rc"` with `continue-on-error: true`; gate notification/final failure on the saved nonzero output or reliable failure status.
- Add `contents: read` to workflow permissions.
- Implement a real default range-drift OSV query/intersection path, and add a test that exercises `main(["current-audit", ...])` without injecting `range_drift_querier` so the scheduled/default path cannot silently regress to a no-op.
