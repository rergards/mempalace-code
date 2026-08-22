---
slug: LLM-PROFILE-AWARE-USAGE-RULES
status: completed
authority: non_authoritative
goal: "Make canonical and packaged MemPalace guidance choose only capabilities exposed by the active MCP profile and stop safely when a capability is absent."
risk: medium
risk_note: "The change is documentation-led, but these instructions control destructive correction, taxonomy fallback, and retry behavior across clients with materially different tool surfaces."
files:
  - path: docs/LLM_USAGE_RULES.md
    change: "Make the sole canonical managed block capability-aware for correction, taxonomy discovery, method-not-found, retry, and contradictory-host paths while preserving profile-specific routing blocks."
  - path: mempalace_code/agent_plugin/skills/mempalace/SKILL.md
    change: "Tighten the distinct four-tool minimal skill so absent delete and taxonomy capabilities route to bounded host/owner recovery without naming unavailable tools."
  - path: tests/test_mcp_tool_profiles.py
    change: "Extend profile-derived guidance checks across minimal, code, notes, and full profiles, including unavailable-method and bounded-fallback behavior."
  - path: tests/test_agent_plugin_package.py
    change: "Extend packaged-skill contract coverage for lost context, repeated calls, absent capabilities, and contradictory host instructions while retaining the concise minimal-tool boundary."
acceptance:
  - id: AC-1
    when: "the focused guidance contract evaluates a correction under the exact four-tool minimal profile"
    then: "the resulting instruction never calls delete functionality and instead requires one tools/list capability check or a richer registration/owner-controlled host action."
  - id: AC-2
    when: "the focused guidance contract evaluates unknown wing or room input with taxonomy discovery tools present and absent"
    then: "it selects the available discovery tool when present and otherwise stops after a bounded fallback without inventing a wing, room, or broader search."
  - id: AC-3
    when: "a guidance fixture returns JSON-RPC method-not-found for an unavailable MemPalace method"
    then: "the agent is directed to refresh the available tool list once, never invent or retry an unavailable method, and never remove a filter or broaden scope without owner intent."
  - id: AC-4
    when: "the canonical-boundary and profile-drift checks inspect the repository and a synthetic duplicate or mismatched profile block"
    then: "the live repository retains one full managed block in docs/LLM_USAGE_RULES.md, a distinct minimal packaged skill aligned to profile truth, no embedded copy in docs/AGENT_INSTALL.md, and the synthetic drift is rejected."
  - id: AC-5
    when: "the focused fixture matrix exercises minimal and richer profiles with lost context, unavailable tools, repeated calls, and contradictory host instructions"
    then: "every case produces a bounded capability-aware action or owner stop, with no duplicate mutation, invented method, or implicit authority expansion."
out_of_scope:
  - "Changing MCP profile membership, selector resolution, tool schemas, server dispatch, or runtime tool negotiation."
  - "Restoring usage-rule injection or a duplicate managed block in docs/AGENT_INSTALL.md."
  - "Adding a new documentation generator, validator, gate, profile, or generic guidance abstraction."
  - "Changing storage contents, delete semantics, taxonomy data, or host registration commands."
