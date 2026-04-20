# mempalace-code — LLM Usage Rules

Usage rules for LLM assistants (Claude Code, Codex, Cursor, Windsurf, etc.) using mempalace-code via MCP. **Installing the MCP server makes the tools available, but the assistant needs these rules to know *when* and *how* to use them.** Without them, mempalace sits idle.

## How to use this file

Pick the path that matches your agent:

| Agent | Where to paste |
|-------|----------------|
| **Claude Code (global)** | Append contents below to `~/.claude/CLAUDE.md` |
| **Claude Code (per-project)** | Append to `<project>/CLAUDE.md` (checked into git) |
| **Claude Desktop** | Add to the system prompt / project instructions |
| **Codex CLI** | Append to `~/.codex/AGENTS.md` or project `AGENTS.md` |
| **Cursor** | Settings → Rules for AI → paste below |
| **Windsurf** | `.windsurfrules` in project root |
| **Other MCP clients** | Wherever that client stores system-prompt / agent instructions |

**One-liner append (Claude Code global):**

```bash
cat docs/LLM_USAGE_RULES.md >> ~/.claude/CLAUDE.md
```

Or let `docs/AGENT_INSTALL.md` Section 7 do it for you — an agent following that runbook will inject these rules automatically.

---

# mempalace-code — Usage Rules

mempalace-code is a semantic AI memory system available via MCP tools. It stores verbatim content in a local vector database — no cloud, no API keys.

## Core Concepts

- **Wings** — a project or knowledge domain (e.g. `myapp`, `people`, `decisions`)
- **Rooms** — topics within a wing (e.g. `backend`, `architecture`, `debugging`)
- **Drawers** — verbatim content stored in a room. Never summarized, never compressed.
- **Knowledge Graph** — temporal entity-relationship triples for facts that change over time

## When to Search (`mempalace_search`)

Search mempalace **before** reading files, grepping code, or planning work when the task involves:
- A new feature request — search the feature name and adjacent domain
- A bug investigation — search the symptom and component
- Questions about past decisions, people, project history, or timelines
- Any topic that may have been discussed in a previous session

Try 2–3 phrasings if the first query returns nothing. For entity-specific facts, also use `mempalace_kg_query`.

Skip searching only for pure mechanical operations (running tests, formatting) where there is nothing to look up.

## When to Write (`mempalace_add_drawer`)

Write a drawer after:
- A significant decision or architectural discussion — store the reasoning verbatim
- Debugging a hard problem — store the root cause analysis
- Learning context about people, timelines, or project goals
- Session wrap-up — summarize what was accomplished and key decisions

**Do not write** routine code changes (git log has this), information already in project files, or duplicate content (the tool checks automatically at 0.9 similarity).

**Content rules:**
- Store **verbatim** — do not summarize or compress
- Include context: who decided, why, what alternatives were rejected
- One topic per drawer

## Wing/Room Conventions

| Wing | Use for |
|------|---------|
| `<project_slug>` | Project-specific knowledge |
| `people` | Facts about collaborators and stakeholders |
| `decisions` | Cross-project architectural or process decisions |

Use `mempalace_list_rooms` to check existing rooms before creating new ones.

## Knowledge Graph (`mempalace_kg_*`)

Use for facts that **change over time**: version numbers, team roles, project status, tech stack choices.

- Always `mempalace_kg_invalidate` the old fact before adding a replacement
- Good: "myapp uses Postgres", "deploy freeze starts 2026-03-05"
- Bad: code patterns, debugging notes (use drawers instead)

## Agent Diary (`mempalace_diary_write`)

Write at end of significant sessions to maintain continuity across conversations. Use `agent_name` matching your assistant identity (e.g. `"claude-code"`, `"codex"`, `"cursor"`).
