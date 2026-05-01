slug: STORE-SCHEMA-PARTIAL-MIGRATE-TEST
round: 1
date: 2026-05-01
commit_range: 0c612ff..b1bc7aa
findings:
  - id: F-1
    title: "Negative log assertions used substring matching, masking future column-name collisions"
    severity: low
    location: "tests/test_storage.py:869-879"
    claim: "AC-2 verifies the migration log lists only the newly-added columns. The original assertions used `\"hall\" not in log_msg`, `\"language\" not in log_msg`, etc. — bare substring checks. They pass currently because no other field name in `_META_FIELD_SPEC` contains those substrings, but a future field rename (e.g. `language_v2`, `shall_x`) would either silently mask a regression (a re-added `hall` column hidden by an unrelated `shall_x`) or fire a spurious failure. The migration log message uses Python list-repr formatting, so the precise marker for column membership is `'<col>'` (single-quoted) rather than a raw substring."
    decision: fixed
    fix: "Replaced substring checks with list-repr-quoted matches (`f\"'{col}'\" not in log_msg`) and consolidated the three `not in` assertions into a loop over the already-present columns. The check now matches exactly what the migration logger emits, immune to future field-name overlaps."
  - id: F-2
    title: "Positive log assertion required only one absent column to appear (`any` instead of `all`)"
    severity: low
    location: "tests/test_storage.py:876-879"
    claim: "The original assertion `assert any(col in log_msg for col in absent_cols)` would pass even if the migration logged just one of the many absent columns. A regression that mis-reported the cols-to-add list (truncated, deduplicated, partially populated) would slip through the log-content check entirely. The companion AC-3 row-default check would still catch a column-not-actually-added regression, but the AC-2 contract is on the *log message* itself."
    decision: fixed
    fix: "Strengthened to `assert all(...)`: every absent column must appear in the log message. Combined with the F-1 fix (list-repr quoting), this is now a precise, one-to-one match between `_META_FIELD_SPEC` membership and log content."
  - id: F-3
    title: "`PARTIAL_12_COLS` literal duplicates the inline schema definition"
    severity: info
    location: "tests/test_storage.py:843-856"
    claim: "The set of 12 column names is hard-coded twice — once in the `pa.schema(...)` field list and once as the `PARTIAL_12_COLS` literal used to compute `absent_cols`. Could be derived from `partial_schema.names`. Minor DRY."
    decision: dismissed
  - id: F-4
    title: "Test does not cover semantic search recall after partial migration"
    severity: info
    location: "tests/test_storage.py:800"
    claim: "AC-1/2/3 are met, but the pre-existing row's vector is never validated end-to-end via `store.search` after migration — only metadata roundtrip is asserted. A regression that corrupted vector ingestion during `add_columns` would not be caught. Out of scope for this S-sized task; the vector column is unchanged by `add_columns`."
    decision: dismissed
totals:
  fixed: 2
  backlogged: 0
  dismissed: 2
fixes_applied:
  - "Switched negative log-message checks (already-present columns) from raw substring to list-repr-quoted matching, so future field renames cannot create accidental collisions."
  - "Strengthened the absent-column log assertion from `any` to `all`, so every newly-added column must appear in the migration log."
new_backlog: []
