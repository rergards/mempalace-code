slug: MINE-WATCH-GITIGNORE-CACHE
round: 1
date: 2026-04-19
commit_range: c4e36c2..HEAD (staged)
findings:
  - id: F-1
    title: "Double Path construction per .gitignore event in _invalidate_gitignore_cache"
    severity: info
    location: "mempalace/watcher.py:37-39"
    claim: >
      The loop body calls Path(path) twice — once for the .name check and once to
      compute .parent. A single local p = Path(path) would avoid the redundant object
      construction. Performance impact is negligible (only .gitignore events, which
      are rare), and the code is readable as-is.
    decision: dismissed

  - id: F-2
    title: "_invalidate_gitignore_cache called unconditionally when respect_gitignore=False"
    severity: info
    location: "mempalace/watcher.py:192"
    claim: >
      watch_and_mine() calls _invalidate_gitignore_cache() on every event batch
      regardless of the respect_gitignore flag. When respect_gitignore=False the
      matcher_cache is never populated by _is_relevant_change (the gitignore block
      is guarded by `if respect_gitignore`), so every eviction call is a guaranteed
      no-op iteration over the batch. Adding a `if respect_gitignore:` guard at the
      call site would skip the loop, but the overhead is O(batch_size) Path
      constructions — negligible in practice. Adding the guard would also couple the
      call site to an internal invariant of _is_relevant_change.
    decision: dismissed

  - id: F-3
    title: "No watch_and_mine integration test exercising eviction in the watch loop"
    severity: info
    location: "tests/test_watcher.py"
    claim: >
      TestInvalidateGitignoreCache provides thorough unit coverage of the helper
      function (5 cases: modified/added/deleted .gitignore, non-.gitignore event,
      absent key). TestWatchAndMine exercises the broader watch loop but no test
      sends a batch containing both a .gitignore event and an affected file to verify
      that freshly loaded matcher state is used for the same-batch file. Adding such
      a test would require pre-populating a real .gitignore on disk and constructing
      a pre-populated matcher_cache — meaningful complexity for a case already fully
      covered by the unit tests at the function boundary.
    decision: dismissed

totals:
  fixed: 0
  backlogged: 0
  dismissed: 3

fixes_applied: []

new_backlog: []
