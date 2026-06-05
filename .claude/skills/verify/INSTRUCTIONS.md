# Verify Changes

Detect what changed, run the right checks, and report a clear pass/fail verdict.

## Step 1: Detect What Changed

First check for a saved baseline SHA:

```bash
cat .verify-state 2>/dev/null || echo "NO_BASELINE"
```

Then detect changed files:

```bash
# Unstaged + staged working tree changes
git diff --name-only HEAD 2>/dev/null
git diff --name-only --cached 2>/dev/null
```

```bash
# Committed changes — from baseline SHA if available, else HEAD~1
BASELINE=$(cat .verify-state 2>/dev/null)
if [ -n "$BASELINE" ]; then
  git diff --name-only "$BASELINE"..HEAD 2>/dev/null
else
  git diff --name-only HEAD~1 HEAD 2>/dev/null
fi
```

Classify the combined file list into these categories (a change can trigger multiple):

- **core**: `mempalace_code/**/*.py`, `mempalace/*.py` (storage, miner, searcher, mcp_server, compatibility shims)
- **tests**: `tests/*.py`
- **docs**: `docs/*.md`, `README.md`, `CLAUDE.md`
- **config**: `pyproject.toml`, `uv.lock`, `setup.py`, `.claude/`, `.github/workflows/`

If no changes detected (clean tree, no baseline delta), run all checks — this is a health check invocation.

## Step 2: Run Verification

### Core checks (always run)

Run in parallel:

| Check | Command | Timeout |
|-------|---------|---------|
| Lint | `ruff check mempalace_code/ tests/ scripts/` | 30s |
| Format | `ruff format --check mempalace_code/ tests/ scripts/` | 30s |
| Tests | `python -m pytest tests/ -x -q -m "not needs_network"` | 120s |
| Typecheck | `python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"` | 120s |
| Strict slice typecheck | `python -m pyright -p pyrightconfig.strict.json` | 60s |
| Public safety | `python scripts/public_safety_scan.py --tracked --staged` | 30s |
| Scorecard | `python scripts/quality_scorecard.py --check` | 30s |

The scorecard check is stdlib-only (no install, no network) and validates the
quality scorecard's shape, determinism, public-safety, and committed artifact
freshness. The public-safety scan checks tracked and staged repository files for
private local paths, secret-like tokens, and local-only raw artifacts. After a
quality change lands, regenerate the committed artifacts with
`python scripts/quality_scorecard.py --write` (see `docs/quality/README.md`).

### If storage changed — add these

```bash
python -m pytest tests/test_storage.py tests/test_backup.py -v
```

### If miner changed — add these

```bash
python -m pytest tests/test_miner.py tests/test_lang_detect.py -v
```

### If MCP tools changed — add these

```bash
python -m pytest tests/test_mcp_server.py -v
```

### If dependencies changed — add these

First check current and target versions against OSV or an equivalent advisory
source. Do not accept a target version in an affected advisory range.

Then audit a fresh resolver environment, not only the existing `.venv`:

```bash
python -m pip install pip-audit
pip-audit
python3.13 -m venv /tmp/mempalace-ci-venv
/tmp/mempalace-ci-venv/bin/python -m pip install -e ".[dev,treesitter]"
/tmp/mempalace-ci-venv/bin/python -m pytest tests/ -v -m "not needs_network"
```

If an optional extra changed, create a separate fresh environment for that
extra and run its focused compatibility tests. For ChromaDB, do not install or
raise into affected 1.x versions while GHSA-f4j7-r4q5-qw2c applies.

## Step 3: Report Results

After all checks complete, output a verdict:

```
## Verification Results

| Check | Status | Notes |
|-------|--------|-------|
| Lint | PASS/FAIL | N errors |
| Format | PASS/FAIL | N files need formatting |
| Tests | PASS/FAIL | N passed, M failed |

**Verdict: PASS** — Ready to commit.
— or —
**Verdict: FAIL** — Fix issues before committing.
```

Rules for the verdict:
- **PASS**: All checks passed
- **FAIL**: ANY check failed — list the failed checks and suggest fixes

**If verdict is PASS** — save the current HEAD SHA as the new baseline:

```bash
git rev-parse HEAD > .verify-state
```

**If verdict is FAIL** — do NOT update `.verify-state`. The baseline should reflect the last known-good state so the next run still catches everything that changed since then.

## Common Failures

If a check fails, suggest the fix:

| Error Pattern | Likely Fix |
|---------------|-----------|
| Ruff lint errors | `ruff check --fix mempalace_code/ tests/ scripts/` |
| Ruff format errors | `ruff format mempalace_code/ tests/ scripts/` |
| Import errors | Check venv: `pip install -e ".[dev]"` |
| Test failures | Read the error, fix the code |
| Missing fixture | Check conftest.py |

## When to Use

- **Before committing** — standard pre-commit gate
- **After merging a feature branch** — always run full checks regardless of what changed
- **After rebasing** — verify nothing broke during merge
- **Health check** — run with no changes to verify everything is working
- **User invokes `/verify`** — always honour, even if no changes detected
