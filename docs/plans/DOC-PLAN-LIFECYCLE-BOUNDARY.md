---
slug: DOC-PLAN-LIFECYCLE-BOUNDARY
status: active
authority: non_authoritative
goal: "Make every tracked implementation plan self-identify its lifecycle and remain non-authoritative when retrieved without surrounding context"
risk: medium
risk_note: "The change is documentation-only, but it mechanically updates the tracked plan corpus and must classify active, completed, superseded, and evidence-poor historical artifacts without creating false live authority."
public_evidence: [docs/plans/]
files:
  - path: docs/plans/
    change: "Add the directory lifecycle contract and mechanically annotate every tracked plan with one lifecycle status and an explicit non-authoritative boundary while preserving plan bodies."
  - path: .claude/skills/task-plan/INSTRUCTIONS.md
    change: "Make plan creation and transition rules use the directory contract, repository-backed lifecycle states, and fresh external mutation authority."
  - path: tests/test_agent_skill_authority_contract.py
    change: "Extend the existing agent-facing contract suite with corpus, malformed-state, stale-active, direct-retrieval, and packaging/search boundary coverage."
acceptance:
  - id: AC-1
    when: "the focused lifecycle contract enumerates git ls-files 'docs/plans/*.md' and excludes only the exact directory contract path docs/plans/README.md"
    then: "every remaining tracked implementation plan has exactly one status from active, completed, superseded, or historical, and every plan containing commands also declares itself non-authoritative"
  - id: AC-2
    when: "the focused contract compares docs/plans/README.md with .claude/skills/task-plan/INSTRUCTIONS.md"
    then: "both identify repository/backlog state as the lifecycle source, define the same transitions, and require fresh authority outside plan text for every mutation"
  - id: AC-3
    when: "the completed plan front matter and implementation path set are inspected"
    then: "public_evidence is exactly docs/plans/, and changes are confined to the tracked plan corpus, its directory contract, the task-plan owner, and the focused existing contract test"
  - id: AC-4
    when: "repository search and package-boundary fixtures inspect a historical plan without conversation context"
    then: "the tracked ignored plan remains discoverable in repository/source-distribution inputs, is absent from the package-only wheel surface, and its own metadata says it is historical and non-authoritative"
  - id: AC-5
    when: "the implementation owner and validation diff are inspected"
    then: "the existing YAML plan format, task-plan instructions, and agent-skill contract suite are extended, with no archive tree, runtime validator, release gate, or second plan owner"
  - id: AC-6
    when: "focused negative fixtures omit status, conflict with repository-backed status, mark a non-open task active, or directly retrieve a historical plan"
    then: "the first three cases fail with bounded lifecycle diagnostics, while direct retrieval exposes the historical and non-authoritative metadata before any plan commands"
out_of_scope:
  - "Editing docs/BACKLOG.yaml, archived backlog files, runtime MemPalace code, packaging configuration, release workflows, or external state"
  - "Moving or copying plans into a new archive, deleting historical plan bodies, or rewriting preserved commands"
  - "Adding a production validator, CLI command, CI workflow, broad phrase scanner, or release gate"
  - "Granting implementation, Git, publication, or deployment authority through any plan status"
