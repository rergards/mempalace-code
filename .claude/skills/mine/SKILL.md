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
mempalace-code health --json
```

Record baseline:
- `total_rows`
- `ok`
- `errors` and `warnings`

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
mempalace-code mine <target_dir> [--full]
```

Options:
- `--full`: Force full rebuild (ignore content hashes)
- Default: Incremental (only changed files)

Monitor output for:
- Files processed
- Drawers filed
- Errors/warnings

### Step 4: Post-mine Validation

```bash
mempalace-code health --json
```

Compare to baseline:
- Did `total_rows` change as expected?
- Is `ok` still `true`?
- Are `errors` and `warnings` empty?

### Step 5: Verify Search Works

```bash
mempalace-code search "main function" --wing <project_wing> --results 3
```

Confirm results return from the mined project.

## Output Format

```
## Mining Report

Target: <directory>
Mode: [incremental | full]

Before:
- Drawers: N

After:
- Drawers: N (+M new)
- Files processed: N
- Drawers filed: N

Health: [OK | WARN: <issue>]
Search test: [PASS | FAIL]

Issues:
- [any errors or warnings]
```

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| 0 files scanned | Wrong path or gitignore | Check path, verify files exist |
| Health FAIL after mine | optimize() corruption | Stop and request approval before `mempalace-code repair --rollback` |
| Search returns empty | Embedding mismatch | Full re-mine: `mempalace-code mine <target_dir> --full` |
| Wing not created | No recognizable code files | Check language support |
