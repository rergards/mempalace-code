---
slug: DEPENDENCY-SCHEDULED-AUDIT-CI
status: completed
authority: non_authoritative
goal: "Add a scheduled dependency audit workflow for current resolved packages without changing dependency bounds or uv.lock."
risk: medium
risk_note: "This is a hosted CI and dependency-security change with networked advisory/resolver checks; false positives can create noisy issues and false negatives can miss vulnerable current packages."
files:
  - path: .github/workflows/dependency-audit.yml
    change: "Add a scheduled and workflow_dispatch GitHub Actions workflow that runs the current dependency audit, uploads the sanitized report, opens or updates an issue-backed backlog item on actionable drift, and preserves the failing status after notification."
  - path: scripts/dependency_upgrade_gate.py
    change: "Extend the existing stdlib dependency audit script with a current-audit mode that audits current lock/resolver state, checks OSV and PyPI yanked metadata, applies an explicit allowlist, emits sanitized reports and issue payloads, and never writes dependency metadata."
  - path: tests/test_dependency_upgrade_gate.py
    change: "Add focused unit tests for current-audit install planning, OSV and yanked checks, allowlist expiry/mismatch behavior, public-safe reports, no dependency-file mutation, workflow wiring, and issue-backed backlog notification payloads."
  - path: docs/DEPENDENCY_UPGRADE_GATE.md
    change: "Document the scheduled current-audit workflow, allowlist schema, notification behavior, public-safe report boundary, and the distinction from dependency-upgrade reports."
  - path: docs/dependency-audit-allowlist.json
    change: "Add the public allowlist file with schema_version and empty entries; future accepted risks must include advisory id, package, affected range, reason, and expiry date."
  - path: docs/quality/scorecard.json
    change: "Regenerate the deterministic quality scorecard after adding current-audit tests."
  - path: docs/quality/scorecard.md
    change: "Regenerate the human-readable scorecard alongside the JSON artifact."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_dependency_audit_workflow_declares_schedule_dispatch_artifact_and_notification -q` is run"
    then: "the new workflow is proven to have both `schedule` and `workflow_dispatch` triggers, uploads the sanitized audit report artifact, has issue-write permission only for failure notification, and does not contain steps that run `uv lock`, edit `pyproject.toml`, or edit `uv.lock`."
  - id: AC-2
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_plans_default_dev_and_all_optional_extra_installs -q` is run"
    then: "the current-audit command plans fresh resolver audits for the default install, `[dev]`, and every optional extra declared in pyproject.toml, including `[treesitter]`, `[spellcheck]`, `[chroma]`, and `[watch]`."
  - id: AC-3
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_queries_osv_for_current_direct_lock_versions -q` is run"
    then: "OSV queries are made for current locked direct dependency versions including `lancedb`, `sentence-transformers`, `pyyaml`, `packaging`, `chromadb`, and the tree-sitter packages, and the report stores only package names, versions, advisory ids, and remediation notes."
  - id: AC-4
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_fails_and_writes_issue_payload_for_unallowlisted_advisory -q` is run"
    then: "an unallowlisted advisory causes a nonzero audit result, writes a sanitized issue payload for the dependency-audit backlog follow-up, and avoids private resolver caches, machine paths, credentials, or raw tool output."
  - id: AC-5
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_requires_exact_unexpired_allowlist_entries -q` is run"
    then: "an advisory is accepted only when the allowlist entry exactly matches advisory id, package, affected range, reason, and a non-expired expiry date; expired, missing, or mismatched entries fail the audit."
  - id: AC-6
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_flags_yanked_versions_and_newly_affected_specifier_ranges -q` is run"
    then: "a yanked current package version or a newly affected declared direct dependency range produces an actionable audit finding and issue payload even when resolver installation itself succeeds."
  - id: AC-7
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_does_not_modify_pyproject_or_lockfile -q` is run"
    then: "the current-audit command leaves the contents and hashes of `pyproject.toml` and `uv.lock` unchanged while producing its report and issue payload."
  - id: AC-8
    when: "`python -m pytest tests/test_dependency_upgrade_gate.py::test_dependency_audit_docs_define_allowlist_and_report_boundaries -q` is run"
    then: "the docs define scheduled-current-audit scope, the required allowlist fields, the public-safe output contract, and the boundary that workflow runtime is statically checked unless a real hosted run is triggered."
out_of_scope:
  - "Raising dependency bounds, changing dependency specifiers, or refreshing `uv.lock`."
  - "Committing scheduled audit reports generated by GitHub Actions runs."
  - "Editing `docs/BACKLOG.yaml` or backlog archive metadata; failure notification is an issue-backed follow-up surface."
  - "Replacing the existing dependency-upgrade manifest/report gate."
  - "Guaranteeing hosted schedule execution during implementation; static workflow checks and unit tests cover wiring unless a real workflow run is triggered."
contract_policy:
  flow: full_spdd
  reason: "Strict provider/pipeline and dependency-security task that changes hosted CI behavior and advisory handling."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The repository must have a GitHub Actions dependency audit workflow on `schedule` and `workflow_dispatch`."
      source: "backlog acceptance"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The scheduled audit must install and resolver-audit the default package plus every dev/optional install surface in fresh environments without changing dependency bounds."
      source: "backlog acceptance"
      acceptance_ids: [AC-2, AC-7]
    - id: REQ-3
      statement: "The audit must query OSV or an equivalent advisory source for current direct dependency versions from the lockfile, including runtime and optional tree-sitter/chroma dependencies."
      source: "backlog acceptance"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Known accepted risks must be explicit allowlist entries with advisory id, package, affected range, reason, and expiry date, and must fail closed when stale or mismatched."
      source: "backlog acceptance"
      acceptance_ids: [AC-5]
    - id: REQ-5
      statement: "Actionable drift from an advisory, yanked package, or newly affected declared range must produce a sanitized issue-backed backlog follow-up payload."
      source: "backlog acceptance"
      acceptance_ids: [AC-4, AC-6]
    - id: REQ-6
      statement: "Published reports, artifacts, and issue payloads must be public-safe and contain only package names, versions, advisory ids, and remediation notes."
      source: "backlog acceptance and CLAUDE.md public-safety guidance"
      acceptance_ids: [AC-3, AC-4, AC-8]
  surfaces:
    - name: "Dependency audit workflow"
      kind: internal
      paths: [".github/workflows/dependency-audit.yml"]
      expected_behavior: "Run on a weekly cron and workflow_dispatch, set up Python, run the current-audit command, upload the sanitized JSON/Markdown artifact on every run, create or update a single dependency-audit GitHub issue when actionable findings exist, then fail the workflow when the audit status is not success."
    - name: "Dependency audit CLI"
      kind: cli
      paths: ["scripts/dependency_upgrade_gate.py"]
      expected_behavior: "Add a `current-audit` subcommand that reuses existing pyproject/lock parsing and resolver runner helpers, audits default/dev/all optional extras, queries OSV for current direct dependency versions and declared-range drift, checks PyPI yanked metadata, applies the allowlist, emits sanitized report and issue-body files, and never mutates `pyproject.toml` or `uv.lock`."
    - name: "Dependency audit tests"
      kind: internal
      paths: ["tests/test_dependency_upgrade_gate.py"]
      expected_behavior: "Mock advisory, yanked, resolver, clock, and issue-output helpers to cover success, advisory failure, yanked failure, range drift, allowlist expiry, no-mutation, workflow shape, and report redaction deterministically without live network calls."
    - name: "Dependency audit documentation"
      kind: internal
      paths: ["docs/DEPENDENCY_UPGRADE_GATE.md", "docs/dependency-audit-allowlist.json"]
      expected_behavior: "Document how the scheduled current audit differs from upgrade audits, how allowlist entries expire, what gets published, how issues are updated, and why generated run reports are artifacts rather than committed docs."
    - name: "Quality scorecard artifacts"
      kind: internal
      paths: ["docs/quality/scorecard.json", "docs/quality/scorecard.md"]
      expected_behavior: "Reflect the added dependency current-audit test coverage so the existing scorecard freshness check remains green."
  invariants:
    - id: INV-1
      statement: "This task must not change dependency specifiers, package ceilings, or `uv.lock` content."
      applies_to: ["pyproject.toml", "uv.lock", ".github/workflows/dependency-audit.yml", "scripts/dependency_upgrade_gate.py"]
    - id: INV-2
      statement: "Scheduled audit reports generated by workflow runs are uploaded as artifacts and are not committed to the repository."
      applies_to: [".github/workflows/dependency-audit.yml", "scripts/dependency_upgrade_gate.py"]
    - id: INV-3
      statement: "The existing dependency-upgrade gate and its report freshness enforcement remain intact for changes to `pyproject.toml` or `uv.lock`."
      applies_to: ["scripts/dependency_upgrade_gate.py", ".github/workflows/ci.yml", "docs/DEPENDENCY_UPGRADE_GATE.md"]
    - id: INV-4
      statement: "Public output must not include private paths, resolver cache directories, raw command output, credentials, hostnames, or tokens."
      applies_to: ["scripts/dependency_upgrade_gate.py", ".github/workflows/dependency-audit.yml", "docs/DEPENDENCY_UPGRADE_GATE.md"]
    - id: INV-5
      statement: "The ChromaDB optional backend remains deprecated and capped below 1.x unless a separate audited upgrade task changes that policy."
      applies_to: ["pyproject.toml", "docs/DEPENDENCY_UPGRADE_GATE.md", "docs/dependency-audit-allowlist.json"]
  risks:
    - id: RISK-1
      risk: "The workflow could accidentally refresh dependency metadata while trying to audit it."
      mitigation: "Keep current-audit read-only for `pyproject.toml` and `uv.lock`, add hash/no-mutation tests, and make workflow-shape tests reject `uv lock` or dependency-file write steps."
    - id: RISK-2
      risk: "A broad allowlist could hide unrelated vulnerable package versions."
      mitigation: "Require exact advisory id, normalized package, affected range, reason, and non-expired expiry date; test expired and mismatched entries."
    - id: RISK-3
      risk: "Scheduled failures could spam issues on every cron run."
      mitigation: "Use a stable issue title or marker and update the existing dependency-audit issue instead of creating duplicates."
    - id: RISK-4
      risk: "Live OSV/PyPI/pip-audit behavior can be flaky in unit tests."
      mitigation: "Keep unit tests fully mocked and reserve live network behavior for the hosted workflow and optional manual workflow_dispatch runs."
    - id: RISK-5
      risk: "Report or issue payloads could leak temp resolver paths or raw tool output."
      mitigation: "Emit structured sanitized summaries only and add a regression test with fake private paths in resolver output."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_dependency_audit_workflow_declares_schedule_dispatch_artifact_and_notification -q"
      proves: "The workflow trigger, artifact, notification, permissions, and no-bound-edit wiring are present."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_plans_default_dev_and_all_optional_extra_installs -q"
      proves: "Fresh resolver audits cover the default package plus dev and all optional extras from pyproject.toml."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_queries_osv_for_current_direct_lock_versions -q"
      proves: "Current direct dependency versions from the lockfile are queried against advisory data and published in sanitized form."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_fails_and_writes_issue_payload_for_unallowlisted_advisory -q"
      proves: "Unallowlisted advisories fail the audit and produce a public-safe issue-backed backlog payload."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_requires_exact_unexpired_allowlist_entries -q"
      proves: "Allowlist entries are exact, bounded, and expiry-enforced."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_flags_yanked_versions_and_newly_affected_specifier_ranges -q"
      proves: "Yanked package versions and newly affected declared ranges become actionable findings."
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_current_audit_does_not_modify_pyproject_or_lockfile -q"
      proves: "The current audit does not mutate dependency bounds or lockfile content."
      acceptance_ids: [AC-7]
    - id: VER-8
      command: "python -m pytest tests/test_dependency_upgrade_gate.py::test_dependency_audit_docs_define_allowlist_and_report_boundaries -q"
      proves: "The docs preserve the allowlist schema, public-safe output boundary, and hosted-runtime verification boundary."
      acceptance_ids: [AC-8]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_dependency_upgrade_gate.py -k 'current_audit or dependency_audit_workflow' -q"
        proves: "All focused scheduled-current-audit behaviors remain stable across success, failure, allowlist, yanked/range, no-mutation, workflow, and docs cases."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
      - id: REG-2
        command: "python scripts/dependency_upgrade_gate.py current-audit --help"
        proves: "The public CLI exposes the current-audit entry point without requiring a manifest or dependency-bound changes."
        acceptance_ids: [AC-2, AC-7]
      - id: REG-3
        command: "actionlint .github/workflows/dependency-audit.yml"
        proves: "The new workflow YAML is syntactically valid; hosted schedule execution remains unproven until an actual GitHub Actions run."
        acceptance_ids: [AC-1]
      - id: REG-4
        command: "ruff check scripts/dependency_upgrade_gate.py tests/test_dependency_upgrade_gate.py"
        proves: "The edited script and tests pass the lint subset relevant to this task."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
      - id: REG-5
        command: "ruff format --check scripts/dependency_upgrade_gate.py tests/test_dependency_upgrade_gate.py"
        proves: "The edited script and tests satisfy repository formatting."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
      - id: REG-6
        command: "python scripts/quality_scorecard.py --check"
        proves: "The regenerated scorecard artifacts match the repository test shape after scheduled-audit tests are added."
        acceptance_ids: [AC-2, AC-3, AC-4, AC-5, AC-6, AC-8]
---

## Design Notes

- Reuse `scripts/dependency_upgrade_gate.py` instead of adding a second dependency-audit script. The existing file already has stdlib pyproject/lock parsing, OSV query helpers, resolver-audit runners, report hashing, and redaction-sensitive tests.
- Add a `current-audit` subcommand that takes no target manifest. It should read current direct dependencies from `pyproject.toml` and resolved versions from `uv.lock`, then audit the current state only.
- Resolver-audit plan:
  - always audit the default install;
  - audit `[dev]`;
  - discover every optional extra from `[project.optional-dependencies]` and audit each one separately, including `treesitter`, `spellcheck`, `chroma`, and `watch`;
  - use disposable virtualenvs and transient `pip-audit` installation, matching the existing upgrade gate pattern.
- Direct advisory checks should query OSV for current locked direct versions and record sanitized findings for runtime, dev, and optional direct dependencies. The named packages in the backlog (`lancedb`, `sentence-transformers`, `pyyaml`, `packaging`, `chromadb`, and tree-sitter packages) must be covered by tests.
- Add PyPI release metadata checks for yanked current direct versions. Keep this injectable in tests like the OSV and resolver helpers.
- For "previously safe target range becomes affected", compare OSV affected package/range metadata against the declared direct dependency specifier. If range intersection is too broad to decide safely, fail closed with a finding that names package, advisory id, declared range, and remediation note.
- Add `docs/dependency-audit-allowlist.json` with shape `{"schema_version": 1, "entries": []}`. Each non-empty entry must include `advisory_id`, `package`, `affected_range`, `reason`, and `expires`. The command should reject expired, missing, unknown, or mismatched entries.
- Do not edit `docs/BACKLOG.yaml`. The workflow should create or update a single GitHub issue using a stable marker/title such as `[dependency-audit] current dependency audit findings`. When `gh` is unavailable or permissions are missing, the workflow should still upload the issue-body artifact and fail so a maintainer can act.
- Workflow execution pattern:
  - run the audit step with captured exit status so report files are produced;
  - upload sanitized JSON and issue-body artifacts with `if: always()`;
  - on nonzero audit status, use `gh issue list` / `gh issue create` / `gh issue edit` with `GITHUB_TOKEN` and `issues: write`;
  - finish with a final step that exits with the original audit status.
- Report and issue payloads must never include raw resolver output, temp directories, cache paths, credentials, hostnames, tokens, or private remotes. Keep only package names, versions, advisory ids, yanked flags, allowlist status, and remediation notes.
- Regenerate `docs/quality/scorecard.json` and `docs/quality/scorecard.md` after adding tests because the CI lint job runs `python scripts/quality_scorecard.py --check`.
- Verification boundary: `actionlint` and unit tests prove workflow syntax and expected structure. A real hosted scheduled run is not proven unless the workflow is triggered on GitHub via cron or workflow_dispatch.
