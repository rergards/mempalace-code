---
name: release
description: Cut and verify a public release through publish remote, hosted CI, PyPI, and GitHub Release status
disable-model-invocation: false
---

# Release Workflow

Cut a public release. Use after `/release-prep` has synced docs, changelog, and
version metadata.

## When to Use

- Ready to cut a new release
- User says "release", "publish", "ship", or "bump version"

## Steps

### Step 1: Preflight

Run the committed-tree public-safety scan before any release claim. This checks
that HEAD itself — the exact tree that will be published — contains no private
local paths, secret-like tokens, or local-only artifact paths. Use this as the
release-readiness check after merge and before pushing a release tag:

```bash
python scripts/public_safety_scan.py --committed
```

A non-zero exit means HEAD contains a public-safety violation. Fix the
violation, commit the fix, and re-run before proceeding. Do not bypass this
check — the committed-tree scan is the authoritative before-release gate because
it reads git objects directly, independent of worktree state.

Run `/verify`. If dependency bounds, lockfiles, workflows, storage, miner, or
optional extras changed, also run the dependency gate:

```bash
python -m pytest tests/ -v -m "not needs_network"
python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"
ruff check mempalace_code/ tests/ scripts/
ruff format --check mempalace_code/ tests/ scripts/
```

For dependency changes:

```bash
python -m pip install pip-audit
pip-audit
```

Then reproduce the relevant hosted resolver surface in a clean temp venv. At
minimum for package-bound or lockfile changes:

```bash
python3.13 -m venv /tmp/mempalace-ci-venv
/tmp/mempalace-ci-venv/bin/python -m pip install -e ".[dev,treesitter]"
/tmp/mempalace-ci-venv/bin/python -m pytest tests/ -v -m "not needs_network"
```

Check current public state:

```bash
grep -E "^version\s*=" pyproject.toml
git ls-remote --tags publish 'refs/tags/v*' | tail -10
python - <<'PY'
import json, urllib.request
data = json.load(urllib.request.urlopen("https://pypi.org/pypi/mempalace-code/json"))
print(data["info"]["version"])
PY
```

Do not rely on local tags or private remotes for public release truth.

### Step 2: Confirm Version

Use the version prepared by `/release-prep`. If the version is unclear, classify
the bump:

| Change Type | Version Bump |
|-------------|--------------|
| Breaking changes (API, CLI, storage format) | Major (X.0.0) |
| New features (languages, MCP tools) | Minor (0.X.0) |
| Bug fixes, docs, internal | Patch (0.0.X) |

Ask user to confirm version if unclear.

### Step 3: Commit

```bash
git status --short
git add pyproject.toml CHANGELOG.md README.md docs/LLM_USAGE_RULES.md uv.lock
git commit -m "chore: release vX.Y.Z"
```

Only add files that are part of the release. Never stage private local notes,
tokens, temp files, or unrelated work.

### Step 4: Tag

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
```

### Step 5: Push to Public Release Remote

Ask user before pushing unless they already explicitly asked to publish:

```
Ready to push release vX.Y.Z to publish?
- git push publish main
- git push publish vX.Y.Z

Proceed? [y/n]
```

```bash
git push publish main
git push publish vX.Y.Z
```

The tag triggers `.github/workflows/publish.yml` and publishes to PyPI through
trusted publishing. Do not run manual `twine upload` unless the workflow is
unavailable and the user explicitly approves the fallback.

### Step 6: Verify Hosted Status

Run the release-status gate first. It checks every public publication surface
and exits non-zero when any blocker remains:

```bash
python scripts/release_status_gate.py --version X.Y.Z \
  --repo rergards/mempalace-code \
  --remote publish \
  --branch main
```

The gate checks:
1. publish remote git tag (`v X.Y.Z` on the `publish` remote)
2. branch Tests workflow — most recent completed run on `main` must be green
3. Publish to PyPI workflow — most recent completed run must be green
4. GitHub Release metadata — non-draft, non-prerelease, `isLatest=true`
5. PyPI JSON — `info.version == X.Y.Z` and both wheel and sdist present
6. Install smoke — `pip install --no-cache-dir mempalace-code==X.Y.Z` in a disposable venv

A release is **not shipped** when any blocker remains. Report the gate's
`Remaining blockers` list verbatim in the release summary and do not use
"shipped" or "latest" language until the gate exits 0.

For machine-readable status (e.g. Autopilot gating):

```bash
python scripts/release_status_gate.py --version X.Y.Z --json
```

**Diagnostic-only mode** (skips install smoke; cannot be labeled fully shipped):

```bash
python scripts/release_status_gate.py --version X.Y.Z --skip-smoke
```

If the gate finds blockers, investigate the specific surface that failed.
Manual fallback diagnostics for individual surfaces:

```bash
# Tag
git ls-remote --tags publish "refs/tags/vX.Y.Z"

# Workflows
gh run list --repo rergards/mempalace-code --branch main --workflow Tests --limit 5
gh run list --repo rergards/mempalace-code --workflow "Publish to PyPI" --limit 5

# GitHub Release
gh release view vX.Y.Z --repo rergards/mempalace-code

# PyPI JSON
python - <<'PY'
import json, urllib.request
version = "X.Y.Z"
data = json.load(urllib.request.urlopen("https://pypi.org/pypi/mempalace-code/json"))
print(data["info"]["version"])
assert data["info"]["version"] == version
PY
```

If PyPI is visible but `gh release view` reports no release, create the GitHub
Release only after hosted Tests are green:

```bash
gh release create vX.Y.Z --repo rergards/mempalace-code \
  --title "vX.Y.Z" \
  --notes-file /tmp/mempalace-release-notes.md
```

Release notes are public: include user-facing changes, package/version advisory
IDs, and verification boundaries. Do not include private remotes, local paths,
tokens, hostnames, or incident-only details.

## Output

```
## Release vX.Y.Z

Version: X.Y.Z
Tag: vX.Y.Z
Pushed to publish: [yes/no]
Release status gate: [passed/failed]

Remaining blockers:
- [none or exact blocker from release_status_gate.py output]
```
