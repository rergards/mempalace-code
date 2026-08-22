---
slug: SPLIT-NAME-DETECTION-OPT-IN
status: completed
authority: non_authoritative
goal: "Make split transcript person detection require explicit known-names configuration."
risk: low
risk_note: "The behavior change is confined to the split module's absent-config default and is covered by focused loader, extraction, output, and safety tests."
files:
  - path: mempalace_code/split_mega_files.py
    change: "Remove the generic fallback-name behavior so unavailable known-names configuration resolves to no configured people while preserving list and mapping inputs."
  - path: tests/test_split_mega_files.py
    change: "Replace fallback expectations with absent-config opt-in coverage and retain configured-name, username-map, split-output, and non-regular-target regression coverage."
acceptance:
  - id: AC-1
    when: "split person loading and extraction run with known_names.json absent against transcript text containing representative former fallback names"
    then: "the loader returns an empty list and extraction reports no people from those names"
  - id: AC-2
    when: "split person loading and extraction run with list-form names or dict-form names and username_map configuration"
    then: "the loader and extraction return exactly the explicitly configured names and mapped username values"
  - id: AC-3
    when: "split output tests exercise regular output plus FIFO, symlink, hardlink, directory, and partial-write refusal paths"
    then: "regular chunks retain their filename and content contract, while non-regular targets fail closed and source preservation behavior remains unchanged"
  - id: AC-4
    when: "the focused split tests and the configured non-network repository suite are executed"
    then: "both commands exit successfully with the opt-in behavior and existing split regressions covered"
out_of_scope:
  - "Changing person detection in entity_registry.py, entity_detector.py, general extraction, or other non-split consumers."
  - "Changing the known_names.json schema, path, caching contract, configured list semantics, or username_map semantics."
  - "Changing split naming, chunk contents, source backup behavior, or regular-file safety protections."
  - "Editing backlog metadata, release bookkeeping, or runner-owned finalization artifacts."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release correctness work changes a filename-classification default at a safety-sensitive split boundary."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Absent known-names configuration must produce no configured people and no common-name matches."
      source: "AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "List-form names and dict-form names plus username_map must retain their explicit configuration behavior."
      source: "AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Split output contracts and all current non-regular-file refusal protections must remain unchanged."
      source: "AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Focused split coverage and the configured non-network suite must both validate the completed change."
      source: "AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "split known-names loader"
      kind: internal
      paths: ["mempalace_code/split_mega_files.py"]
      expected_behavior: "Returns no people when optional configuration is unavailable and otherwise preserves explicitly configured names and username mappings used by split filenames."
    - name: "split behavior tests"
      kind: internal
      paths: ["tests/test_split_mega_files.py"]
      expected_behavior: "Proves absent-config opt-in behavior, configured inputs, filename output, and fail-closed non-regular output handling."
  invariants:
    - id: INV-1
      statement: "List-form known_names.json remains a names list, and dict-form names and username_map retain their existing meanings."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py"]
    - id: INV-2
      statement: "Sessions without detected people continue to use the existing unknown filename component."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py"]
    - id: INV-3
      statement: "FIFO, symlink, hardlink, directory, descriptor, partial-write, and source-preservation guards remain fail-closed."
      applies_to: ["mempalace_code/split_mega_files.py", "tests/test_split_mega_files.py"]
  risks:
    - id: RISK-1
      risk: "A stale module-level KNOWN_PEOPLE value could make a test appear to cover absent configuration without exercising extraction behavior."
      mitigation: "Set extraction's effective known-people value from the absent-config loader result in the focused test and assert both the empty loader result and empty extraction result."
    - id: RISK-2
      risk: "Removing the fallback could accidentally disturb dict-form username mappings or explicit list names."
      mitigation: "Retain and tighten the existing list, dict, username-map, and content-extraction assertions around exact configured values."
    - id: RISK-3
      risk: "Editing the split module could regress output naming or the recently hardened non-regular-target boundary."
      mitigation: "Keep the production edit within the known-name default and run the focused split/source-guard check plus the configured suite."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_split_mega_files.py tests/test_regular_source_guard.py -q"
      proves: "Focused behavior covers absent configuration, explicit list and mapping inputs, unknown-name output, regular split output, and non-regular source and target failure paths."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The exact configured non-network suite remains green after the split person-detection behavior change."
        acceptance_ids: [AC-3, AC-4]
---

## Design Notes

- Keep `_load_known_names_config()` as the single config reader and cache owner. Change only the no-config result consumed by `_load_known_people()` from the generic built-in list to a fresh empty list; remove the unused fallback constant and update stale comments and docstrings.
- Treat missing, unreadable, non-regular, and malformed configuration as unavailable configuration for person-list loading. The existing loader already collapses these cases to `None`; the safe opt-in result is an empty people list and an empty username map.
- Preserve list-form JSON as the direct people list. Preserve dict-form `names` and `username_map` independently, including a mapping-only dict that can still identify a configured username without populating content-name matching.
- `KNOWN_PEOPLE` remains initialized from `_load_known_people()` at module import. Focused tests that redirect `_KNOWN_NAMES_PATH` must explicitly set the effective `KNOWN_PEOPLE` value when asserting `extract_people()` so the test cannot pass through stale import-time state.
- Strengthen the absent-config test with at least two representative former fallback names in ordinary transcript prose and assert no person extraction. Retain exact assertions for configured list names, dict names, and username mapping.
- Do not alter `extract_people()` scanning limits, regex matching, sorting, the three-person filename cap, or the `unknown` filename component used when no person is detected.
- Preserve every existing split-output test in `tests/test_split_mega_files.py`; they are the regression boundary for output contents, dry-run behavior, FIFOs, symlinks, hardlinks, directories, descriptor validation, partial writes, and source backup preservation.
- Command context basis: `pyproject.toml` declares pytest and test discovery under `tests`; `CLAUDE.md` defines the exact non-network full-suite command. The focused provider command adds `tests/test_regular_source_guard.py` because the backlog explicitly retains source-side non-regular-file protections, while the configured runner owns the broad suite.
