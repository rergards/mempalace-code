---
slug: MCP-MINE-TRIGGER
status: completed
authority: non_authoritative
goal: "Expose mempalace_mine MCP tool so agents can trigger project re-mining without CLI access"
risk: low
risk_note: "Thin wrapper around existing mine() which already has incremental/full modes and returns stats; no new core logic"
files:
  - path: mempalace/mcp_server.py
    change: "Add tool_mine handler function and mempalace_mine entry in TOOLS dict"
  - path: tests/test_mcp_server.py
    change: "Add TestToolMine class: successful incremental mine, full mine, invalid directory, wing override"
acceptance:
  - id: AC-1
    when: "mempalace_mine is called with a valid project directory"
    then: "Returns {success: true, files_processed: N, files_skipped: N, drawers_filed: N, elapsed_secs: F} with correct counts"
  - id: AC-2
    when: "mempalace_mine is called with full=true on an already-mined directory"
    then: "files_skipped is 0 (all files re-processed regardless of hash match)"
  - id: AC-3
    when: "mempalace_mine is called with a non-existent directory path"
    then: "Returns {success: false, error: ...} without raising an exception"
  - id: AC-3b
    when: "mempalace_mine is called with a path that exists but is a file (not a directory)"
    then: "Returns {success: false, error: ...} without raising an exception"
  - id: AC-3c
    when: "mempalace_mine is called with an existing directory that lacks mempalace.yaml/mempal.yaml"
    then: "Returns {success: false, error: ...} without raising an exception or terminating the MCP server (no sys.exit)"
  - id: AC-4
    when: "mempalace_mine is called with wing='custom_wing'"
    then: "Mined drawers are filed under the custom_wing wing (verified via direct store query, not search/status)"
  - id: AC-5
    when: "tools/list is called on the MCP server"
    then: "mempalace_mine appears in the tool list with correct input schema"
resolved_questions:
  - q: "Should mempalace_mine accept any existing directory, or only directories with mempalace.yaml/mempal.yaml?"
    a: "Only valid mempalace projects. Directories missing config get {success: false, error: ...} gracefully — the handler preflights this check before calling mine()."
  - q: "When wing is omitted, should the tool preserve mine() semantics exactly or diverge?"
    a: "Preserve exactly. The tool passes wing_override=None which lets mine() use config['wing'] with dotnet_structure solution-wing detection."
out_of_scope:
  - "Conversation mining (--mode convos) — separate tool if needed"
  - "Watch mode (long-running, not suitable for request-response MCP)"
  - "Dry-run mode (agents should mine for real, not preview)"
  - "include_ignored paths (can be added later if needed)"
---

## Design Notes

- **Handler function `tool_mine(directory, wing=None, full=False)`:**
  - Validates `directory` exists and is a directory; returns error dict if not.
  - Validates `mempalace.yaml` or `mempal.yaml` exists in the directory; returns error dict if missing (avoids `sys.exit(1)` from `load_config()`).
  - Resolves `palace_path` from `_config.palace_path` (same as other handlers).
  - Calls `mine(project_dir=directory, palace_path=palace_path, wing_override=wing, incremental=not full, kg=_kg)`.
  - Wraps return in `{"success": True, **stats}`.
  - Catches `(Exception, SystemExit)` and returns `{"success": False, "error": str(e)}` — `SystemExit` must be caught because `load_config()` and other miner internals call `sys.exit(1)` on fatal errors. Both preflight validation AND the broad catch are needed (belt-and-suspenders: preflight covers the known case; catch covers unknown future `sys.exit` calls).

- **Parameter design:**
  - `directory` (required, string): absolute path to the project root to mine.
  - `wing` (optional, string): override wing name. When omitted, `mine()` uses `config["wing"]` from the project's `mempalace.yaml`, with `dotnet_structure` projects additionally detecting the solution-derived wing via `_detect_sln_wing()`. The MCP tool preserves these existing semantics exactly.
  - `full` (optional, boolean, default false): when true, forces full rebuild (`incremental=False`).

- **Registration:** Add to TOOLS dict after `mempalace_delete_wing` (in the write-tools section), before diary tools. The tool modifies palace state so it belongs in the write group.

- **KG integration:** Pass the module-level `_kg` singleton so type-extraction triples (Python class hierarchies, .NET types) are populated during mining.

- **Stdout suppression:** `mine()` prints progress to stdout. The MCP server uses stdio transport, so stdout writes would corrupt the JSON-RPC stream. Use the fd-level suppression pattern from `watcher.py:_quiet_mine()`: `os.dup2(devnull, 1/2)` with flush-before-restore. Do NOT use `contextlib.redirect_stdout(io.StringIO())` — it only redirects Python-level writes and buffered text can still leak to real stdout on restore. The fd-level approach is proven safe in the watcher and handles C-extension writes too.

- **Test approach:** Use the existing `_patch_mcp_server` + isolated `tmp_path` palace fixture pattern. Create a small temp project directory with a Python file, call `tool_mine`, verify stats and that drawers exist in the store. Additionally include at least one protocol-level test calling `handle_request({"method": "tools/call", ...})` to verify registration and dispatch through the same path as other MCP tool tests (see `tests/test_mcp_server.py:49`).

- **Doc updates:** Add `mempalace_mine` to the MCP tool inventory in the `mcp_server.py` module docstring and `README.md` tool list (write-tools section).
