---
slug: RELEASE-DRUNK-PATH-APP-CONTRACTS
status: completed
authority: non_authoritative
goal: "Document the existing direct diary-write and guarded-update recovery contracts for humans and agents, with synchronized drift coverage."
risk: low
risk_note: "The change is limited to public instructions and their existing docs-drift test owner; runtime, release gates, packaging, credentials, and publication remain unchanged."
files:
  - path: README.md
    change: "Add concise recovery guidance beside the direct diary-write and opt-in update command surfaces."
  - path: docs/UPDATES.md
    change: "Document the missing --yes refusal contract for human and JSON modes, including exit 2, zero mutation, and emitted recovery commands."
  - path: docs/LLM_USAGE_RULES.md
    change: "Add direct-CLI diary ambiguity and guarded-update refusal rules while preserving the existing MCP ambiguous-write protocol."
  - path: tests/test_docs_drift_guard.py
    change: "Extend the existing documentation-contract owner to keep all three public direct-CLI recovery passages aligned with the runtime wording."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing human-readable scorecard after the documentation-contract test change."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable scorecard from the same canonical generator."
acceptance:
  - id: AC-1
    when: "README readers inspect the direct diary-write and opt-in update command surfaces"
    then: "they are told that a successful diary write prints stable poststate and a search command, that retained output permits that exact reconciliation, that unavailable output forbids retry and routes to exposed same-agent diary read or owner reconciliation, and that a missing --yes update refusal supplies the guarded recovery path"
  - id: AC-2
    when: "a guarded update mutation is invoked without --yes in human or JSON mode and docs/UPDATES.md is checked against the observable CLI result"
    then: "the documented contract is exit 2 before mutation, a concise human recovery command, or exactly one JSON object on stdout containing recovery_command"
  - id: AC-3
    when: "an agent follows docs/LLM_USAGE_RULES.md after an ambiguous direct diary write or a guarded update confirmation refusal"
    then: "it uses the retained printed search when available, never retries when the response or command is unavailable, inspects exposed same-agent diary read or stops for owner reconciliation, reviews mutation authority before using the emitted update recovery_command, and retains the existing MCP ambiguous-write protocol"
  - id: AC-4
    when: "the documentation, diary, updater, MCP-rule, and installed-capable golden contract contours exercise the completed change"
    then: "the documented recovery statements remain synchronized with stable diary poststate, exit-2 zero-mutation update refusals, single-object JSON output, and the implementation diff contains no runtime, gate, workflow, package, auth, provider-client, or publication changes"
out_of_scope:
  - "Changing diary storage, output, search, IDs, MCP behavior, or any runtime module."
  - "Changing updater confirmation, rendering, eligibility, mutation, scheduler, installer, or rollback behavior."
  - "Adding a command, helper, schema, mode, abstraction, validator script, release gate, or duplicated protocol."
  - "Changing backlog metadata, dependencies, workflows, package artifacts, credentials, provider clients, release state, or publication state."
