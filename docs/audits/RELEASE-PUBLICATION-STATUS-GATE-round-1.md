slug: RELEASE-PUBLICATION-STATUS-GATE
round: 1
date: 2026-06-11
commit_range: 404491c..HEAD
findings:
  - id: F-1
    title: "check_workflow_run accepts any successful completed run, masking a newer failed run"
    severity: high
    location: "scripts/release_status_gate.py:174"
    claim: >
      The function filtered all completed runs then checked if any had conclusion='success'.
      This means a list like [completed/failure (newest), completed/success (older)] would
      return STATUS_OK because the older success is found first. GitHub's gh run list returns
      runs newest-first, so the most recent completed run must be evaluated exclusively.
      A newer red run followed by an older green run would falsely report the gate as passed.
    decision: fixed
    fix: >
      Replaced the 'any-success-in-window' logic with 'most-recent-completed-run' logic.
      Take completed[0] (newest completed run per gh run list ordering), check its conclusion,
      and return OK only if that single run succeeded. Updated the detail messages accordingly.

  - id: F-2
    title: "Partial-smoke JSON path not asserted in to_dict() roundtrip"
    severity: low
    location: "tests/test_release_status_gate.py:529"
    claim: >
      test_gate_json_output_is_machine_readable_and_surface_complete checked
      result_skip.partial (from the Python object) but not data_skip["partial"] (from the
      serialized dict). GateResult.to_dict() includes 'partial', but the test left the
      serialization path unverified.
    decision: fixed
    fix: "Added assert data_skip[\"partial\"] is True directly after the dict is obtained."

  - id: F-3
    title: "No regression test for stale-success masking scenario"
    severity: medium
    location: "tests/test_release_status_gate.py"
    claim: >
      The Codex review (codex-hardening-round-1.md) confirmed that before the F-1 fix,
      check_workflow_run([failure, success]) returned STATUS_OK for both SURFACE_TESTS and
      SURFACE_PUBLISH. No test existed that would catch a regression back to the old
      any-success logic.
    decision: fixed
    fix: >
      Added test_workflow_stale_success_does_not_mask_newer_failure which injects a runs list
      of [completed/failure (newest), completed/success (older)] and asserts STATUS_FAIL for
      both SURFACE_TESTS and SURFACE_PUBLISH.

totals:
  fixed: 3
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "scripts/release_status_gate.py: check_workflow_run now evaluates only the most recent completed run (completed[0]) instead of any successful completed run in the window"
  - "tests/test_release_status_gate.py: assert data_skip[\"partial\"] is True added to JSON roundtrip test"
  - "tests/test_release_status_gate.py: added test_workflow_stale_success_does_not_mask_newer_failure regression test"

new_backlog: []
