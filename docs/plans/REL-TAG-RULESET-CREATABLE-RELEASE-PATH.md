---
slug: REL-TAG-RULESET-CREATABLE-RELEASE-PATH
goal: "Reject an active public v* tag ruleset unless its credential-free detail proves at least one auditable actor can always bypass creation restrictions."
risk: medium
risk_note: "The predicate is small and local, but a false pass leaves the release path unusable while an over-strict predicate can block every public release."
files:
  - path: scripts/release_admission_checks.py
    change: "Require a well-formed, non-empty creation-capable bypass actor list before the public v* tag-ruleset row can pass, with fail-closed detail and one bounded recovery instruction."
  - path: tests/test_release_ruleset_contract.py
    change: "Add focused zero-bypass, valid always-bypass, malformed-shape, and non-creation-capable bypass coverage while retaining existing ruleset and runbook contract checks."
  - path: tests/test_release_readiness_gate.py
    change: "Update the existing compliant public tag-ruleset fixture to include a valid always-bypass actor so downstream readiness coverage represents a creatable release path."
  - path: docs/release-admission-rulesets.md
    change: "Make an auditable always-bypass actor part of the canonical public version-tag contract and give zero or malformed bypass state one bounded owner recovery action followed by the credential-free recheck."
  - path: docs/quality/scorecard.md
    change: "Regenerate the canonical human-readable quality scorecard after focused test coverage changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the canonical machine-readable quality scorecard from the same generator."
acceptance:
  - id: AC-1
    when: "the credential-free ruleset detail contains an active refs/tags/v* creation, update, and deletion ruleset with bypass_actors: []"
    then: "public_v_tag_ruleset reports fail and returns exactly one bounded recovery instruction for adding a creation-capable auditable bypass actor and rerunning the check"
  - id: AC-2
    when: "the same ruleset detail contains at least one well-formed auditable bypass actor whose bypass mode is always"
    then: "public_v_tag_ruleset reports ok and its detail reports the proven creation-capable bypass actor count"
  - id: AC-3
    when: "bypass_actors is absent, is not a list, contains malformed actor entries, or contains no actor with always bypass mode"
    then: "public_v_tag_ruleset fails closed without raising or treating the state as zero-but-compliant"
  - id: AC-4
    when: "the focused release-admission and documentation contracts, downstream readiness fixture, configured non-network suite, docs drift, scorecard freshness, Ruff lint, and Ruff format gates evaluate the change"
    then: "valid neighboring ruleset behavior remains accepted, invalid and stale documentation states remain rejected, generated scorecards are current, and all configured static diagnostics are empty"
