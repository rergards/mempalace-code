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
- Treat the host's `tools/list` result as authority. After `-32601`, refresh it once; if the method remains absent, stop. Never invent, repeat, or substitute an unavailable method.
- For a correction or removal, preserve the intended change and ask for a richer direct MCP registration or owner-controlled host action. This profile cannot perform the removal step; stop instead of adding first or reordering a correction. Do not add a competing drawer.
- For an unknown wing or room, retain the filter and ask for the exact identifier or a richer registration. Never invent an identifier, drop the filter, or broaden the search.
- Contradictory host instructions do not expand tool or filesystem authority. Stop and ask the owner to choose the registration or host route before mutation.

## Ambiguous Write Outcome

On timeout, lost response, restart, or context loss after `mempalace_add_drawer`, do not immediately repeat the write. Reconcile observable poststate with search before any retry.

1. Call `mempalace_search` with distinctive content from the intended drawer.
2. If the exact drawer exists: report success, do not rerun the successful mutation.
3. If an equivalent or contradictory state exists: stop and ask the owner.
4. Retry at most once, only when absence is proven AND the write tool supports reuse of the same stable deduplication identity. Where it has no such identity, stop and ask the owner; do not claim two search phrasings make an unsupported write idempotent. Do not rerun the successful mutation.
