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

2. **Backlog priorities** — Run `backlog list --status open --file docs/BACKLOG.yaml` and find:
   - Highest priority open items across sections
   - Any items with `status: in_progress`
   - Blocked items and their dependencies

3. **Section progress**
   ```bash
   backlog list --status all --file docs/BACKLOG.yaml
   ```
   Count done vs open per section.

## Output Format

### Recent (last few commits)
- Bullet list of recent changes

### In Progress
- Tasks currently being worked on

### Next Up (highest priority pending)
- Top 3-5 pending items sorted by priority
- Note any blocking dependencies

### Section Progress
- code_mining: N/M done
- mcp_tools: N/M done
- storage_reliability: N/M done
- documentation: N/M done
