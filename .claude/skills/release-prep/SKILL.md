---
name: release-prep
description: Audit and prepare public release metadata before the separately authorized release workflow
disable-model-invocation: true
---

# Release Prep

Use for release notes, public-document synchronization, and a proposed version
bump before `/release`.

## Canonical owners

Read `AGENTS.md`, `docs/RELEASING.md`, `CHANGELOG.md`, and `pyproject.toml` in
full. Use the `publish` remote as release history; local tags may include
unpublished upstream history.

## Guards

- Run `autopilot doctor --json`; require `safe_to_edit=true` for every proposed
  local path.
- Never invoke Codex, Claude, Gemini, another model/provider, or an authenticated
  client during release preparation.
- Never read, copy, inspect, require, or transmit credentials, API keys, OAuth
  tokens, keychains, auth files, paid-account state, or ambient credentials.
- Inspection authorizes no edits. Require fresh authority for the exact docs,
  changelog, and version paths before writing.
- Commit, push, tag, publication, and candidate cleanup each require separate
  explicit authority. This skill performs none of them.
- Never use `--force`, rewrite a public ref, or infer release identity from a
  local tag.

## Inspect

Resolve the last plain `vX.Y.Z` tag with
`python scripts/release_public_read.py --version-tags`. Compare that tag through
`HEAD` and inspect the current public behavior owners. Report:

- user-visible additions, changes, fixes, and compatibility notes;
- public docs or examples that disagree with executable behavior;
- package, optional-extra, CLI, MCP, or Python-support changes;
- the smallest semantic-version bump justified by that diff.

Do not turn internal plans, local paths, machines, agent identities, incident
details, or private release evidence into public notes.

## Apply when authorized

Update only the confirmed version owner, one consolidated release entry in
`CHANGELOG.md`, and public docs proven stale by the diff. Do not create a second
release procedure or tracked validation log.

## Validate

```bash
python scripts/docs_drift_guard.py
python scripts/public_safety_scan.py --tracked --staged
python scripts/quality_scorecard.py --check
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

The live preflight is read-only. A failure stops the handoff; it does not
authorize a gate, ruleset, remote, or workflow repair.

## Output

Report the last published tag, proposed version and reason, exact modified
paths, validation results, and one next action. Hand off to `/release` only when
the prepared tree is coherent. Report the commit command instead of running it.
