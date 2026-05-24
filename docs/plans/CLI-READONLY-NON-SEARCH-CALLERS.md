---
slug: CLI-READONLY-NON-SEARCH-CALLERS
goal: "Finish the read-only non-search CLI/MCP no-embedder audit"
risk: medium
risk_note: "Several small store-open changes span CLI, backup, and MCP tests; missing-palace and write-path boundaries must stay explicit."
files:
  - path: mempalace_code/cli_commands/maintenance.py
    change: "Open health and repair --rollback --dry-run stores with read_only=True while keeping cleanup, repair live rollback, and full repair writable."
  - path: mempalace_code/cli_commands/query.py
    change: "Open read stores with read_only=True and use read_only only for compress --dry-run; keep live compress writable because it upserts embeddings."
  - path: mempalace_code/cli_commands/export_import.py
    change: "Open export stores with read_only=True and keep import writable."
  - path: mempalace_code/backup.py
    change: "Open the metadata-count store in create_backup with read_only=True while preserving archive creation behavior."
  - path: mempalace_code/mcp/tools/write.py
    change: "Open delete tools with create=True so writable MCP paths do not accidentally use the read-only runtime store handle."
  - path: tests/test_cli.py
    change: "Add focused no-embedder CLI regressions for health, read, compress --dry-run, repair rollback dry-run, and live compress write behavior."
  - path: tests/test_export.py
    change: "Add export regressions proving normal and --with-embeddings exports read existing LanceDB data without initializing the embedder."
  - path: tests/test_backup.py
    change: "Add create_backup metadata regressions proving backup counts/wings are collected without initializing the embedder."
  - path: tests/test_mcp_server.py
    change: "Add MCP no-embedder coverage for file_context, mempalace_read, diary_read, and delete-after-read write upgrade behavior."
  - path: tests/test_cli_command_modules.py
    change: "Add a source-audit regression that inventories direct CLI/MCP open_store(create=False) callers and classifies intentional writable or search-dependent exceptions."
acceptance:
  - id: AC-1
    when: "a populated LanceDB palace is used by CLI health, read, export, backup create, compress --dry-run, and repair --rollback --dry-run while LanceStore._get_embedder is patched to raise after seeding"
    then: "each command returns its expected report, slice, archive, export, or dry-run output without raising the patched embedder failure or printing model-loading text"
  - id: AC-2
    when: "read-only CLI commands are pointed at a missing or uninitialized palace path while LanceStore._get_embedder is patched to raise"
    then: "they keep their no-palace or zero-export behavior, do not create the missing palace directory as a side effect, and do not initialize the embedder"
  - id: AC-3
    when: "live write-capable paths run after read-only opens, including compress without --dry-run and MCP delete tools after a cached read call"
    then: "the write operation still succeeds through a write-capable store handle instead of failing because a read-only handle was reused"
  - id: AC-4
    when: "MCP non-search read tools file_context, mempalace_read, and diary_read read a populated LanceDB palace while LanceStore._get_embedder is patched to raise"
    then: "the tools return the expected chunks, line slices, and diary entries without initializing the embedder"
  - id: AC-5
    when: "the read-only non-search caller inventory regression is run after implementation"
    then: "remaining unqualified create=False store opens are limited to documented writable, search/embedding-dependent, or already-covered status/layers/graph paths, with no duplicate implementation scope for CLI-LAYERS-GRAPH-READONLY-NO-EMBEDDER"
out_of_scope:
  - "Changing semantic search, code search, duplicate checks, Layer3 search, or architecture explain-subsystem paths that need query embeddings."
  - "Changing mining, import, cleanup, live repair, migration, restore, or other write-heavy maintenance behavior beyond keeping their store opens classified."
  - "Changing the embedding model, LanceDB schema, schema migration behavior, or storage read_only implementation."
  - "Reworking the previous CLI-STATUS-READONLY-NO-EMBEDDER or CLI-LAYERS-GRAPH-READONLY-NO-EMBEDDER source changes."
