---
slug: REL-ADMISSION-EXACT-SHA-PROTECTED-REFS
status: completed
authority: non_authoritative
goal: "Bind release publication to one exact green candidate SHA, guarded public refs, orphan-tag detection, and fresh dependency-audit evidence."
risk: high
risk_note: "Release admission and public GitHub rulesets can block or allow publication; live checks must fail closed while remaining read-only."
files:
  - path: scripts/release_admission_checks.py
    change: "Add shared stdlib-only helpers/constants for exact SHA, aggregate check, protected ref, orphan tag, dependency-audit freshness, and remediation rows."
  - path: scripts/release_preflight.py
    change: "Add --expect-sha admission, candidate-ref/tag SHA identity checks, aggregate required-check lookup, dependency-audit freshness check, and fail-closed JSON rows."
  - path: scripts/release_readiness_gate.py
    change: "Add read-only public admission rows for protected refs, aggregate check state, orphan tags, and scheduled audit freshness without requiring mutation credentials."
  - path: scripts/release_status_gate.py
    change: "Extend post-publication surfaces with exact-SHA workflow checks, protected-ref/ruleset reporting, orphan tag detection, and dependency-audit freshness."
  - path: scripts/docs_drift_guard.py
    change: "Synchronize release docs with the new canonical exact-SHA preflight and status-gate commands."
  - path: .github/workflows/ci.yml
    change: "Add one stable aggregate release-required check that depends on all release-critical CI jobs."
  - path: .github/workflows/publish.yml
    change: "Require exact candidate SHA, successful aggregate check for that SHA, fresh dependency audit, and protected-ref/ruleset predicates before publish."
  - path: docs/RELEASING.md
    change: "Document the reviewed-SHA workflow, aggregate required check, protected public refs, orphan-tag handling, and release-status evidence boundaries."
  - path: docs/DEPENDENCY_UPGRADE_GATE.md
    change: "Document the scheduled audit freshness predicate used by release admission."
  - path: docs/release-admission-rulesets.md
    change: "Add the public main and v* ruleset contract, restrictive tag policy, and auditable break-glass boundary."
  - path: tests/test_release_preflight.py
    change: "Cover matching SHA, SHA drift, unavailable aggregate status, stale/failed checks, audit staleness, and bounded remediations."
  - path: tests/test_release_readiness_gate.py
    change: "Cover readiness rows for protection/rulesets, aggregate checks, orphan tags, and dependency-audit freshness using injected fixtures."
  - path: tests/test_release_status_gate.py
    change: "Cover exact-SHA workflow status, protection/ruleset reporting, orphan public v* tags, PyPI identity mismatches, and audit lookup failures."
  - path: tests/test_release_ruleset_contract.py
    change: "Add hermetic tests for the documented main and v* ruleset contract and break-glass metadata."
  - path: tests/test_release_workflow_admission.py
    change: "Add workflow-shape tests for the aggregate CI check and publish admission step wiring."
  - path: tests/test_docs_drift_guard.py
    change: "Update documentation drift fixtures for the new release command contract."
acceptance:
  - id: AC-1
    when: "release preflight is run with --expect-sha <40-hex> in matching and drift fixture cases"
    then: "it exits successfully only when HEAD, intended tag target, reviewed SHA, and public release candidate SHA are identical."
  - id: AC-2
    when: "release admission queries the stable aggregate required check for the candidate SHA"
    then: "missing, stale, cancelled, skipped, failed, or unqueryable check state blocks publication with a remediation row."
  - id: AC-3
    when: "public main and v* ruleset state is inspected through the read-only GitHub surface"
    then: "main reports force-push/deletion rejection plus the aggregate required check, and v* reports restrictive create/update/delete policy with auditable break-glass metadata."
  - id: AC-4
    when: "release readiness or status runs without repository mutation credentials"
    then: "protection and ruleset state is reported as ok/fail/error instead of attempting to modify GitHub settings."
  - id: AC-5
    when: "a public v* tag lacks the expected non-draft GitHub Release or matching PyPI identity"
    then: "the status gate reports the orphan tag explicitly while preserving existing immutable tag evidence such as v1.13.2."
  - id: AC-6
    when: "the latest scheduled dependency audit is missing, failed, stale, expired, or unqueryable"
    then: "release admission fails closed and names one bounded remediation."
  - id: AC-7
    when: "focused release admission tests run against hermetic fixtures"
    then: "matching SHA, drift, unavailable status, stale/failed checks, missing protection, orphan tags, and audit staleness are covered."
  - id: AC-8
    when: "any release admission predicate fails"
    then: "human and JSON output include one bounded remediation for that failed predicate."
