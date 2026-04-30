slug: CODE-LANGUAGE-CATALOG-FRESH-PR4
round: 1
date: "2026-04-30"
commit_range: 6d047aa..HEAD
findings:
  - id: F-1
    title: "Invalid-language test did not prove storage is skipped"
    severity: low
    location: "tests/test_searcher.py:145"
    claim: >
      test_code_search_invalid_language_matches_catalog used the palace_path fixture even
      though unsupported-language validation should return before opening storage. A
      regression that opened the palace before returning the catalog error could still pass
      against a valid fixture, weakening coverage of the validation order.
    decision: fixed
    fix: >
      Replaced the fixture dependency with a monkeypatched open_store that fails if called,
      then invoked code_search with an unused palace path and asserted the exact catalog
      error response.
  - id: F-2
    title: "Catalog set drift invariants were not tested"
    severity: low
    location: "tests/test_language_catalog.py:84"
    claim: >
      The catalog keeps extension detection, miner-readable extensions, detected labels,
      and searchable labels as separate sets. Existing tests checked specific labels but
      did not catch drift where a new extension could be detectable but not mined, or a
      searchable label could become unreachable from detection.
    decision: fixed
    fix: >
      Added a catalog invariant test asserting extension keys match readable extensions and
      searchable languages are included in detected languages.
totals:
  fixed: 2
  backlogged: 0
  dismissed: 0
fixes_applied:
  - "Strengthened invalid-language code_search coverage to assert validation happens before storage access."
  - "Added catalog invariant coverage for extension/readable and searchable/detected set drift."
new_backlog: []
