---
slug: DOCS-RUNBOOK-DRUNK-LLM-CONSISTENCY
status: completed
authority: non_authoritative
goal: "Keep release candidate identity and install-question state deterministic when an agent loses context."
risk: low
risk_note: "The change is limited to two public runbook facts and their existing stdlib documentation guard; runtime, packaging, workflows, and external state remain untouched."
files:
  - path: docs/AGENT_INSTALL.md
    change: "Correct the Section 2 lead-in so its declared question count agrees with Q1 through Q6 without changing any question or install step."
  - path: scripts/docs_drift_guard.py
    change: "Add line-anchored runbook consistency checks for exactly one candidate-SHA commit-tree assignment and agreement between the install count statement and the Q1-Q6 headings."
  - path: tests/test_docs_drift_guard.py
    change: "Add focused positive and negative contract cases for duplicate candidate assignment, install question-count drift, and malformed Q-heading sequences."
acceptance:
  - id: AC-1
    when: "The documentation drift guard evaluates the release runbook, including a fixture with a repeated line-anchored candidate commit-tree assignment."
    then: "The canonical runbook is accepted with exactly one assignment, while the duplicate fixture is rejected with a release-runbook diagnostic."
  - id: AC-2
    when: "The documentation drift guard evaluates the install runbook lead-in and its numbered Section 2 headings, including a mismatched-count fixture."
    then: "The canonical runbook reports six questions matching Q1 through Q6, while a count or heading mismatch is rejected with an install-runbook diagnostic."
  - id: AC-3
    when: "The repository documentation drift command and the focused documentation guard test module run from the repository root."
    then: "Both commands exit successfully and report no documentation-contract regressions."
  - id: AC-4
    when: "The completed change and its focused checks are inspected."
    then: "Only the install prose, stdlib documentation guard, and its tests change; runtime, dependency, workflow, backlog, and external state remain unchanged."
out_of_scope:
  - "Changing the release candidate construction, branch promotion, tagging, or publication flow."
  - "Changing the content, order, parsing, defaults, or effects of install questions Q1 through Q6."
  - "Changing .claude release skills, runtime modules, dependencies, CI workflows, backlog metadata, or external services."
