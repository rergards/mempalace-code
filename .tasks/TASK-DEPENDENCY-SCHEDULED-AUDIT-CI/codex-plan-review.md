verdict: READY

# Plan Review — DEPENDENCY-SCHEDULED-AUDIT-CI (strict)

## Summary

The plan is implementable as written. It extends the existing stdlib-only
`scripts/dependency_upgrade_gate.py` with a `current-audit` subcommand, adds a
separate scheduled `.github/workflows/dependency-audit.yml`, an allowlist file,
focused tests, doc updates, and regenerates the quality scorecard. All eight
acceptance criteria map to named, runnable pytest tests; the files list is
complete and every file is represented in the `surfaces:` canvas; and the
hosted-runtime verification boundary is named explicitly.

## Verification against repo state (read-only checks performed)

- `scripts/dependency_upgrade_gate.py` is stdlib-only with injectable
  `advisory_querier`/`resolver_runner`/`git_runner` seams and existing
  pyproject/lock parsing, OSV query, resolver-audit, and redaction tests — the
  reuse claim (Design Notes) holds. Adding `current-audit` is additive and does
  not disturb `audit`/`verify-report`/`ci-check` (INV-3 preserved).
- `pyproject.toml` declares exactly the four non-dev optional extras the plan
  names (`spellcheck`, `chroma`, `watch`, `treesitter`) plus the `dev` group, so
  AC-2's enumeration is concrete and testable.
- Runtime direct deps (`lancedb`, `sentence-transformers`, `pyyaml`,
  `packaging`) and `chromadb`/tree-sitter extras match AC-3's named packages.
- `quality_scorecard.py --check` enforces byte-identical committed
  `docs/quality/scorecard.{json,md}`; it counts `tests/` test functions, so
  adding tests forces regeneration — both artifacts are correctly in the files
  list (REG-6 is self-enforcing).
- `actionlint` 1.7.12 is installed locally (REG-3 runnable); `uv.lock` exists
  (current-audit can read resolved versions); `docs/dependency-upgrade-reports/`
  does not exist, consistent with INV-2 (run reports are artifacts, not
  committed).
- The existing AC-6 doc test keywords (`collect`, `advisories`, `resolver`,
  `uv.lock`, `schema_version`, `pyproject_hash`, `lockfile_hash`,
  `GHSA-f4j7-r4q5-qw2c`, `<1`) are all present in the current doc; AC-8's
  additive doc edits will not regress that test as long as the keywords stay.
- The existing `ci.yml` already uses `${{ github.workspace }}` and `https://`
  URLs and passes `public_safety_scan.py --tracked --staged`, so the new
  workflow file has precedent for clearing the public-safety gate.

## Contract canvas evaluation

- `task_contract:` present (version 1, mode strict). PASS
- `contract_policy:` present, `flow: full_spdd`, `sync_gate: required`,
  `verification_path: automated`. PASS
- No backlog metadata (`docs/BACKLOG.yaml`, archive files) listed as
  provider-owned/touched files; `out_of_scope` and design notes explicitly keep
  BACKLOG.yaml untouched and route notification to an issue-backed follow-up.
  PASS
- Every acceptance criterion (AC-1..AC-8) has a linked `verification:` row
  (VER-1..VER-8). PASS
- All `verification:` commands are runnable shell (`python -m pytest …`); no
  placeholder/prose-only commands. PASS
- `regression_plan.applies: true`; every AC is covered by REG-1
  (acceptance_ids AC-1..AC-8); all REG commands are runnable (pytest, CLI
  `--help`, `actionlint`, `ruff`, scorecard `--check`) with no placeholders.
  PASS
- All `surfaces:` paths correspond to entries in the `files:` list and vice
  versa. PASS

## Gaps

gaps:
  - severity: low
    claim: "RISK-3 (scheduled failures spam a new issue every cron run) is mitigated only by workflow YAML design; no acceptance criterion statically asserts the single-issue/stable-marker dedup. AC-1's 'then' verifies schedule+dispatch triggers, artifact upload, issue-write permission, and absence of dependency-file/uv-lock edit steps, but not that the workflow lists-then-updates one stable issue."
    evidence: "docs/plans/DEPENDENCY-SCHEDULED-AUDIT-CI.md:22-24 (AC-1) vs lines 130-131 (RISK-3) and 214-219 (design notes)"
    suggested_fix: "Optionally extend the AC-1 test to also assert the workflow body contains a stable issue marker/title and invokes `gh issue list`/`gh issue edit` before `gh issue create`. The gh runtime behavior remains a named hosted boundary, but the dedup wiring is statically checkable. Non-blocking; the boundary is already disclosed in out_of_scope line 51."
  - severity: low
    claim: "REG-2 `python scripts/dependency_upgrade_gate.py current-audit --help` does not strictly prove 'without requiring a manifest' — argparse prints help and exits 0 even when required args exist."
    evidence: "docs/plans/DEPENDENCY-SCHEDULED-AUDIT-CI.md:180-182 (REG-2)"
    suggested_fix: "No change required for correctness; the real proof that current-audit takes no manifest lives in the AC-2/AC-7 unit tests (VER-2, VER-7). Leave REG-2 as a smoke check or tighten its `proves:` wording to 'exposes the entry point' rather than 'without requiring a manifest'."

## Decision

No critical or high-severity gaps. Acceptance criteria are observable and
testable, the files list is complete, there are no hidden TBD/deferred blockers,
the stdlib-only / separate-workflow / preserve-existing-gate constraints are
respected, and the contract canvas is fully compliant. Verdict: READY.
