---
slug: REL-CI-PYTEST-BOUNDED-PARAM-ID
goal: "Give every invalid installed-CLI inventory payload a short stable pytest ID so verbose collection cannot print the oversized payload"
risk: low
risk_note: "The change is limited to test collection metadata in one existing parametrization and preserves all exercised values and assertions."
files:
  - path: tests/test_release_readiness_gate.py
    change: "Wrap the six existing invalid inventory payload cases in pytest.param with concise semantic IDs, including a bounded ID for the oversized-output boundary case."
acceptance:
  - id: AC-1
    when: "pytest collects the installed CLI inventory reconciliation parametrization"
    then: "collection succeeds with exactly six concise, distinct semantic node IDs for the existing invalid payload cases"
  - id: AC-2
    when: "the malformed JSON and structurally invalid inventory cases run by their explicit node IDs"
    then: "each case still exercises the existing fail-closed ValueError behavior and completes without changing the payload under test"
  - id: AC-3
    when: "the payload one byte larger than INSTALLED_CLI_INVENTORY_OUTPUT_LIMIT runs under pytest -v"
    then: "the emitted node ID uses the short oversized-output label, contains none of the repeated payload body, and the boundary case completes"
out_of_scope:
  - "Changing installed CLI inventory parsing, limits, recorder behavior, or release-readiness production code"
  - "Renaming unrelated parametrized tests or globally overriding pytest ID generation"
  - "Changing hosted workflow configuration or pytest verbosity"
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: scope, behavioral impact, verification effort, rollout risk, and removal cost are confined to test metadata in one existing parametrization; no auth, data, migration, provider, or pipeline boundary is touched."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
---

## Design Notes

- Keep `test_installed_cli_inventory_reconciliation_fails_closed` and its six payload values unchanged; represent each entry as `pytest.param(value, id="...")` so the ID remains adjacent to the case it names.
- Use short semantic IDs for malformed JSON, empty members, duplicate members, a nested command, an unsafe command segment, and oversized output. Keep every ID independent of payload size and content.
- Preserve the oversized expression `rrg.INSTALLED_CLI_INVENTORY_OUTPUT_LIMIT + 1`; only its pytest collection label changes.
- Verify collection output separately from focused execution because the hosted failure occurs while pytest formats the verbose node ID before the oversized case runs.
