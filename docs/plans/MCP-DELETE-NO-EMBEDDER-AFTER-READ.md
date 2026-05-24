---
slug: MCP-DELETE-NO-EMBEDDER-AFTER-READ
goal: "Let MCP delete tools delete existing Lance rows after read-only cache access without starting the embedder"
risk: medium
risk_note: "Small storage-open change, but it touches Lance schema-open timing and must preserve add/upsert embedding behavior."
files:
  - path: mempalace_code/storage.py
    change: "Open existing Lance tables in write-capable mode without eager embedder initialization; keep embedder use lazy for vector creation and new-table schema creation."
  - path: tests/test_mcp_server.py
    change: "Add real stdio MCP regressions for status-then-delete_drawer/delete_wing under fresh HOME and offline HuggingFace settings, including no model-output assertions."
  - path: tests/test_storage.py
    change: "Add LanceStore regressions proving existing-table get/delete/delete_wing avoid _get_embedder while add/upsert still initialize embeddings."
acceptance:
  - id: AC-1
    when: "a seeded Lance palace is served by python -m mempalace_code.mcp_server --tools status,delete_drawer with MEMPALACE_PALACE_PATH set, fresh HOME, HF_HUB_OFFLINE=1, and TRANSFORMERS_OFFLINE=1, then mempalace_status is called before mempalace_delete_drawer for an existing drawer id"
    then: "delete_drawer returns success, a follow-up status shows one fewer drawer, and captured stdout/stderr contain no HuggingFace or sentence-transformers model-loading markers"
  - id: AC-2
    when: "the same real stdio setup calls mempalace_status before mempalace_delete_wing for an existing wing"
    then: "delete_wing returns success with the expected deleted_count, a follow-up status shows the wing removed, and captured stdout/stderr contain no model-loading markers"
  - id: AC-3
    when: "the real stdio setup calls mempalace_status before deleting a missing drawer id or missing wing"
    then: "the delete tool returns its structured not-found error instead of No palace found or an internal tool error, and no model-loading markers are emitted"
  - id: AC-4
    when: "an existing Lance table is reopened with open_store(create=True) while LanceStore._get_embedder is patched to raise"
    then: "metadata get, delete by id, and delete_wing on existing rows complete without raising the patched embedder failure"
  - id: AC-5
    when: "add or upsert is attempted on an existing Lance table while LanceStore._get_embedder is patched to raise after the store is opened"
    then: "the operation raises the patched embedder failure, proving vector-writing paths still initialize embeddings when documents are written"
out_of_scope:
  - "Changing MCP tool schemas, tool profile selection, or JSON-RPC dispatch semantics"
  - "Changing semantic search, duplicate detection, mining, import, backup, cleanup, or repair behavior"
  - "Changing the default embedding model, benchmark gates, ChromaDB backend behavior, or Lance vector dimensions"
  - "Changing backlog metadata or archiving this task"
