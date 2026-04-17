---
name: mine
description: Mine a project with pre/post validation — verifies palace health before and after mining
disable-model-invocation: false
---

# Mine Project

Mine a codebase into the palace with validation checks.

## When to Use

- First-time indexing of a new project
- Re-mining after code changes
- Troubleshooting mining issues
- User says "mine", "index", "scan project"

## Steps

### Step 1: Pre-flight Health Check

```bash
mempalace health --json
```

Record baseline:
- Current drawer count
- Current wing count
- Health status

### Step 2: Validate Target

Check target directory exists and has code:

```bash
ls -la <target_dir>
find <target_dir> -name "*.py" -o -name "*.js" -o -name "*.ts" | head -5
```

Check for `.gitignore` exclusions:
- `node_modules/`, `venv/`, `__pycache__/` should be excluded
- `.git/` is always excluded

### Step 3: Run Mining

```bash
mempalace mine <target_dir> [--full]
```

Options:
- `--full`: Force full rebuild (ignore content hashes)
- Default: Incremental (only changed files)

Monitor output for:
- Files scanned
- Chunks created
- Errors/warnings

### Step 4: Post-mine Validation

```bash
mempalace health --json
```

Compare to baseline:
- Drawer count increased?
- New wing created?
- Health still OK?

### Step 5: Verify Search Works

```bash
mempalace search "main function" --wing <project_wing> --limit 3
```

Confirm results return from the mined project.

## Output Format

```
## Mining Report

Target: <directory>
Mode: [incremental | full]

Before:
- Drawers: N
- Wings: N

After:
- Drawers: N (+M new)
- Wings: N
- Files scanned: N
- Chunks created: N

Health: [OK | WARN: <issue>]
Search test: [PASS | FAIL]

Issues:
- [any errors or warnings]
```

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| 0 files scanned | Wrong path or gitignore | Check path, verify files exist |
| Health FAIL after mine | optimize() corruption | `mempalace repair --rollback` |
| Search returns empty | Embedding mismatch | Full re-mine: `mempalace mine --full` |
| Wing not created | No recognizable code files | Check language support |
