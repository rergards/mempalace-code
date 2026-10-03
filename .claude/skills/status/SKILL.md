---
name: status
description: Show current project status - recent work, in-progress tasks, and next priorities from backlog
disable-model-invocation: false
---

# Project Status Check

Quickly summarize project status: what was done recently, what's in progress, and what's next.

## Steps

1. **Recent commits** (last 10 on main)
   ```bash
   git log --oneline -10 main
   ```

2. **Canonical backlog** — Read `backlog_context {}`,
   `backlog_workset_context {}`, and `backlog_workset_queue {}` from the verified
   `.backlog` project connection. Follow bounded pages using returned tokens.
   Report task states, P0..P3 priorities, holds, dependencies and eligible queue.
   An empty queue requires reporting blockers; open+held tasks remain unfinished.
   Queue readiness does not establish executor authority, ownership or capacity.

3. **Fallback and history** — Discover and verify the absolute `backlog-utility`
   binary; use `call --store .backlog --project mempalace-code --principal
   <principal> --name <tool> --arguments-file <json>` with `{}` for initial reads.
   Missing, malformed or mismatched access means unknown; do not read active YAML
   as a fallback. `docs/BACKLOG.yaml` supplies historical section metadata only.
   `docs/BACKLOG-archived.yaml` supplies historical completion evidence only.
   Recovery: `<absolute-backlog-utility> validate --store .backlog`.

## Output

Report recent commits, canonical task state/hold counts, highest priorities and
eligible queue entries. Distinguish archive history from canonical current
completion. Report executor ownership unknown unless independently observed.
Invocation authorizes read-only status inspection only.