contract_policy:
  flow: full_spdd
  reason: "Strict profile-routing guidance governs destructive correction and recovery behavior at an LLM-to-MCP capability boundary."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Minimal-profile correction guidance must not call unavailable delete functionality and must provide a bounded richer-profile or owner-host route."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Wing and room discovery guidance must branch on available taxonomy capabilities and stop safely when they are absent."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Method-not-found recovery must prohibit invented tools, repeated unavailable calls, and silent scope broadening."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The sole canonical full block, distinct minimal skill, profile truth, and drift checks must remain synchronized without changing the install-guide boundary."
      source: "current backlog contract AC-4 and CLARIFY-LLM-PROFILE-AWARE-USAGE-RULES decision"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Focused tests must cover profile capability differences and degraded-context recovery cases."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "canonical managed usage rules"
      kind: internal
      paths: ["docs/LLM_USAGE_RULES.md"]
      expected_behavior: "Describe capability discovery and bounded correction/taxonomy recovery that remains safe under minimal, code, notes, and full tool sets."
    - name: "packaged minimal Agent Plugin skill"
      kind: internal
      paths: ["mempalace_code/agent_plugin/skills/mempalace/SKILL.md"]
      expected_behavior: "Operate only through the four packaged tools and hand absent-capability work to a richer registration or owner-controlled host path."
    - name: "profile-aware guidance contracts"
      kind: internal
      paths: ["tests/test_mcp_tool_profiles.py", "tests/test_agent_plugin_package.py"]
      expected_behavior: "Derive expectations from PROFILES and reject unsafe guidance under capability loss, repeated calls, lost context, and contradictory authority."
  invariants:
    - id: INV-1
      statement: "PROFILES remains the authoritative static tool-set definition; this task does not change any profile membership or full-profile default."
      applies_to: ["tests/test_mcp_tool_profiles.py", "tests/test_agent_plugin_package.py"]
    - id: INV-2
      statement: "docs/LLM_USAGE_RULES.md retains exactly one ordered mempalace-rules marker pair, and no full-block copy is introduced elsewhere."
      applies_to: ["docs/LLM_USAGE_RULES.md"]
    - id: INV-3
      statement: "The packaged skill mentions exactly the four minimal-profile MemPalace tool names and stays within its existing 55-line limit."
      applies_to: ["mempalace_code/agent_plugin/skills/mempalace/SKILL.md", "tests/test_agent_plugin_package.py"]
    - id: INV-4
      statement: "docs/AGENT_INSTALL.md remains unchanged and continues to expose read-only Agent Plugin discovery with one recovery command."
      applies_to: ["docs/LLM_USAGE_RULES.md", "mempalace_code/agent_plugin/skills/mempalace/SKILL.md"]
    - id: INV-5
      statement: "Ambiguous write outcomes continue to reconcile current state before any bounded retry and stop on equivalent or contradictory state."
      applies_to: ["docs/LLM_USAGE_RULES.md", "mempalace_code/agent_plugin/skills/mempalace/SKILL.md"]
  risks:
    - id: RISK-1
      risk: "Full-profile prose can leak unavailable delete or taxonomy calls into reduced-profile clients."
      mitigation: "Gate every optional operation on the observed tools/list result and derive test matrices from PROFILES."
    - id: RISK-2
      risk: "Making the minimal skill mirror the full block could violate packaging concision and restore duplicate authority."
      mitigation: "Keep the skill independently minimal, preserve the exact-tool and line-count assertions, and retain the byte-level canonical-boundary regression."
    - id: RISK-3
      risk: "Recovery prose can accidentally authorize a wider search or repeated mutation after context loss."
      mitigation: "Use explicit one-list/one-retry bounds, retain original filters and intended correction, and require an owner stop on contradictions."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_mcp_tool_profiles.py::TestProfileAwareUsageRules tests/test_agent_plugin_package.py::TestAgentPluginProfileAwareSafety tests/test_docs_drift_guard.py::test_agent_rules_have_one_canonical_source_across_release_shape -q"
      proves: "The focused profile matrix enforces correction and taxonomy capability branches, method-not-found and degraded-context stops, minimal-skill constraints, and the sole-canonical-block boundary."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python scripts/docs_drift_guard.py"
        proves: "The existing configured documentation guard accepts the synchronized canonical/profile/package shape and rejects profile-tool or duplicate-block drift."
        acceptance_ids: [AC-4]
---

## Design Notes

- Treat `mempalace_code/mcp_tool_profiles.py::PROFILES` as read-only source data. Tests should derive capability sets from it instead of copying minimal, code, notes, or full membership into a second fixture.
- Keep the unscoped managed block as the canonical full reference. Add a short capability preamble that uses the client's `tools/list` result once per connection or after `-32601`; do not imply runtime profile negotiation.
- Correction guidance must distinguish wrong content from evolved content while making deletion conditional on an exposed delete tool. When deletion is absent, preserve the intended correction and direct the agent to a richer direct registration or an owner-approved `mempalace-code` host command without guessing that command's authority or target.
- Taxonomy recovery must make `mempalace_get_taxonomy`, `mempalace_list_wings`, and `mempalace_list_rooms` optional. If none is exposed, retain the original filter and ask for the exact identifier or richer registration; never retry by dropping `wing` or `room`.
- After `-32601`, refresh `tools/list` at most once because the host may have changed registrations. If the method remains absent, stop that operation. Repeated calls, synthesized names, nearby-tool substitution, and scope broadening are forbidden.
- Contradictory host instructions do not grant MCP or filesystem authority. Preserve the narrower observed capability set and ask the owner to choose the registration/host route before mutation.
- Keep the packaged skill optimized for minimal-profile execution and within 55 lines. Express absent-capability recovery generically so its MemPalace tool-name set remains byte-aligned with `PROFILES["minimal"]`.
- Extend the existing test owners instead of adding a parser or test module. Profile tests should parse the canonical managed/profile blocks and exercise a table derived from `PROFILES`; package tests should retain exact tool-name, secret, deletion-name, line-count, and ambiguous-write assertions while adding the degraded-context matrix.
- Reuse `scripts/docs_drift_guard.py::_canonical_rules_block` and `agent_instruction_boundary_errors` unchanged. Their existing byte checks protect the sole canonical block and prohibit a duplicate in `docs/AGENT_INSTALL.md` or the packaged plugin.
- The focused pytest command runs from the repository root in the documented project virtualenv. `python scripts/docs_drift_guard.py` is the existing configured docs-drift gate from `scripts/gate_inventory.py`; implementation must not wrap or alter it.
- This is isolated guidance/profile documentation work, so the incident-class registry block does not apply.
