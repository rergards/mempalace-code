---
slug: MCP-REQUIRED-STRINGS-REJECT-BLANK
status: completed
authority: non_authoritative
goal: "Reject empty and whitespace-only schema-required MCP strings at the shared dispatch boundary before any handler runs."
risk: medium
risk_note: "The predicate is small, but it changes the shared 29-tool JSON-RPC boundary and must preserve handler input, process continuity, mutation safety, profiles, and exact-wheel release evidence."
files:
  - path: mempalace_code/mcp/dispatch.py
    change: "Extend the existing schema-based argument guard to reject blank required strings with a bounded field-naming -32602 response while passing valid values through unchanged."
  - path: tests/test_mcp_protocol_compat.py
    change: "Extend the existing dispatch and real-stdio schema-guard owner with live-registry blank matrices, handler non-invocation, verbatim valid-input, same-process continuity, and disposable-palace post-state coverage."
  - path: scripts/release_install_metadata_smoke.py
    change: "Extend the existing declared Agent Plugin MCP subprocess probe so exact-wheel installer qualification directly proves blank required-string rejection and a subsequent valid request in the same process."
  - path: tests/test_installed_artifact_behavior.py
    change: "Update the installed-artifact smoke seams and response fixtures to prove the declared MCP probe admits only the expected bounded rejection and continuation behavior."
acceptance:
  - id: AC-1
    when: "Each schema-required string property discovered from the live 29-tool registry is submitted once as an empty string and once as a whitespace-only string, with valid placeholders for its sibling required arguments."
    then: "Dispatch returns JSON-RPC -32602 for every case before the selected handler is invoked."
  - id: AC-2
    when: "A real full-profile stdio process receives blank required strings and then a valid request without restarting."
    then: "Each error names the invalid argument or arguments, echoes no submitted content, exposes no traceback, and the subsequent valid request succeeds in that same process."
  - id: AC-3
    when: "A schema-required string contains non-whitespace content with leading or trailing whitespace."
    then: "Dispatch invokes the handler with the exact original string rather than trimming or rewriting it."
  - id: AC-4
    when: "Blank required values are sent for kg_add, add_drawer, diary_write, search, code_search, file_context, read, mine, and required architecture tools against a disposable seeded palace."
    then: "All calls fail at dispatch and the palace and knowledge-graph byte/post-state snapshots remain unchanged."
  - id: AC-5
    when: "The existing missing, null, wrong-type, undeclared-argument, duplicate-ID, malformed-line continuation, and minimal, kg, code, notes, and full profile scenarios execute."
    then: "Their established JSON-RPC errors, continuation behavior, handler results, and exposed tool sets remain unchanged."
  - id: AC-6
    when: "The canonical release-readiness check installs the exact candidate wheel and invokes its declared mempalace-code-mcp command from the existing isolated installer smoke."
    then: "The installed process rejects a blank required string through the shared dispatch boundary and completes the following valid request."
out_of_scope:
  - "Changing tool-specific optional-string semantics, handler-level normalization, or valid-string whitespace preservation."
  - "Changing the separate CLI diary-write or CLI search behavior owned by other backlog tasks."
  - "Adding a validator module, JSON Schema runtime dependency, schema keyword, tool, profile, release gate, or install harness."
  - "Changing backlog metadata, archiving the task, committing, publishing, or releasing."
