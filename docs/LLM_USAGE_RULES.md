# mempalace-code — LLM Usage Rules

Usage rules for any MCP-capable LLM agent (Claude Code, Codex, Cursor, Windsurf, Continue.dev, Zed, Aider, …) using mempalace-code. **Installing the MCP server makes the tools available, but the assistant needs these rules to know *when* and *how* to use them.** Without them, mempalace sits idle.

> The README states an assistant can "learn the memory protocol automatically from `mempalace_status`." That claim is aspirational — `mempalace_status` returns stats, not protocol. Explicit rules are still required until MCP tool descriptions carry the full protocol.

## How to use this file

Pick the path that matches your agent (alphabetical — no preference):

| Agent | Where to paste |
|-------|----------------|
| Aider | `CONVENTIONS.md` or `.aider.conf.yml` read-rules |
| Claude Code (global) | Append below to `~/.claude/CLAUDE.md` |
| Claude Code (per-project) | Append below to `<project>/CLAUDE.md` (checked into git) |
| Claude Desktop | Add to the system prompt / project instructions |
| Codex CLI (global) | Append to `~/.codex/AGENTS.md` |
| Codex CLI (per-project) | Append to `<project>/AGENTS.md` |
| Continue.dev | `.continuerules` or `~/.continue/config.json` system message |
| Cursor | Settings → Rules for AI → paste below |
| Windsurf | `.windsurfrules` in project root |
| Zed | `assistant.system_prompt` in settings |
| Other MCP clients | Wherever that client stores system-prompt / agent instructions |

**One-liner append examples:**

```bash
# Claude Code (global)
cat docs/LLM_USAGE_RULES.md >> ~/.claude/CLAUDE.md

# Codex CLI (global)
cat docs/LLM_USAGE_RULES.md >> ~/.codex/AGENTS.md
```

