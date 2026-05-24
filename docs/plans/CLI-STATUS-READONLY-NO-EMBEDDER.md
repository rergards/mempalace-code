---
slug: CLI-STATUS-READONLY-NO-EMBEDDER
goal: "Make mempalace-code status read LanceDB inventory without starting the embedding model"
risk: low
risk_note: "Small CLI read-path change using existing LanceStore read_only support; main risk is drifting missing-palace behavior."
files:
  - path: mempalace_code/mining/orchestrator.py
    change: "Open status stores with read_only=True, avoid filesystem creation for absent palaces, and keep inventory/storage output behavior intact."
  - path: tests/test_miner.py
    change: "Add focused status regressions that fail if LanceStore embedder initialization is called during populated, missing, or empty-palace status reads."
acceptance:
  - id: AC-1
    when: "a populated LanceDB palace is passed to status while LanceStore._get_embedder is patched to raise"
    then: "status prints the drawer count, wing/room inventory, and storage/version metrics without raising the patched embedder failure or printing model-loading text"
  - id: AC-2
    when: "status is run against a missing palace path while LanceStore._get_embedder is patched to raise"
    then: "status reports that no palace was found, does not create the palace directory, and does not touch the embedder"
  - id: AC-3
    when: "status is run against an initialized but empty LanceDB palace while LanceStore._get_embedder is patched to raise"
    then: "status prints a valid zero-drawer inventory without raising the patched embedder failure"
  - id: AC-4
    when: "the CLI open_store(create=False) audit command is run after implementation"
    then: "the output classifies status as fixed and leaves no unreviewed read-only non-search CLI caller with an unqualified writable/default store open"
out_of_scope:
  - "Changing search/query commands that need embeddings for semantic lookup"
  - "Changing mining, import, cleanup, repair, migration, or other write/maintenance mutation paths"
  - "Changing the embedding model, LanceDB schema, storage migration behavior, or MCP read-only store cache"
contract_policy:
  flow: full_spdd
  reason: "Standard bug task touching CLI storage behavior and model-startup side effects"
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The status command must use a LanceDB read-only inventory path and must not initialize the embedding model."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-3]
    - id: REQ-2
      statement: "Missing-palace status handling must remain user-visible and must not create a new palace path as a side effect."
      source: "failure-path guard"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Other CLI open_store(create=False) callers must be audited so the same model-startup issue is not left unreviewed on read-only non-search paths."
      source: "backlog acceptance"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "status inventory"
      kind: "cli"
      paths: ["mempalace_code/mining/orchestrator.py"]
      expected_behavior: "status opens existing LanceDB palaces with read_only=True, reads counts/metadata/storage metrics, and never needs the embedder."
    - name: "status regression tests"
      kind: "internal"
      paths: ["tests/test_miner.py"]
      expected_behavior: "tests patch LanceStore._get_embedder to raise so any accidental model initialization fails deterministically."
  invariants:
    - id: INV-1
      statement: "Populated status output must still include total drawer count, wing/room rows, and LanceDB storage/version metrics."
      applies_to: ["mempalace_code/mining/orchestrator.py"]
    - id: INV-2
      statement: "Search/query paths must continue to initialize embeddings when semantic lookup requires a query vector."
      applies_to: ["mempalace_code/mining/orchestrator.py"]
    - id: INV-3
      statement: "Write-capable store opens must continue to create or migrate schema when commands need mutation."
      applies_to: ["mempalace_code/mining/orchestrator.py"]
  risks:
    - id: RISK-1
      risk: "Using read_only=True can turn a missing or uninitialized table into a stub instead of an exception."
      mitigation: "Add explicit status preflight/empty-table handling and cover missing and empty palaces separately."
    - id: RISK-2
      risk: "A test could pass while model output still leaks from the real CLI path."
      mitigation: "Patch the concrete LanceStore._get_embedder method and assert captured stdout/stderr contains no model-loading markers."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_miner.py -k 'status and no_embedder' -q"
      proves: "populated status reads inventory and metrics without initializing the embedder"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_miner.py -k 'status and missing_palace' -q"
      proves: "missing-palace status reports the absence without creating the path or initializing the embedder"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_miner.py -k 'status and empty_palace' -q"
      proves: "empty initialized LanceDB status remains a valid zero-drawer read without model startup"
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "rg -n \"open_store\\([^\\n]*create=False\" mempalace_code/cli_commands mempalace_code/mining/orchestrator.py mempalace_code/backup.py"
      proves: "CLI create=False callers are visible for the read-only non-search audit and can be classified before handoff"
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_miner.py -k 'status_' -q"
        proves: "existing multi-wing and storage-metric status behavior continues alongside the no-embedder regressions"
        acceptance_ids: [AC-1, AC-3]
      - id: REG-2
        command: "ruff check mempalace_code/mining/orchestrator.py tests/test_miner.py"
        proves: "status implementation and focused tests remain lint-clean"
        acceptance_ids: [AC-1, AC-2, AC-3]
---

## Design Notes

- `LanceStore` already has `read_only=True` support that opens an existing table without schema migration or `_ensure_embedder()`. MCP read tools already route through that mode; the CLI status path should use the same store-opening contract.
- In `status(palace_path)`, check for a missing palace before opening the store so the read-only path does not print a misleading zero-drawer table for a path that does not exist. Do not create directories from status.
- After `open_store(palace_path, create=False, read_only=True)`, handle the LanceDB "directory exists but drawers table is absent" boundary explicitly. Treat an initialized empty table as a valid `0 drawers` inventory, but keep absent/uninitialized palace messaging for a missing table stub.
- Use `count()`, `count_by_pair("wing", "room")`, and `storage_stats()` as today. These are metadata/scan operations and should not call `_embed()` or `_ensure_embedder()`.
- Regression tests should create any populated/empty palace before patching `LanceStore._get_embedder` to raise. The patch should be active only around the `status()` call so setup can use the normal write path.
- Capture both stdout and stderr in no-embedder tests and assert common model-loading markers are absent, including `Loading embedding model`, `Loading weights`, `huggingface`, and `sentence-transformers`.
- Audit CLI `open_store(create=False)` callers with the `VER-4` command. Do not alter search/query paths in this task. If another clearly read-only non-search CLI caller is proven to have the same model-startup behavior, either include the same `read_only=True` fix with a focused regression or record it as a separate backlog item instead of mixing in unrelated maintenance behavior.
