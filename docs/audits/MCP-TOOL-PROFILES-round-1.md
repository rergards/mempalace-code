slug: MCP-TOOL-PROFILES
round: 1
date: 2026-05-09
commit_range: 3294c89..HEAD
findings:
  - id: F-1
    title: "AGENT_INSTALL.md wiring never applies a profile — always registers full 28-tool default"
    severity: high
    location: "docs/AGENT_INSTALL.md:489,512,552,568"
    claim: >
      The install runbook (Section 2 Q4, Section 5 wiring) had no question for profile
      selection and all four wiring commands (Claude Code CLI, Claude Code JSON fallback,
      Codex CLI, Codex TOML fallback) omitted --profile entirely. An agent executing the
      runbook always registered the full 28-tool default, defeating the feature's stated
      purpose of reducing tool-surface cost at server startup.
    decision: fixed
    fix: >
      Added Q5 (MCP tool profile) between Q4 (scope) and the former Q5 (mining, renumbered
      Q6). Q5 asks the human to choose full/minimal/kg/code/notes and sets MCP_PROFILE.
      All four wiring locations now include --profile=$MCP_PROFILE (CLI) or
      --profile=<MCP_PROFILE> (JSON/TOML fallbacks with substitution note).

  - id: F-2
    title: "code profile table description says 'no write/diary tools' but mempalace_mine is a write tool"
    severity: medium
    location: "README.md:370, examples/mcp_setup.md:47, docs/LLM_USAGE_RULES.md:226"
    claim: >
      README.md and examples/mcp_setup.md described the code profile as 'no write/diary
      tools'. However the code profile explicitly includes mempalace_mine, which is a
      re-indexing write path. docs/LLM_USAGE_RULES.md reinforced the mismatch by saying
      the profile is for 'read-only code archaeology'. Users choosing --profile=code to
      limit risk still granted re-mining capability without knowing it.
    decision: fixed
    fix: >
      README.md and examples/mcp_setup.md updated to 'no drawer-write/diary tools (mine
      included)'. LLM_USAGE_RULES.md updated to 'omits drawer-write (add_drawer,
      delete_drawer, delete_wing) and diary tools but retains mempalace_mine for on-demand
      index refresh', removing the 'read-only' qualifier. Profile membership unchanged;
      only documentation corrected.

totals:
  fixed: 2
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "Added Q5 (MCP_PROFILE) to AGENT_INSTALL.md and threaded --profile into all four wiring locations"
  - "Corrected 'no write/diary tools' → 'no drawer-write/diary tools (mine included)' in README.md and examples/mcp_setup.md"
  - "Removed 'read-only' qualifier from LLM_USAGE_RULES.md code profile description; named the excluded tools explicitly"

new_backlog: []