contract_policy:
  flow: full_spdd
  reason: "Standard storage-reliability task touching CLI/MCP store-open behavior and model-startup side effects"
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Safe read-only non-search CLI paths must use LanceStore read_only=True and must not initialize the embedding model."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "Writable or embedding-dependent paths must remain writable or explicitly classified instead of being mechanically converted."
      source: "backlog acceptance"
      acceptance_ids: [AC-3, AC-5]
    - id: REQ-3
      statement: "MCP non-search read tools must be covered by no-embedder regressions through the existing runtime read-only store path."
      source: "backlog acceptance"
      acceptance_ids: [AC-4]
    - id: REQ-4
      statement: "The implementation must confirm this task does not duplicate the already archived layers/graph no-embedder work."
      source: "backlog acceptance"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "maintenance CLI read paths"
      kind: "cli"
      paths: ["mempalace_code/cli_commands/maintenance.py", "tests/test_cli.py"]
      expected_behavior: "health and rollback dry-run use read_only=True for metadata/version reads; cleanup and live repair remain writable."
    - name: "query CLI read and dry-run paths"
      kind: "cli"
      paths: ["mempalace_code/cli_commands/query.py", "tests/test_cli.py"]
      expected_behavior: "read and compress --dry-run avoid embedder startup while live compress continues to upsert compressed drawers."
    - name: "export and backup read paths"
      kind: "cli"
      paths: ["mempalace_code/cli_commands/export_import.py", "mempalace_code/backup.py", "tests/test_export.py", "tests/test_backup.py"]
      expected_behavior: "export and backup metadata collection scan stored rows without schema migration or model initialization."
    - name: "MCP read and write boundaries"
      kind: "api"
      paths: ["mempalace_code/mcp/tools/write.py", "tests/test_mcp_server.py"]
      expected_behavior: "read tools continue through runtime read_only=True, while delete tools request create=True so write operations are not accidentally read-only."
    - name: "caller inventory"
      kind: "internal"
      paths: ["tests/test_cli_command_modules.py"]
      expected_behavior: "a focused audit test lists direct create=False store opens and forces intentional classification of remaining writable/search exceptions."
  invariants:
    - id: INV-1
      statement: "Search and duplicate-detection paths may still initialize embeddings because query vectors are required."
      applies_to: ["mempalace_code/cli_commands/query.py", "tests/test_cli_command_modules.py"]
    - id: INV-2
      statement: "Commands that mutate store contents must still use write-capable handles and may create or migrate schema when needed."
      applies_to: ["mempalace_code/cli_commands/maintenance.py", "mempalace_code/cli_commands/query.py", "mempalace_code/mcp/tools/write.py"]
    - id: INV-3
      statement: "Missing-palace read-only commands must not create palace directories merely to report absence or produce an empty export."
      applies_to: ["mempalace_code/cli_commands/maintenance.py", "mempalace_code/cli_commands/query.py", "mempalace_code/cli_commands/export_import.py", "mempalace_code/backup.py"]
    - id: INV-4
      statement: "Existing status, layers, and palace graph read-only fixes remain owned by their completed tasks and are not reworked here."
      applies_to: ["tests/test_cli_command_modules.py"]
  risks:
    - id: RISK-1
      risk: "read_only=True returns a missing-table stub, which can hide missing-palace behavior if callers do not guard it."
      mitigation: "Add missing/uninitialized palace tests and keep explicit no-palace handling where user-visible behavior depends on it."
    - id: RISK-2
      risk: "A mechanical conversion could break commands that later upsert, delete, recover, or compact store data."
      mitigation: "Use conditional read_only for dry-run-only flows, switch delete tools to create=True, and cover write-after-read behavior."
    - id: RISK-3
      risk: "The audit could overlap the already completed layers/graph task and cause redundant source churn."
      mitigation: "Inventory previous status/layers/graph surfaces as already covered and keep this implementation focused on remaining direct CLI/MCP callers."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_cli.py -k 'readonly_non_search_no_embedder or compress_live_remains_writable' -q"
      proves: "CLI health, read, compress dry-run, repair rollback dry-run, missing-palace boundaries, and live compress write behavior match AC-1 through AC-3"
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-2
      command: "python -m pytest tests/test_export.py -k 'readonly_no_embedder' -q"
      proves: "export reads stored drawers and optional raw vectors without initializing the embedder"
      acceptance_ids: [AC-1]
    - id: VER-3
      command: "python -m pytest tests/test_backup.py -k 'readonly_no_embedder' -q"
      proves: "create_backup collects drawer count and wing metadata without initializing the embedder"
      acceptance_ids: [AC-1]
    - id: VER-4
      command: "python -m pytest tests/test_mcp_server.py -k 'readonly_non_search_no_embedder or delete_after_read_upgrade' -q"
      proves: "MCP file_context, mempalace_read, diary_read, and delete-after-read write behavior avoid accidental embedder startup or read-only handle reuse"
      acceptance_ids: [AC-3, AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_cli_command_modules.py -k 'readonly_non_search_inventory' -q"
      proves: "the direct store-open inventory is classified and excludes duplicate layers/graph implementation scope"
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_cli.py tests/test_export.py tests/test_backup.py tests/test_mcp_server.py -k 'read_command or export or backup_metadata or file_context or read_slice or diary_read or delete' -q"
        proves: "existing user-facing read/export/backup/MCP behaviors stay compatible around the focused no-embedder changes"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-2
        command: "ruff check mempalace_code/cli_commands/maintenance.py mempalace_code/cli_commands/query.py mempalace_code/cli_commands/export_import.py mempalace_code/backup.py mempalace_code/mcp/tools/write.py tests/test_cli.py tests/test_export.py tests/test_backup.py tests/test_mcp_server.py tests/test_cli_command_modules.py"
        proves: "changed source and focused tests remain lint-clean"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Current completed coverage:
  - `CLI-STATUS-READONLY-NO-EMBEDDER` already moved `mempalace_code/mining/orchestrator.py::status()` to `read_only=True`.
  - `CLI-LAYERS-GRAPH-READONLY-NO-EMBEDDER` already moved `mempalace_code/layers.py` metadata reads and `mempalace_code/palace_graph.py` direct graph reads to `read_only=True`, with MCP graph regression coverage.
- Remaining safe direct CLI conversions:
  - `cmd_health()` only probes table metadata/data fragments through `health_check()`.
  - `cmd_read()` only calls `reader.read_slice()` over stored documents/metadata.
  - `cmd_export()` only iterates stored rows, including `--with-embeddings`, which reads the stored vector column and does not compute new embeddings.
  - `create_backup()` only opens the store for metadata counts before creating the tarball.
  - `cmd_compress()` is safe only for `--dry-run`; live mode upserts compressed drawers and must stay write-capable.
  - `cmd_repair --rollback --dry-run` is safe as a version-walk probe; live rollback and full rebuild must stay write-capable.
- Remaining MCP read tools already use `runtime._get_store(create=False)`, which opens `read_only=True`; add explicit no-embedder tests for `mempalace_file_context`, `mempalace_read`, and `mempalace_diary_read` because they were not part of the layers/graph task.
- `mempalace_delete_drawer` and `mempalace_delete_wing` are write tools but currently call `_get_store()` without `create=True`. Change them to `create=True` so a previous read-only call cannot leave deletion on a read-only handle.
- Keep search/embedding-dependent paths classified, not converted: CLI `search`, `searcher.py`, MCP `mempalace_search`, `mempalace_code_search`, `mempalace_check_duplicate`, Layer3 search, and architecture `tool_explain_subsystem()`.
- For no-embedder regressions, seed any populated palace before patching `LanceStore._get_embedder` to raise. Capture stdout and stderr and assert common model-loading markers are absent.
- The inventory regression should be intentionally small: inspect direct `open_store(create=False)` call sites in `mempalace_code/cli_commands`, `mempalace_code/backup.py`, `mempalace_code/searcher.py`, `mempalace_code/layers.py`, `mempalace_code/palace_graph.py`, and MCP runtime/tools, then assert each remaining unqualified caller is classified as writable, search-dependent, or already covered by the archived status/layers/graph tasks.
