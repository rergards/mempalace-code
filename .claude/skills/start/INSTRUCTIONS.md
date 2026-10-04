# Session Startup

Quick environment check and context load. Run at session start and after every context compression.

**Do not restate rules from `AGENTS.md`.** This skill verifies environment state and loads work context only.

## Steps

### Step 1: Verify Environment (run all in parallel)

```bash
git branch --show-current
```

```bash
if MP_WORKTREE_STATUS=$(git status --porcelain --untracked-files=all 2>/dev/null); then
  if [ -z "$MP_WORKTREE_STATUS" ]; then
    echo "git: clean (tracked and untracked)"
  else
    printf '%s\n' "$MP_WORKTREE_STATUS"
  fi
else
  echo "git: unknown — run git rev-parse --show-toplevel"
fi
```

```bash
# Check Python venv is active and has mempalace installed
python -c "import mempalace_code; print(f'mempalace-code: {mempalace_code.__file__}')" 2>/dev/null || echo "mempalace-code: NOT installed in active Python"
```

```bash
# Check palace health
mempalace-code health --json 2>/dev/null \
  | python -c 'import json,sys; d=json.load(sys.stdin); print("palace: {} drawers ({})".format(d.get("total_rows", 0), "healthy" if d.get("ok") else "unhealthy"))' \
  || echo "palace: unreachable"
```

```bash
# Check the committed verification baseline and Git read status
MP_VERIFY_BASELINE=$(cat .verify-state 2>/dev/null)
if [ -z "$MP_VERIFY_BASELINE" ]; then
  echo "verify: no baseline (run /verify)"
elif ! git rev-parse --verify --end-of-options "$MP_VERIFY_BASELINE^{commit}" >/dev/null 2>&1 \
  || ! git merge-base --is-ancestor "$MP_VERIFY_BASELINE" HEAD 2>/dev/null; then
  echo "verify: unknown baseline (run /verify)"
elif MP_UNVERIFIED_COUNT=$(git rev-list --count "$MP_VERIFY_BASELINE..HEAD" 2>/dev/null); then
  if [ "$MP_UNVERIFIED_COUNT" -gt 0 ]; then
    echo "UNVERIFIED: $MP_UNVERIFIED_COUNT commits since last verify"
  else
    echo "verify: current"
  fi
else
  echo "verify: unknown Git state (run git rev-parse --show-toplevel)"
fi
```

**Check:**
- Branch SHOULD be `main`. If on a feature branch, note it.
- If mempalace is not installed, warn: `pip install -e ".[dev,spellcheck,treesitter]"`
- If palace is unreachable, warn: `mempalace-code health`
- If unverified commits >= 30, escalate: "run `/verify` before any new work."

### Step 2: Load Active Backlog

Read the verified project-bound `.backlog` connection:
`backlog_context {}`, `backlog_workset_context {}`, then
`backlog_workset_queue {}`. Follow bounded pages with their returned tokens.
Report open, draft, held and dependency-blocked tasks separately. An empty queue
requires reporting its hold/blocker reasons; it does not prove completion.
No task execution or backlog mutation is authorized by startup.

CLI fallback: discover and verify the absolute `backlog-utility` binary; use
`call --store .backlog --project mempalace-code --principal <principal>
--name <tool> --arguments-file <json>` with `{}` for these initial reads.
If access is absent, malformed or mismatched, report backlog state unknown.
Recovery: `<absolute-backlog-utility> validate --store .backlog`.

### Step 3: Acknowledge Readiness

Output 4-5 lines max:

```
On `main` branch. [clean | changes: <tracked and untracked paths> | Git status unknown]. Python [mempalace installed | warn: not installed].
Palace: [N drawers | unhealthy | unreachable — run mempalace-code health]
[verify: current | UNVERIFIED: N commits — run /verify | no baseline | unknown baseline/Git state]
[Backlog: <open/held/blocked counts>; <eligible queue count> | unknown — validate .backlog]
```
