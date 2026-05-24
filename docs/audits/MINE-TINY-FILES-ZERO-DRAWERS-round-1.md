slug: MINE-TINY-FILES-ZERO-DRAWERS
round: 1
date: 2026-05-24
commit_range: e5c7079..HEAD
findings:
  - id: F-1
    title: "Tautological assertion in incremental-separation test"
    severity: medium
    location: "tests/test_miner.py:4911"
    claim: >
      The assertion `r2["files_skipped"] < r2["files_skipped"] + r2["files_tiny"]`
      simplifies to `0 < r2["files_tiny"]`, which is already guaranteed true by the
      preceding `assert r2["files_tiny"] == 3`. It provides zero regression protection
      against the original bug (tiny files inflating files_skipped); a re-introduction
      of that bug would still pass this assertion while only the files_tiny == 3 check
      would catch it. The comment "Tiny files must NOT inflate files_skipped" is also
      misleading since the assertion does not test that invariant.
    decision: fixed
    fix: >
      Replaced the tautological assertion with `assert r2["files_skipped"] == 1`,
      which directly verifies that only the one unchanged normal file is counted as
      skipped and tiny files do not inflate the count.

  - id: F-2
    title: "files_tiny incremented for all zero-chunk files, not only size-based tiny ones"
    severity: low
    location: "mempalace_code/mining/orchestrator.py:474"
    claim: >
      The label "Files too small to index" and the key name `files_tiny` imply the
      cause is file size. In practice, `if not specs: files_tiny += 1` fires for any
      file that yields zero chunks — including files composed entirely of blank lines
      or comments, or any future chunker edge cases. The user-facing message could be
      misleading if someone sees it for a non-tiny file.
    decision: dismissed
    fix: ~

  - id: F-3
    title: "Incremental re-mine calls delete_by_source_file for tiny files on every run"
    severity: low
    location: "mempalace_code/mining/orchestrator.py:438"
    claim: >
      When a tiny file is re-encountered in incremental mode, its hash is absent from
      existing_hashes (nothing was stored on the first pass), so the code falls through
      to the delete+rechunk path. `collection.delete_by_source_file` is called even
      though there is nothing to delete, and the file is re-chunked only to yield zero
      specs again. For a project with many tiny files this adds unnecessary delete calls
      on every incremental mine.
    decision: backlogged
    backlog_slug: MINE-TINY-FILES-SKIP-ON-REHASH

totals:
  fixed: 1
  backlogged: 1
  dismissed: 1

fixes_applied:
  - "tests/test_miner.py: replaced tautological `files_skipped < files_skipped + files_tiny` assertion with `files_skipped == 1` to directly guard against tiny files inflating the skipped count"

new_backlog:
  - slug: MINE-TINY-FILES-SKIP-ON-REHASH
    summary: "Skip re-processing tiny files on incremental mine when content is unchanged"
