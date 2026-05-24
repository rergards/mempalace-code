slug: MCP-DELETE-NO-EMBEDDER-AFTER-READ
round: 1
date: 2026-05-24
commit_range: 1fc42ae..a3499ea
findings:
  - id: F-1
    title: "_ARROW_TYPES dict duplicated in _target_drawer_schema and _open_or_create migration block"
    severity: low
    location: "mempalace_code/storage.py:282,441"
    claim: >
      The identical dict {"string": pa.string(), "int32": pa.int32(), "float32": pa.float32()}
      was defined in two places: inside _target_drawer_schema() and inline inside the migration
      block of _open_or_create(). If a contributor adds a new type tag to _META_FIELD_SPEC and
      updates only one location, the other silently fails with a KeyError during schema migration
      or creation. The docstring on _target_drawer_schema also incorrectly claimed it was used by
      the migrate-existing path (it no longer was after this implementation).
    decision: fixed
    fix: >
      Extracted a module-level helper function _meta_arrow_types() that both callers now use.
      Updated _target_drawer_schema docstring to clarify it is create-only; migration path uses
      _META_FIELD_SPEC directly.

  - id: F-2
    title: "MCP subprocess result.returncode not asserted in _run_mcp_stdio tests"
    severity: low
    location: "tests/test_mcp_server.py:3430"
    claim: >
      _run_mcp_stdio calls subprocess.run but does not check result.returncode. A server crash
      after emitting partial responses would not trigger an explicit failure on the exit code.
      The len(responses) == 4 assertion in each test provides strong implicit coverage because a
      crashed server would deliver fewer responses, but the root cause would be mis-reported as
      a response count mismatch rather than a process failure.
    decision: dismissed
    fix: ~

  - id: F-3
    title: "drawers_before >= 1 is a weak lower-bound assertion in offline MCP tests"
    severity: info
    location: "tests/test_mcp_server.py:3504,3569"
    claim: >
      The offline delete-drawer and delete-wing tests assert drawers_before >= 1 rather than
      == 4 (the exact count seeded by the fixture). The delta assertion (status_after ==
      drawers_before - 1 / drawers_before - deleted_count) provides correct behavioral coverage,
      so this is an observation only.
    decision: dismissed
    fix: ~

totals:
  fixed: 1
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "Extracted _meta_arrow_types() helper to deduplicate _ARROW_TYPES dict from _target_drawer_schema and _open_or_create migration block; updated _target_drawer_schema docstring"

new_backlog: []
