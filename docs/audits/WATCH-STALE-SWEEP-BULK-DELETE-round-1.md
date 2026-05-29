slug: WATCH-STALE-SWEEP-BULK-DELETE
round: 1
date: 2026-05-29
commit_range: 4e10c96..fe37ecd
findings:
  - id: F-1
    title: "chr(39) obfuscation inconsistent with adjacent quote-escaping style"
    severity: low
    location: "mempalace_code/storage.py:720"
    claim: >
      The IN-predicate item escaping used `p.replace(chr(39), chr(39) * 2)` while the
      adjacent wing escaping on the next line uses `wing.replace("'", "''")`. Both produce
      identical output but the chr() form is harder to read at a glance. A future reader
      editing the predicate might not immediately see they are the same operation and could
      introduce an inconsistency.
    decision: fixed
    fix: "Replaced `chr(39)` form with `\"'\" + p.replace(\"'\", \"''\") + \"'\"`  for consistency with the wing escaping pattern directly above it."

  - id: F-2
    title: "source_files parameter missing Iterable[str] type annotation"
    severity: info
    location: "mempalace_code/storage.py:166,700"
    claim: >
      Both the DrawerStore base class and LanceStore override declare `source_files`
      without a type annotation. Callers pass a set[str]; the implementation handles any
      iterable. Pyright (with correct pythonpath) raises no error, so there is no runtime
      or type-checking impact, but adding `Iterable[str]` would match the style of the
      rest of the public API.
    decision: dismissed

  - id: F-3
    title: "TOCTOU between count_rows and table.delete"
    severity: info
    location: "mempalace_code/storage.py:722-726"
    claim: >
      count_rows is used to gate the table.delete call and to accumulate the return value.
      Under concurrent writes the row count could change between these two calls, causing
      the returned count to diverge from the actual deleted-row count. This is a pre-existing
      pattern (identical to delete_by_source_file) and the local LanceDB model assumes a
      single writer; no race has been reported in practice.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "storage.py: replaced chr(39) with plain string literal in IN-predicate source_file escaping for consistency"

new_backlog: []