contract_policy:
  flow: full_spdd
  reason: "Strict planning applies because these agent-facing release and install contracts must fail closed under lost or stale context."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "docs/RELEASING.md contains exactly one line-anchored CANDIDATE_SHA commit-tree assignment."
      source: "Current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The Section 2 question-count statement agrees with the contiguous Q1 through Q6 headings."
      source: "Current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The live docs-drift command and focused documentation tests remain green."
      source: "Current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The implementation introduces no runtime, dependency, workflow, backlog, or external-state change."
      source: "Current backlog contract AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "Release runbook candidate identity"
      kind: internal
      paths: ["docs/RELEASING.md"]
      expected_behavior: "The reviewed tree is converted into the release candidate once, and later steps reuse that immutable CANDIDATE_SHA."
    - name: "Agent install question sequence"
      kind: internal
      paths: ["docs/AGENT_INSTALL.md"]
      expected_behavior: "The Section 2 lead-in declares six questions and the existing Q1-Q6 sequence remains unchanged."
    - name: "Public documentation drift guard"
      kind: internal
      paths: ["scripts/docs_drift_guard.py", "tests/test_docs_drift_guard.py"]
      expected_behavior: "The guard accepts the canonical runbooks and returns path-specific errors for duplicate candidate assignment or install count drift."
  invariants:
    - id: INV-1
      statement: "Release candidate construction, immutable retry branches, hosted-check admission, promotion, tagging, and publication commands retain their current order and meaning."
      applies_to: ["docs/RELEASING.md"]
    - id: INV-2
      statement: "Install questions Q1 through Q6 retain their current prompts, parsing, safe defaults, skip conditions, and downstream variables."
      applies_to: ["docs/AGENT_INSTALL.md"]
    - id: INV-3
      statement: "The documentation guard remains stdlib-only and performs read-only repository inspection."
      applies_to: ["scripts/docs_drift_guard.py"]
    - id: INV-4
      statement: "Runtime code, dependencies, workflows, release skills, backlog metadata, and external systems are outside the mutation boundary."
      applies_to: ["docs/AGENT_INSTALL.md", "scripts/docs_drift_guard.py", "tests/test_docs_drift_guard.py"]
  risks:
    - id: RISK-1
      risk: "A loose substring count could mistake prose references for executable candidate assignments."
      mitigation: "Count only line-anchored CANDIDATE_SHA assignments whose value invokes git commit-tree, and test a real duplicated assignment."
    - id: RISK-2
      risk: "A hard-coded phrase check could pass after the numbered question sequence changes."
      mitigation: "Derive the numbered Section 2 heading sequence and compare it with the declared count, requiring contiguous Q1 through Q6 in the current contract."
    - id: RISK-3
      risk: "The correction could accidentally rewrite operational runbook steps."
      mitigation: "Limit prose editing to the count word and keep focused tests around existing guard behavior."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_runbook_consistency_accepts_canonical_release_and_install_docs -q"
      proves: "The canonical single candidate assignment and six-question install sequence are accepted together."
      acceptance_ids: [AC-1, AC-2]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_runbook_consistency_rejects_duplicate_candidate_sha_assignment -q"
      proves: "A repeated candidate commit-tree assignment fails with a bounded release-runbook error."
      acceptance_ids: [AC-1]
    - id: VER-3
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_runbook_consistency_rejects_install_question_count_mismatch -q"
      proves: "A declared count that disagrees with the Q1-Q6 headings fails with a bounded install-runbook error."
      acceptance_ids: [AC-2]
    - id: VER-4
      owner: provider
      command: "python scripts/docs_drift_guard.py"
      proves: "The live public documentation set, including both runbook contracts, passes the existing stdlib drift gate without runtime or external mutation."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-5
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py -q"
      proves: "The focused documentation contract suite remains green across existing and new guard behavior."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-6
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_runbook_consistency_rejects_non_contiguous_install_question_headings -q"
      proves: "A six-heading fixture with a missing or reordered Q number fails the contiguous Q1-through-Q6 contract independently of the declared count."
      acceptance_ids: [AC-2]
    - id: VER-7
      owner: provider
      command: "git status --short"
      proves: "The completed worktree contains implementation changes only in docs/AGENT_INSTALL.md, scripts/docs_drift_guard.py, and tests/test_docs_drift_guard.py, with no runtime, dependency, workflow, or backlog path changes."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_docs_drift_guard.py -q"
        proves: "Existing documentation drift fixtures continue to accept synchronized docs and reject malformed release and install guidance."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- Live evidence at planning time shows one line-anchored `CANDIDATE_SHA=$(git commit-tree ...)` assignment in `docs/RELEASING.md`. Preserve that canonical line; the residual release work is the regression contract, not a speculative prose rewrite.
- Add the two consistency predicates to `scripts/docs_drift_guard.py`, the existing stdlib owner for public release and install documentation contracts, and call them from `evaluate()` so `python scripts/docs_drift_guard.py` enforces both boundaries.
- Scope the release predicate to `docs/RELEASING.md`. Do not broaden this task into synchronization changes for `.claude/skills/release/SKILL.md`.
- Parse line-anchored Section 2 question headings and the single lead-in count statement. Reject missing, duplicated, non-contiguous, or mismatched Q headings with a diagnostic naming `docs/AGENT_INSTALL.md`.
- Reuse `_make_repo()` and the existing positive/negative guard-test style in `tests/test_docs_drift_guard.py`; mutate synthetic fixtures for failure evidence instead of changing live files during tests.
- Keep the malformed-heading fixture at six headings while making its Q sequence non-contiguous, so it exercises the heading-sequence predicate independently of the declared-count predicate.
- Inspect the completed worktree with `git status --short` and reject any implementation path outside `docs/AGENT_INSTALL.md`, `scripts/docs_drift_guard.py`, and `tests/test_docs_drift_guard.py`.
- Verification commands run from the repository root. `pyproject.toml` declares `tests` as the pytest path and excludes `needs_network` and `slow` tests by default; the guard itself is documented as stdlib-only.
