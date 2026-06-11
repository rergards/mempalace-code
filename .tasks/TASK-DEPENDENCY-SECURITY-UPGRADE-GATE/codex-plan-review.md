verdict: NEEDS_CHANGES

# Plan Review — DEPENDENCY-SECURITY-UPGRADE-GATE (strict)

## Summary

The contract canvas is structurally complete and well-formed. `task_contract` (v1, strict) is
present; `contract_policy` is `full_spdd` with `sync_gate: required` and
`verification_path: automated`; every acceptance criterion (AC-1..AC-6) has a linked
`verification` row (VER-1..VER-6) and at least one `regression_plan.checks` row
(REG-1 covers all six; REG-2→AC-6; REG-3→AC-4; REG-4 covers all six; REG-5→AC-5);
`regression_plan.applies: true` with non-empty checks; all verification/regression commands are
runnable shell commands (pytest / actionlint / python script); no backlog or archive files appear
in the files list, surfaces, or touched files, and `out_of_scope` explicitly excludes
backlog/bookkeep edits.

Several non-obvious claims were verified against the live repo and hold:

- `docs/audits/` is in the public-safety scan's `LOCAL_ONLY_PREFIXES`
  (scripts/public_safety_scan.py:20-26), so routing reports to `docs/dependency-upgrade-reports/`
  is correct, and REG-2 exercises the real test.
- Adding `tests/test_dependency_upgrade_gate.py` genuinely stales the scorecard: `collect_tests`
  counts test files and functions (scripts/quality_scorecard.py:299-300), the lint job runs
  `quality_scorecard.py --check` (.github/workflows/ci.yml:67), and the plan now lists
  docs/quality/scorecard.{json,md} (lines 15-18) with REG-4 — this resolves the earlier review's
  high gap.
- actionlint (REG-5) and the named hosted-only verification boundary (design note line 189)
  resolve the earlier review's medium gap.
- `chromadb>=0.5.0,<1` cap and the GHSA note exist (pyproject.toml:52-54), matching INV-4/AC-4;
  optional extras (dev, spellcheck, chroma, watch, treesitter) match the plan (pyproject.toml:49-62).
- `tomllib` is stdlib-safe on the supported `>=3.11` runtime (pyproject.toml:6); scripts/ is not in
  the pyright include (pyproject.toml:143-148) nor the strict slice (pyrightconfig.strict.json), so
  the new script has no typecheck obligation.

One high-severity design gap blocks readiness, plus one medium completeness gap.

gaps:
  - severity: high
    claim: "The `ci-check` change-detection design is internally contradictory and leaves the most
      common case — a PR that does not touch dependencies and ships no report — broken or
      unspecified. Design note line 187 makes report-hash comparison the sole authority, calls the
      diff base 'optional', and asserts the step is 'implementable without a deferred design
      choice'. But hash comparison alone cannot detect change-from-base when no report exists. After
      this task lands there is no committed report (files list lines 6-18 add none; out_of_scope
      line 39 forbids generating one). Taken literally, '(a mismatch OR missing matching report)
      means the gate requires a fresh report' is fail-closed: the next clean PR has no matching
      report and FAILS ci-check — breaking every PR that does not touch deps, including the PR that
      introduces the gate. The only no-diff-base alternative is fail-open (no report + nothing to
      compare => pass), which lets an unaudited dependency bump through and silently violates REQ-5.
      Either way a base ref (PR merge-base / push before-SHA, or a per-step path/diff guard) is
      ESSENTIAL — not optional — making this a real deferred design decision the plan claims to have
      avoided. It is also non-trivial here: actions/checkout@v5 runs at the default shallow depth
      (no fetch-depth in ci.yml), so a merge-base diff is unavailable without also editing the
      checkout step, which the plan does not list."
    evidence: "docs/plans/DEPENDENCY-SECURITY-UPGRADE-GATE.md:186-187 (ci-check detects changes;
      diff base called optional; 'hash comparison is the deciding signal'); :39 (out_of_scope: no
      report generated); :6-18 (files list has no docs/dependency-upgrade-reports/*.json baseline);
      AC-5 lines 32-34 and VER-5 lines 140-143 cover only (changed+no-match => fail) and
      (match => pass), never (unchanged+no-report => pass); .github/workflows/ci.yml:23,37,53,72,93
      (checkout with no fetch-depth => depth 1, no merge-base available)"
    suggested_fix: "Pin the change-detection mechanism before implementation. Make a base ref the
      primary 'did pyproject.toml/uv.lock change in this PR' detector (merge-base on pull_request,
      before-SHA on push, or a per-step path guard), and use report-hash matching only as the
      freshness validator once a change is detected; then add `fetch-depth: 0` (or an explicit
      base-ref fetch) to the ci.yml checkout step and list that edit. Add an AC + verification +
      regression row proving ci-check PASSES on a no-dep-change, no-report workspace, so the
      clean-PR path is covered, not just the fail/pass-with-report paths. Revise design note 187 so
      it no longer calls the diff base optional or claims there is no deferred design choice. (If
      instead the intent is an always-current committed baseline report, then a
      docs/dependency-upgrade-reports/*.json file must be added to the files list and reconciled
      with out_of_scope.)"
  - severity: medium
    claim: "The CI lint job runs `ruff check mempalace_code/ tests/ scripts/` and
      `ruff format --check mempalace_code/ tests/ scripts/` as hard gates, so the new
      scripts/dependency_upgrade_gate.py and tests/test_dependency_upgrade_gate.py must pass both —
      but the plan's verification and regression_plan never run ruff. An implementer running only
      the listed commands can land code that fails the hosted lint job."
    evidence: ".github/workflows/ci.yml:62-63 (ruff check + format over scripts/ and tests/); plan
      regression_plan REG-1..REG-5 (lines 152-171) cover pytest, public-safety, chroma-compat,
      scorecard --check, and actionlint, but no ruff check/format"
    suggested_fix: "Add a regression check such as `ruff check scripts/ tests/` and
      `ruff format --check scripts/ tests/` (or scoped to the two new files) so the plan's own
      verification set exercises the lint gate the new files must pass."

## Verdict rationale

The contract canvas is complete and the architectural claims I spot-checked hold against current
repo state; the earlier review's three gaps (scorecard files, actionlint/boundary, diff-base
mention) are addressed in this revision. The remaining blocker is the `ci-check` change-detection
design: the chosen resolution at line 187 is logically self-contradictory and, as written, would
either fail every clean PR or be a no-op that misses REQ-5 — a hidden blocker the mocked AC-5
unit test does not catch because it never exercises the no-dep-change, no-report path. That is a
high-severity gap that would cause the hosted gate to fail or miss its requirement, so the verdict
is NEEDS_CHANGES.