contract_policy:
  flow: full_spdd
  reason: "This standard pre-release bug changes a shared MCP provider boundary and its exact-wheel qualification evidence."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Every live-registry required string must reject empty and whitespace-only values before handler invocation."
      source: "Current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Blank-input errors must be bounded, field-specific, content-safe, and recoverable within the same stdio process."
      source: "Current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The dispatcher may inspect stripped content only for the blank predicate and must pass valid strings verbatim."
      source: "Current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Representative read, search, write, diary, KG, mine, file, and architecture calls with blank required values must leave durable state unchanged."
      source: "Current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Existing parameter-error precedence, malformed-input recovery, request-ID behavior, and all five profile contracts must remain compatible."
      source: "Current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Exact-wheel release qualification must directly exercise the shared required-string guard through the installed MCP launcher."
      source: "Current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "MCP tools/call required-string validation"
      kind: api
      paths: [mempalace_code/mcp/dispatch.py]
      expected_behavior: "Derive required string names from each active registry schema, reject values whose stripped form is empty with -32602 before handler invocation, and retain the original value for accepted calls."
    - name: "Installed declared MCP qualification"
      kind: internal
      paths: [scripts/release_install_metadata_smoke.py]
      expected_behavior: "The existing exact-wheel installer probe sends one blank required-string call and one following valid call through the declared minimal-profile launcher and validates both responses."
  invariants:
    - id: INV-1
      statement: "Optional string arguments retain their existing omitted, empty, whitespace-only, and handler-owned semantics."
      applies_to: [mempalace_code/mcp/dispatch.py]
    - id: INV-2
      statement: "Accepted required strings reach handlers byte-for-byte unchanged; dispatch performs no normalization or rewriting."
      applies_to: [mempalace_code/mcp/dispatch.py, tests/test_mcp_protocol_compat.py]
    - id: INV-3
      statement: "Missing arguments, nulls, wrong primitive types, undeclared arguments, unknown or profile-hidden tools, and compatibility noise retain their existing validation order and response contracts."
      applies_to: [mempalace_code/mcp/dispatch.py, tests/test_mcp_protocol_compat.py]
    - id: INV-4
      statement: "The 29 tool schemas, five profile memberships, handlers, and profile selector grammar do not change."
      applies_to: [mempalace_code/mcp/dispatch.py]
    - id: INV-5
      statement: "The installed smoke remains credential-free, isolated, neutral-directory based, and driven by the already declared Agent Plugin MCP command."
      applies_to: [scripts/release_install_metadata_smoke.py, tests/test_installed_artifact_behavior.py]
  risks:
    - id: RISK-1
      risk: "A broad string check could reject optional blank values or normalize valid handler input."
      mitigation: "Select only names present in schema.required whose declared property type is string, call strip only in the predicate, and assert exact captured handler arguments for accepted values."
    - id: RISK-2
      risk: "Validation after handler dispatch could allow search, embedding, filesystem, diary, or KG side effects before the error."
      mitigation: "Keep the predicate in dispatch before the handler call, assert spy handlers are untouched across the live registry, and compare disposable palace/KG state around real stdio requests."
    - id: RISK-3
      risk: "A source-only regression could leave the packaged launcher accepting blank values."
      mitigation: "Extend the existing declared-MCP installer probe and require the canonical exact-wheel release-readiness command rather than creating a parallel install harness."
    - id: RISK-4
      risk: "Changing response sequencing in the installed probe could hide a crashed or desynchronized stdio process."
      mitigation: "Use distinct request IDs, require the exact response count and order, validate the blank -32602 response, and require a later valid tools/list result from the same subprocess."
  verification:
    - id: VER-1
      owner: provider_owned
      command: "python -m pytest tests/test_mcp_protocol_compat.py -q"
      proves: "The focused MCP protocol owner exhausts live-registry required strings, verifies pre-handler rejection, exact valid-value preservation, real-stdio continuity, unchanged disposable state, and existing malformed/type guard behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: provider_owned
      command: "python -m pytest tests/test_installed_artifact_behavior.py::TestDeclaredMCPRequiredStringGuard -q"
      proves: "The focused installed-smoke seam requires a blank -32602 response followed by a valid response and rejects missing, reordered, malformed, or false-success response shapes."
      acceptance_ids: [AC-2, AC-6]
    - id: VER-3
      owner: configured_runner_owned
      command: "python scripts/release_readiness_gate.py --check --candidate-sha \"$CANDIDATE_SHA\" --json"
      proves: "The canonical readiness owner builds the exact candidate wheel and directly exercises the extended declared MCP probe through its installed launcher in the existing isolated installer matrix."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner_owned
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The exact configured non-network suite preserves missing/null/type/undeclared guards, duplicate and malformed request behavior, all five profiles, handlers, storage, KG, and installed-artifact seams."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Extend the validation sequence already owned by `handle_request`: object shape, active-tool lookup, compatibility-noise removal, undeclared arguments, type validation/coercion, missing required arguments, blank required strings, then handler invocation. Preserve every earlier error's precedence and text.
- Derive blank candidates from the selected active registry entry: intersect `input_schema.required` with properties whose declared type is `string`. A value is invalid when `value.strip()` is empty. Use the stripped form only for that boolean decision; keep `tool_args` unchanged for the handler.
- Return one deterministic `-32602` response naming all blank required argument names in schema-required order. Include field names only. Do not echo values, request content, exception detail, or traceback text.
- In `tests/test_mcp_protocol_compat.py`, build the exhaustive matrix from live `TOOLS` rather than copying tool names. Supply typed placeholders for sibling required fields, replace the handler with a recording sentinel, and cover `""`, spaces, tabs, and mixed whitespace. Assert every rejection precedes the sentinel.
- Use a separate accepted-value matrix with leading/trailing whitespace and the same recording seam. Assert the sentinel receives the exact original strings. Include an optional-string control proving optional blank values are still forwarded under their existing handler-owned contract.
- Extend the existing real-stdio helpers with one bounded full-profile sequence covering the named mutation and query families. Seed one disposable palace/KG, capture a deterministic repository-relative file-byte or semantic state snapshot before the requests, send blank cases with unique IDs, send a final valid request, then require identical post-state and clean stderr. Do not initialize handlers merely to prove rejection when a dispatcher sentinel supplies stronger evidence.
- Keep existing missing/null/type/undeclared, malformed-line continuation, duplicate request-ID, and profile tests as regression owners. Add no second profile registry or schema inventory.
- Extend `_probe_declared_mcp_command` in `scripts/release_install_metadata_smoke.py`; retain the packaged minimal profile from `mcp.json`. After initialize/tools-list, submit a whitespace-only `content` to `mempalace_check_duplicate`, require `-32602` naming `content` without echo, then issue a second tools/list request and require the canonical minimal tool tuple. This directly proves rejection and same-process recovery without creating palace state or loading embeddings.
- Update `_mcp_responses` and add `TestDeclaredMCPRequiredStringGuard` in `tests/test_installed_artifact_behavior.py` so the smoke parser fails closed on absent, reordered, extra, non-JSON, content-echoing, or false-success responses.
- Command context basis: `pyproject.toml` declares pytest and repository-root test discovery; `scripts/gate_inventory.py` owns the exact non-network and release-readiness commands; `scripts/release_readiness_gate.py` builds the exact wheel and runs `release_install_metadata_smoke.py` through isolated installer environments; `tests/test_mcp_protocol_compat.py` already owns real stdio malformed-input and schema-guard coverage.
- No `incident_proof` block applies because this checkout has no `docs/quality/incident-class-registry.yaml` registry to match this runtime fix.
- PLAN does not execute tests, builds, release gates, verification wrappers, or generated-plan validation.