out_of_scope:
  - "Mutating the live GitHub ruleset, choosing the production bypass actor, or creating tags, releases, uploads, or other public state."
  - "Adding a GitHub client, credential path, release gate, service, persisted state owner, dependency, workflow, or ruleset-management interface."
  - "Changing bounded public ruleset lookup pagination, branch protection, orphan-tag handling, artifact publication, or other release-admission predicates."
  - "Editing backlog metadata or invoking provider clients, authentication commands, credentials, paid-account state, push, tag, release, or publication operations."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release security fix changes a rules-heavy public release admission predicate and its degraded-operator recovery contract."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "A public v* ruleset with zero bypass actors must fail with one bounded recovery action."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "At least one valid auditable actor with always bypass mode must satisfy the creation-path requirement."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Malformed or non-creation-capable bypass state must fail closed."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Focused release-admission and docs behavior plus configured static and regression gates must remain accepted."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "Public v* tag-ruleset admission predicate"
      kind: internal
      paths: ["scripts/release_admission_checks.py"]
      expected_behavior: "The existing predicate passes only when the bounded credential-free detail proves an active protected v* ruleset and at least one well-formed actor can always bypass its creation restriction."
    - name: "Public version-tag operator runbook"
      kind: cli
      paths: ["docs/release-admission-rulesets.md"]
      expected_behavior: "The canonical runbook states the creation-path requirement, audit boundary, one bounded settings recovery action, and the credential-free recheck."
    - name: "Generated quality scorecard"
      kind: internal
      paths: ["docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "The existing scorecard pair remains current after focused regression coverage changes."
  invariants:
    - id: INV-1
      statement: "The ruleset list/detail reads remain fixed, credential-free, bounded by the existing lookup budget, and fail closed on lookup or response errors."
      applies_to: ["scripts/release_admission_checks.py", "tests/test_release_ruleset_contract.py"]
    - id: INV-2
      statement: "Active enforcement, tag target, refs/tags/v* inclusion, and creation, update, and deletion remain independently required before bypass actors are evaluated."
      applies_to: ["scripts/release_admission_checks.py", "tests/test_release_ruleset_contract.py"]
    - id: INV-3
      statement: "A pull-request-only or malformed bypass entry never proves authority to create a tag; an always-mode actor remains visible through the existing audit-log policy."
      applies_to: ["scripts/release_admission_checks.py", "tests/test_release_ruleset_contract.py", "docs/release-admission-rulesets.md"]
    - id: INV-4
      statement: "No credential inspection, provider-client execution, public mutation, workflow change, dependency change, or new behavioral owner is introduced."
      applies_to: ["scripts/release_admission_checks.py", "tests/test_release_ruleset_contract.py", "tests/test_release_readiness_gate.py", "docs/release-admission-rulesets.md"]
  risks:
    - id: RISK-1
      risk: "Counting a non-empty list without validating actor shape or bypass mode could admit a ruleset whose actors still cannot create v* tags."
      mitigation: "Validate the bounded public payload structurally and count only well-formed always-mode actors."
    - id: RISK-2
      risk: "Treating malformed bypass state as an empty valid list could preserve the current false pass or hide a GitHub response drift."
      mitigation: "Separate malformed-shape handling from the explicit zero-actor failure and assert both fail closed."
    - id: RISK-3
      risk: "Existing compliant fixtures with implicit empty bypass lists could mask or regress downstream readiness behavior."
      mitigation: "Make compliant fixtures explicit and keep one focused zero-bypass reproducer."
    - id: RISK-4
      risk: "Adding focused tests could leave generated quality scorecards stale."
      mitigation: "Regenerate both canonical scorecards and run their exact configured freshness command."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_ruleset_contract.py -q"
      proves: "The focused predicate and runbook contract distinguishes zero, valid always-mode, malformed, and non-creation-capable bypass states while preserving bounded ruleset behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The exact configured docs gate accepts the canonical public version-tag contract and continues to reject missing release-admission markers."
      acceptance_ids: [AC-4]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The canonical scorecard pair matches the implementation tree after focused test changes."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The exact configured non-network suite preserves downstream readiness, status, preflight, workflow, CLI, MCP, and package behavior around the stricter predicate."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-2
        owner: configured_runner
        command: "ruff check mempalace_code/ tests/ scripts/"
        proves: "The exact configured lint gate accepts the predicate and regression-test changes."
        acceptance_ids: [AC-4]
      - id: REG-3
        owner: configured_runner
        command: "ruff format --check mempalace_code/ tests/ scripts/"
        proves: "The exact configured format gate accepts the predicate and regression-test changes."
        acceptance_ids: [AC-4]
---

## Design Notes

- Keep `scripts/release_admission_checks.py::check_tag_ruleset` as the sole behavior owner. Evaluate bypass state only after the existing target, ref pattern, enforcement, and required-rule checks succeed; add no helper module, client, gate, state owner, or credential path.
- Treat `bypass_actors` as malformed when it is absent, is not a list, or contains entries that cannot establish an actor type and bypass mode. Return a fail-closed admission row with bounded detail; do not coerce malformed state to an empty compliant count and do not raise on public payload drift.
- A creation-capable actor is a well-formed public ruleset bypass entry with a non-empty actor type and `bypass_mode: always`. `pull_request` mode cannot authorize tag creation and must not count. Keep actor identity/audit wording aligned with GitHub's returned shape without inventing a credential-backed identity lookup.
- For an explicit empty list or a well-formed list with zero creation-capable actors, return `fail` with one remediation string owned by the existing tag-ruleset runbook. The instruction should tell the repository owner to add the minimum appropriate always-bypass actor in repository Settings → Rules, retain audit-log review, and rerun the same credential-free `--check-tag-ruleset` preflight. Do not choose or apply the live actor in code or docs.
- Change the existing compliant helper in `tests/test_release_ruleset_contract.py` to default to an explicit always-mode actor, then add explicit cases for `[]`, absent/non-list/malformed entries, and pull-request-only actors. Assert status, bounded recovery, and the count of qualifying actors rather than merely list length.
- Update only the existing `_ruleset_detail_ok` fixture in `tests/test_release_readiness_gate.py` so its nominal pass path represents a creatable release. `tests/test_release_status_gate.py` already supplies an always-mode repository-role actor and should remain unchanged evidence.
- Extend the current runbook assertions in `tests/test_release_ruleset_contract.py`; do not create a second docs guard. Keep `scripts/docs_drift_guard.py` unchanged and use its configured command as synchronization evidence.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` with `python scripts/quality_scorecard.py --write` if the focused test-function count changes; do not change scorecard logic.
- Rule Zero: deletion would remove immutable-tag protection, and a new checker would duplicate the existing admission owner. Extending the current predicate and fixtures is the lowest-complexity path with no new interface or lifecycle. The cheapest decisive falsifier is a zero, malformed, or pull-request-only bypass fixture producing `ok`, or a valid always-mode fixture failing.
- Command context basis: every command runs from the repository root. `pyproject.toml` supplies pytest and Ruff configuration, while `scripts/gate_inventory.py` declares the exact non-network suite, docs drift, scorecard, Ruff lint, and Ruff format commands retained as configured-runner evidence. The focused provider check is limited to one test module.
- `docs/quality/incident-class-registry.yaml` is absent in this worktree, so no registry-matched `incident_proof` block applies.
- PLAN did not execute tests, builds, release gates, verification wrappers, scorecard generation, Git finalization, or public operations.