out_of_scope:
  - "Mutating historical public tags or repairing v1.13.2."
  - "Creating a parallel release script outside the existing release gate owners."
  - "Writing backlog metadata or backlog archive files."
  - "Using local readiness/status commands to mutate GitHub repository settings."
contract_policy:
  flow: full_spdd
  reason: "Strict release-admission task spanning CI integrity, public ref protection, GitHub read-only state, and publication safety."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Canonical preflight must accept --expect-sha <40-hex> and bind all release-candidate SHA views to that exact value."
      source: "AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Release admission must require one stable aggregate green check for the exact candidate SHA."
      source: "AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Public main and v* must have a documented, inspectable protection/ruleset contract."
      source: "AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Readiness and status gates must report protection/ruleset state using read-only credentials."
      source: "AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Public v* tags without matching release and PyPI identity must be surfaced as orphan evidence."
      source: "AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Scheduled dependency audit freshness must be a fail-closed release-admission predicate."
      source: "AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-7
      statement: "Hermetic tests must cover the required happy, failure, and boundary cases."
      source: "AC-7"
      acceptance_ids: [AC-7]
    - id: REQ-8
      statement: "Every failed predicate must provide one bounded remediation in human and JSON output."
      source: "AC-8"
      acceptance_ids: [AC-8]
  surfaces:
    - name: "release preflight CLI"
      kind: cli
      paths: ["scripts/release_preflight.py", "scripts/release_admission_checks.py"]
      expected_behavior: "Pre-tag and tag-workflow admission compare expected SHA, HEAD, tag target, public candidate ref, aggregate check state, and scheduled audit freshness."
    - name: "release readiness and status gates"
      kind: cli
      paths: ["scripts/release_readiness_gate.py", "scripts/release_status_gate.py", "scripts/release_admission_checks.py"]
      expected_behavior: "Existing release gate output gains read-only protection/ruleset, orphan-tag, exact-SHA, and audit-freshness surfaces."
    - name: "GitHub Actions release path"
      kind: internal
      paths: [".github/workflows/ci.yml", ".github/workflows/publish.yml"]
      expected_behavior: "Tests workflow exposes one stable aggregate release-required check; publish workflow gates PyPI/GitHub Release creation on exact SHA and read-only admission checks."
    - name: "release documentation"
      kind: internal
      paths: ["docs/RELEASING.md", "docs/DEPENDENCY_UPGRADE_GATE.md", "docs/release-admission-rulesets.md", "scripts/docs_drift_guard.py"]
      expected_behavior: "Release runbook and drift guard name the reviewed-SHA command, aggregate check, ruleset contract, dependency-audit freshness, and bounded remediations."
    - name: "release admission tests"
      kind: internal
      paths: ["tests/test_release_preflight.py", "tests/test_release_readiness_gate.py", "tests/test_release_status_gate.py", "tests/test_release_ruleset_contract.py", "tests/test_release_workflow_admission.py", "tests/test_docs_drift_guard.py"]
      expected_behavior: "Hermetic fixtures cover matching and failing release-admission predicates without live GitHub, PyPI, or package-install side effects."
  invariants:
    - id: INV-1
      statement: "Default release_preflight.py without live admission options remains local, deterministic, and non-mutating."
      applies_to: ["scripts/release_preflight.py"]
    - id: INV-2
      statement: "Readiness and status gates never require write credentials to report GitHub protection or ruleset state."
      applies_to: ["scripts/release_readiness_gate.py", "scripts/release_status_gate.py"]
    - id: INV-3
      statement: "The existing six post-publication surfaces remain required; new checks add blockers without weakening tag, Tests, Publish, Release, PyPI, or install-smoke evidence."
      applies_to: ["scripts/release_status_gate.py", "tests/test_release_status_gate.py"]
    - id: INV-4
      statement: "The publish workflow remains tag-triggered and does not add workflow_dispatch or release-event publication."
      applies_to: [".github/workflows/publish.yml"]
    - id: INV-5
      statement: "Historical public tags remain immutable evidence and are only reported."
      applies_to: ["scripts/release_status_gate.py", "docs/RELEASING.md"]
  risks:
    - id: RISK-1
      risk: "A stale green workflow run could mask a newer failed candidate SHA."
      mitigation: "Query the aggregate check by exact headSha and reject any run or check whose head SHA differs from --expect-sha."
    - id: RISK-2
      risk: "GitHub API schema or permission errors could be mistaken for absence of risk."
      mitigation: "Treat parse errors, missing fields, and nonzero gh calls as error blockers with sanitized diagnostics."
    - id: RISK-3
      risk: "Branch protection could drift after local source lands."
      mitigation: "Document the ruleset contract and require a live read-only status/readiness row after the owner applies the GitHub rulesets."
    - id: RISK-4
      risk: "The aggregate check could omit a release-critical CI job, including one added to ci.yml later."
      mitigation: "Workflow-shape tests assert the aggregate job depends on exactly the required CI jobs, publish checks the same stable name, and every ci.yml job is classified as release-critical, the aggregate check, or an AGGREGATE_EXEMPT_CI_JOBS entry with a recorded reason, so a newly added job fails until it is classified."
  verification:
    - id: VER-1
      owner: provider
      command: "PYTHONPATH=. pytest tests/test_release_preflight.py -q"
      proves: "Focused preflight behavior for exact SHA identity, aggregate check admission, dependency-audit freshness, failure rows, and CLI wiring."
      acceptance_ids: [AC-1, AC-2, AC-6, AC-7, AC-8]
    - id: VER-2
      owner: provider
      command: "PYTHONPATH=. pytest tests/test_release_status_gate.py -q"
      proves: "Focused public status behavior for exact-SHA workflow checks, protection/ruleset reporting, orphan tags, PyPI identity, audit freshness, and sanitized remediations."
      acceptance_ids: [AC-2, AC-4, AC-5, AC-6, AC-7, AC-8]
    - id: VER-3
      owner: provider
      command: "PYTHONPATH=. pytest tests/test_release_readiness_gate.py -q"
      proves: "Focused readiness behavior for read-only protection/ruleset rows, aggregate candidate checks, orphan evidence, audit freshness, and failure propagation."
      acceptance_ids: [AC-2, AC-4, AC-6, AC-7, AC-8]
    - id: VER-4
      owner: provider
      command: "PYTHONPATH=. pytest tests/test_release_ruleset_contract.py tests/test_release_workflow_admission.py -q"
      proves: "Ruleset contract and workflow-shape fixtures cover protected main, restrictive v* policy, aggregate job dependencies, and publish admission wiring."
      acceptance_ids: [AC-2, AC-3, AC-7, AC-8]
    - id: VER-5
      owner: provider
      command: "actionlint .github/workflows/*.yml"
      proves: "Dev dependency actionlint from pyproject.toml syntax-checks the modified CI and publish workflows after aggregate/admission wiring."
      acceptance_ids: [AC-1, AC-2]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "PYTHONPATH=. pytest tests/test_release_preflight.py tests/test_release_status_gate.py tests/test_release_readiness_gate.py tests/test_release_ruleset_contract.py tests/test_release_workflow_admission.py tests/test_docs_drift_guard.py -q"
        proves: "Focused regression suite for all changed release admission gates and synchronized release documentation fixtures."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
