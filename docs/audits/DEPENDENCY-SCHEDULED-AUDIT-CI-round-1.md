slug: DEPENDENCY-SCHEDULED-AUDIT-CI
round: 1
date: 2026-06-11
commit_range: 9f8e737..HEAD
findings:
  - id: F-1
    title: "Workflow audit step swallows failure — issue creation and final fail never run"
    severity: high
    location: ".github/workflows/dependency-audit.yml:31"
    claim: >
      The audit step runs `python ... current-audit`, then `echo "audit_exit=$?" >>
      "$GITHUB_OUTPUT"`. The `echo` command resets `$?` to 0, so the step always exits 0
      and `steps.audit.outcome` is always `'success'`. The downstream issue-creation and
      fail steps both check `steps.audit.outcome == 'failure'`, so they never run when the
      audit finds actionable findings. Workflow effectively silences all failures.
    decision: fixed
    fix: >
      Restructured the audit step to use `set +e`, capture `rc=$?` from the Python
      command, write `audit_exit=$rc` to GITHUB_OUTPUT, then `exit $rc`. With
      `continue-on-error: true`, GitHub Actions sets `steps.audit.outcome = 'failure'`
      when the step exits nonzero, which correctly triggers the downstream conditions.

  - id: F-2
    title: "Workflow permissions omit contents: read — checkout may fail on private repos"
    severity: high
    location: ".github/workflows/dependency-audit.yml:8"
    claim: >
      The workflow declares `permissions: issues: write` only. In GitHub Actions, explicit
      `permissions` drops all unspecified scopes. `actions/checkout` requires `contents: read`
      to fetch repository source. On private repositories or under strict token settings,
      the checkout step fails before the audit runs.
    decision: fixed
    fix: >
      Added `contents: read` to the workflow permissions block alongside `issues: write`.

  - id: F-3
    title: "Default range-drift querier is a no-op but docs claim range drift is checked"
    severity: medium
    location: "scripts/dependency_upgrade_gate.py:770"
    claim: >
      `_default_range_drift_querier()` returns `[[] for _ in queries]`. The scheduled
      workflow invokes the CLI without injection, so production runs never produce
      `range_drift` findings. The docs at line 186 stated "Checks whether any declared
      direct dependency specifier intersects with an active advisory range (range drift)"
      as if this is unconditionally performed, which is false for the default path.
      Additionally, no test exercised `cmd_current_audit` without injecting
      `range_drift_querier`, leaving the default code path untested.
    decision: fixed
    fix: >
      Updated the `_default_range_drift_querier` docstring to clearly state it is an
      intentional no-op and that range-drift detection requires a custom integration.
      Updated `docs/DEPENDENCY_UPGRADE_GATE.md` to replace the false claim with an
      accurate statement that range-drift findings are only produced when a custom
      range-drift querier is provided. Added
      `test_current_audit_default_range_drift_querier_produces_no_findings` which calls
      `cmd_current_audit` without injecting `range_drift_querier`, verifying the default
      path completes without crashing and produces zero range_drift findings.

totals:
  fixed: 3
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "workflow: add contents: read permission and fix audit step exit code propagation (set +e / rc=$? / exit $rc)"
  - "script: update _default_range_drift_querier docstring to document intentional no-op behavior"
  - "docs: correct DEPENDENCY_UPGRADE_GATE.md range-drift bullet to reflect default behavior"
  - "tests: add test_current_audit_default_range_drift_querier_produces_no_findings for default no-injection path"
  - "scorecard: regenerate docs/quality/scorecard.json and scorecard.md (test count 2368 → 2369)"

new_backlog: []