contract_policy:
  flow: full_spdd
  reason: "Standard bug task touching MCP runtime storage behavior and offline/model-startup side effects"
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "mempalace_delete_drawer must succeed after an MCP read tool cached a read-only Lance handle, without initializing the embedder."
      source: "backlog acceptance"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "mempalace_delete_wing must have the same no-embedder delete-after-read behavior as delete_drawer."
      source: "backlog acceptance"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Delete not-found cases must remain structured tool errors and must not regress to No palace found after a read-only cache upgrade."
      source: "failure-path guard"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Existing Lance table opens that only need metadata or deletion must not load embeddings, while document writes still compute vectors."
      source: "root-cause boundary"
      acceptance_ids: [AC-4, AC-5]
  surfaces:
    - name: "Lance existing-table open"
      kind: "store"
      paths: ["mempalace_code/storage.py"]
      expected_behavior: "write-capable opens first reuse an existing table without _ensure_embedder; schema creation and vector-writing calls remain the places that need embedding dimensions or vectors."
    - name: "MCP delete-after-read real usage"
      kind: "api"
      paths: ["tests/test_mcp_server.py"]
      expected_behavior: "stdio JSON-RPC tests reproduce status-then-delete under offline fresh HOME and assert successful deletion plus clean output."
    - name: "Storage embedder boundary"
      kind: "internal"
      paths: ["tests/test_storage.py"]
      expected_behavior: "unit-level storage tests isolate the no-embedder get/delete behavior from add/upsert paths that must still embed documents."
  invariants:
    - id: INV-1
      statement: "runtime._get_store(create=True) must still replace a cached read-only MCP store with a write-capable handle for delete tools."
      applies_to: ["mempalace_code/storage.py", "tests/test_mcp_server.py"]
    - id: INV-2
      statement: "Creating a brand-new Lance table must still use the configured embedding model to build the vector schema."
      applies_to: ["mempalace_code/storage.py"]
    - id: INV-3
      statement: "add, upsert, search, and duplicate-check paths must still initialize embeddings when query or document vectors are required."
      applies_to: ["mempalace_code/storage.py", "tests/test_storage.py"]
    - id: INV-4
      statement: "Read-only missing-palace behavior must still return No palace found without creating the palace directory."
      applies_to: ["mempalace_code/storage.py", "tests/test_mcp_server.py"]
  risks:
    - id: RISK-1
      risk: "Moving embedder initialization later could skip schema migration for existing Lance tables."
      mitigation: "Implement existing-table handling so metadata-column migration can be decided from the existing table schema without needing model dimensions; keep new-table creation gated on embedder dimensions."
    - id: RISK-2
      risk: "A direct handler test could miss stderr/stdout noise from the real MCP stdio process."
      mitigation: "Add subprocess stdio JSON-RPC tests with captured output and offline fresh HOME, not only in-process handler calls."
    - id: RISK-3
      risk: "Avoiding embedder startup for delete could accidentally suppress embedding for add/upsert."
      mitigation: "Add storage tests that patch _get_embedder after opening the store and require add/upsert to hit that patch."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_mcp_server.py -k 'delete_after_read_offline_no_embedder and delete_drawer' -q"
      proves: "real stdio status-then-delete_drawer succeeds offline without model output"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_mcp_server.py -k 'delete_after_read_offline_no_embedder and delete_wing' -q"
      proves: "real stdio status-then-delete_wing succeeds offline without model output"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_mcp_server.py -k 'delete_after_read_offline_no_embedder and not_found' -q"
      proves: "missing drawer and wing deletes stay structured and do not become No palace found"
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_storage.py -k 'write_open_no_embedder_delete' -q"
      proves: "existing Lance table get/delete/delete_wing work after write-capable open without _get_embedder"
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_storage.py -k 'existing_table_add_upsert_still_embed' -q"
      proves: "document write paths still initialize embeddings when vectors are required"
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_mcp_server.py -k 'delete_after_read_upgrade or delete_after_read_offline_no_embedder' -q"
        proves: "existing MCP read-cache upgrade behavior remains covered alongside the real stdio no-embedder regressions"
        acceptance_ids: [AC-1, AC-2, AC-3]
      - id: REG-2
        command: "python -m pytest tests/test_storage.py -k 'delete_wing or write_open_no_embedder_delete or existing_table_add_upsert_still_embed' -q"
        proves: "Lance delete behavior and storage embedder boundaries remain compatible"
        acceptance_ids: [AC-4, AC-5]
      - id: REG-3
        command: "ruff check mempalace_code/storage.py tests/test_mcp_server.py tests/test_storage.py"
        proves: "changed source and focused regressions remain lint-clean"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- The current MCP delete tools already call `runtime._get_store(create=True)`, and runtime already discards a cached read-only handle before opening a write-capable one. Keep that MCP boundary; the regression is that `LanceStore` write-capable open eagerly calls `_ensure_embedder()` before it knows whether an existing table can simply be opened for metadata/delete work.
- In `LanceStore._open_or_create()`, try to open the existing Lance table before initializing the embedder. If the table exists, return it after any needed metadata-column compatibility handling that can be derived from `_META_FIELD_SPEC` and the existing schema. Do not compute embedding dimensions just to delete rows.
- Only require `_ensure_embedder()` when creating a new Lance table from scratch or when `_embed()` is called by add/upsert/query-style vector work. `add()` and `upsert()` already call `_embed(documents)`, so they should continue to initialize embeddings lazily at the point vectors are actually needed.
- Keep read-only mode unchanged: `read_only=True` still avoids directory creation, schema migration, and embedder initialization, and missing-palace reads should still become the standard MCP `No palace found` response.
- The stdio tests should seed the palace in the parent process using the deterministic test embedder, then spawn `python -m mempalace_code.mcp_server --tools ...` with `MEMPALACE_PALACE_PATH`, a fresh `HOME`/`USERPROFILE`, `HF_HUB_OFFLINE=1`, and `TRANSFORMERS_OFFLINE=1`. Send JSON-RPC lines for `initialize`, `mempalace_status`, delete, and follow-up status, then assert both JSON results and captured output.
- Use a shared helper in `tests/test_mcp_server.py` for model-output assertions, with markers such as `huggingface`, `sentence-transformers`, `Loading embedding model`, `Loading weights`, and `No sentence-transformers model found`.
- Add lower-level storage tests because they localize the root cause better than MCP tests: reopen an existing table with `_get_embedder` patched to raise, prove `get()`/`delete()`/`delete_wing()` work, then separately prove `add()` and `upsert()` still hit the patched embedder.
