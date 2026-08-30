---
slug: REL-TAG-RULESET-CREATABLE-RELEASE-PATH
status: completed
authority: non_authoritative
goal: "Verify the observable v* tag ruleset without inventing bypass state, while preserving restricted creation and immutable publication."
risk: medium
risk_note: "A false pass can leave every release tag uncreatable; a false fail can block publication."
files:
  - path: CHANGELOG.md
    change: "Record the corrected public version-tag admission behavior in the pending release notes."
  - path: scripts/release_admission_checks.py
    change: "Require aggregated refs/tags/v* creation, update, and deletion protection without counting or identifying hidden bypass actors."
  - path: scripts/docs_drift_guard.py
    change: "Keep the existing break-glass and audit-log prose markers aligned with the owner-verified bypass boundary."
  - path: tests/test_release_ruleset_contract.py
    change: "Cover omitted bypass data, aggregated/reordered rulesets, inactive rulesets, bounded recovery, and required creation/update/deletion."
  - path: tests/test_release_readiness_gate.py
    change: "Keep the existing readiness fixture aligned with restricted creation and immutable version tags."
  - path: tests/test_release_status_gate.py
    change: "Keep the existing status fixture aligned with the same public contract."
  - path: docs/release-admission-rulesets.md
    change: "Document the observable credential-free contract, the owner-verified bypass boundary, and one complete recovery command."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing scorecard after focused test changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable scorecard."
acceptance:
  - id: AC-1
    when: "active matching rulesets aggregate creation, update, and deletion while omitting bypass_actors"
    then: "public_v_tag_ruleset reports ok without claiming an actor count or identity"
  - id: AC-2
    when: "any required rule type is absent from the active aggregate"
    then: "public_v_tag_ruleset fails with the existing repository-bound contract recovery"
  - id: AC-3
    when: "creation, update, and deletion are split or reordered across active matching rulesets"
    then: "the aggregate contract remains order-independent and inactive rulesets do not alter it"
  - id: AC-4
    when: "focused, full, docs, scorecard, lint, format, and type gates evaluate the change"
    then: "all pass and the live credential-free public state reports the observable contract truthfully"
out_of_scope:
  - "Mutating the live GitHub ruleset, pushing a tag, publishing artifacts, or changing credentials or bypass actors."
  - "Adding an authenticated release check, client, credential path, release gate, service, state owner, dependency, workflow, or ruleset-management interface."
contract_policy:
  flow: full_spdd
  reason: "This pre-release fix changes the public release-admission contract and operator recovery."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Credential-free public evidence must prove restricted creation and post-publication immutability without inventing hidden bypass state."
      source: "live public and owner-authorized read-only GitHub ruleset details observed 2026-08-30"
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: REQ-2
      statement: "The recovery path must name the public repository and a complete executable recheck."
      source: "Rule Zero drunk-user and drunk-LLM contract"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Existing release and static gates remain green."
      source: "repository release contract"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "Public v* tag-ruleset admission predicate"
      kind: internal
      paths: ["scripts/release_admission_checks.py"]
      expected_behavior: "Aggregated creation, update, and deletion rules pass without consulting or reporting hidden bypass state."
    - name: "Public version-tag operator runbook"
      kind: cli
      paths: ["docs/release-admission-rulesets.md"]
      expected_behavior: "The runbook separates public admission evidence from owner-verified bypass authority and gives one complete recovery command."
    - name: "Generated quality scorecard"
      kind: internal
      paths: ["docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "The existing scorecard pair remains current."
  invariants:
    - id: INV-1
      statement: "Ruleset reads remain fixed, bounded, credential-free, and fail closed on lookup or response errors."
      applies_to: ["scripts/release_admission_checks.py", "tests/test_release_ruleset_contract.py"]
    - id: INV-2
      statement: "No hidden bypass list, credential, provider client, or live mutation becomes automated release-admission evidence."
      applies_to: ["scripts/release_admission_checks.py", "docs/release-admission-rulesets.md"]
    - id: INV-3
      statement: "The active matching aggregate requires creation, update, and deletion; bypass identity stays an owner-verified setting."
      applies_to: ["scripts/release_admission_checks.py", "tests/test_release_ruleset_contract.py"]
  risks:
    - id: RISK-1
      risk: "Treating an omitted bypass list as empty invents a zero-actor result from unavailable evidence."
      mitigation: "Do not read, count, or identify bypass_actors in the credential-free gate; document the separate owner verification."
    - id: RISK-2
      risk: "Returning after the first ruleset can miss a required rule supplied by another active matching ruleset."
      mitigation: "Evaluate every bounded active matching ruleset and require the aggregate contract before passing."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_ruleset_contract.py tests/test_release_readiness_gate.py tests/test_release_status_gate.py -q"
      proves: "The observable ruleset contract, omitted bypass behavior, aggregation, recovery, readiness, and status fixtures agree."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The canonical release runbook stays synchronized."
      acceptance_ids: [AC-4]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "Generated scorecards match the tree."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The complete non-network suite preserves adjacent release and product behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-2
        owner: configured_runner
        command: "ruff check mempalace_code/ tests/ scripts/"
        proves: "Lint accepts the bounded change."
        acceptance_ids: [AC-4]
      - id: REG-3
        owner: configured_runner
        command: "ruff format --check mempalace_code/ tests/ scripts/"
        proves: "Formatting accepts the bounded change."
        acceptance_ids: [AC-4]
---

## Design Notes

- Rule Zero keeps `check_tag_ruleset()` as the sole owner and preserves the existing restricted-creation security boundary.
- The decisive live falsifier compared the public omission with an explicitly authorized read-only owner lookup: the active ruleset has `creation`, `update`, and `deletion`, and the configured release actor has `always` bypass. No credential or actor identity enters the release gate or public artifact.
- Multiple active matching rulesets aggregate. Scan all bounded details and require the union to contain `creation`, `update`, and `deletion`.
- The credential-free gate reports only observable rules. Repository-owner setup verifies minimal bypass authority separately and after any authority or ruleset change.
- Recovery names the public repository, the owner-only Settings check, and `python scripts/release_preflight.py --repo rergards/mempalace-code --check-tag-ruleset --json`.
- No live mutation, authenticated release check, AI client, new gate, helper module, dependency, or state owner is introduced.
