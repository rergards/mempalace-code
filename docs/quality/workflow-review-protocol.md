# Workflow Review Protocol

Public-safe protocol for using a multi-agent Claude workflow to improve this
repo without publishing raw local evidence.

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

Minimum verification after acting on a workflow review:

```bash
ruff check mempalace_code/ tests/ scripts/
ruff format --check mempalace_code/ tests/ scripts/
python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"
python -m pyright -p pyrightconfig.strict.json
python scripts/public_safety_scan.py --tracked --staged
python scripts/quality_scorecard.py --check
python -m pytest tests/ -x -q -m "not needs_network"
```

If hosted workflow behavior matters, verify the real GitHub Actions run before
calling the change published.
