verdict: READY

# Plan Review — RELEASE-PUBLICATION-STATUS-GATE (strict)

## Summary

The plan adds an executable, stdlib-only release-status gate under `scripts/`
that verifies every public publication surface (publish-remote tag, branch Tests
workflow, Publish-to-PyPI workflow, GitHub Release metadata, PyPI JSON files,
fresh no-cache install smoke) before a release may be called shipped, plus a
mocked test suite, an updated release skill, and regenerated quality-scorecard
artifacts. It is ready to implement.

## Validation performed against current repo state

- **Workflow names match.** `.github/workflows/ci.yml` is `name: Tests` and
  `.github/workflows/publish.yml` is `name: Publish to PyPI`, so the plan's
  `gh run list --workflow Tests` and `--workflow "Publish to PyPI"` references
  (Design Notes lines 182-183) are correct. `ci.yml` triggers on push to `main`,
  consistent with `--branch main`.
- **scripts/ gate pattern is established.** `dependency_upgrade_gate.py`,
  `public_safety_scan.py`, and `migrate_storage_smoke.py` each have a paired
  `tests/test_*.py`. The new `scripts/release_status_gate.py` +
  `tests/test_release_status_gate.py` follows the same convention — no
  architectural contradiction.
- **Scorecard regeneration is genuinely required, not busywork.**
  `check_committed_artifacts` (scripts/quality_scorecard.py:564-576) re-renders
  and compares the committed `docs/quality/scorecard.{md,json}`, emitting
  `stale-artifact` and failing `run_check` on any drift. The scorecard counts
  every non-fixture `tests/*.py` (`test_files`/`test_functions`), so adding the
  new test file makes the committed scorecard stale and would fail the CI
  `--check`. The plan correctly lists both artifacts as regenerate-only and
  guards it with REG-5.
- **Lint/type scoping is accurate.** CI lints `scripts/` (ci.yml:62) and pyright
  `include = ["mempalace_code", "tests"]` (pyproject.toml:145). The plan's Design
  Note (line 177) reflects this exactly: ruff (REG-3) covers the new script,
  pyright (REG-4) covers the new test file.

## Contract canvas checks (strict)

- `task_contract:` present (version 1, mode strict). ✓
- `contract_policy:` present with `flow: full_spdd`, `sync_gate: required`,
  `verification_path: automated`, and a concrete `reason`. ✓
- Every acceptance criterion has a `verification:` row via `acceptance_ids`
  (AC-1→VER-1 … AC-6→VER-6). ✓
- Every acceptance criterion has a `regression_plan.checks` row (AC-1..AC-5 via
  REG-1/3/4/5, AC-5 also REG-2, AC-6 via REG-6). ✓
- `regression_plan.applies: true` with non-placeholder, runnable commands. ✓
- No backlog files (`docs/BACKLOG.yaml`, archives) appear in `files`,
  `surfaces`, or `touched_files`; out_of_scope explicitly excludes them. ✓
- All `verification`/`regression_plan.checks` commands are runnable shell
  commands grounded in current manifests (pytest/ruff/pyright dev tooling in
  pyproject, `quality_scorecard.py --check` exists, `rg` over a tracked file).
  No prose-only or `manual:` rows. ✓

## Gaps

gaps:
  - severity: low
    claim: "REG-4 'proves' wording implies pyright type-checks the new script, but pyright include is scoped to mempalace_code/ and tests/ only — scripts/release_status_gate.py is not type-gated."
    evidence: "pyproject.toml:145 (include = [\"mempalace_code\", \"tests\"]); plan REG-4 lines 161-164 and Design Note line 177"
    suggested_fix: "No plan change required (the plan's own Design Note already acknowledges pyright covers tests/ and ruff covers scripts/). Implementer should simply not rely on pyright to catch type errors inside the new script; ruff (REG-3) is the only static gate covering it. REG-4 still correctly proves the repository type gate stays green."

## Verdict rationale

All six acceptance criteria are observable via specific pytest node IDs or a
concrete `rg` invocation. The file list is complete: script, test, skill, and
both scorecard artifacts — and the scorecard inclusion is verified-necessary, not
speculative. No hidden TBD/deferred design work. No architectural contradiction
(scripts/ gate + paired test is the existing pattern; workflow names verified).
Every behavior change has associated test coverage. The single observation above
is low-severity and already anticipated by the plan's design notes, so it does
not block implementation.
