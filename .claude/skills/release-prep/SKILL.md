---
name: release-prep
description: Pre-release docs sync — diff HEAD against the last v* tag on the publish remote, list feature additions, update README language/tool inventory, draft the CHANGELOG release entry, propose the version bump. Runs before /release. Prevents shipping with stale docs.
disable-model-invocation: false
---

# Release Prep Workflow

Prepare docs for a PyPI release. Complements `/release` — this is the **docs sync** step; `/release` is the **cut + publish** step.

## When to Use

- Before running `/release`.
- After a batch of features has landed on `main` and you need to know "what's new since last publish?"
- User says: "prepare for release", "what's new since last publish", "update docs before release".

## Golden Rule

**Use the `publish` remote, not local tags.** Local tags can include inherited upstream tags that were never published. PyPI watches the `publish` remote.

## Steps

### Step 1: Resolve last published version

```bash
# Last v* tag on the publish remote (PyPI source of truth)
LAST_TAG=$(git ls-remote --tags publish 2>/dev/null \
  | grep -E 'refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' \
  | awk '{print $2}' | sed 's|refs/tags/||' \
  | sort -V | tail -1)
echo "Last published: $LAST_TAG"
```

If `publish` is not a git remote, fall back to asking the user which remote holds releases — do **not** use the latest local tag blindly.

Compare against `pyproject.toml` — if they differ, flag and investigate before continuing.

### Step 2: List commits since last publish

```bash
git log "$LAST_TAG..HEAD" --oneline
git log "$LAST_TAG..HEAD" --oneline | wc -l
```

Group by conventional-commit scope. Ignore noise: `chore: archive completed tasks`, `chore: autopilot housekeeping`, `fix(*): auto-fix verify errors`.

Categorize user-facing changes:

| Category | Signal |
|----------|--------|
| New feature | `feat(*)` with description (e.g. `feat(MINE-DART): Dart language support`) |
| New MCP tool | `feat(MCP-*)` or diff touches `mempalace_code/mcp_server.py` tool registry |
| Bug fix | `fix(*)` not tagged `auto-fix verify` |
| Docs | `docs(*)` |
| Breaking | Any commit whose body says "BREAKING" or touches storage format / public API |
| Dependency change | Diff touches `pyproject.toml` or `uv.lock` |

### Step 3: Detect feature surface changes

Cross-check the commit log against the code to catch anything the commit messages missed.

**New languages in the miner** — diff language dispatch tables:

```bash
git diff "$LAST_TAG..HEAD" -- mempalace_code/miner.py mempalace_code/mining/ \
  | grep -E '^\+.*(LANG_|_chunks|parse_|tool_|language.*=.*")'
```

**MCP surface changes** — verify the current public contract and inspect changed tool families:

```bash
python scripts/docs_drift_guard.py --json
git diff --name-status "$LAST_TAG..HEAD" -- \
  mempalace_code/mcp/registry.py mempalace_code/mcp/tools/
```

**Python version bumps** — scan `pyproject.toml` history for `requires-python` changes.

**Dependency bounds or lockfile changes** — list direct packages and run advisory
checks before drafting public notes:

```bash
git diff "$LAST_TAG..HEAD" -- pyproject.toml uv.lock
python - <<'PY'
import tomllib
data = tomllib.load(open("pyproject.toml", "rb"))
print("runtime:", data["project"]["dependencies"])
print("optional:", data["project"].get("optional-dependencies", {}))
print("dev:", data.get("dependency-groups", {}).get("dev", []))
PY
```

Do not raise an optional dependency ceiling into a known affected advisory
range. Record held upgrades in `docs/BACKLOG.yaml` and `docs/plans/`.

### Step 4: Check docs for staleness

For each item in Step 3, verify it appears in the right docs file.

| Change | Doc that must update |
|--------|----------------------|
| New language | `README.md` — "What gets indexed" bullet + Language-Aware Code Mining table |
| New MCP tool | `README.md` — MCP tool inventory tables (Read / Write / Graph / Diary groups) |
| New MCP tool | `docs/LLM_USAGE_RULES.md` — Routing table + any relevant rule section |
| Python minimum bump | `README.md` Requirements section + `pyproject.toml` `requires-python` |
| Dependency bound/security change | `CHANGELOG.md`, `CLAUDE.md`, and any relevant plan/backlog item |
| Breaking change | `CHANGELOG.md` under `### Breaking` |
| Any feature | `CHANGELOG.md` under the release header for this version |

Report each stale location as a to-fix item. Do not assume commit messages already covered it.