---

## Design Notes

- Keep `scripts/release_admission_checks.py` library-only: no CLI, no mutation, stdlib plus injected command/HTTP seams.
- Use a single stable aggregate check name, for example `release-required`, in constants, docs, workflow tests, publish.yml, and ruleset documentation.
- Add the aggregate job to `ci.yml` with `needs` covering the release-critical jobs and `if: always()` so skipped, cancelled, failed, and missing upstream jobs can be converted into one failed required check.
- `--expect-sha` should validate exactly 40 lowercase or uppercase hex characters, normalize to lowercase for comparisons, and fail before live lookups when malformed.
- Candidate identity should compare `git rev-parse HEAD`, `git rev-list -n 1 <tag>`, the reviewed `--expect-sha`, and the configured public candidate ref, normally `origin/main` after a bounded fetch in publish.yml.
- Publish.yml should compute `TAG_SHA` and `MAIN_SHA`, call preflight with `--expect-sha "$TAG_SHA"`, and run read-only admission before build/publish jobs can create PyPI artifacts or a GitHub Release.
- GitHub checks should be queried by exact candidate SHA and stable check name. A green older run on the same branch is a blocker, because it does not prove the candidate.
- Dependency-audit freshness should use the latest completed scheduled or workflow_dispatch run of the `Dependency Audit` workflow. Success within a documented freshness window passes; missing, stale, failed, cancelled, skipped, or parse-error results fail closed.
- Orphan-tag detection should enumerate public `v*` tags and compare the expected version tag against GitHub Release and PyPI JSON identity. Existing `v1.13.2` remains immutable evidence in output and docs.
- Ruleset/protection checks should use read-only GitHub API calls and report `ok`, `fail`, or `error`. Local scripts must not create or edit rulesets.
- Every predicate row should include a `remediation` field in JSON and one concise human message, for example rerun the named workflow for SHA, apply the documented ruleset, create the missing GitHub Release, or wait for PyPI propagation then rerun status.
- The implementation requires an owner to apply the documented GitHub rulesets after the aggregate check exists, then rerun the read-only status gate against the public repository.