contract_policy:
  flow: full_spdd
  reason: "Strict planning applies because a large public documentation corpus carries mutating commands across a rules-heavy human-to-LLM authority boundary."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Every tracked implementation plan declares one repository-backed lifecycle state and explicit zero mutation authority."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The directory contract and task-plan owner define one source of truth, transition model, and authority boundary."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The ignored-but-tracked corpus remains declared public evidence and bounds implementation scope."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Repository discovery and distribution boundaries are documented from current Git and Hatch configuration, and directly retrieved stale plans remain self-contained."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Lifecycle handling extends the existing plan format, task-plan owner, and focused contract suite without a parallel archive or uncited new gate."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Focused checks cover missing, contradictory, stale-active, and direct historical retrieval cases."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "tracked plan corpus and directory contract"
      kind: internal
      paths: ["docs/plans/"]
      expected_behavior: "Each implementation plan selected from tracked docs/plans/*.md after excluding only docs/plans/README.md is self-describing on direct retrieval; README.md defines lifecycle classification, transitions, repository discovery, distribution visibility, authority, and uncertain-state recovery."
    - name: "plan creation owner"
      kind: internal
      paths: [".claude/skills/task-plan/INSTRUCTIONS.md"]
      expected_behavior: "New plans start with a valid lifecycle marker, transitions follow current repository evidence, and plan content never supplies mutation authority."
    - name: "plan lifecycle contract"
      kind: internal
      paths: ["tests/test_agent_skill_authority_contract.py"]
      expected_behavior: "Focused fixtures and live-corpus assertions reject missing, conflicting, or stale status while proving direct-retrieval and packaging/search boundaries."
  invariants:
    - id: INV-1
      statement: "Implementation-plan bodies, commands, acceptance criteria, and historical evidence remain byte-for-byte unchanged apart from front-matter lifecycle additions; docs/plans/README.md is the directory contract and is outside the implementation-plan corpus."
      applies_to: ["docs/plans/"]
    - id: INV-2
      statement: "A plan in any lifecycle state grants no source, backlog, Git, deployment, publication, or external mutation authority."
      applies_to: ["docs/plans/", ".claude/skills/task-plan/INSTRUCTIONS.md"]
    - id: INV-3
      statement: "docs/BACKLOG.yaml and docs/BACKLOG-archived.yaml remain the repository evidence for open and completed task state and are not implementation-owned files."
      applies_to: ["docs/plans/", ".claude/skills/task-plan/INSTRUCTIONS.md"]
    - id: INV-4
      statement: "The wheel remains limited to mempalace_code, and no packaging or release configuration changes are introduced."
      applies_to: ["docs/plans/", "pyproject.toml"]
  risks:
    - id: RISK-1
      risk: "A mechanical bulk edit could omit a tracked plan or alter preserved plan content."
      mitigation: "Drive coverage from git ls-files with only docs/plans/README.md excluded, constrain edits to front matter, and compare each post-change implementation plan with the immutable pre-edit Git commit while permitting only the exact lifecycle-field insertions."
    - id: RISK-2
      risk: "An old plan could be incorrectly marked active because its prose still sounds current."
      mitigation: "Require an exact open-backlog match for active; fall back to historical and non-authoritative when repository evidence is absent or ambiguous."
    - id: RISK-3
      risk: "Directory and skill prose could drift into different lifecycle or authority rules."
      mitigation: "Keep the directory contract canonical for artifact semantics and add one section-bound agreement test in the existing contract suite."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_agent_skill_authority_contract.py::test_tracked_plan_lifecycle_metadata_matches_repository_state -q"
      proves: "Every tracked docs/plans/*.md implementation plan after excluding only docs/plans/README.md has exactly one allowed status, explicit non-authority, and repository-backed active/completed/superseded/historical classification; the README exclusion is exact and unique."
      acceptance_ids: [AC-1, AC-3]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_agent_skill_authority_contract.py::test_plan_lifecycle_contract_and_task_skill_agree -q"
      proves: "The directory contract and creation owner agree on lifecycle source, transitions, authority, and uncertain-state recovery."
      acceptance_ids: [AC-2, AC-5]
    - id: VER-3
      owner: provider
      command: "python -m pytest tests/test_agent_skill_authority_contract.py::test_plan_lifecycle_contract_rejects_missing_or_contradictory_status -q"
      proves: "Missing, duplicate, invalid, or repository-conflicting lifecycle metadata fails with a bounded diagnostic."
      acceptance_ids: [AC-1, AC-6]
    - id: VER-4
      owner: provider
      command: "python -m pytest tests/test_agent_skill_authority_contract.py::test_plan_lifecycle_contract_rejects_stale_active_status -q"
      proves: "An active marker without an exact current open-backlog match is rejected rather than retained as stale authority."
      acceptance_ids: [AC-2, AC-6]
    - id: VER-5
      owner: provider
      command: "python -m pytest tests/test_agent_skill_authority_contract.py::test_historical_plan_direct_retrieval_is_non_authoritative -q"
      proves: "Reading a historical plan by itself exposes historical status and zero mutation authority before preserved commands."
      acceptance_ids: [AC-4, AC-6]
    - id: VER-6
      owner: provider
      command: "python -m pytest tests/test_agent_skill_authority_contract.py::test_plan_repository_and_distribution_boundaries_are_truthful -q"
      proves: "The test observes tracked ignored plans in repository/source inputs and the package-only wheel boundary without changing packaging configuration."
      acceptance_ids: [AC-3, AC-4, AC-5]
    - id: VER-7
      owner: provider
      command: "python -m pytest tests/test_agent_skill_authority_contract.py::test_plan_lifecycle_bulk_edit_preserves_prechange_content -q"
      proves: "Every implementation plan present in the recorded immutable pre-edit Git commit matches that baseline byte-for-byte after accounting only for the exact inserted lifecycle fields; no baseline plan is deleted, renamed, or otherwise rewritten, and docs/plans/README.md is treated only as the new directory contract."
      acceptance_ids: [AC-1, AC-3]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_agent_skill_authority_contract.py::test_each_mutation_requires_fresh_exact_single_use_authority -q"
        proves: "Existing task-plan mutation authority remains exact, current, single-use, and independent of plan lifecycle metadata."
        acceptance_ids: [AC-2, AC-5]
