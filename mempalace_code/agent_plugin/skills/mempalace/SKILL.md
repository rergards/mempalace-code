---
name: mempalace
description: Use local MemPalace memory through the minimal MCP profile when prior project context or durable note capture matters.
---

# MemPalace Minimal Memory

Use this skill only when the MCP client exposes these tools:

- `mempalace_status`
- `mempalace_search`
- `mempalace_check_duplicate`
- `mempalace_add_drawer`

## Retrieve

- Call `mempalace_search` before substantial repo/history work when prior decisions, incidents, people, timelines, or project context could exist.
- Try two focused query phrasings before treating a miss as unindexed or stale context.
- Scope by wing only when the user or current repo clearly identifies the project.
- Call `mempalace_status` only for explicit inventory or diagnostics requests.

## Store

- Store durable decisions, root causes, supplied facts, and reusable handoff context verbatim.
- Before a substantial write, call `mempalace_check_duplicate` with the intended content.
- If a near duplicate exists, merge the new fact into one concise drawer instead of creating drift.
- Call `mempalace_add_drawer` with one topic per drawer and clear wing/room metadata.

## Guards

- Never store secrets, credentials, private keys, tokens, or sensitive personal data.
- Never claim a search miss proves absence. It only means the memory was not found by that query.
- Do not remove stored content through this plugin; the portable minimal profile exposes no removal action.
- If a needed operation is outside these four tools, use host tools or ask the user for a richer direct MCP registration.
