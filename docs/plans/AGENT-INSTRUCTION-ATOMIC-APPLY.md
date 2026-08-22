---
slug: AGENT-INSTRUCTION-ATOMIC-APPLY
status: completed
authority: non_authoritative
goal: "Remove public instruction-file mutation guidance and make the existing Agent Plugin package the only supported automated instruction-loading boundary"
risk: medium
risk_note: "The implementation deletes release-facing setup behavior and rewrites an existing documentation guard; a weak negative contract could allow unsafe CLAUDE.md or AGENTS.md mutation guidance to return."
files:
  - path: docs/AGENT_INSTALL.md
    change: "Replace Section 7 injection, inline rules copy, and manual-paste fallback with a fail-closed Agent Plugin loading boundary and one concrete package-discovery recovery command."
  - path: docs/LLM_USAGE_RULES.md
    change: "Keep the full rules block as the sole canonical source while removing target-specific paste, insert, replace, marker-management, and AGENT_INSTALL injection directions."
  - path: scripts/docs_drift_guard.py
    change: "Replace two-copy managed-block parity with a negative contract that requires one canonical rules block, scans every repository documentation file and packaged Agent Plugin member for arbitrary duplicate or orphan copies, forbids an AGENT_INSTALL mutation route, and reports bounded recovery guidance."
  - path: tests/test_docs_drift_guard.py
    change: "Replace mutation-positive and two-copy parity fixtures with focused positive and negative coverage for the plugin-only boundary, unsafe target states, duplicate/retry/partial cases, and arbitrary-named duplicate or orphan rules copies in repository documentation and packaged Agent Plugin members."
acceptance:
  - id: AC-1
    when: "the public installation instructions reach agent-instruction setup after a successful MemPalace install"
    then: "they direct a compatible client only to the directory returned by mempalace-code agent-plugin path --json and contain no instruction to write, paste, insert, replace, restore, or otherwise mutate CLAUDE.md or AGENTS.md"
  - id: AC-2
    when: "default or skipped setup, malformed or legacy markers/content, a missing or wrong target, a symlinked target or parent, duplicate retry, or partial prior execution is represented in the focused safety fixtures"
    then: "the documentation contract performs no instruction-file operation and returns the single recovery command mempalace-code agent-plugin path --json"
  - id: AC-3
    when: "the repository documentation and packaged Agent Plugin are inspected after the change"
    then: "no automated apply or restore path remains, so no unaudited backup, mode-preservation, atomic-replace, fsync, poststate, or idempotency promise is exposed; repeated package discovery remains read-only"
  - id: AC-4
    when: "the release-shape guards inspect canonical rules ownership and packaged members"
    then: "docs/LLM_USAGE_RULES.md contains the sole full managed rules block, docs/AGENT_INSTALL.md contains no copy, the package contains its distinct concise skill and no instructions.md orphan, and a synthetic duplicate or orphan fails"
  - id: AC-5
    when: "focused negative tests inject guidance for a wrong target, substituted backup, changed mode, symlink parent, post-replace failure, or repeated apply/restore"
    then: "each case is rejected as an unsupported instruction-file mutation route with the same concrete package-discovery recovery command"
out_of_scope:
  - "Implementing an instruction-file writer, backup/restore owner, marker migration, or filesystem transaction protocol"
  - "Adding direct CLAUDE.md, AGENTS.md, GEMINI.md, Cursor, Aider, Continue, Windsurf, Zed, or other client-specific mutation automation"
  - "Changing the canonical rules body, the packaged minimal-profile skill content, Agent Plugin manifests, MCP profiles, or runtime MCP behavior"
  - "Changing backlog metadata, release bookkeeping, Git history, publication state, or external client configuration"