---

## Design Notes

- Use `status` with exactly one value from `active`, `completed`, `superseded`, or `historical`, plus `authority: non_authoritative`, in the existing YAML front matter. Keep these fields before executable-looking body content so direct retrieval carries the boundary.
- Add `docs/plans/README.md` as the named directory contract. This is a distinct artifact contract for the existing corpus, not a second creation workflow or archive.
- Classify `active` only from an exact open item in `docs/BACKLOG.yaml`; classify `completed` from exact archived completion evidence; use `superseded` only with an explicit replacement reference; use `historical` when no reliable state evidence exists. Ambiguity follows the backlog recovery rule: historical, non-authoritative, owner decision before execution.
- Define the implementation-plan corpus as paths returned by `git ls-files 'docs/plans/*.md'` except the exact directory contract path `docs/plans/README.md`; assert that no other tracked Markdown path is excluded. Apply the 2026-08-22 audit mechanically to that corpus. Preserve each existing front-matter field and body; the new task plan is active while its exact backlog item remains open.
- The directory contract must state that lifecycle is descriptive repository state. Every mutation still requires fresh authority from the owning workflow, independent of `active` status.
- Document the observed public shape: `.gitignore` suppresses newly generated `docs/plans/` files by default, already tracked plans remain available to Git/repository search and source-distribution inputs, and `[tool.hatch.build.targets.wheel] packages = ["mempalace_code"]` keeps repository docs out of wheels.
- Extend `tests/test_agent_skill_authority_contract.py`; do not add a production validator or CI gate. This cites the 2026-08-22 audit as the concrete failure and keeps enforcement beside the existing task-plan authority contract.
- Add one focused preservation check in that suite. Before editing the corpus, record the current Git `HEAD` as the immutable pre-change commit in the focused test; require every implementation-plan path from that commit to remain present, and permit only insertion of the exact lifecycle front-matter fields before requiring byte equality for all preserved content. The parent runner performs staging only after this provider-owned check passes, and the recorded commit keeps the check meaningful after landing.
- Build synthetic temporary repositories for missing, duplicate/invalid, repository-conflicting, and stale-active fixtures. Use one real tracked historical plan for direct-retrieval evidence, chosen by repository state rather than filename convention.
- Verification commands run from the repository root with the project virtualenv. `pyproject.toml` provides pytest and PyYAML through the development dependencies; each command targets one focused contract test and does not require network access.