Run the deterministic contract check after documentation edits:

```bash
python scripts/docs_drift_guard.py
```

It verifies the package version, Python minimum, MCP tool/profile counts, LLM
profile blocks, changelog release heading, README badge, and the canonical
GitHub About source text in `docs/RELEASING.md`.

### Step 5: Propose version bump

| What changed | Bump |
|--------------|------|
| Any breaking change (API / CLI / storage format / MCP tool signatures) | Major (X.0.0) |
| New languages, new MCP tools, new CLI commands, behavior changes that are backwards-compatible | Minor (0.X.0) |
| Only bug fixes, docs, CI, internal refactors | Patch (0.0.X) |

State the reasoning. Ask the user to confirm.

### Step 6: Draft the CHANGELOG release entry

Open `CHANGELOG.md`. If scattered per-task entries already exist at the top (pattern: `## YYYY-MM-DD · TASK-SLUG`), **consolidate** them under a single release header:

```markdown
## vX.Y.Z — YYYY-MM-DD

### Added
- **N new languages in the code miner:**
  - **<Lang>** — <symbol types>; <notable features> (<TASK-SLUG>)
  - …
- **N new MCP tools:**
  - `mempalace_<name>` — <one-line purpose> (<TASK-SLUG>)
  - …

### Changed
- **<human-friendly summary>** — <what shifted>, <why it matters> (<TASK-SLUG>)

### Fixed
- <if applicable>

### Breaking
- <if applicable — otherwise omit the section>
```

Do **not** leave the per-task entries above the release header; consolidate them into bullets beneath it. One release header per version.

### Step 7: Update README and LLM_USAGE_RULES

Apply the to-fix items from Step 4. Touch `README.md` and `docs/LLM_USAGE_RULES.md` directly. Do not ask the user to paste snippets — just make the edits.

### Step 8: Bump `pyproject.toml`

```bash
# Replace "<NEW>" with the confirmed version
grep -E "^version\s*=" pyproject.toml
```

Edit the file; do not use `sed -i` unless portable (`sed -i '' 's/…/…/'` on macOS, plain `sed -i` on Linux). Prefer the Edit tool.

### Step 9: Commit

```bash
git add pyproject.toml CHANGELOG.md README.md docs/LLM_USAGE_RULES.md
git commit -m "chore: prepare release vX.Y.Z"
```

Do **not** tag or push. That is `/release`'s job.

### Step 10: Run the live pre-tag check

Immediately before `/release` creates the tag, run the canonical command:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

The default preflight remains static and network-free. This explicit opt-in
command adds the read-only live upstream comparison before the immutable tag is
created.

### Step 11: Hand off

Report:

```
## Release-prep for vX.Y.Z

Last published: vA.B.C (publish remote)
Commits since:  <N>

Features added:
- <language list>
- <MCP tool list>
- <other>

Docs updated:
- README.md: <what>
- CHANGELOG.md: v<version> release header
- docs/LLM_USAGE_RULES.md: <if touched>
- pyproject.toml: <old> → <new>

Next: run /release to cut the tag and push to publish.
```

## Gotchas

- **`git describe --tags --abbrev=0` is wrong for this use case.** It returns the most recent local tag regardless of origin. Upstream tags pulled into the fork (e.g. v3.0.0 from an inherited upstream) will poison the result. Always use `git ls-remote --tags publish`.
- **`pyproject.toml` version and the `publish`-remote latest tag should match** after the last release. If `pyproject.toml` is ahead, the previous release was cut but the tag never pushed — investigate before bumping again.
- **Do not push to `origin` on release.** Per project feedback: releases go to `publish` only. `/release` handles this; this skill does not push.
- **Dependency changes need an audit trail.** Before release notes claim a package upgrade is safe, verify current and target versions against OSV or an equivalent advisory source and test a clean hosted-CI-equivalent resolver. Public notes may include advisory IDs and version ranges; private resolver paths and local incident details stay out.
- **Skip the per-task changelog headers.** Some autopilot flows write `## YYYY-MM-DD · TASK-SLUG` entries at the top of CHANGELOG as work lands. Before release, consolidate them into a single release header with grouped bullets. Do not leave both forms.

## Output

```
## Release-prep summary

Last published: <vX.Y.Z>
Proposed version: <vA.B.C> (<major|minor|patch>)
Commits:       <N> since <vX.Y.Z>
Features:      <count> new languages, <count> new MCP tools
Docs updated:  <list>
Version file:  bumped
Committed:     <yes|no>

Hand off to: /release
```
