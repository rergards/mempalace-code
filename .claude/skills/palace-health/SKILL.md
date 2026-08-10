---
name: palace-health
description: Check palace health, suggest repairs, run auto-backup
disable-model-invocation: false
---

# Palace Health Check

Diagnose and fix palace storage issues.

## When to Use

- Search returns empty unexpectedly
- Drawer counts don't match
- MCP tools return errors
- After a crash or unexpected termination
- Before/after major operations (mining, restore)

## Steps

### Step 1: Run Health Check

```bash
mempalace-code health --json
```

Parse the JSON output. Check for:
- `ok: true/false` — overall health
- `total_rows` — number of stored drawers
- `errors` — list of issues found
- `warnings` — non-fatal storage findings

### Step 2: Diagnose Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ok: false`, fragment errors | LanceDB corruption | Preview `mempalace-code repair --rollback --dry-run`, then request approval |
| `total_rows = 0` but files exist | Table unreadable | Preview `mempalace-code repair --rollback --dry-run`, then request approval |
| Search returns empty | Embedding mismatch or corruption | Re-mine or restore backup |
| Wing missing | Partial delete or corruption | Restore from backup |

### Step 3: Check Backups

```bash
mempalace-code backup list
```

If corruption detected and backups exist:

```bash
# Dry run first
mempalace-code repair --rollback --dry-run
```

Report the exact rollback candidate or backup path. Do not mutate storage until
the user explicitly authorizes one exact action.

```bash
# After explicit approval: rollback
mempalace-code repair --rollback

# Or restore from backup
mempalace-code restore <backup.tar.gz>
```

### Step 4: Verify Recovery

After repair/restore:

```bash
mempalace-code health
mempalace-code search "test query" --results 3
```

## Output Format

```
## Palace Health Report

Status: HEALTHY / DEGRADED / CORRUPT
Drawers: N
Last backup: YYYY-MM-DD HH:MM

Issues found:
- [issue description]

Recommended action:
- [action to take]
```
