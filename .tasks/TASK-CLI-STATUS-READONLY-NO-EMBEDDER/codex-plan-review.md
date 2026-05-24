verdict: READY

notes:
  - The plan correctly leverages the existing `LanceStore(read_only=True)` and `open_store(..., read_only=True)` contract (mempalace_code/storage.py:1402-1423), which already short-circuits embedder init and even tolerates a missing `lance/` directory by returning a stub with `_table=None`.
  - `count()`, `count_by_pair()`, and `storage_stats()` (mempalace_code/storage.py:481-485, 683-693, 884-909) all already guard `_table is None`, so the empty-palace AC-3 case is naturally supported without extra branching.
  - The current implementation at mempalace_code/mining/orchestrator.py:594-636 opens the store with `create=False` only — without `read_only=True` — which is exactly what triggers embedder startup; the plan's minimal change correctly targets this site.
  - AC-1/AC-2/AC-3 each have a unique pytest `-k` selector under VER-1/VER-2/VER-3 and a regression sibling via REG-1 using `status_`, plus a ruff regression in REG-2. Acceptance ↔ verification ↔ regression linkage is complete and consistent.
  - The audit scope under VER-4 (`mempalace_code/cli_commands`, `mempalace_code/mining/orchestrator.py`, `mempalace_code/backup.py`) covers every relevant CLI caller in the repo; `mempalace_code/cli.py` has no `open_store` calls, and searcher/layers/palace_graph paths legitimately need the embedder and are correctly declared out of scope.
  - `task_contract`, `contract_policy` (flow: full_spdd, sync_gate: required, verification_path: automated), `regression_plan`, requirements, surfaces, invariants, risks, and verification rows are all present, well-formed, and all command rows are runnable shell commands (pytest / rg). No placeholder or prose-only commands.

gaps: []
