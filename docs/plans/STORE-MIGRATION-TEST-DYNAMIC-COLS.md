---
slug: STORE-MIGRATION-TEST-DYNAMIC-COLS
status: completed
authority: non_authoritative
goal: "Replace hardcoded new_string_cols list in test_migration_existing_rows_get_empty_defaults with a derivation from _META_FIELD_SPEC"
risk: low
risk_note: "Single-line test change; no production code touched; _META_FIELD_SPEC already imported in the test module"
files:
  - path: tests/test_storage.py
    change: "Replace hardcoded 13-element new_string_cols list with OLD_9_COLS set + list comprehension over _META_FIELD_SPEC"
acceptance:
  - id: AC-1
    when: "test_migration_existing_rows_get_empty_defaults runs"
    then: "new_string_cols is derived dynamically and all 13 current string columns are still asserted"
  - id: AC-2
    when: "a new string field is appended to _META_FIELD_SPEC"
    then: "the test automatically asserts that field's migration default is empty-string without any test-code change"
  - id: AC-3
    when: "a non-string field (int32/float32) is in _META_FIELD_SPEC but not in OLD_9_COLS"
    then: "it is correctly excluded from new_string_cols (type_tag filter guards this)"
out_of_scope:
  - "Changes to storage.py or _META_FIELD_SPEC itself"
  - "Assertion of numeric column defaults (compression_ratio, original_tokens, chunk_index)"
  - "Any other test functions"
---

## Design Notes

- `_META_FIELD_SPEC` is already imported at `tests/test_storage.py:14` — no import change required.
- `OLD_9_COLS` must list every field present in the old 9-column schema used by the test's `old_schema` fixture (lines 405-416): `id`, `text`, `vector`, `wing`, `room`, `source_file`, `chunk_index`, `added_by`, `filed_at`. None of these are in `_META_FIELD_SPEC` (the first three are LanceDB-native, not metadata fields), but including them in `OLD_9_COLS` is harmless and documents intent clearly.
- The derivation:
  ```python
  OLD_9_COLS = {"id", "text", "vector", "wing", "room", "source_file", "chunk_index", "added_by", "filed_at"}
  new_string_cols = [name for name, type_tag, _ in _META_FIELD_SPEC if type_tag == "string" and name not in OLD_9_COLS]
  ```
  This produces the same 13 names as the hardcoded list today (hall, topic, type, agent, date, ingest_mode, extract_mode, language, symbol_name, symbol_type, source_hash, extractor_version, chunker_strategy). Verified by cross-checking `_META_FIELD_SPEC` at `storage.py:156-185`.
- The `for col in new_string_cols` assertion loop on line 456 is unchanged — only the list construction above it changes.
- `OLD_9_COLS` should be defined as a local variable inside the test method, not at module scope, to keep it co-located with the test context it documents.
