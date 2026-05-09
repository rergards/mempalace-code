---
slug: MCP-TOOL-PROFILES
goal: "Add startup-time MCP tool profiles plus explicit include/exclude filtering while keeping full as the default"
risk: medium
risk_note: "Changes server startup argument parsing and MCP dispatch visibility; hidden tools must be filtered from both tools/list and direct tools/call without changing existing default schemas"
files:
  - path: mempalace_code/mcp_tool_profiles.py
    change: "Add declarative profile definitions, selector alias/wildcard expansion, include/exclude precedence, and clear validation errors for startup parsing"
  - path: mempalace_code/mcp_server.py
    change: "Parse --profile/--tools/--include/--exclude at startup, build an active tool registry from TOOLS, use it for tools/list and tools/call, and exit before the MCP loop on invalid selections"
  - path: tests/test_mcp_tool_profiles.py
    change: "Add focused tests for profile contents, selector expansion, precedence, invalid selectors, empty selections, and docs/rules consistency"
  - path: tests/test_mcp_server.py
    change: "Add JSON-RPC dispatch tests proving default full behavior, profile-filtered tools/list output, and hidden-tool rejection"
  - path: README.md
    change: "Document the profile names, startup flags, examples, default full behavior, and GitHub issue #6 rationale; remove stale all-or-nothing limitation text"
  - path: docs/AGENT_INSTALL.md
    change: "Add MCP profile selection to the install decision tree, wire selected flags into Claude/Codex examples, and make usage-rules injection choose the matching profile block"
  - path: docs/LLM_USAGE_RULES.md
    change: "Add profile-matched usage-rule blocks or generated profile sections that reference only tools enabled by the selected profile"
  - path: examples/mcp_setup.md
    change: "Update MCP setup examples with profile, explicit tools, and exclude variants"
  - path: mempalace_code/README.md
    change: "Update package module summary from fixed 28-tool wording to profiled MCP toolsets with 28-tool full default"
acceptance:
  - id: AC-1
    when: "the MCP server is started without profile flags and a client sends initialize plus tools/list"
    then: "tools/list exposes the same full 28-tool set as today, including mempalace_delete_wing, mempalace_mine, mempalace_extract_reusable, and mempalace_diary_read"
  - id: AC-2
    when: "the MCP server is started with --profile=minimal and a client sends tools/list"
    then: "the response contains exactly mempalace_status, mempalace_search, mempalace_check_duplicate, and mempalace_add_drawer"
  - id: AC-3
    when: "the MCP server is started with --profile=code and a client sends tools/list"
    then: "the response includes code-oriented tools such as mempalace_code_search, mempalace_file_context, mempalace_explain_subsystem, and mempalace_extract_reusable, while omitting write/diary tools such as mempalace_add_drawer and mempalace_diary_write"
  - id: AC-4
    when: "the MCP server is started with --profile=minimal --include=kg_query --exclude=search and a client sends tools/list"
    then: "mempalace_kg_query is present, mempalace_search is absent, and exclude takes precedence after include"
  - id: AC-5
    when: "the MCP server is started with --tools=search,add_drawer,diary_* and a client sends tools/list"
    then: "the response contains exactly mempalace_search, mempalace_add_drawer, mempalace_diary_write, and mempalace_diary_read"
  - id: AC-6
    when: "a client calls mempalace_delete_wing directly while the active profile is minimal"
    then: "the MCP response is a JSON-RPC error with code -32601 and a message that says the tool is not enabled by the active MCP profile"
  - id: AC-7
    when: "startup receives an unknown profile, an unknown tool selector, a wildcard selector that matches no tools, or filters that leave zero active tools"
    then: "the process exits before the stdio MCP loop with a nonzero status and a stderr message naming the invalid profile or selector"
  - id: AC-8
    when: "the profile/rules consistency test parses docs/LLM_USAGE_RULES.md for each documented profile"
    then: "each profile-matched rules block references no mempalace_* tool that is hidden by that profile"
  - id: AC-9
    when: "documentation examples are checked with rg for profile=minimal, --tools, --exclude, and issue #6 references"
    then: "README.md, docs/AGENT_INSTALL.md, docs/LLM_USAGE_RULES.md, and examples/mcp_setup.md show the new static profile controls and no longer claim MCP exposure is all-or-nothing"
out_of_scope:
  - "Dynamic runtime tool discovery or per-request tool negotiation"
  - "Changing existing tool names, input schemas, handler return payloads, or the default full tool list"
  - "Splitting the whole mcp_server.py monolith; MCP-SERVER-MODULE-SPLIT remains separate backlog work"
  - "Changing storage, embedding, miner, watcher, or KG persistence behavior"
  - "Client-specific MCP configuration beyond documented startup command examples"
---

## Design Notes

- Keep the existing `TOOLS` mapping as the authoritative schema/handler registry. Add a small `mcp_tool_profiles.py` helper so profile logic is tested without importing or editing the full MCP monolith.
- Profile base sets:
  - `minimal`: `status`, `search`, `check_duplicate`, `add_drawer`.
  - `kg`: `minimal` plus `kg_query`, `kg_add`, `kg_invalidate`, `kg_timeline`.
  - `code`: `code_search`, `file_context`, `find_implementations`, `find_references`, `show_project_graph`, `show_type_dependencies`, `explain_subsystem`, `extract_reusable`, `mine`, `status`.
  - `notes`: `status`, `search`, `add_drawer`, `check_duplicate`, `list_wings`, `list_rooms`, `get_taxonomy`, `traverse`, `find_tunnels`, `graph_stats`, `diary_write`, `diary_read`.
  - `full`: all keys in `TOOLS`.
- Selector grammar:
  - Accept full tool names (`mempalace_search`) and short names (`search`).
  - Accept trailing wildcard selectors (`diary_*`, `mempalace_diary_*`) only when they match at least one known tool.
  - Normalize selectors to full tool names before validation and set operations.
- Precedence:
  - Start from `--profile` base set, default `full`.
  - `--tools` replaces the profile base set. Treat `--tools` and `--include` together as invalid to avoid ambiguous additive vs replacement behavior.
  - `--include` adds selectors to the profile base set.
  - `--exclude` removes selectors last, so exclude wins.
  - Empty final selections are invalid.
- CLI parsing can live in `mcp_server.main(argv=None)` with `argparse`. `handle_request` should accept an optional active registry for tests, while module-level startup stores the resolved registry used by stdio serving.
- `tools/list` must iterate over the active registry only. `tools/call` must check the active registry before schema coercion or handler invocation; hidden tools should not be callable even if they still exist in `TOOLS`.
- Preserve lazy-startup behavior: resolving profiles and returning `tools/list` must not import miner, torch, sentence-transformers, or open LanceDB. Keep subprocess import-blocker tests for this path.
- Invalid startup flags should fail before logging "MemPalace MCP Server starting..." or entering the stdin loop. Use a short stderr error such as `Invalid MCP tool profile: ...` or `Unknown MCP tool selector: ...`.
- Docs should reference GitHub issue #6 and state why this is static startup filtering: it lowers persistent tool-schema surface while preserving stable named-tool triggers in usage rules.
- Usage rules should be machine-checkable. Prefer marked profile blocks, for example `<!-- mcp-profile:minimal start -->`, so tests can parse each block and compare referenced `mempalace_*` names against `mcp_tool_profiles.PROFILES`.
- Verification commands after implementation:
  - `python -m pytest tests/test_mcp_tool_profiles.py tests/test_mcp_server.py -q`
  - `ruff check mempalace_code/ tests/`
  - `ruff format --check mempalace_code/ tests/`
