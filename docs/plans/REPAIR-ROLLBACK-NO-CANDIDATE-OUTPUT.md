---
slug: REPAIR-ROLLBACK-NO-CANDIDATE-OUTPUT
status: completed
authority: non_authoritative
goal: "Emit one ordered, unambiguous rollback summary when no healthy prior version exists."
risk: medium
risk_note: "The change is confined to CLI rendering, but stream choice, exit status, and recovery wording are operator-facing pre-release safety behavior."
files:
  - path: mempalace_code/cli_commands/maintenance.py
    change: "Reuse cmd_repair's rollback branch to emit the complete no-candidate result once on the outcome-appropriate stream, with explicit mutation and exit meaning."
  - path: tests/test_cli.py
    change: "Strengthen deterministic in-process coverage for dry-run and live no-candidate output, stream routing, mutation wording, recovery guidance, separator count, and exit status."
  - path: tests/test_cli_golden_scenarios.py
    change: "Extend the existing source/installed subprocess harness with a real single-version palace scenario and ordered separate/merged stream assertions."
  - path: docs/quality/scorecard.md
    change: "Refresh the generated human-readable quality scorecard after the source and test changes."
  - path: docs/quality/scorecard.json
    change: "Refresh the generated machine-readable quality scorecard after the source and test changes."
acceptance:
  - id: AC-1
    when: "repair --rollback is run against a palace with no healthy prior version in dry-run and live modes while stdout/stderr are captured separately and with stderr merged into stdout"
    then: "each invocation contains exactly one complete summary ordered as header, mode, no-candidate diagnosis, mutation result, exit meaning, and full-rebuild recovery command, without cross-stream fragments"
  - id: AC-2
    when: "the no-candidate summary is inspected for dry-run and live invocations"
    then: "dry-run states that preview completed with no changes, while live states that rollback was attempted but no restore or full rebuild occurred and the palace remained unchanged"
  - id: AC-3
    when: "no candidate exists for repair --rollback --dry-run and repair --rollback"
    then: "dry-run exits 0 and labels that exit as a completed non-mutating preview; live exits 1 and labels that exit as a failed rollback with the existing full-rebuild command as the next action"
  - id: AC-4
    when: "the direct console executable runs both no-candidate modes against a disposable single-version palace"
    then: "the captured output has one terminal separator block, no adjacent separator-only blocks, and no evidence that an implicit rebuild ran"
out_of_scope:
  - "Changing LanceDB version enumeration, candidate health checks, or rollback selection."
  - "Performing an implicit full rebuild, changing full-rebuild implementation, or weakening backup and health checks."
  - "Changing successful candidate preview, successful restore semantics, unrelated repair failures, or other CLI commands."
  - "Editing backlog metadata, release gates, or publication state."
