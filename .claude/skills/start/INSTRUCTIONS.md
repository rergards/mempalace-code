# Session Startup

Quick environment check and context load. Run at session start and after every context compression.

**Do not restate rules from `AGENTS.md`.** This skill verifies environment state and loads work context only.

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
python -c "import mempalace_code; print(f'mempalace-code: {mempalace_code.__file__}')" 2>/dev/null || echo "mempalace-code: NOT installed in active Python"
```

```bash
# Check palace health
mempalace-code health --json 2>/dev/null \
  | python -c 'import json,sys; d=json.load(sys.stdin); print("palace: {} drawers ({})".format(d.get("total_rows", 0), "healthy" if d.get("ok") else "unhealthy"))' \
  || echo "palace: unreachable"
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
- If palace is unreachable, warn: `mempalace-code health`
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
Palace: [N drawers | unhealthy | unreachable — run mempalace-code health]
[verify: current | UNVERIFIED: N commits — run /verify | no baseline]
[Active blockers: <count> item(s) in IMMEDIATE (from BACKLOG.yaml) | IMMEDIATE clear]
```
