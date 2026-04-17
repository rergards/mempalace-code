# Session Startup

Quick environment check and context load. Run at session start and after every context compression.

**Do NOT restate rules from CLAUDE.md** — they are always loaded. This skill verifies environment state and loads work context only.

## Steps

### Step 1: Verify Environment (run all in parallel)

```bash
git branch --show-current
```

```bash
git status --porcelain | grep -v "^??" || echo "clean"
```

```bash
# Check Python venv is active and has mempalace installed
python -c "import mempalace; print(f'mempalace: {mempalace.__file__}')" 2>/dev/null || echo "mempalace: NOT installed in active Python"
```

```bash
# Check palace health
python -c "from mempalace.storage import LanceStore; s=LanceStore(); print(f'palace: {s.count()} drawers')" 2>/dev/null || echo "palace: unreachable"
```

```bash
# Check for unverified commits
BASELINE=$(cat .verify-state 2>/dev/null)
if [ -n "$BASELINE" ]; then
  COUNT=$(git log --oneline "$BASELINE"..HEAD 2>/dev/null | wc -l | tr -d ' ')
  [ "$COUNT" -gt 0 ] && echo "UNVERIFIED: $COUNT commits since last verify" || echo "verify: current"
else
  echo "verify: no baseline (run /verify)"
fi
```

**Check:**
- Branch SHOULD be `main`. If on a feature branch, note it.
- If mempalace is not installed, warn: `pip install -e ".[dev]"`
- If palace is unreachable, warn: `mempalace health`
- If unverified commits >= 30, escalate: "run `/verify` before any new work."

### Step 2: Load Active Backlog

```bash
backlog list --status open --section immediate --file docs/BACKLOG.yaml 2>/dev/null || echo "no backlog CLI"
```

Show items as-is. If empty, IMMEDIATE section is clear.

### Step 3: Acknowledge Readiness

Output 4-5 lines max:

```
On `main` branch. [clean | tracked: <files>]. Python [mempalace installed | warn: not installed].
Palace: [N drawers | unreachable — run mempalace health]
[verify: current | UNVERIFIED: N commits — run /verify | no baseline]
[Active blockers: <count> item(s) in IMMEDIATE (from BACKLOG.yaml) | IMMEDIATE clear]
```
