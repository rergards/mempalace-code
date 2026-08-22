---
slug: CLI-CHROMA-RETIREMENT-CLEAN-ERROR
status: completed
authority: non_authoritative
goal: "Render the existing Chroma runtime-retirement exception as one actionable CLI error."
risk: medium
risk_note: "The code change is narrow, but it modifies the shared CLI dispatch boundary used by every command."
files:
  - path: mempalace_code/cli.py
    change: "Catch only ChromaRuntimeRetiredError at command dispatch, print its existing message once to stderr, and exit nonzero without a traceback."
  - path: tests/test_cli.py
    change: "Add CLI-level legacy-palace coverage for clean stderr/exit behavior and regressions for unaffected LanceDB and migrate-storage paths."
acceptance:
  - id: AC-1
    when: "A CLI command opens a palace directory containing only the legacy chroma.sqlite3 marker."
    then: "The command exits nonzero, emits one stderr error, and produces no traceback."
  - id: AC-2
    when: "The CLI renders ChromaRuntimeRetiredError from a legacy Chroma-only palace."
    then: "Stderr includes mempalace-code[chroma-migration] and the exact mempalace-code migrate-storage SRC DST --verify recovery command from the existing exception message."
  - id: AC-3
    when: "A direct storage caller opens an explicit Chroma backend or a Chroma-only palace."
    then: "The call still raises ChromaRuntimeRetiredError with its existing message and performs no storage migration or palace mutation."
  - id: AC-4
    when: "Representative LanceDB CLI behavior and migrate-storage CLI success and failure paths are exercised."
    then: "Their exit behavior, output, dispatch arguments, and storage selection remain unchanged."
  - id: AC-5
    when: "The focused CLI/Chroma regression command and configured complete non-network suite are executed."
    then: "Both exit zero while covering the clean retirement error, direct storage exception, LanceDB boundary, and migration CLI behavior."
out_of_scope:
  - "Changing Chroma/Lance backend detection or ChromaRuntimeRetiredError message text."
  - "Changing the migrate-storage bridge, dependency extras, backup/verification behavior, or runtime backend policy."
  - "Catching arbitrary RuntimeError or other unexpected exceptions at the CLI boundary."
  - "Editing backlog metadata, publishing, versioning, or release finalization."
contract_policy:
  flow: full_spdd
  reason: "Strict release-blocking CLI task at a shared error boundary with migration recovery and direct-storage invariants."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "CLI dispatch must normalize ChromaRuntimeRetiredError into one actionable stderr error and a nonzero exit without a traceback."
      source: "current backlog contract AC-1 and AC-2"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "The normalization must remain exclusive to the CLI boundary so direct storage callers retain the typed exception."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-3
      statement: "LanceDB runtime and migrate-storage CLI behavior must remain unchanged."
      source: "current backlog contract AC-4 and AC-5"
      acceptance_ids: [AC-4, AC-5]
  surfaces:
    - name: "Top-level CLI dispatch"
      kind: cli
      paths: ["mempalace_code/cli.py", "tests/test_cli.py"]
      expected_behavior: "Only the typed Chroma retirement failure is converted to a single stderr error and nonzero SystemExit; successful dispatch and unrelated failures retain existing behavior."
  invariants:
    - id: INV-1
      statement: "ChromaRuntimeRetiredError and CHROMA_RUNTIME_RETIRED_MESSAGE remain owned by storage.py and unchanged."
      applies_to: ["mempalace_code/cli.py", "tests/test_cli.py"]
    - id: INV-2
      statement: "Direct open_store and ChromaStore callers continue receiving ChromaRuntimeRetiredError rather than SystemExit or rendered CLI output."
      applies_to: ["mempalace_code/cli.py", "tests/test_cli.py"]
    - id: INV-3
      statement: "LanceDB selection, stale-marker precedence, and migrate-storage dispatch, backup, verification, and dependency behavior remain unchanged."
      applies_to: ["mempalace_code/cli.py", "tests/test_cli.py"]
  risks:
    - id: RISK-1
      risk: "A broad catch could hide unrelated programming or storage failures behind the retirement message."
      mitigation: "Catch ChromaRuntimeRetiredError by exact type only around dispatch and retain existing exception behavior for every other failure."
    - id: RISK-2
      risk: "Duplicating recovery text in the CLI could drift from the storage-owned migration command or extra."
      mitigation: "Render str(exc) directly and assert the existing exact command and extra in CLI output."
    - id: RISK-3
      risk: "Wrapping too much of main() could alter argparse exits or successful post-command version checks."
      mitigation: "Place the catch at the dispatch call only and exercise unaffected CLI paths."
  verification:
    - id: VER-1
      owner: configured_runner
      command: "python -m pytest tests/ -x -q -m \"not needs_network\""
      proves: "The exact configured non-network suite covers the new CLI error behavior and preserves direct storage, LanceDB, and migration CLI behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_cli.py::TestChromaRuntimeRetiredCli tests/test_cli.py::TestMigrateStorageCommand tests/test_chroma_import_errors.py tests/test_storage_lance.py::TestOpenStoreFactory -q"
        proves: "Focused CLI and storage coverage verifies the clean retirement rendering, exact recovery message, typed direct-call exception, LanceDB boundary, and unchanged migration command."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Import `ChromaRuntimeRetiredError` from `mempalace_code.storage`; keep the message and recovery-command constants storage-owned.
- Wrap only `dispatch[args.command](args)`. On the typed exception, write one `Error: {exc}` line to stderr and raise `SystemExit(1)` without exception chaining so the console entry point cannot emit a traceback.
- Use a real Chroma-only marker fixture through a CLI command whose store open reaches the shared dispatch boundary. Assert nonzero exit, empty/unchanged stdout as appropriate, one stderr error, absence of `Traceback`, and exact recovery strings.
- Retain existing direct-call tests as boundary evidence: storage callers still receive the typed exception, the marker remains present, and no Lance directory is created.
- Keep a representative healthy LanceDB CLI assertion and the existing `TestMigrateStorageCommand` coverage in the focused regression contour. The command runs from the repository root using the Python/pytest setup declared by `pyproject.toml` and CLAUDE.md.
