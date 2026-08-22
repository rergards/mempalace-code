---
slug: DEPENDENCY-SECURITY-UPGRADE-GATE
status: completed
authority: non_authoritative
goal: "Add a repo dependency-upgrade audit gate that enumerates targets, blocks vulnerable ranges, and verifies fresh resolver audits before lock refresh."
risk: medium
risk_note: "The gate is a maintenance/pipeline change around dependency and lockfile edits; false negatives could admit vulnerable targets, while false positives could block legitimate releases."
files:
  - path: scripts/dependency_upgrade_gate.py
    change: "Add a stdlib-only command-line gate that reads pyproject/uv.lock, validates a target manifest, queries OSV (or configured equivalent), runs fresh-environment resolver audits, writes redacted public reports, and verifies reports in CI."
  - path: tests/test_dependency_upgrade_gate.py
    change: "Add focused tests for dependency enumeration, advisory blocking, optional-extra audit selection, ChromaDB advisory boundaries, report freshness, and CI changed-file enforcement."
  - path: docs/DEPENDENCY_UPGRADE_GATE.md
    change: "Document the target manifest schema, report location, required command order, redaction rules, and the rule that uv.lock is refreshed only after the audited resolver passes."
  - path: .github/workflows/ci.yml
    change: "Add a dependency-upgrade gate step that runs on pull requests/pushes, passes an explicit base ref (pull_request base SHA, push before-SHA) to `ci-check`, and requires a fresh verified report whenever pyproject.toml or uv.lock changed from that base; also set `fetch-depth: 0` on the gate job's checkout step because actions/checkout@v5 defaults to a depth-1 clone that cannot resolve the base ref."
  - path: docs/quality/scorecard.json
    change: "Regenerate the committed quality-scorecard data via `python scripts/quality_scorecard.py --write` after adding tests/test_dependency_upgrade_gate.py, because the new test file changes the repository test shape and the CI lint job's `quality_scorecard.py --check` fails on stale artifacts."
  - path: docs/quality/scorecard.md
    change: "Regenerate the human-readable scorecard alongside scorecard.json in the same `python scripts/quality_scorecard.py --write` run."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_audit_report_enumerates_direct_current_and_target_versions -q` is run"
    then: "the generated report lists every direct runtime, dev, and optional dependency from pyproject metadata with its current lockfile version, declared specifier, target version, and group/extra before any lock refresh is accepted"
  - id: AC-2
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_target_advisory_blocks_report_and_mentions_advisory -q` is run"
    then: "an OSV response marking a selected target version as affected makes the gate exit nonzero, names the package and advisory id, and does not emit a passing report"
  - id: AC-3
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_changed_optional_extras_drive_fresh_resolver_audits_only_for_changed_extras -q` is run"
    then: "the resolver-audit plan always includes a fresh default install, includes dev when dev dependencies change, includes only optional extras whose bounds changed, and skips unchanged optional extras"
  - id: AC-4
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_chromadb_one_x_target_is_rejected_while_ghsa_f4j7_r4q5_qw2c_affects_it -q` is run"
    then: "a target manifest that raises ChromaDB into an OSV-affected 1.x release is rejected and the current `chromadb>=0.5.0,<1` ceiling remains the documented safe boundary"
  - id: AC-5
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_ci_check_requires_fresh_report_before_pyproject_or_lock_change -q` is run"
    then: "the CI gate fails when pyproject.toml or uv.lock changed without exactly one matching public dependency-upgrade report, and passes when the report matches the current file hashes and successful audit status"
  - id: AC-6
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_dependency_gate_docs_define_order_and_public_report_schema -q` is run"
    then: "docs assert the required order: collect targets, query advisories, run fresh resolver audits, write the public report, refresh uv.lock only after success, then run hosted-CI-equivalent clean pip tests"
  - id: AC-7
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_ci_check_passes_when_dependencies_unchanged_and_no_report_exists -q` is run"
    then: "`ci-check` exits zero on a workspace where neither pyproject.toml nor uv.lock differs from the provided base ref and no dependency-upgrade report exists, so clean PRs that do not touch dependencies are never blocked by the gate"
out_of_scope:
  - "Raising any dependency ceiling, changing dependency specifiers, or refreshing uv.lock in this task."
  - "Adding the separate scheduled dependency audit workflow for unchanged current dependencies."
  - "Removing the deprecated ChromaDB backend or adopting ChromaDB 1.x while GHSA-f4j7-r4q5-qw2c affects the available 1.x line."
  - "Guaranteeing supply-chain integrity beyond package metadata, advisory databases, fresh resolver output, and repo test coverage."
  - "Editing backlog metadata, archive files, or bookkeep-owned task state."
contract_policy:
  flow: full_spdd
  reason: "Strict security and provider/pipeline task that changes the gate for dependency and lockfile edits."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The gate must enumerate current and target versions for direct runtime, dev, and optional dependencies from package metadata before dependency bounds or uv.lock are accepted."
      source: "backlog acceptance"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The gate must query OSV or an equivalent advisory source for both current and selected target direct dependency versions and block affected target ranges."
      source: "backlog acceptance"
      acceptance_ids: [AC-2, AC-4]
    - id: REQ-3
      statement: "The gate must run resolver-level audits in fresh environments for the default install and each dependency group or optional extra whose bounds changed."
      source: "backlog acceptance"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Deprecated optional backends must stay capped away from affected ranges; ChromaDB 1.x remains blocked while GHSA-f4j7-r4q5-qw2c affects that line."
      source: "backlog acceptance and CLAUDE.md storage backend policy"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "CI must fail dependency metadata or lockfile changes unless a fresh successful dependency-upgrade report for the same file hashes is present, and must pass changes that do not touch dependency files even when no report exists."
      source: "upgrade gate requirement"
      acceptance_ids: [AC-5, AC-7]
    - id: REQ-6
      statement: "Contributor documentation must define the exact gate order and public-safe report schema so future upgrades are repeatable."
      source: "repeatability requirement"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Dependency upgrade gate script"
      kind: cli
      paths: ["scripts/dependency_upgrade_gate.py"]
      expected_behavior: "Expose `audit`, `verify-report`, and `ci-check` subcommands; `ci-check` takes an explicit `--base-ref` and decides whether pyproject.toml/uv.lock changed via `git diff` against it, failing closed when the base ref is missing or unresolvable; parse pyproject.toml and uv.lock with stdlib TOML support; call advisory and resolver-audit runners through injectable helpers for testability; emit redacted JSON reports under a public docs path."
    - name: "Dependency gate tests"
      kind: internal
      paths: ["tests/test_dependency_upgrade_gate.py"]
      expected_behavior: "Mock advisory and subprocess runners to prove enumeration, failure, boundary, and CI report checks without contacting live networks or creating real resolver environments during unit tests."
    - name: "Dependency gate documentation"
      kind: internal
      paths: ["docs/DEPENDENCY_UPGRADE_GATE.md"]
      expected_behavior: "Document target manifests, changed group/extra selection, ChromaDB 1.x hold policy, public report redaction, and the lock-refresh sequence."
    - name: "Hosted CI guard"
      kind: internal
      paths: [".github/workflows/ci.yml"]
      expected_behavior: "Run the script's CI check in the existing Tests workflow with `fetch-depth: 0` on the gate job's checkout and an explicit base ref (`github.event.pull_request.base.sha` on pull_request, `github.event.before` on push) passed to `ci-check`, so pull requests that change pyproject.toml or uv.lock cannot pass without a fresh successful dependency-upgrade report while PRs that leave both files untouched pass with no report."
  invariants:
    - id: INV-1
      statement: "This task must not change dependency specifiers, package ceilings, or uv.lock content."
      applies_to: ["scripts/dependency_upgrade_gate.py", "docs/DEPENDENCY_UPGRADE_GATE.md", ".github/workflows/ci.yml"]
    - id: INV-2
      statement: "The default install remains local-first and zero-API-by-default; advisory/network checks run only when the explicit dependency-upgrade gate command or CI gate is invoked."
      applies_to: ["scripts/dependency_upgrade_gate.py", ".github/workflows/ci.yml"]
    - id: INV-3
      statement: "Reports and logs committed to the repository must include only package names, versions, advisory ids, remediation notes, hashes, and command names; no private paths, tokens, resolver caches, hostnames, or credentials."
      applies_to: ["scripts/dependency_upgrade_gate.py", "docs/DEPENDENCY_UPGRADE_GATE.md"]
    - id: INV-4
      statement: "ChromaDB remains a deprecated optional backend capped below 1.x until the relevant advisory no longer affects the chosen target and the clean chroma audit/compat path passes."
      applies_to: ["scripts/dependency_upgrade_gate.py", "docs/DEPENDENCY_UPGRADE_GATE.md"]
  risks:
    - id: RISK-1
      risk: "A target manifest could omit a direct dependency and make the audit look complete."
      mitigation: "Compare target manifest package/group coverage against parsed pyproject direct dependencies and fail on missing or unknown direct targets."
    - id: RISK-2
      risk: "Unit tests that hit live OSV or pip-audit would be flaky and slow."
      mitigation: "Keep network and subprocess execution behind injectable helpers; unit tests assert command construction and decisions with fixtures, while the real gate is exercised by explicit audit/CI commands."
    - id: RISK-3
      risk: "CI could accept a stale report generated for older dependency files."
      mitigation: "Include pyproject.toml and uv.lock hashes in the report and make `ci-check` compare them to the current workspace before passing."
    - id: RISK-4
      risk: "Public reports could accidentally include private temp paths from resolver output."
      mitigation: "Store structured summaries only, redact command output to package/version/advisory fields, and add tests that plant a private path in fake tool output and assert it is absent from the report."
    - id: RISK-5
      risk: "ChromaDB 1.x could be raised because API compatibility tests pass even though security advisories remain active."
      mitigation: "Make advisory status a hard gate before resolver tests and keep a dedicated ChromaDB advisory-boundary test."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_audit_report_enumerates_direct_current_and_target_versions -q"
      proves: "The report includes direct dependency coverage, current lock versions, declared specifiers, target versions, and dependency groups/extras."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_target_advisory_blocks_report_and_mentions_advisory -q"
      proves: "Affected target versions fail closed and surface package/advisory evidence without writing a passing report."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_changed_optional_extras_drive_fresh_resolver_audits_only_for_changed_extras -q"
      proves: "Fresh resolver audits are scoped to default plus changed dependency groups/extras."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_chromadb_one_x_target_is_rejected_while_ghsa_f4j7_r4q5_qw2c_affects_it -q"
      proves: "The legacy ChromaDB backend cannot be raised into an advisory-affected 1.x target."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_ci_check_requires_fresh_report_before_pyproject_or_lock_change -q"
      proves: "CI enforcement rejects dependency metadata/lock changes without exactly one fresh successful report for the current file hashes."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_dependency_gate_docs_define_order_and_public_report_schema -q"
      proves: "The contributor docs preserve the required gate order and public report schema."
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_ci_check_passes_when_dependencies_unchanged_and_no_report_exists -q"
      proves: "The clean-PR path is covered: when neither dependency file changed from the base ref and no report exists, `ci-check` passes instead of failing closed or silently passing dependency changes."
      acceptance_ids: [AC-7]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_dependency_upgrade_gate.py -q"
        proves: "All dependency-upgrade gate decisions remain stable across happy path, advisory failure, Chroma boundary, report freshness, clean-PR pass, and docs schema checks."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-2
        command: "python -m pytest tests/test_public_safety_scan.py::test_repository_scan_rejects_local_only_artifact_path -q"
        proves: "The public-safety scan still rejects local-only artifact paths while dependency reports use the documented public-safe location instead of docs/audits."
        acceptance_ids: [AC-6]
      - id: REG-3
        command: "python -m pytest tests/test_chroma_compat.py -q"
        proves: "Existing deprecated Chroma compatibility coverage still runs without requiring a ChromaDB ceiling raise."
        acceptance_ids: [AC-4]
      - id: REG-4
        command: "python scripts/quality_scorecard.py --check"
        proves: "The committed docs/quality/scorecard.{json,md} artifacts match the repository test shape after tests/test_dependency_upgrade_gate.py is added, so the CI lint job's scorecard freshness gate passes instead of failing on stale artifacts."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
      - id: REG-5
        command: "actionlint .github/workflows/ci.yml"
        proves: "The edited Tests workflow YAML — including the fetch-depth checkout change and base-ref expressions — is syntactically valid and the new dependency-upgrade gate step is well-formed; this is a static syntax/version check only and hosted execution stays unproven until a real pull_request/push trigger runs the workflow."
        acceptance_ids: [AC-5, AC-7]
      - id: REG-6
        command: "ruff check scripts/dependency_upgrade_gate.py tests/test_dependency_upgrade_gate.py"
        proves: "The new gate script and test file pass the same ruff lint gate the hosted CI lint job runs over scripts/ and tests/."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-7
        command: "ruff format --check scripts/dependency_upgrade_gate.py tests/test_dependency_upgrade_gate.py"
        proves: "The new files pass the hosted CI lint job's ruff format gate so the lint job cannot fail on formatting after this task lands."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
---

## Design Notes

- Add a repo maintenance script rather than a runtime dependency. Use only stdlib modules (`argparse`, `json`, `hashlib`, `subprocess`, `tempfile`, `tomllib`, `urllib`) so normal package installs stay local-first and zero-API-by-default.
- Target manifest format: JSON with exact target versions keyed by package plus changed dependency surfaces, for example `{"targets": {"lancedb": "0.33.0"}, "changed_groups": ["runtime"], "changed_extras": []}`. The script should reject unknown target packages and any missing direct dependency target for a changed group/extra.
- Dependency enumeration source of truth:
  - runtime dependencies from `[project].dependencies`;
  - dev dependencies from `[dependency-groups].dev` and `[project.optional-dependencies].dev`;
  - optional dependencies from `[project.optional-dependencies]`, including `chroma`, `spellcheck`, `watch`, and `treesitter`;
  - current resolved versions from `uv.lock` when present, with a clear failure when a direct dependency cannot be matched.
- `audit` mode should query OSV `querybatch` or the configured equivalent for both current and target versions of every direct dependency in scope. Treat an affected target as a hard failure before running resolver audits.
- Fresh resolver audits should use disposable temp virtualenvs and command summaries, not the developer's `.venv`: default install always, `[dev]` when dev changed, and only optional extras named by `changed_extras`. The script may install `pip-audit` inside each temp env; do not add it as a project runtime dependency.
- Public reports should live outside `docs/audits/` because the existing public-safety scan treats `docs/audits/` as a local-only artifact path. Use a documented public path such as `docs/dependency-upgrade-reports/<slug>.json`, and store only hashes, package names, versions, advisory ids, verdicts, and sanitized command summaries.
- `verify-report` should re-check report schema, file hashes, status, changed groups/extras, and advisory/resolver verdict fields. `ci-check` should decide whether `pyproject.toml` or `uv.lock` changed via the base-ref diff below, require exactly one matching report under the public report directory when they did, and delegate report validation to `verify-report`.
- Change detection in `ci-check` is pinned: a git base ref is the primary and required change detector, and report-hash matching is only the freshness validator applied after a change is detected. Hash matching alone cannot decide the change question — after this task lands there is no committed baseline report (out of scope), so a hash-only rule would either fail every clean PR (fail-closed on "missing report") or wave through unaudited bumps (fail-open). The pinned behavior:
  - `ci-check` takes an explicit `--base-ref`; the workflow passes `github.event.pull_request.base.sha` on `pull_request` and `github.event.before` on `push`, and the gate diffs `pyproject.toml`/`uv.lock` against that ref.
  - Neither file changed from the base → **pass**, with or without a report present. This is the clean-PR path (AC-7) and is what lets the gate land with no committed report without breaking every subsequent PR.
  - Either file changed from the base → require exactly one report under the public report directory whose recorded `pyproject.toml`/`uv.lock` content hashes match the current workspace files and whose audit status is success (via `verify-report`); a missing report, hash mismatch, or non-success status fails the gate (AC-5).
  - Base ref missing or unresolvable (e.g. all-zero push before-SHA on a force-push) → fail closed by treating the dependency files as changed, so a broken base ref can never let an unaudited bump through.
  Because `actions/checkout@v5` runs at the default depth-1 clone in this workflow, the gate job's checkout must set `fetch-depth: 0` (or explicitly fetch the base ref) — that checkout edit is part of this task's `.github/workflows/ci.yml` change and is covered by the actionlint regression check.
- Wire the CI gate into the existing Tests workflow without creating the separate scheduled audit workflow. The scheduled audit task remains separate backlog scope for unchanged current dependencies.
- Validate the edited workflow statically with `actionlint .github/workflows/ci.yml`. Name the verification boundary explicitly in the docs and this plan: the YAML wiring of the new gate step — including the `fetch-depth: 0` checkout change and the base-ref event expressions — is syntax- and version-checked only; its hosted runtime behavior is not execution-tested unless a real `pull_request`/`push` trigger runs the Tests workflow.
- Run `ruff check` and `ruff format --check` over the new script and test file before landing (REG-6/REG-7): the hosted CI lint job gates on `ruff check mempalace_code/ tests/ scripts/` and `ruff format --check` over the same paths, so the new files must pass both locally.
- Regenerate the committed quality scorecard after the new test file lands: adding `tests/test_dependency_upgrade_gate.py` changes the repository test shape, which stales `docs/quality/scorecard.json` and `docs/quality/scorecard.md` and would fail the CI lint job's `python scripts/quality_scorecard.py --check`. Run `python scripts/quality_scorecard.py --write` to refresh both artifacts and keep `--check` green (REG-4).
- Keep the ChromaDB rule explicit: API compatibility tests are not enough to raise the ceiling; the selected ChromaDB target must be advisory-clean first, and GHSA-f4j7-r4q5-qw2c blocks the available 1.x line until the advisory source says otherwise.
