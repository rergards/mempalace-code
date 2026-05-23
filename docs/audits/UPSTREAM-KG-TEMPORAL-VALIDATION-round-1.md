slug: UPSTREAM-KG-TEMPORAL-VALIDATION
round: 1
date: 2026-05-23
commit_range: 74aaf23..3241040
findings:
  - id: F-1
    title: "Bulk invalidation helpers bypass temporal validation for ended"
    severity: high
    location: "mempalace_code/knowledge_graph.py:265"
    claim: >
      invalidate_by_source_file(), invalidate_by_predicates(),
      invalidate_arch_by_project_root(), and
      invalidate_legacy_arch_ns_project_for_wing() each set valid_to
      directly from the caller-supplied ended string without routing through
      _parse_temporal(). A natural-language value like "last month" is stored
      verbatim in the database, corrupting the affected rows and violating
      REQ-1 (all KG temporal write inputs must reject invalid strings).
      No test existed that would catch this regression.
    decision: fixed
    fix: >
      Added _parse_temporal(ended) call immediately after the default-date
      fallback in all four bulk helpers. The call raises ValueError before
      the connection is opened or any UPDATE is issued.

  - id: F-2
    title: "Date-only valid_to is falsely exclusive for same-day datetime as_of"
    severity: medium
    location: "mempalace_code/knowledge_graph.py:119"
    claim: >
      _in_window() converted a date-only valid_to to midnight UTC via
      _as_comparable(). A datetime as_of on the same calendar day (e.g.
      as_of="2026-05-10T12:00:00Z") compared as greater than midnight,
      causing cmp > vt to be True and the row to be excluded. This broke
      inclusive end-boundary semantics (INV-3) for any mixed date/datetime
      query pattern on the same calendar day, including the canonical
      valid_from == valid_to single-point window.
      No test existed for this mixed-type boundary condition.
    decision: fixed
    fix: >
      Added _as_comparable_vt() which maps date-only values to 23:59:59 UTC
      (end-of-day) instead of 00:00:00 UTC, encoding "valid through end of
      that calendar day" semantics. _in_window() now uses _as_comparable_vt()
      for the valid_to comparison only; valid_from and _validate_window()
      continue to use _as_comparable() (start-of-day), so equal-endpoint
      windows remain accepted without change.
      Added test_date_only_valid_to_inclusive_for_same_day_datetime_as_of
      covering midnight, midday, 23:59:59, and next-day midnight as_of cases.
      Added test_bulk_invalidation_helpers_reject_invalid_ended covering all
      four bulk helpers with invalid ended strings.

totals:
  fixed: 2
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "Added _parse_temporal(ended) validation in invalidate_by_source_file(), invalidate_by_predicates(), invalidate_arch_by_project_root(), and invalidate_legacy_arch_ns_project_for_wing() before any DB mutation"
  - "Added _as_comparable_vt() helper with end-of-day (23:59:59 UTC) semantics for date-only valid_to; updated _in_window() to use it for the upper-bound comparison"
  - "Added two new test methods: test_date_only_valid_to_inclusive_for_same_day_datetime_as_of and test_bulk_invalidation_helpers_reject_invalid_ended"

new_backlog: []

notes:
  - >
    The row-by-row inverted-window guard (comparing ended against each active
    valid_from before UPDATE) was not added to the bulk helpers. These helpers
    are called from internal mining code with today's date as the default, so
    the practical inversion risk is low. Bulk callers supplying an explicit
    ended that precedes a stored valid_from are now at least guaranteed to
    receive a ValueError if the ended string is malformed. A future task could
    add the pre-check for bulk helpers if the need arises.
