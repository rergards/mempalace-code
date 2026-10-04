# doc-refresh

Weekly documentation refresh + maintenance. All steps mechanical — execute sequentially.

## Constraints

- Only document what exists in code (verify by reading source).
- Never remove correct content — only update stale entries and add missing ones.
- `AGENTS.md` is the canonical instruction owner; `CLAUDE.md` must remain exactly `@AGENTS.md`.
- Verify counts by running commands, not from memory.
- Update "Last updated" dates on modified doc files.

## Step 1 — Audit staleness

Run in parallel:

```bash
git log --oneline -1 -- docs/BACKUP_RESTORE.md docs/AGENT_INSTALL.md AGENTS.md CLAUDE.md README.md
```
```bash
git log --oneline -30 main
```
Read `backlog_context {}`, `backlog_workset_context {}`, and
`backlog_workset_queue {}` from the verified project-bound `.backlog` connection;
follow bounded pages. CLI fallback uses a verified absolute `backlog-utility`
binary with `call --store .backlog --project mempalace-code --principal
<principal> --name <tool> --arguments-file <json>` (`{}` for initial reads).
Unavailable, malformed or mismatched access means unknown; do not fall back to
active YAML. Report blocked/held tasks and an empty queue explicitly.

For each doc, diff changed source files since last doc commit:

| Doc | Diff scope |
|-----|-----------|
| BACKUP_RESTORE.md | `mempalace_code/backup.py`, `mempalace_code/storage.py` |
| AGENT_INSTALL.md | `mempalace_code/mcp/` (`registry.py`, `tools/`), `mempalace_code/mcp_tool_profiles.py` |
| AGENTS.md | `.claude/skills/`, `mempalace_code/**/*.py` modules |
| CLAUDE.md | `AGENTS.md` pointer contract only |
| README.md | CLI commands, MCP tools, installation |

Skip docs where diff is empty or test-only.

## Step 2 — Update stale docs

### README.md

Check: new CLI commands, new MCP tools, installation changes, supported languages list.

### AGENTS.md and CLAUDE.md

Check the `AGENTS.md` Key Modules table, architecture principles, and public-safe
boundaries. Require `CLAUDE.md` to contain exactly `@AGENTS.md` plus one newline.

### AGENT_INSTALL.md

Check: MCP tool list matches the `TOOLS` registry in `mempalace_code/mcp/registry.py`, installation steps work.

### BACKUP_RESTORE.md

Check: CLI commands match implementation, filter semantics current.

## Step 3 — Backlog doc gaps

Only with explicit backlog-completion authority, refresh the exact canonical task
and use `backlog_complete` with current version, revision, contract digest and
passing evidence for every acceptance ID. Preserve owner holds and unresolved
prerequisites. A docs refresh or YAML retirement never establishes completion.
Persist the exact typed request and stable request ID before mutation; reconcile
fresh context after uncertain results. Never edit canonical JSON by hand.

## Step 4 — Maintenance

Run read-only checks every run. Execute mutating substeps only within the active request; otherwise report proposed changes and validation findings.

### 4a. Backlog validate

```bash
<absolute-backlog-utility> validate --store .backlog
```

Discover and verify the absolute binary first. Report validator failures; repair
only through supported operations with explicit authority. Preserve the store.

### 4b. Durable-context audit

Search MemPalace wing `mempalace` for the changed topic. Flag stale source/task
references and duplicated canonical docs. Keep current product truth in tracked
files; keep original evidence, decisions, and root causes in focused drawers.

### 4c. Verify check

Read verification-baseline status with the command in `.claude/skills/start/INSTRUCTIONS.md` → Step 1. Preserve its Git exit-status and ancestry checks; failed reads mean unknown.

If >= 30 unverified commits: flag prominently, recommend `/verify` before next deploy.

### 4d. Dead doc references

```bash
git grep -n -o -E 'docs/[a-zA-Z0-9_./-]+\.md' -- docs AGENTS.md CLAUDE.md .claude/ \
  ':(exclude)docs/plans/**' ':(exclude)docs/audits/**' ':(exclude)docs/demo/**' \
  ':(exclude).claude/prompts/**' | while IFS=: read -r file line path; do
  [ ! -f "$path" ] && echo "DEAD REF: $file:$line -> $path"
done
```

Fix dead refs in `AGENTS.md` and `.claude/`. Keep `CLAUDE.md` as the exact pointer. Report count.

### 4e. RTK savings (if rtk installed)

```bash
rtk discover 2>&1 | head -40 || true
rtk gain 2>&1 | head -15 || true
```

## Output

```
Updated: [files modified]
Docs: README [N changes] | AGENTS [N sections] | AGENT_INSTALL [changes] | BACKUP_RESTORE [changes]
Backlog gaps: [N resolved]
Maintenance: validate [pass/fail] | memory [clean/N stale] | verify [N unverified] | dead refs [N in key files]
```
