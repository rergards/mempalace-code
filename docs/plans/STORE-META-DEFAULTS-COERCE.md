---
slug: STORE-META-DEFAULTS-COERCE
status: completed
authority: non_authoritative
goal: "Replace hardcoded int/float coercions in _meta_defaults() with a loop over _META_FIELD_SPEC type_tags"
risk: low
risk_note: "Single-function change; no behavior difference for existing fields; covered by existing AC-15 test"
files:
  - path: mempalace/storage.py
    change: "Replace the three hardcoded coercion lines in _meta_defaults() with a loop over _META_FIELD_SPEC that calls int() for 'int32' and float() for 'float32' type_tags"
acceptance:
  - id: AC-1
    when: "_meta_defaults() source is read"
    then: "No field-name literals (chunk_index, compression_ratio, original_tokens) appear in coercion lines; only the _META_FIELD_SPEC loop is present"
  - id: AC-2
    when: "A new ('example_count', 'int32', 0) entry is appended to _META_FIELD_SPEC and _meta_defaults({'example_count': '7'}) is called"
    then: "result['example_count'] is the integer 7 without any change to _meta_defaults()"
  - id: AC-3
    when: "python -m pytest tests/test_storage_lance.py -v is run"
    then: "All tests pass including the existing AC-15 numeric coercion test"
out_of_scope:
  - "Changes to _META_FIELD_SPEC entries or their defaults"
  - "Changes to _META_DEFAULTS, _META_KEYS, or schema generation"
  - "New tests (existing AC-15 covers the coercion behavior)"
  - "ChromaDB backend"
---

## Design Notes

- `_META_FIELD_SPEC` already enumerates every metadata field as `(name, type_tag, default)` where `type_tag` is one of `"string"`, `"int32"`, `"float32"`. The loop mirrors the pattern already used in `_target_drawer_schema()` (line 205).
- The merged dict is populated before the loop runs, so `merged[name]` is always present (default or caller-supplied), making `.get()` with a fallback unnecessary.
- Replacement loop (drop into `_meta_defaults()` after the merge block):
  ```python
  for name, type_tag, _ in _META_FIELD_SPEC:
      if type_tag == "int32":
          merged[name] = int(merged[name])
      elif type_tag == "float32":
          merged[name] = float(merged[name])
  ```
- Only numeric type_tags (`int32`, `float32`) need explicit coercion; strings are left as-is.
- No change to the function signature, return type, or observable output for any currently valid input.
