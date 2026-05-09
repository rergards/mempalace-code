slug: MCP-SERVER-MODULE-SPLIT
phase: polish
date: 2026-05-09
commit_range: aa1a706..d7d9e64
reverted: false
findings:
  - id: P-1
    title: "mcp_server.py shim re-exports unused private dispatch internals"
    category: structural
    location: "mempalace_code/mcp_server.py:11"
    evidence: "_NOISE_KEYS and _active_registry re-exported from dispatch; no code imports them from mcp_server"
    decision: fixed
    fix: "Removed _NOISE_KEYS and _active_registry from mcp_server.py re-export line"

  - id: P-2
    title: "mcp_server.py shim re-exports unused private runtime state globals"
    category: structural
    location: "mempalace_code/mcp_server.py:14-26"
    evidence: "_kg, _store, _store_read_only re-exported; test_mcp_server.py was patching these on mcp_server instead of mcp.runtime, making the patches no-ops (tools use runtime._ directly)"
    decision: fixed
    fix: "Removed _kg, _store, _store_read_only from shim; fixed the one test that patched these to patch mcp.runtime directly (consistent with all other tests in the file)"

  - id: P-3
    title: "Identical category_map dict defined twice in architecture.py"
    category: structural
    location: "mempalace_code/mcp/tools/architecture.py:103-114 and 217-228"
    evidence: "tool_find_references and tool_explain_subsystem each define a 10-entry category_map dict with identical keys and values; second definition even comments 'same map as tool_find_references'"
    decision: fixed
    fix: "Hoisted to module-level constant _CATEGORY_MAP; both functions now reference it"

  - id: P-4
    title: "registry.py docstring references internal task criterion AC-1"
    category: verbal
    location: "mempalace_code/mcp/registry.py:4-6"
    evidence: "\"required by AC-1 (mempalace_status through mempalace_diary_read)\" — AC-1 is a task acceptance criterion that has no meaning to future maintainers; the insertion order is already explained by the inline comment below"
    decision: fixed
    fix: "Removed the AC-1 reference; kept 'Validates duplicate names at import time.' The insertion-order rationale is preserved in the inline comment on line 29"

  - id: P-5
    title: "Obvious comment restates existence/isdir checks in tool_mine"
    category: verbal
    location: "mempalace_code/mcp/tools/write.py:88"
    evidence: "# Validate directory exists and is a directory — restates what dir_path.exists() and dir_path.is_dir() obviously do"
    decision: fixed
    fix: "Removed the comment"

totals:
  fixed: 5
  dismissed: 0

fixes_applied:
  - "mcp_server.py: removed _NOISE_KEYS and _active_registry from dispatch re-export line"
  - "mcp_server.py: removed _kg, _store, _store_read_only from runtime re-export block"
  - "test_mcp_server.py: fixed TestLazyStartup.test_ac4 to patch mcp.runtime directly instead of mcp_server shim (was a no-op patch; also the only test that triggered AttributeError after shim cleanup)"
  - "architecture.py: hoisted duplicate category_map to module-level _CATEGORY_MAP constant; removed both local definitions"
  - "registry.py: removed AC-1 reference from module docstring"
  - "write.py: removed comment restating obvious directory-existence check"