contract_policy:
  flow: full_spdd
  reason: "This standard pre-release runtime bug changes recovery-command output and failure semantics consumed by humans, agents, pipes, and installed-executable checks."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "No-candidate rollback output must remain a single ordered diagnosis under separate and merged stream capture."
      source: "current backlog contract AC-1 and AC-4"
      acceptance_ids: [AC-1, AC-4]
    - id: REQ-2
      statement: "Dry-run and live no-candidate results must explicitly state whether rollback, restore, or rebuild mutation occurred."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Dry-run no-candidate remains a successful preview and live no-candidate remains a nonzero failed rollback, with each exit meaning present in output."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
  surfaces:
    - name: "Repair rollback human-output contract"
      kind: cli
      paths: ["mempalace_code/cli_commands/maintenance.py"]
      expected_behavior: "cmd_repair emits one complete no-candidate summary on stdout for the successful dry-run outcome and on stderr for the failing live outcome before returning or exiting."
  invariants:
    - id: INV-1
      statement: "recover_to_last_working_version remains the sole rollback selector and mutator, with the existing dry_run argument and result fields unchanged."
      applies_to: ["mempalace_code/cli_commands/maintenance.py"]
    - id: INV-2
      statement: "No-candidate handling never invokes the full-rebuild path; it only prints the existing mempalace-code repair recovery command."
      applies_to: ["mempalace_code/cli_commands/maintenance.py", "tests/test_cli.py", "tests/test_cli_golden_scenarios.py"]
    - id: INV-3
      statement: "Candidate preview, successful restore, missing-palace, unsupported-store, and restore-exception exit behavior remain unchanged."
      applies_to: ["mempalace_code/cli_commands/maintenance.py", "tests/test_cli.py"]
    - id: INV-4
      statement: "The golden CLI harness continues to run from a neutral directory with disposable HOME/XDG state and uses the absolute installed console when MEMPALACE_TEST_INSTALLED_CLI is configured."
      applies_to: ["tests/test_cli_golden_scenarios.py"]
  risks:
    - id: RISK-1
      risk: "Keeping the header on stdout while writing the diagnosis to stderr would preserve the original reordering under pipes."
      mitigation: "Assemble the complete outcome block before emission and assert both separate-stream ownership and true stderr-to-stdout merged order."
    - id: RISK-2
      risk: "Removing only one print could leave duplicate blank or separator-only terminal blocks."
      mitigation: "Give the summary one terminal separator owner and assert occurrence and adjacency constraints in unit and subprocess output."
    - id: RISK-3
      risk: "Wording could imply that the recovery suggestion was executed or that live no-candidate changed storage."
      mitigation: "Use explicit attempted/found/mutated statements and verify row count plus health after both subprocess invocations."
    - id: RISK-4
      risk: "In-process mocks could pass while buffering or console-script behavior still reorders output."
      mitigation: "Retain deterministic unit coverage and add a real subprocess scenario to the existing installed-capable golden suite."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_cli.py::TestRepairRollbackCommand::test_repair_rollback_no_candidate_output_contract -q"
      proves: "A deterministic parameterized CLI test proves dry-run/live stream ownership, exact ordering, mutation statements, recovery guidance, separator uniqueness, and exit codes."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_cli_golden_scenarios.py::test_cli_golden_rollback_no_candidate_output -q"
      proves: "The direct subprocess path creates a single-version palace, exercises separate and merged capture, and proves no restore or rebuild mutation in source mode."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-3
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The canonical exact-wheel installed golden gate runs the same subprocess scenario through the installed mempalace-code executable."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-4
      owner: provider
      command: "python scripts/quality_scorecard.py --check"
      proves: "The repository's existing generated quality artifacts match the changed source and test corpus."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_cli.py::TestRepairRollbackCommand::test_repair_rollback_dry_run_healthy_palace -q"
        proves: "A healthy candidate preview remains non-mutating and returns normally after the renderer is reordered."
        acceptance_ids: [AC-2, AC-3]
      - id: REG-2
        owner: provider
        command: "python -m pytest tests/test_cli.py::TestRepairRollbackCommand::test_repair_rollback_live_restore_exception_exits_1 -q"
        proves: "An exception during restore remains a nonzero failure with its existing degraded-state diagnosis."
        acceptance_ids: [AC-3]
---

## Design Notes

- Reuse `cmd_repair`; keep output assembly local to the rollback branch. Add no renderer helper, response type, storage method, flag, or alternate recovery route.
- Build the rollback summary before emitting it. For no-candidate outcomes, write the complete block once to stdout in dry-run mode and once to stderr in live mode. The inactive stream stays empty for that block, so shell redirection cannot place the diagnosis before its header.
- Preserve the current title and palace line. Order the remaining fields as mode, no-candidate reason, explicit mutation result, explicit exit meaning, existing `Try: mempalace-code repair (full rebuild)` guidance, and one terminal separator.
- Dry-run wording must distinguish candidate search from mutation: the preview ran, no candidate was found, and no restore or rebuild occurred. Live wording must state that rollback was attempted, no candidate was found, and the palace was not modified or rebuilt.
- Keep exit behavior exact: dry-run no-candidate returns normally with status 0; live no-candidate emits the full block and exits 1. The recovery command is advice only.
- Strengthen the existing `TestRepairRollbackCommand` class with one parameterized no-candidate contract test rather than creating a parallel test class. Patch only `recover_to_last_working_version`, record its `dry_run` argument, and assert the full ordered output plus zero duplicate separators.
- Extend `_run_cli` in the golden suite only as needed to support real merged stderr/stdout capture; retain its timeout, offline environment, neutral cwd, and installed-console selection. Do not add a second subprocess harness.
- The golden scenario should create a disposable one-version Lance palace through public CLI operations, run both no-candidate modes, and compare post-command rows/health with pre-command state. Run the live case last because it exits 1; neither case may print rebuild progress such as extraction, backup, or rebuilding messages.
- Command context basis: `pyproject.toml` declares Python 3.11+, pytest, repository-root test discovery, and `mempalace-code = mempalace_code:main`. `tests/test_cli_golden_scenarios.py` already switches from `python -m mempalace_code.cli` to the absolute installed console when `MEMPALACE_TEST_INSTALLED_CLI` is set. `scripts/gate_inventory.py` owns VER-3 byte-for-byte as the configured exact-wheel gate.
- `docs/quality/incident-class-registry.yaml` is absent in this checkout, so this runtime fix has no registry-matched incident-proof block.
- PLAN did not run tests, builds, installed smokes, verification wrappers, or generated-plan validation.