contract_policy:
  flow: full_spdd
  reason: "A standard release-blocker changes human-facing and agent-facing mutation-recovery instructions whose authority, poststate, and retry boundaries must remain machine-verifiable."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "README must explain direct diary reconciliation and guarded update refusal recovery beside their command surfaces."
      source: "Current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "docs/UPDATES.md must state the complete missing --yes human and JSON refusal contract."
      source: "Current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Agent rules must cover direct CLI recovery without weakening the separate MCP ambiguous-write protocol."
      source: "Current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Existing direct diary, guarded updater, MCP-rule, docs-drift, and installed-capable golden contracts must remain aligned without implementation-surface changes."
      source: "Current backlog contract AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "README direct CLI recovery summary"
      kind: cli
      paths: ["README.md"]
      expected_behavior: "The command reference gives a concise reconcile-before-retry path for diary writes and points refused update mutations to the emitted recovery command."
    - name: "Update recovery runbook"
      kind: cli
      paths: ["docs/UPDATES.md"]
      expected_behavior: "The canonical updater guide distinguishes human and JSON missing-confirmation output and states exit and mutation boundaries."
    - name: "Agent direct CLI recovery rules"
      kind: cli
      paths: ["docs/LLM_USAGE_RULES.md"]
      expected_behavior: "Agents reconcile direct diary poststate and review update authority before using the exact emitted recovery command."
    - name: "Direct CLI documentation contract tests"
      kind: internal
      paths: ["tests/test_docs_drift_guard.py"]
      expected_behavior: "The existing documentation-test owner rejects loss or contradiction of the direct diary, update refusal, and MCP-preservation statements."
    - name: "Generated quality scorecard"
      kind: artifact
      paths: ["docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "Both existing scorecard views remain current after the documentation-contract test change."
  invariants:
    - id: INV-1
      statement: "Diary runtime output remains the existing stable ID, wing, room, topic, and bounded Verify before retry search command; the full entry body is not added to success output."
      applies_to: ["README.md", "docs/LLM_USAGE_RULES.md", "tests/test_docs_drift_guard.py"]
    - id: INV-2
      statement: "Missing --yes remains an exit-2 refusal before apply or scheduler mutation, with human Recovery output or one JSON object on stdout containing recovery_command."
      applies_to: ["README.md", "docs/UPDATES.md", "docs/LLM_USAGE_RULES.md", "tests/test_docs_drift_guard.py"]
    - id: INV-3
      statement: "The existing MCP ambiguous-write protocol remains authoritative for MCP drawer, KG, and diary tools and is not rewritten as a direct CLI protocol."
      applies_to: ["docs/LLM_USAGE_RULES.md", "tests/test_docs_drift_guard.py"]
    - id: INV-4
      statement: "Runtime, release gates, workflows, dependencies, package surfaces, auth, provider clients, credentials, and publication state remain unchanged."
      applies_to: ["README.md", "docs/UPDATES.md", "docs/LLM_USAGE_RULES.md", "tests/test_docs_drift_guard.py"]
  risks:
    - id: RISK-1
      risk: "Instructions could require a printed search after the response containing it was lost, leaving a degraded actor to invent or repeat the write."
      mitigation: "Use the printed search only when output was retained; when it is unavailable, forbid retry and route to exposed same-agent diary read or owner reconciliation."
    - id: RISK-2
      risk: "Update guidance could imply that --yes is optional or that an agent may reconstruct a broader mutation command."
      mitigation: "State exit 2 and zero mutation, require authority review, and direct the actor to the exact emitted recovery command."
    - id: RISK-3
      risk: "Direct CLI additions could blur or weaken the established MCP ambiguity protocol."
      mitigation: "Keep a distinct direct CLI subsection and retain the existing MCP protocol text under focused regression coverage."
  verification:
    - id: VER-1
      owner: configured_runner
      command: "python -m pytest tests/test_docs_drift_guard.py::test_direct_cli_recovery_contracts_stay_synchronised -q"
      proves: "README, docs/UPDATES.md, and docs/LLM_USAGE_RULES.md contain the required direct diary and guarded update recovery contracts while retaining the MCP ambiguity markers."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: configured_runner
      command: "python -m pytest tests/test_cli.py::TestDiaryWrite -q"
      proves: "The unchanged diary handler still stores once and emits bounded stable poststate plus its concrete recovery search command."
      acceptance_ids: [AC-1, AC-3, AC-4]
    - id: VER-3
      owner: configured_runner
      command: "python -m pytest tests/test_updater.py::TestUpdateCommand -q"
      proves: "The unchanged guarded apply and scheduler commands still refuse missing confirmation with exit 2, no mutation, and matching human or JSON recovery output."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-4
      owner: configured_runner
      command: "python -m pytest tests/test_cli_golden_scenarios.py::test_installed_cli_paths_are_self_consistent_and_reconcilable -q"
      proves: "The installed-capable real-CLI contour still reconciles diary poststate and emits one parseable update-refusal object without creating update artifacts."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The canonical generated scorecard pair is current after the documentation-test change."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python -m pytest tests/test_docs_drift_guard.py -q"
        proves: "The complete focused documentation-contract suite remains green after extending its existing owner."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-2
        owner: configured_runner
        command: "python -m pytest tests/test_docs_drift_guard.py::test_llm_usage_rules_has_ambiguous_write_outcome_protocol -q"
        proves: "The pre-existing MCP timeout and reconcile-before-retry protocol remains present after adding direct CLI rules."
        acceptance_ids: [AC-3, AC-4]
---

## Design Notes

- Treat `mempalace_code/cli_commands/diary.py`, `mempalace_code/cli_commands/update.py`, `tests/test_cli.py`, `tests/test_updater.py`, and `tests/test_cli_golden_scenarios.py` as unchanged evidence. Do not edit them.
- In README, place diary recovery immediately after the existing `mempalace-code diary write` example and update refusal recovery immediately after the existing opt-in update commands. Keep README concise and route updater detail to `docs/UPDATES.md`.
- Reuse the runtime terms `Diary entry stored.`, stable `ID`, `Wing`, `Room`, `Topic`, `Verify before retry`, and `Recovery` where exact alignment matters. Do not paste a sample diary body or promise an idempotent diary write.
- Use the search command printed by successful diary output only when that output was retained after an ambiguous result. An exact hit means success and forbids repeating the write. If the response or command is unavailable, forbid retry and route to exposed `mempalace_diary_read` for recent same-agent entries or stop for owner reconciliation. Do not invent a stable deduplication identity or a direct CLI read command.
- In `docs/UPDATES.md`, cover all existing guarded mutations: `update apply`, `update scheduler install`, and `update scheduler remove`. Without `--yes`, each exits 2 before package, scheduler, service, log, state, lease, or palace mutation.
- Human mode prints a concise refusal plus `Recovery: <command>`. JSON mode emits exactly one parseable object on stdout, no human prose on stderr, and includes `ok: false`, `stage: confirmation`, `exit_code: 2`, and `recovery_command` ending in the matching `--yes --json` command.
- In `docs/LLM_USAGE_RULES.md`, add a direct CLI recovery subsection outside the existing MCP `Ambiguous Write Outcome` protocol. Require the agent to review current scope and mutation authority before using the emitted updater recovery command; it must not add flags, change the action, or invent a nearby retry.
- Extend `tests/test_docs_drift_guard.py` in its existing live-document assertion style. One focused test should bind the three public owners to positive contract markers and retain the existing MCP protocol assertion; do not add a new guard script or duplicate runtime tests.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` with `python scripts/quality_scorecard.py --write`; do not change scorecard logic.
- Verification commands run from the repository root with the Python/pytest context in `pyproject.toml`; its default pytest configuration selects `tests` and excludes `needs_network` and `slow`. PLAN records these commands without executing them.
