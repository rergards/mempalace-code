# Workflow Review Protocol

Public-safe protocol for using a multi-agent Claude workflow to improve this
repo without publishing raw local evidence.

## Publishable Summary Schema

Every surviving finding in a sanitized public summary must include these fields:

| Field | Purpose |
|-------|---------|
| `Review lens` | Which lens produced the finding (correctness, public-safety, etc.) |
| `Finding` | Concise description of the issue |
| `Evidence` | Concrete file path and line number in the repo (relative path only) |
| `Action taken` | Relative file path changed and what was done — or `n/a` when deferred |
| `Verification` | Command used to confirm the fix — or `n/a` when deferred |
| `Deferral reason` | Backlog item identifier and acceptance criteria — or `n/a` when fixed |

**Passive review output is insufficient.** A summary that only lists findings
without verified code, test, or documentation changes does not constitute a
deliverable. Every surviving finding must resolve through exactly one concrete
outcome branch:

**Actionability rule:** Every surviving finding must satisfy exactly one of:

- **Fixed branch**: `Action taken` contains a concrete relative file path and
  `Verification` contains a non-trivial command.
- **Deferred branch**: `Deferral reason` contains a backlog item identifier
  (e.g. `BACKLOG-ID`) and includes acceptance criteria text.

Empty values, `none`, `n/a`, and generic prose do not satisfy either branch.
A finding that neither changes code/tests/docs with verification nor becomes a
backlog item with acceptance criteria is ceremonial and must not be published.

**Guard command** — run before publishing or committing a synthesized summary:

```bash
python scripts/workflow_summary_guard.py --file path/to/summary.md
# or from stdin (e.g. a PR-body snippet):
cat pr-body.md | python scripts/workflow_summary_guard.py
```

The guard exits nonzero if any finding lacks evidence, lacks an action or
deferral branch, or contains a private path, absolute host path, or secret-like
token. Diagnostics report the rule id and position only — matched sensitive
content is never echoed.

## Raw-Transcript Boundary

Raw multi-agent outputs and local evidence paths must remain under git-ignored
local paths such as `.tasks/`, `.protocols/`, and `docs/audits/`. Do not paste
raw transcript excerpts, absolute host paths, or private workspace references
into public summary files or PR bodies.

## Trigger

Use this after a focused implementation is ready for review, especially for
quality-gate, release, security, dependency, CI, or public-demo changes.

## Inputs

- Current branch diff against `main`.
- Relevant public files only: source, tests, public docs, CI config, package
  metadata.
- Explicit task acceptance criteria and verification commands.
- Local-only evidence paths may be used by the operator, but must not be pasted
  into public artifacts.

## Lenses

Run independent reviewers for these lenses:

- Correctness: behavior, edge cases, failure modes.
- Determinism: stable output, ordering, caches, generated artifacts.
- Public-safety: secrets, private paths, local-only artifacts, publishable docs.
- Test coverage: real regression protection, not only happy-path assertions.
- Spec compliance: task acceptance criteria, repo rules, release boundaries.
- Maintainability: scoped design, duplication, future ratchets.

## Refutation

Each finding must pass a skeptical refutation step before implementation:

- Check the exact code path and tests.
- Reject findings based only on style preference or imagined behavior.
- Keep only findings with a concrete file, behavior, or missing gate.
- Record deliberate deferrals separately from fixes.

## Synthesis

The synthesis lead deduplicates surviving findings into:

- Implement now: actionable, low-ambiguity fixes in scope.
- Defer: valuable but separate backlog item.
- Reject: disproven or out-of-scope findings.

The public summary may include counts and categories. Do not publish raw model
transcripts, private local paths, hostnames, tokens, or task workspace contents.

## Implementation

Apply only vetted, scoped fixes. Update tests and canonical gates first, then
update public docs/backlog/scorecard. Keep raw workflow outputs under ignored
local paths such as `.tasks/`, `.protocols/`, or `docs/audits/`.

## Verification

After acting on a workflow review, run the full canonical `/verify` gate set in
`.claude/skills/verify/INSTRUCTIONS.md`. Its commands come from
`scripts/gate_inventory.py`, and `scripts/docs_drift_guard.py` keeps them in step,
so this protocol does not keep its own copy.

If hosted workflow behavior matters, verify the real GitHub Actions run before
calling the change published.