For per-project installs, append to whichever rules file the agent reads (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.windsurfrules`, `.continuerules`, etc.) using the same `cat … >> <target>` pattern.

`docs/AGENT_INSTALL.md` §7 automates the injection for Claude Code. Other hosts are manual today — paste the block below.

**Agent identity for diary:** set `MEMPALACE_AGENT_NAME` in the environment of the host that runs the MCP server (e.g. `claude-code`, `codex`, `cursor-ai`, `zed-assistant`). The rules reference this variable rather than hardcoding a name.

---

# mempalace-code — Usage Rules

mempalace-code is a local semantic memory system exposed over MCP. Content is stored verbatim in a vector database; no cloud, no API keys, no summarisation.

## Mental model

- **Wing** — a project or knowledge domain. One per repo, plus cross-project wings like `people`, `decisions`.
- **Room** — a topic within a wing (`backend`, `debugging`, `meetings`). Organisational; searches ignore rooms unless you scope explicitly.
- **Drawer** — verbatim content stored in a room. Persistent, shared across agents, retrieved by meaning.
- **Knowledge Graph (KG)** — entity-relationship triples with validity windows. For facts that evolve (versions, roles, statuses, deadlines).
- **Diary** — agent-scoped first-person session log. Read on next session to restore continuity; not team-authoritative.

## Routing: which tool, when?

| Task                                                | Primary tool                         |
|-----------------------------------------------------|--------------------------------------|
| "Have we discussed X before?" / past decisions      | `mempalace_search`                   |
| "What is the current value of X?" (temporal fact)   | `mempalace_kg_query`                 |
| "How did X change over time?"                       | `mempalace_kg_timeline`              |
| Find a function/class/symbol/file                   | `mempalace_code_search`              |
| All indexed chunks for a specific file              | `mempalace_file_context`             |
| Refresh/re-mine an indexed source/docs directory    | `mempalace_mine`                     |
| Explain how a subsystem works                       | `mempalace_explain_subsystem`        |
| Classify dependencies as core / platform / glue     | `mempalace_extract_reusable`         |
| Inheritance chain (ancestors + descendants)         | `mempalace_show_type_dependencies`   |
| Project-level dependency graph (.NET)               | `mempalace_show_project_graph`       |
| Walk related rooms from a starting room             | `mempalace_traverse`                 |
| Find rooms that bridge two wings                    | `mempalace_find_tunnels`             |
| Save a decision, root cause, or discussion          | `mempalace_add_drawer`               |
| Save/update a temporal fact                         | `mempalace_kg_invalidate` + `mempalace_kg_add` |
| End-of-session continuity note (self-scoped)        | `mempalace_diary_write`              |
| Resume prior session continuity                     | `mempalace_diary_read`               |
| Verify palace is alive before relying on it         | `mempalace_status`                   |

Default to `mempalace_search` only when no more specific tool applies.

## Search rules

Call `mempalace_search` **before substantial repo exploration** (reading many files, broad grepping, planning) when prior context could plausibly exist — new feature requests, bug investigations, questions about past decisions, people, timelines, or project history.

- Try 2–3 reformulations on low-confidence or empty results before giving up.
- Scope with `wing=<project_slug>` for project-local topics; omit for cross-cutting ones.
- On persistent miss, proceed with host tools and consider writing a drawer after the task so the next agent finds it.
- For entity-specific facts, also call `mempalace_kg_query`.

Skip search for pure mechanical operations (run tests, format files, rename within one file).

## Index freshness rules

MCP search only sees indexed content. If a source/docs directory is missing or stale and the tool exists, use `mempalace_mine(directory=...)` to refresh it before relying on search. For conversation/log exports, use the CLI path (`mempalace-code mine <dir> --mode convos`) or ask the human to run it; `mempalace_mine` is project-source re-mining only.

For large monorepos, prefer the highest-ROI initialized subdirectory first when the human wants a trial. Do not assume unsupported extensions are indexed: normal scans skip file types outside the miner catalog unless an exact file path is force-included.

## Existing memory systems

If the repo already has curated memory docs (`MEMORY.md`, project notes, hand-written summaries), do not mirror them wholesale into drawers. Use stores by job:
- KG = volatile current facts that need exact lookup or history.
- Drawers = verbatim source material, decisions, root causes, and discussion excerpts.
- Diary = this agent's own continuity notes.
- Curated docs = compressed narrative, rationale, and human-maintained summaries.

Do not turn a carefully compressed memory file into drawer content unless the human explicitly asks. Prefer adding precise KG triples for facts that drift and drawers for original verbatim evidence.

## Knowledge Graph rules

Use the KG for facts that **change over time** or need **exact-match lookup** — version numbers, stack choices, ownership, statuses, deadlines.

Update protocol: `mempalace_kg_query` → `mempalace_kg_invalidate` (old triple, today's date) → `mempalace_kg_add` (new triple, validity window). Never leave two live triples for the same `(subject, predicate)`.

Bad for KG: code patterns, debugging notes, prose — those belong in a drawer.

## Drawer rules

Write a drawer after:
- A significant decision or architectural discussion — include reasoning and rejected alternatives.
- Debugging a hard problem — capture the root cause, not the symptom.
- Durable context about people, timelines, or project goals.
- Significant session wrap-up others might need.

**Before filing substantial new prose, call `mempalace_check_duplicate`** and merge rather than overwrite if a near-duplicate exists.

Content rules: store verbatim; one topic per drawer; keep it ≤ ~60 lines; reference file paths and issue/PR IDs rather than pasting large blobs. See Appendix A for the recommended template.

## Wing & room conventions

| Wing              | Use for                                              |
|-------------------|------------------------------------------------------|
| `<project_slug>`  | Project-specific knowledge. One wing per repo.       |
| `people`          | Facts about collaborators and stakeholders.          |
| `decisions`       | Cross-project architectural or process decisions.    |

Call `mempalace_list_wings` / `mempalace_list_rooms` before inventing new names. Reuse existing rooms (`backend`, `frontend`, `architecture`, `debugging`, `meetings`, `infrastructure`, `general`) unless a genuinely new topic warrants a new one.

## Diary rules

`mempalace_diary_write` creates an agent-scoped first-person session record.

- Pass `agent_name` = the value of `MEMPALACE_AGENT_NAME` from the environment. Do not guess, do not hardcode another agent's identity.
- Write once at end of a meaningful session — not per message.
- Content: what was attempted, what shipped, what remains, where you left off.
- Read with `mempalace_diary_read` at session start when continuity matters.

Diary ≠ drawer. Diary is for the same agent's next run; drawer is for the team.

## Never

- Never fabricate a tool call or invent tool names. If the tool is not in your MCP tool list, it is not available — fall back to host tools.
- Never store secrets, tokens, credentials, private keys, or PII (home addresses, phone numbers, government IDs) in drawers or the KG. Collaborator context (name, role, team, preferences, working relationships) in the `people` wing is fine — that is the wing's purpose.
- Never summarise or compress drawer content; store verbatim.
- Never create a new wing when an existing one fits.
- Never leave two live KG triples for the same `(subject, predicate)`.
- Never call `mempalace_delete_drawer` or `mempalace_delete_wing` except to correct content that is *wrong*. Evolved facts get a new drawer / a KG invalidate-and-add, not a delete.
- Never treat diary entries as team-authoritative memory. They are agent-scoped context, not a source of truth.
- Never infer absence from a search miss. "Not found" means "not indexed or not phrased to match," not "does not exist."

---

## Profile-specific routing

The MCP server can be started with a named tool profile to reduce prompt/tool-surface cost
(see [README — MCP tool profiles](../README.md#mcp-tool-profiles) and GitHub issue #6).
Each profile exposes a subset of the 29 tools. Use only the tools listed in the active profile;
all others will return a "not enabled" error if called.

<!-- mcp-profile:minimal start -->
### Profile: minimal

Active tools: `mempalace_status`, `mempalace_search`, `mempalace_check_duplicate`, `mempalace_add_drawer`.

| Task | Tool |
|------|------|
| Palace health check | `mempalace_status` |
| Semantic search | `mempalace_search` |
| Duplicate check before filing | `mempalace_check_duplicate` |
| Save a decision or note | `mempalace_add_drawer` |

The `minimal` profile is ideal for agents that only need to search and write notes. It does not
include KG, code search, diary, or graph navigation tools.
<!-- mcp-profile:minimal end -->

<!-- mcp-profile:kg start -->
### Profile: kg

Active tools: `mempalace_status`, `mempalace_search`, `mempalace_check_duplicate`,
`mempalace_add_drawer`, `mempalace_kg_query`, `mempalace_kg_add`,
`mempalace_kg_invalidate`, `mempalace_kg_timeline`.

| Task | Tool |
|------|------|
| Palace health check | `mempalace_status` |
| Semantic search | `mempalace_search` |
| Duplicate check before filing | `mempalace_check_duplicate` |
| Save a decision or note | `mempalace_add_drawer` |
| Query an entity's current facts | `mempalace_kg_query` |
| Add a temporal fact | `mempalace_kg_add` |
| Retire an outdated fact | `mempalace_kg_invalidate` |
| See how facts changed over time | `mempalace_kg_timeline` |

The `kg` profile is a superset of `minimal` with the four core KG tools added. Suitable when
tracking evolving facts (versions, assignments, deadlines) alongside drawer notes.
<!-- mcp-profile:kg end -->

<!-- mcp-profile:code start -->
### Profile: code

Active tools: `mempalace_status`, `mempalace_code_search`, `mempalace_file_context`,
`mempalace_find_implementations`, `mempalace_find_references`, `mempalace_show_project_graph`,
`mempalace_show_type_dependencies`, `mempalace_explain_subsystem`, `mempalace_extract_reusable`,
`mempalace_mine`.

| Task | Tool |
|------|------|
| Palace health check | `mempalace_status` |
| Find a function/class/symbol | `mempalace_code_search` |
| All indexed chunks for a file | `mempalace_file_context` |
| Find types implementing an interface | `mempalace_find_implementations` |
| Find all usages of a type | `mempalace_find_references` |
| Project dependency graph (.NET) | `mempalace_show_project_graph` |
| Inheritance/implementation chain | `mempalace_show_type_dependencies` |
| Explain how a subsystem works | `mempalace_explain_subsystem` |
| Classify deps as core/platform/glue | `mempalace_extract_reusable` |
| Re-mine a project directory | `mempalace_mine` |

The `code` profile omits drawer-write (`add_drawer`, `delete_drawer`, `delete_wing`) and diary
tools but retains `mempalace_mine` for on-demand index refresh. Use it for code archaeology
and architecture review.
<!-- mcp-profile:code end -->

<!-- mcp-profile:notes start -->
### Profile: notes

Active tools: `mempalace_status`, `mempalace_search`, `mempalace_add_drawer`,
`mempalace_check_duplicate`, `mempalace_list_wings`, `mempalace_list_rooms`,
`mempalace_get_taxonomy`, `mempalace_traverse`, `mempalace_find_tunnels`,
`mempalace_graph_stats`, `mempalace_diary_write`, `mempalace_diary_read`.

| Task | Tool |
|------|------|
| Palace health check | `mempalace_status` |
| Semantic search | `mempalace_search` |
| Save a decision or note | `mempalace_add_drawer` |
| Duplicate check before filing | `mempalace_check_duplicate` |
| List all wings | `mempalace_list_wings` |
| List rooms in a wing | `mempalace_list_rooms` |
| Full wing/room taxonomy | `mempalace_get_taxonomy` |
| Walk the palace graph | `mempalace_traverse` |
| Find cross-wing connections | `mempalace_find_tunnels` |
| Graph connectivity overview | `mempalace_graph_stats` |
| Write a session diary entry | `mempalace_diary_write` |
| Read recent diary entries | `mempalace_diary_read` |

The `notes` profile is for agents focused on knowledge management — recording decisions,
navigating the graph, and maintaining session continuity via diary — without code-search
or KG mutation tools.
<!-- mcp-profile:notes end -->

---

# Appendix A — Drawer template (recommended)

```
# <topic in one line>

**Context:** who was involved, when, what triggered this.
**Decision / finding:** one or two sentences, direct.
**Why:** reasoning, tradeoffs, rejected alternatives.
**Impact:** what this changes going forward, who is affected.
**References:** file paths, PRs, issue IDs, related drawers.
```

The template is a recommendation, not a schema. Skip sections that do not apply. Keep total length ≤ ~60 lines; reference files rather than pasting them.

# Appendix B — Query craft

- Prefer **declarative phrasing**: `"why we chose Postgres over MySQL"` beats `"postgres mysql decision"`.
- Use proper-noun spellings verbatim — project slugs, code names, library names.
- `mempalace_search` is meaning-based; exact substrings are not guaranteed to match.
- `mempalace_code_search` is symbol-aware; prefer it for function/class/file lookups.
- Scope with `wing=` when you know the topic is project-local; leave it off for cross-cutting concerns (people, decisions, general conventions).
- If two phrasings return nothing, consider that the palace may not have been taught this yet — that is a signal to *write* after the task completes.

# Appendix C — Maintenance

- `mempalace_status` at session start when you intend to rely heavily on memory; a stale or empty palace should change your plan.
- `mempalace_check_duplicate` before filing substantial new prose.
- Prefer additive corrections over destructive ones: new drawers preserve history; deletions erase it.
- No update tool exists. To correct *wrong* content: `mempalace_search` the drawer → `mempalace_delete_drawer` with its ID → `mempalace_add_drawer` with the fix. For *evolved* facts, add a new drawer instead and let history stand; track current state in the KG.
- For .NET/TypeScript/Kotlin/Java code graphs that rely on pre-mined symbol data, check that the wing has been mined with the relevant language before calling `mempalace_find_implementations`, `mempalace_find_references`, `mempalace_show_project_graph`, `mempalace_show_type_dependencies`, or `mempalace_extract_reusable`. Empty results from these often mean "not mined," not "no matches."
