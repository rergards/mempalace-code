slug: MINE-MULTI
round: 1
date: 2026-04-18
commit_range: b012c11..HEAD
findings:
  - id: F-1
    title: "Wing name collision with --force silently merges two distinct projects"
    severity: medium
    location: "mempalace/cli.py:214"
    claim: >
      When two projects in the parent directory derive the same wing name,
      the first is mined successfully and added to the in-memory `existing_wings`
      set. Under `--force`, the wing-exists guard is bypassed, so the second
      project is also mined into the same wing — silently merging unrelated
      codebase content. This corrupts the palace without any warning to the user.
    decision: fixed
    fix: >
      Added a pre-loop deduplication pass in `cmd_mine_all` that collects all
      derived wing names before mining begins. If two projects map to the same
      name, the second is skipped with a WARN message printed to stderr
      explaining the collision and how to resolve it (rename folder or configure
      a unique wing in mempalace.yaml). Added `test_mine_all_dedup_wing_names`
      to verify the first project is mined and the second is skipped.

  - id: F-2
    title: "No test verifying --include-ignored is split and forwarded to mine()"
    severity: low
    location: "mempalace/cli.py:237"
    claim: >
      The `--include-ignored` argument undergoes comma-splitting logic before
      being passed to `mine(include_ignored=...)`. This logic is untested: no
      test asserts that `--include-ignored path1,path2` results in
      `mine()` receiving `["path1", "path2"]`. A regression here would silently
      drop user-specified paths from the scan.
    decision: backlogged
    backlog_slug: MINE-MULTI-INCLUDE-IGNORED-TEST

totals:
  fixed: 1
  backlogged: 1
  dismissed: 0

fixes_applied:
  - "Added duplicate wing name detection in cmd_mine_all before the mining loop;
    second project with the same derived wing name is skipped with a WARN message
    and counted as skipped. Added test_mine_all_dedup_wing_names to cover this path."

new_backlog:
  - slug: MINE-MULTI-INCLUDE-IGNORED-TEST
    summary: "Add test verifying --include-ignored comma-splitting and pass-through to mine()"