contract_policy:
  flow: full_spdd
  reason: "Strict release-blocker work changes a rules-heavy human-to-LLM installation boundary and its release-shape enforcement."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The public install path must not ask a human or agent to improvise mutation of CLAUDE.md or AGENTS.md."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Every formerly classified target, marker, retry, and partial-execution state must converge on no mutation and one recovery command."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "No filesystem apply contract may remain unless a single audited atomic owner implements its complete backup, replace, fsync, verification, restore, and idempotency contract."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Full rules content must have one source owner and release-shape checks must reject duplicate or orphan artifacts."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Negative regression evidence must cover the named target, backup, mode, symlink, post-replace, and repeated-operation failure classes."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "public agent installation runbook"
      kind: internal
      paths: ["docs/AGENT_INSTALL.md"]
      expected_behavior: "Instruction setup stops at the existing Agent Plugin package boundary and provides one read-only discovery command without direct rules-file mutation or manual-paste fallback."
    - name: "canonical full usage rules"
      kind: internal
      paths: ["docs/LLM_USAGE_RULES.md"]
      expected_behavior: "The full rules remain canonical reference content, while client routing no longer instructs readers or agents to paste or manage that content in instruction files."
    - name: "public documentation drift guard"
      kind: internal
      paths: ["scripts/docs_drift_guard.py", "tests/test_docs_drift_guard.py"]
      expected_behavior: "The existing guard accepts the plugin-only shape and rejects any reintroduced mutation route, duplicate full block, or orphan packaged instructions copy with a bounded diagnostic."
  invariants:
    - id: INV-1
      statement: "mempalace_code/agent_plugin/skills/mempalace/SKILL.md remains the concise minimal-profile skill and does not become a copy of the full rules document."
      applies_to: ["mempalace_code/agent_plugin/skills/mempalace/SKILL.md", "docs/LLM_USAGE_RULES.md"]
    - id: INV-2
      statement: "Agent Plugin manifests, schemas, package discovery, MCP command, and minimal tool profile retain their existing behavior."
      applies_to: ["mempalace_code/agent_plugins.py", "mempalace_code/agent_plugin/plugin.json", "mempalace_code/agent_plugin/mcp.json"]
    - id: INV-3
      statement: "The canonical usage-rules body and its tool-use semantics remain unchanged by this installation-boundary repair."
      applies_to: ["docs/LLM_USAGE_RULES.md"]
    - id: INV-4
      statement: "The documentation guard remains stdlib-only and read-only against repository content."
      applies_to: ["scripts/docs_drift_guard.py"]
  risks:
    - id: RISK-1
      risk: "Residual prose in either public document could still be interpreted as authority to mutate an instruction file."
      mitigation: "Guard semantic mutation verbs together with CLAUDE.md/AGENTS.md target references and exercise concrete reintroduction fixtures."
    - id: RISK-2
      risk: "Deleting two-copy parity could leave the canonical rules block unguarded or allow a second copy elsewhere."
      mitigation: "Require exactly one line-anchored block in docs/LLM_USAGE_RULES.md and dynamically inspect every repository documentation file and packaged Agent Plugin member; reject the markers or canonical full-block body at every other path regardless of filename."
    - id: RISK-3
      risk: "The recovery text could imply that every client supports Agent Plugins or silently fall back to manual mutation."
      mitigation: "Condition loading on Agent Plugins 1.0 compatibility; unsupported clients stop with no mutation and no fallback writer or paste instruction."
    - id: RISK-4
      risk: "Broad forbidden-word matching could reject explanatory safety prose or unrelated configuration operations."
      mitigation: "Scope the predicate to the agent-instruction setup sections and use behavioral fixtures for target mutation routes instead of repository-wide word bans."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_instruction_setup_uses_plugin_only -q"
      proves: "The public setup route exposes only compatible Agent Plugin loading and the read-only package-discovery recovery command, with no CLAUDE.md or AGENTS.md mutation guidance."
      acceptance_ids: [AC-1]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_agent_instruction_unsafe_states_share_fail_closed_recovery -q"
      proves: "Default, skip, marker/content, missing/wrong target, symlink, retry, and partial-execution states all map to no mutation and one recovery command."
      acceptance_ids: [AC-2]
    - id: VER-3
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_defers_instruction_file_apply_contract -q"
      proves: "No apply or restore contract, filesystem safety promise, or manual fallback remains, while package discovery is read-only and repeatable."
      acceptance_ids: [AC-3]
    - id: VER-4
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_agent_rules_have_one_canonical_source_across_release_shape -q"
      proves: "The live release shape has one full-rules owner, and synthetic arbitrary-named files under repository documentation and the packaged Agent Plugin are rejected when they contain the managed markers or canonical full-block body."
      acceptance_ids: [AC-4]
    - id: VER-5
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_agent_instruction_mutation_failure_classes_are_rejected -q"
      proves: "Wrong-target, substituted-backup, changed-mode, symlink-parent, post-replace, and repeated apply/restore guidance each fail the negative contract."
      acceptance_ids: [AC-5]
    - id: VER-6
      owner: provider
      command: "python scripts/docs_drift_guard.py"
      proves: "The live public documentation set satisfies the updated one-owner, plugin-only instruction boundary."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_agent_plugin_package.py::TestAgentPluginLayout::test_installed_plugin_root_contains_fixed_locations -q"
        proves: "The existing packaged Agent Plugin layout remains discoverable and contains no orphan instructions.md artifact."
        acceptance_ids: [AC-4]
---

## Design Notes

- Delete the Section 7 target selection, marker classification, insert/replace steps, embedded full block, success message, and manual-paste fallback. Replace them with a short compatibility-gated Agent Plugin loading step that uses `mempalace-code agent-plugin path --json`; unsupported clients stop without mutation.
- Update the earlier Section 6 guidance so it no longer routes all agents to Section 7 instruction-file injection. Keep the already documented Agent Plugins 1.0 package path as the supported automation boundary.
- Keep the line-anchored managed block in `docs/LLM_USAGE_RULES.md` byte-for-byte unchanged. Rewrite only its "How to use this file" routing and installation prose so it is reference material and no longer grants authority to paste, insert, replace, or manage instruction files.
- Replace `_managed_block_body()` / `managed_block_errors()` two-copy parity in `scripts/docs_drift_guard.py` with the existing guard owner's one-source predicate. It should require one canonical block in `docs/LLM_USAGE_RULES.md`, dynamically inspect every repository documentation file and packaged Agent Plugin member, reject the managed markers or canonical full-block body at every other path regardless of filename, and reject scoped instruction-file mutation guidance with a diagnostic that names `mempalace-code agent-plugin path --json` as recovery.
- Keep the packaged minimal skill distinct from the full rules. Retain the existing `TestAgentPluginLayout` assertion that `instructions.md` is absent as a layout regression, while the guard fixture proves differently named package members cannot carry an orphan full-rules copy; do not add a generator, package copy, manifest member, helper, or new script.
- Replace the current mutation-positive Section 7 tests and managed-block parity fixtures. Use synthetic unsafe guidance cases to prove rejection for the exact backlog failure classes without creating real targets, symlinks, backups, or instruction-file writes during tests.
- Treat backup identity, mode preservation, same-directory replace, directory fsync, poststate verification, restore, and apply idempotency as an indivisible future-owner contract. This plan removes the apply surface, so none of those partial guarantees remains in public prose.
- Verification commands run from the repository root. `pyproject.toml` declares `tests` as the pytest path and excludes `needs_network` and `slow` by default; `.github/workflows/ci.yml` runs `python scripts/docs_drift_guard.py` as the existing documentation gate.
