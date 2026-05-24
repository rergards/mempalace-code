slug: MINE-TINY-FILES-SKIP-ON-REHASH
round: 1
date: 2026-05-24
commit_range: 2d57ec9..HEAD
findings:
  - id: F-1
    title: "AC-1 missing: no test for tiny-only project incremental re-mine with zero changes"
    severity: medium
    location: "tests/test_miner.py:4864"
    claim: >
      AC-1 requires: "Run a full mine on a project made only of tiny files, then run an
      incremental mine again without modifying any file → second run reports tiny files as
      skipped/unchanged, no drawers filed, palace remains empty." None of the four existing
      tests cover this exact path. test_mine_tiny_files_incremental_separation uses a mixed
      project (1 normal + 3 tiny) and test_mine_tiny_files_changed_tiny_reprocessed always
      modifies a file before the incremental run. A regression in the sidecar load path
      would go undetected.
    decision: fixed
    fix: >
      Added test_mine_tiny_files_no_change_incremental_skip which creates a tiny-only
      project, runs a full mine, then runs an incremental mine with no file changes and
      asserts files_tiny==3, files_skipped==0, drawers_filed==0, and palace.count()==0.

  - id: F-2
    title: "_save_tiny_hashes write is non-atomic"
    severity: low
    location: "mempalace_code/mining/orchestrator.py:87"
    claim: >
      p.write_text(json.dumps(data)) is a non-atomic write. A process crash mid-write
      corrupts the sidecar JSON. However, _load_tiny_hashes wraps the parse in try/except
      and returns {} on any error, so the degradation is graceful: the next run simply
      re-processes all tiny files as if no sidecar existed.
    decision: dismissed
    fix: ~

  - id: F-3
    title: "Stale tiny-hash entries not cleaned up when limit > 0"
    severity: info
    location: "mempalace_code/mining/orchestrator.py:549"
    claim: >
      The stale-tiny sweep (removing sidecar entries for deleted files) is gated on
      incremental and limit == 0, mirroring the identical gate on the existing_hashes
      stale sweep. Files deleted from disk while mining with limit > 0 keep their
      tiny-hash entry until a full walk runs. This is an accepted limitation shared
      with the drawer-backed stale sweep and is out of scope per the task plan.
    decision: dismissed
    fix: ~

totals:
  fixed: 1
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "Added test_mine_tiny_files_no_change_incremental_skip to cover AC-1 (tiny-only project, no-change incremental re-mine)"

new_backlog: []
