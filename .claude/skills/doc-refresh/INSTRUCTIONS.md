# doc-refresh

Weekly documentation refresh + maintenance. All steps mechanical — execute sequentially.

## Constraints

- Only document what exists in code (verify by reading source).
- Never remove correct content — only update stale entries and add missing ones.
- CLAUDE.md is context-loaded every session — keep concise.
- Verify counts by running commands, not from memory.
- Update "Last updated" dates on modified doc files.

## Step 1 — Audit staleness

Run in parallel:

```bash
git log --oneline -1 -- docs/BACKUP_RESTORE.md docs/AGENT_INSTALL.md docs/STORAGE.md CLAUDE.md README.md
```
```bash
git log --oneline -30 main
```
```bash
backlog list --status open --file docs/BACKLOG.yaml
```

For each doc, diff changed source files since last doc commit:

| Doc | Diff scope |
|-----|-----------|
| BACKUP_RESTORE.md | `mempalace/backup.py`, `mempalace/storage.py` |
| AGENT_INSTALL.md | `mempalace/mcp_server.py`, MCP tools |
| STORAGE.md | `mempalace/storage.py`, schema migrations |
| CLAUDE.md | `.claude/skills/`, `mempalace/*.py` modules |
| README.md | CLI commands, MCP tools, installation |

Skip docs where diff is empty or test-only.

## Step 2 — Update stale docs

### README.md

Check: new CLI commands, new MCP tools, installation changes, supported languages list.

### CLAUDE.md

Check: Key Modules table accuracy, new skills tables, architecture principles current.

### AGENT_INSTALL.md

Check: MCP tool list matches `mcp_server.py`, installation steps work.

### BACKUP_RESTORE.md

Check: CLI commands match implementation, filter semantics current.

## Step 3 — Backlog doc gaps

Mark resolved documentation-gap backlog items: `backlog done <SLUG> --summary "summary" --file docs/BACKLOG.yaml`.

## Step 4 — Maintenance

Execute all substeps every run.

### 4a. Backlog validate

```bash
backlog validate --file docs/BACKLOG.yaml
```

Fix any schema errors. Dangling links are warnings — ignore.

### 4b. Memory cleanup

Scan `MEMORY.md` per memory-write-policy. Remove:
- Outdated versions or archived workflows
- Session-specific notes that should have been removed
- Duplicates of CLAUDE.md content

### 4c. Verify check

```bash
BASELINE=$(cat .verify-state 2>/dev/null)
if [ -n "$BASELINE" ]; then
  COUNT=$(git log --oneline "$BASELINE"..HEAD 2>/dev/null | wc -l | tr -d ' ')
  echo "Unverified commits: $COUNT"
else
  echo "No verify baseline — run /verify"
fi
```

If >= 30 unverified commits: flag prominently, recommend `/verify` before next deploy.

### 4d. Dead doc references

```bash
grep -rohn 'docs/[a-zA-Z0-9_./-]*\.md' docs/ CLAUDE.md .claude/ | while IFS=: read -r file line path; do
  [ ! -f "$path" ] && echo "DEAD REF: $file:$line -> $path"
done
```

Fix dead refs in CLAUDE.md and `.claude/`. Report count.

### 4e. RTK savings (if rtk installed)

```bash
rtk discover 2>&1 | head -40 || true
rtk gain 2>&1 | head -15 || true
```

## Output

```
Updated: [files modified]
Docs: README [N changes] | CLAUDE [N sections] | AGENT_INSTALL [changes] | BACKUP_RESTORE [changes]
Backlog gaps: [N resolved]
Maintenance: validate [pass/fail] | memory [clean/N stale] | verify [N unverified] | dead refs [N in key files]
```
