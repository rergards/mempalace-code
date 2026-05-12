slug: GRAPH-TYPED-PAYLOADS
round: 1
date: 2026-05-12
commit_range: 0da5a25..HEAD
findings:
  - id: F-1
    title: "build_graph() docstring describes sets, not lists"
    severity: low
    location: "mempalace_code/palace_graph.py:44"
    claim: >
      The Returns docstring said "wings: set, halls: set" but the public payload
      has been sorted lists since the implementation. Misleads readers about the
      actual return shape; the missing `dates` field was also undocumented.
    decision: fixed
    fix: "Updated docstring to list[str] for wings/halls/dates and added the count/dates fields."

  - id: F-2
    title: "test_dates_limited_to_five_most_recent only asserts length, not which 5"
    severity: medium
    location: "tests/test_palace_graph.py:139"
    claim: >
      The test checked `len == 5` but not WHICH 5 dates were kept.  A regression
      that changed `sorted(...)[-5:]` to `sorted(...)[:5]` would keep the 5 oldest
      instead of the 5 most recent and still pass the test.
    decision: fixed
    fix: "Replaced the length-only assertion with an exact list comparison of the expected 5 most-recent ISO date strings."

  - id: F-3
    title: "traverse() has no test verifying rooms beyond max_hops are excluded"
    severity: low
    location: "tests/test_palace_graph.py:151"
    claim: >
      The existing traverse tests verified hop-0 shape and that connected rooms
      appear, but no test asserted that rooms only reachable at hop N+1 are absent
      when max_hops=N.  A BFS depth-off-by-one would not be caught.
    decision: fixed
    fix: "Added test_traverse_respects_max_hops: with max_hops=1 starting at 'backend', asserts 'architecture' (hop 1) is included and 'frontend' (hop 2) is excluded."

totals:
  fixed: 3
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "Fixed build_graph() docstring: wings/halls/dates all documented as list[str]."
  - "Strengthened test_dates_limited_to_five_most_recent to assert exact 5 most-recent values."
  - "Added test_traverse_respects_max_hops verifying BFS depth boundary."

new_backlog: []
