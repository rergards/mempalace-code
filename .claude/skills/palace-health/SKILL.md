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
mempalace health --json
```

Parse the JSON output. Check for:
- `ok: true/false` — overall health
- `drawer_count` — number of drawers
- `wing_count` — number of wings
- `errors` — list of issues found

### Step 2: Diagnose Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ok: false`, fragment errors | LanceDB corruption | `mempalace repair --rollback` |
| drawer_count = 0 but files exist | Table unreadable | `mempalace repair --rollback` |
| Search returns empty | Embedding mismatch or corruption | Re-mine or restore backup |
| Wing missing | Partial delete or corruption | Restore from backup |

### Step 3: Check Backups

```bash
mempalace backup list
```

If corruption detected and backups exist:

```bash
# Dry run first
mempalace repair --dry-run

# If safe, rollback
mempalace repair --rollback

# Or restore from backup
mempalace restore <backup.tar.gz>
```

### Step 4: Verify Recovery

After repair/restore:

```bash
mempalace health
mempalace search "test query" --limit 3
```

## Output Format

```
## Palace Health Report

Status: HEALTHY / DEGRADED / CORRUPT
Drawers: N
Wings: N
Last backup: YYYY-MM-DD HH:MM

Issues found:
- [issue description]

Recommended action:
- [action to take]
```
