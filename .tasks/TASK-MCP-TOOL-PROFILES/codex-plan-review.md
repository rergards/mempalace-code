verdict: READY

summary:
  The plan covers the substantive surface of GitHub issue #6 cleanly: a separate
  `mcp_tool_profiles.py` helper that owns profile/selector logic, a CLI parsed
  in `mcp_server.main`, and dispatch filtering applied to both `tools/list` and
  `tools/call`. The 28-tool TOOLS registry at `mempalace_code/mcp_server.py:1138`
  matches the plan's profile bases (status/list_wings/list_rooms/get_taxonomy,
  kg_*, find_implementations/find_references/show_*/explain_subsystem/
  extract_reusable, traverse/find_tunnels/graph_stats, search/code_search/
  file_context/check_duplicate, add_drawer/delete_drawer/delete_wing, mine,
  diary_*). All 9 ACs are observable: ACs 1–6 are JSON-RPC dispatch outcomes
  (testable via `handle_request`/subprocess), AC-7 is a process-exit check, AC-8
  is a parser test against `mcp_tool_profiles.PROFILES`, AC-9 is an `rg` doc
  scan. The files list correctly identifies every doc copy of "28 tools" /
  "all-or-nothing" found in the repo (README.md:78,110,335,799;
  docs/AGENT_INSTALL.md:26,48,51–53,826; docs/LLM_USAGE_RULES.md;
  examples/mcp_setup.md; mempalace_code/README.md:23). Lazy-startup is
  preserved because dispatch filtering is metadata-only and the default profile
  is `full`.

gaps:
  - severity: medium
    claim: "The plan calls out '`--tools` and `--include` together are invalid' as a precedence rule in Design Notes, but no AC verifies it. AC-7 lists unknown profile, unknown selector, empty-match wildcard, and zero-active selections — the combo case is not in that list."
    evidence: "docs/plans/MCP-TOOL-PROFILES.md design notes 'Treat --tools and --include together as invalid'; AC-7 enumerates the failure cases."
    suggested_fix: "Add a sub-bullet to AC-7 (or AC-7b) explicitly: 'startup that supplies both --tools and --include exits before the stdio MCP loop with a nonzero status and a stderr message naming the conflicting flags.' Add a matching test in tests/test_mcp_tool_profiles.py."

  - severity: medium
    claim: "docs/AGENT_INSTALL.md Section 7.3 (lines 677–797) embeds a duplicate of the LLM_USAGE_RULES.md usage-rules block intentionally so the runbook is self-contained. If profile markers (e.g. `<!-- mcp-profile:minimal start -->`) are added only to LLM_USAGE_RULES.md, the embedded copy will silently drift. AC-8 only parses LLM_USAGE_RULES.md."
    evidence: "docs/AGENT_INSTALL.md:649 ('Source of truth: ...keep the inline block below in sync with that file') and the duplicated block at 677–797."
    suggested_fix: "Either (a) extend AC-8/the consistency test to also parse the embedded block in docs/AGENT_INSTALL.md (Section 7.3), or (b) replace the embedded literal block with an instruction to inject from LLM_USAGE_RULES.md and add an AC asserting the embedded block is removed/de-duplicated. The plan's docs/AGENT_INSTALL.md entry currently only commits to wiring profile flags into Claude/Codex examples and to making the injection step pick the matching profile block — it does not commit to re-syncing the embedded literal."

  - severity: low
    claim: "AC-8 implies a marker syntax for profile-matched usage-rule blocks but never pins it in an acceptance criterion. The Design Notes say 'Prefer marked profile blocks, for example <!-- mcp-profile:minimal start -->' but the AC just says the test 'parses docs/LLM_USAGE_RULES.md for each documented profile'."
    evidence: "Design Notes line 'Prefer marked profile blocks...'; AC-8 leaves marker format unspecified."
    suggested_fix: "Tighten AC-8 to fix the marker syntax (e.g. 'each profile is delimited by `<!-- mcp-profile:<name> start -->` / `<!-- mcp-profile:<name> end -->`') so the docs change and the consistency test agree on the contract."

  - severity: low
    claim: "No AC explicitly verifies that lazy-startup is preserved when a non-default profile is active. The existing subprocess import-blocker test at tests/test_mcp_server.py:2347 covers the default `full` path; profile-filtered startup is the new behavior."
    evidence: "Design Notes mention 'Keep subprocess import-blocker tests for this path' but no AC requires the test be run for `--profile=minimal` or similar."
    suggested_fix: "Add AC-1b: 'when the MCP server is started with --profile=minimal in a subprocess that blocks miner/torch/sentence_transformers imports, initialize and tools/list still succeed.' Reuse the existing import-blocker subprocess harness from tests/test_mcp_server.py:2347."

  - severity: low
    claim: "examples/gemini_cli_setup.md contains an MCP setup snippet (`gemini mcp add mempalace-code ... -m mempalace_code.mcp_server --scope user`) but is not in the plan's files list. Other agent-setup examples in the same directory are updated; gemini is not."
    evidence: "examples/gemini_cli_setup.md:46 — current MCP add snippet without profile flags. Plan files list includes examples/mcp_setup.md but not gemini_cli_setup.md."
    suggested_fix: "Either add examples/gemini_cli_setup.md to the plan's files list with a 'Add profile/--tools/--exclude variants alongside Claude/Codex examples' note, or document explicitly in out_of_scope that per-host setup files outside mcp_setup.md are unchanged."
