verdict: READY

notes:
  - task_contract present with mode=standard; contract_policy.flow=full_spdd, sync_gate=required, verification_path=automated.
  - All AC-1..AC-5 are linked from both verification rows (VER-1..VER-5) and regression_plan.checks rows (REG-1, REG-2).
  - All verification and regression commands are runnable pytest / ruff invocations against existing test files (`tests/test_cli.py`, `tests/test_export.py`, `tests/test_backup.py`, `tests/test_mcp_server.py`, `tests/test_cli_command_modules.py`).
  - Files list is consistent with the actual `open_store(create=False)` inventory in the codebase: `cli_commands/maintenance.py` (health/rollback dry-run), `cli_commands/query.py` (read, compress dry-run), `cli_commands/export_import.py` (export), `backup.py` (metadata), `mcp/tools/write.py` (delete tools currently call `runtime._get_store()` without `create=True`).
  - Plan correctly classifies search/embedding-dependent and write-heavy paths as out-of-scope (Layer3 search at `layers.py:265,321`, `searcher.py:35,114,291`, cleanup, live compress, live repair, mining).
  - RISK-1/INV-3 explicitly address the missing-palace stub returned by `read_only=True` so callers that print "No palace found" via Exception branches must preserve that behavior; AC-2 forces a regression for that boundary.
  - The MCP read tools (`tool_file_context`, `tool_read`, `tool_diary_read`) already go through `runtime._get_store()` (read-only), matching the design notes' claim that only test coverage is needed there; no source change required.
  - No backlog metadata files (e.g., `docs/BACKLOG.yaml`) appear in files / touched_files / surfaces.
  - regression_plan.applies=true with two runnable checks tagged to every AC; lint scope matches changed source plus changed tests.
