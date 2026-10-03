---
name: release
description: Qualify and publish a mempalace-code release through the canonical runbook
disable-model-invocation: true
---

# Release

Use for `release`, `publish`, or `ship` after release preparation is complete.

## Canonical owner

Read `AGENTS.md` and `docs/RELEASING.md` in full. Execute that runbook in order.
Do not restate or improvise its branch, tag, admission, publication, or recovery
procedure here.

## Guards

- Bind qualification to one reviewed 40-hex candidate SHA.
- Before local edits, run `autopilot doctor --json` and require `safe_to_edit=true`.
  Without the maintainer-local `autopilot` CLI, require an empty
  `git status --porcelain` and confirm no other session or worktree is writing
  to this checkout; otherwise stop.
- Never invoke Codex, Claude, Gemini, another model/provider, or an authenticated
  client as a release check.
- Never read, copy, inspect, require, or transmit API keys, OAuth tokens,
  keychains, client auth files, paid-account state, or ambient credentials.
- Candidate push, `main` update, tag push, candidate deletion, commit, and every
  other remote mutation each require fresh explicit authority.
- Never force-push, move a published tag, bypass protection, or repair a remote
  ruleset from this skill.
- Stop on a dirty candidate, SHA drift, artifact mismatch, red gate, ambiguous
  partial publication, or missing authority. Preserve current state.
- Stop when `docs/quality/acceptance/v$VERSION.md` is missing, is not PASS, or
  records package ids other than the candidate's; hand back to `/release-prep`
  for the installed-candidate acceptance test (`docs/RELEASING.md` section 1a).

## Local qualification

Use the repository owners; do not add another gate:

```bash
python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json
python scripts/release_preflight.py --tag "v$VERSION" --require-clean --expect-sha "$CANDIDATE_SHA"
```

The readiness gate must build and inspect the artifacts and exercise the exact
installed wheel without credentials. The tag preflight's `acceptance_report` row
must be `ok`: the committed acceptance report binds this exact package tree.
Hosted CI must report `release-required` for the same SHA before the next
authorized mutation.

## Output

Report:

- version and candidate SHA;
- acceptance report result;
- local qualification result;
- hosted required-check result;
- artifact filenames and hashes;
- publication state: `not_started`, `partial`, or `complete`;
- the single next command, or the exact blocker.

Never call a partial publication complete. Use only the recovery command emitted
by `release_status_gate.py` for the observed state.
