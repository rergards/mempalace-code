---
slug: DIARY-WRITE-REJECT-BLANK-FIELDS
status: completed
authority: non_authoritative
goal: "Reject blank diary agent and entry values before any palace mutation while preserving valid writes."
risk: medium
risk_note: "The change is narrow, but validation order is a mutation-safety contract exercised by source and installed-wheel CLI processes."
files:
  - path: mempalace_code/cli_commands/diary.py
    change: "Validate agent and entry as non-blank required strings before palace-path resolution, wing derivation, or store open."
  - path: tests/test_cli.py
    change: "Extend the existing diary CLI owner with blank and whitespace-only rejection, output, and absent-palace assertions while retaining valid-write coverage."
  - path: tests/test_cli_golden_scenarios.py
    change: "Add direct subprocess coverage that exercises the same rejection and zero-post-state contract against source and the exact installed candidate wheel."
acceptance:
  - id: AC-1
    when: "A fresh CLI process receives an empty or whitespace-only --agent or --entry value for an absent palace path."
    then: "It exits non-zero with a bounded validation error and does not create or open the palace."
  - id: AC-2
    when: "A CLI process writes a diary entry with non-blank agent and entry values."
    then: "The entry is stored with the existing metadata and the existing bounded Verify before retry search command is printed."
  - id: AC-3
    when: "The focused CLI regression suite exercises diary write after the scoped implementation change."
    then: "Only the CLI diary contract changes; MCP diary handlers and dispatch behavior remain outside this task and unchanged."
  - id: AC-4
    when: "The focused CLI owner and exact-wheel installed golden application checks run."
    then: "They prove rejection exit status, stdout and stderr contracts, and zero palace post-state for blank required fields."
out_of_scope:
  - "MCP diary handlers, MCP dispatch, and the blank-required-string contract owned by MCP-REQUIRED-STRINGS-REJECT-BLANK."
  - "Blank topic or wing handling, parser-level required-option behavior, and diary read behavior."
  - "New validator modules, schemas, modes, gates, or backlog metadata changes."
contract_policy:
  flow: full_spdd
  reason: "This standard bug fix changes a pre-mutation CLI boundary and its installed-package release proof."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Blank and whitespace-only diary agent and entry values fail before palace resolution or open."
      source: "Backlog acceptance AC-1"
      acceptance_ids: [AC-1, AC-4]
    - id: REQ-2
      statement: "Valid diary writes retain their stored metadata and bounded verify-before-retry acknowledgement."
      source: "Backlog acceptance AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The implementation remains confined to the CLI diary owner and existing CLI regression owners."
      source: "Backlog scope and acceptance AC-3"
      acceptance_ids: [AC-3]
  surfaces:
    - name: "Diary write CLI handler"
      kind: cli
      paths: [mempalace_code/cli_commands/diary.py]
      expected_behavior: "Reject agent or entry values whose stripped form is empty before resolving or opening the palace; otherwise preserve the existing write and acknowledgement path."
  invariants:
    - id: INV-1
      statement: "Valid diary entries remain verbatim and keep the existing ID, wing, room, topic, metadata, and bounded recovery-command contracts."
      applies_to: [mempalace_code/cli_commands/diary.py]
    - id: INV-2
      statement: "MCP diary handlers and dispatch are not modified by this CLI-only task."
      applies_to: [mempalace_code/mcp_server.py]
  risks:
    - id: RISK-1
      risk: "Validation after configuration or store access could still create palace state for rejected input."
      mitigation: "Place both checks before palace-path resolution and assert the requested palace path remains absent in in-process and subprocess tests."
    - id: RISK-2
      risk: "A source-only test could pass while the shipped console application retains the defect."
      mitigation: "Run the canonical installed-golden wheel command, whose isolated environment invokes the candidate console script from a neutral cwd."
  verification:
    - id: VER-1
      owner: provider_owned
      command: "python -m pytest tests/test_cli.py -q"
      proves: "The complete focused CLI test module covers valid diary writes, empty and whitespace-only rejection, diagnostics, and absent palace state without filtering away sibling CLI cases."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: configured_runner_owned
      command: "python scripts/release_readiness_gate.py --installed-golden-wheel \"$WHEEL\" --json"
      proves: "The canonical install gate builds an isolated candidate environment and runs the golden CLI subprocess suite from a neutral directory, including diary exit, streams, and zero post-state."
      acceptance_ids: [AC-1, AC-2, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner_owned
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The repository's configured non-network suite preserves existing CLI, storage, recovery-output, and MCP behavior around the scoped change."
        acceptance_ids: [AC-2, AC-3]
---

## Design Notes

- Normalize only for the blank predicate with `value.strip()`; retain the original non-blank agent and entry values for wing derivation, verbatim storage, metadata, and recovery output.
- Emit one concise field-specific error to stderr and exit non-zero. Do not print a success acknowledgement or a `search ""` recovery command on rejection.
- Perform both required-field checks before `MempalaceConfig`, `os.path.expanduser`, wing derivation, `open_store(..., create=True)`, UUID generation, or timestamp generation.
- Parameterize agent and entry independently with `""` and whitespace-only values. Assert the requested palace path is absent after every rejected invocation, including repeated attempts.
- Keep the existing successful `TestDiaryWrite` assertions as the happy-path contract. Extend the installed-capable golden scenario with a dedicated direct-process rejection matrix and snapshot or path assertions for zero post-state.
- Command context comes from `pyproject.toml` (pytest is a dev dependency), `scripts/gate_inventory.py` (the exact configured non-network and installed-golden commands), and `scripts/release_readiness_gate.py` (the installed gate runs `tests/test_cli_golden_scenarios.py` against the candidate console script from a neutral cwd).
- Do not edit or import MCP handlers to share this narrow validation; `MCP-REQUIRED-STRINGS-REJECT-BLANK` owns that contract.
