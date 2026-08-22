---
slug: UPSTREAM-ENTITY-REGISTRY-ATOMIC-SAVE
status: completed
authority: non_authoritative
goal: "Make entity registry saves crash-safe with atomic same-directory replacement."
risk: low
risk_note: "Small isolated persistence change for one JSON registry file, with injectable failure tests around the replace boundary."
files:
  - path: mempalace_code/entity_registry.py
    change: "Replace direct JSON write_text save with temp-file JSON write, flush/fsync, best-effort restrictive chmod, cleanup on failure, and atomic os.replace into the final registry path."
  - path: tests/test_entity_registry.py
    change: "Add focused registry persistence tests for successful loads, pre-replace failures, malformed-load compatibility, and restrictive permissions where supported."
acceptance:
  - id: AC-1
    when: "python -m pytest tests/test_entity_registry.py -k 'save_writes_valid_json_and_loads_existing_data' -q is run"
    then: "a saved registry file parses as JSON and EntityRegistry.load(config_dir=...) returns the saved mode, people, projects, ambiguous_flags, and wiki_cache values."
  - id: AC-2
    when: "python -m pytest tests/test_entity_registry.py -k 'save_failure_before_replace_preserves_existing_registry' -q is run"
    then: "a simulated failure at the atomic replace step raises, leaves the previous entity_registry.json bytes unchanged, and does not leave a partial final registry file."
  - id: AC-3
    when: "python -m pytest tests/test_entity_registry.py -k 'load_malformed_json_still_returns_empty_registry' -q is run"
    then: "EntityRegistry.load(config_dir=...) still returns an empty registry for malformed JSON instead of raising."
  - id: AC-4
    when: "python -m pytest tests/test_entity_registry.py -k 'save_sets_restrictive_permissions_where_supported' -q is run"
    then: "on platforms where chmod/stat mode bits are meaningful, the saved registry has no group/other permissions; unsupported platforms skip or assert only that save succeeds."
out_of_scope:
  - "Changing entity lookup, research, learning, or disambiguation behavior."
  - "Changing the existing malformed JSON load fallback to an exception or backup recovery path."
  - "Introducing a shared atomic-write helper for other files."
  - "Changing onboarding output files such as aaak_entities.md or critical_facts.md."
contract_policy:
  flow: full_spdd
  reason: "Standard reliability task changes persistent user data writes and requires explicit crash-safety behavior."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Entity registry saves must replace the old JSON file atomically after writing and syncing complete JSON to a same-directory temp file."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "Entity registry file permissions must be owner-only where the platform supports chmod/stat mode enforcement."
      source: "backlog acceptance"
      acceptance_ids: [AC-4]
    - id: REQ-3
      statement: "Existing load compatibility must remain unchanged for both valid registry JSON and malformed JSON fallback."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-3]
  surfaces:
    - name: "Entity registry persistence"
      kind: "store"
      paths: ["mempalace_code/entity_registry.py"]
      expected_behavior: "save() creates the parent directory, writes JSON to a temp file in that directory, flushes/fsyncs, applies restrictive permissions best-effort, and atomically replaces entity_registry.json only after the temp write succeeds."
    - name: "Entity registry persistence tests"
      kind: "internal"
      paths: ["tests/test_entity_registry.py"]
      expected_behavior: "focused tests exercise success, pre-replace failure, malformed-load compatibility, and permission behavior without touching the user's real home directory."
  invariants:
    - id: INV-1
      statement: "EntityRegistry.load() must keep returning an empty registry for missing or malformed entity_registry.json."
      applies_to: ["mempalace_code/entity_registry.py"]
    - id: INV-2
      statement: "The registry JSON schema keys and lookup/research/learning semantics must not change."
      applies_to: ["mempalace_code/entity_registry.py"]
    - id: INV-3
      statement: "Tests must use temporary config directories and must not write to the user's real ~/.mempalace."
      applies_to: ["tests/test_entity_registry.py"]
  risks:
    - id: RISK-1
      risk: "A crash or OSError during save could truncate or corrupt the existing registry."
      mitigation: "Write to a same-directory temp file, fsync the file before os.replace, and test a forced replace failure against an existing registry."
    - id: RISK-2
      risk: "Temporary files could remain after failed saves."
      mitigation: "Cleanup the temp file in the exception path and assert no partial final content is exposed."
    - id: RISK-3
      risk: "Permission handling could break on platforms without POSIX mode semantics."
      mitigation: "Use best-effort chmod and make the permission test platform-aware while still requiring restrictive bits where supported."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_entity_registry.py -k 'save_writes_valid_json_and_loads_existing_data' -q"
      proves: "successful atomic-save path emits valid JSON and preserves normal load behavior"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_entity_registry.py -k 'save_failure_before_replace_preserves_existing_registry' -q"
      proves: "failure before rename does not corrupt or truncate the previous registry"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_entity_registry.py -k 'load_malformed_json_still_returns_empty_registry' -q"
      proves: "malformed JSON load fallback stays compatible"
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_entity_registry.py -k 'save_sets_restrictive_permissions_where_supported' -q"
      proves: "saved registry permissions are restrictive where mode bits are meaningful"
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_entity_registry.py -q"
      proves: "all focused entity-registry persistence checks pass together"
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_entity_registry.py -q"
        proves: "registry persistence changes keep valid-load, malformed-load, failure, and permission behavior coherent as a set"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-2
        command: "python -m pytest tests/test_entity_registry.py tests/test_entity_detector.py -q"
        proves: "new registry persistence coverage does not disturb existing entity detection coverage"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- Keep the implementation local to `EntityRegistry.save()` unless a tiny private helper in `entity_registry.py` makes failure cleanup clearer.
- Use a temp file in `self._path.parent`, not the system temp directory, so `os.replace()` stays atomic on the target filesystem.
- Prefer `json.dump(..., indent=2)` or equivalent streamed JSON writing directly into the temp file; avoid constructing partial final-file content.
- After writing the temp file, flush the Python file object and call `os.fsync(file.fileno())` before `os.replace(temp_path, self._path)`.
- Apply `0o600` permissions to the temp file before the replace where supported. Treat `OSError`, `AttributeError`, or permission-mode no-ops as best-effort, not a save failure, unless the write or replace itself failed.
- On any exception before or during replace, attempt to unlink the temp file and re-raise the original exception so callers can see the save failed.
- Do not change `load()` error handling in this task; malformed JSON currently falls back to `_empty()` and the plan preserves that compatibility explicitly.
- In the failure test, create an existing registry, monkeypatch the replace boundary to raise, attempt a second save with different data, then assert the original bytes still parse to the first data.
