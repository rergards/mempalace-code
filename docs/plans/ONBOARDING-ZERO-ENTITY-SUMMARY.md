---
slug: ONBOARDING-ZERO-ENTITY-SUMMARY
status: completed
authority: non_authoritative
goal: "Render completed onboarding summaries with a zero people count and no empty name delimiters."
risk: low
risk_note: "The change is isolated to the existing text formatter and preserves registry data, prompts, defaults, and persistence."
files:
  - path: mempalace_code/entity_registry.py
    change: "Have EntityRegistry.summary() append the parenthesized people-name segment only when at least one person exists."
  - path: tests/test_entity_registry.py
    change: "Add focused formatter coverage for zero people and populated people lists, including the established name truncation boundary."
  - path: tests/test_onboarding.py
    change: "Extend the real CLI subprocess flow to recover from a malformed mode choice, complete with zero people, and assert the final summary has no empty delimiters."
  - path: docs/quality/scorecard.md
    change: "Refresh the generated human-readable quality scorecard after the focused test additions."
  - path: docs/quality/scorecard.json
    change: "Refresh the generated machine-readable quality scorecard after the focused test additions."
acceptance:
  - id: AC-1
    when: "A completed onboarding registry contains zero people and its summary is printed."
    then: "The people line is exactly `People: 0` and contains no empty parentheses or other empty name delimiters."
  - id: AC-2
    when: "An entity registry summary is rendered with one or more people."
    then: "The people count is followed by the existing parenthesized name list, with the established eight-name truncation behavior preserved."
  - id: AC-3
    when: "The real onboarding CLI receives a malformed mode choice, then a valid work-mode choice, an empty first person, and valid answers through completion."
    then: "The CLI retries mode selection, exits successfully, reaches `Setup Complete`, and prints `People: 0` without empty delimiters."
out_of_scope:
  - "Changes to onboarding prompts, input defaults, retry limits, or entity collection semantics."
  - "Changes to the entity registry schema, persistence, generated AAAK files, or project and ambiguous-flag summary lines."
  - "Backlog bookkeeping, release qualification, publication, and installed-package smoke testing."
contract_policy:
  flow: full_spdd
  reason: "This standard bug fix changes a final human-facing CLI state summary and requires formatter-level plus real subprocess proof."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "A zero-person registry summary must render the count without an empty parenthesized name segment."
      source: "backlog AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Populated registry summaries must retain their current people-name output and truncation behavior."
      source: "backlog AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The real onboarding CLI must demonstrate bounded recovery from malformed mode input and a clean zero-person final summary."
      source: "backlog AC-3"
      acceptance_ids: [AC-3]
  surfaces:
    - name: "Entity registry summary formatter"
      kind: internal
      paths: ["mempalace_code/entity_registry.py"]
      expected_behavior: "summary() emits `People: 0` for an empty registry and conditionally includes the existing parenthesized name list for populated registries; onboarding continues to consume this formatter unchanged."
  invariants:
    - id: INV-1
      statement: "Onboarding prompts, mode retry behavior, defaults, and collected entity data remain unchanged."
      applies_to: ["mempalace_code/entity_registry.py", "tests/test_onboarding.py"]
    - id: INV-2
      statement: "Entity registry schema, save/load behavior, and generated onboarding artifacts remain unchanged."
      applies_to: ["mempalace_code/entity_registry.py"]
    - id: INV-3
      statement: "Populated people summaries continue to show at most eight names and append an ellipsis when more than eight people exist."
      applies_to: ["mempalace_code/entity_registry.py", "tests/test_entity_registry.py"]
  risks:
    - id: RISK-1
      risk: "Removing delimiters unconditionally could also remove names from populated summaries."
      mitigation: "Branch only the people-name suffix and cover both empty and populated registries in formatter tests."
    - id: RISK-2
      risk: "A formatter-only test could miss the indentation and multiline behavior visible in Setup Complete."
      mitigation: "Retain real CLI subprocess coverage and assert the final stdout after malformed mode recovery and zero-person completion."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_entity_registry.py -q"
      proves: "Focused formatter tests observe the exact zero-person line and preserve populated name and truncation output."
      acceptance_ids: [AC-1, AC-2]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_onboarding.py::test_malformed_mode_then_minimal_flow_prints_clean_summary -q"
      proves: "The real CLI subprocess rejects malformed mode input, accepts the retry, completes with zero people, and prints the clean final summary."
      acceptance_ids: [AC-1, AC-3]
    - id: VER-3
      owner: provider
      command: "python scripts/quality_scorecard.py --check"
      proves: "The existing generated quality artifacts match the test corpus after the focused coverage change."
      acceptance_ids: [AC-1, AC-2, AC-3]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_entity_registry.py tests/test_onboarding.py -q"
        proves: "The complete focused registry and onboarding modules preserve persistence, abort safety, retry behavior, idempotent setup, and populated summary behavior around the formatting change."
        acceptance_ids: [AC-1, AC-2, AC-3]
---

## Design Notes

- Keep `EntityRegistry.summary()` as the sole formatter. Build the people line from the count and add the existing name-list suffix only when `self.people` is non-empty.
- Preserve insertion order, the first-eight-name limit, and the ellipsis for more than eight names. Do not special-case output in `run_onboarding()`.
- Add direct formatter assertions in `tests/test_entity_registry.py` for an empty registry, one person, and the existing over-eight boundary so the conditional suffix cannot regress populated output.
- Adapt the existing minimal subprocess onboarding scenario in `tests/test_onboarding.py`: prefix one invalid mode answer before the valid work-mode answer, retain empty people/projects and default wings/scan answers, then assert successful completion and the exact clean people line in stdout.
- The verification commands run from the repository root with the repository Python environment. `pyproject.toml` declares `tests` as the pytest root and excludes `needs_network` and `slow` by default; these focused modules need no package-directory or container prefix.
- If the subprocess assertion fails, reproduce only that contour with `python -m pytest tests/test_onboarding.py::test_malformed_mode_then_minimal_flow_prints_clean_summary -q` before widening investigation.
