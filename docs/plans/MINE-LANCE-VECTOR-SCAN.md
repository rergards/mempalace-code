---
slug: MINE-LANCE-VECTOR-SCAN
goal: "Make LanceStore metadata scans project required columns before reading table data."
risk: low
risk_note: "Small storage read-path change limited to metadata-only aggregation methods, with behavior-preserving tests."
files:
  - path: mempalace/storage.py
    change: "Replace post-read to_arrow().select(...) metadata scans with a scan-time projected LanceDB scanner helper for source-file and count aggregations."
  - path: tests/test_storage.py
    change: "Add focused tests proving metadata scan methods request only required columns and preserve empty/missing-column behavior."
acceptance:
  - id: AC-1
    when: "a fake Lance table records scanner(columns=...) calls and get_source_files('alpha') is invoked"
    then: "the recorded projection is exactly ['source_file', 'wing'] and the returned set excludes non-alpha rows"
  - id: AC-2
    when: "a fake Lance table raises if to_arrow() is called directly and get_source_file_hashes('alpha') is invoked"
    then: "the method returns the first hash per source_file using projection ['source_file', 'source_hash', 'wing']"
  - id: AC-3
    when: "count_by('wing') and count_by_pair('wing', 'room') run against a fake table that rejects direct to_arrow() access"
    then: "each method returns the existing aggregate shape while scanner(columns=...) receives only the requested grouping columns"
  - id: AC-4
    when: "get_source_file_hashes('alpha') runs against a table whose projected scan raises because source_hash is absent"
    then: "the method returns {} without propagating the storage exception"
out_of_scope:
  - "Changing vector search, add/upsert, or embedding behavior."
  - "Changing health_check() or recover_to_last_working_version(); that is covered by HEALTH-SCAN-PROJECTION."
  - "Adding a large benchmark or profiler harness in this small fix."
---

## Design Notes

- Add a small LanceStore-local helper such as `_scan_columns(columns)` that calls `self._table.scanner(columns=columns).to_table()`.
- Keep the helper private and minimal so the affected methods share one projection mechanism without changing the public store interface.
- Update `get_source_files()`, `get_source_file_hashes()`, `count_by()`, and `count_by_pair()` to use the helper before filtering or grouping.
- Preserve current failure behavior: `get_source_file_hashes()` still returns `{}` when `source_hash` is unavailable, and empty tables continue returning empty set/dict values.
- Use lightweight fake table/scanner objects in tests so assertions verify scan-time projection directly and do not require profiling a large LanceDB table.
- Leave `iter_all()`, `health_check()`, and recovery probes untouched in this task because they have different semantics and separate backlog coverage.
