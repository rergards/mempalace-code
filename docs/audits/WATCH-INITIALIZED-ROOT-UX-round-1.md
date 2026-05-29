slug: WATCH-INITIALIZED-ROOT-UX
round: 1
date: 2026-05-29
commit_range: 7d43465..HEAD
findings:
  - id: F-1
    title: "AC-1 watch-path assertion uses substring check instead of exact list membership"
    severity: low
    location: "tests/test_watcher.py:1546"
    claim: |
      `assert any(str(project) in p for p in watch_paths_seen)` checks whether any element of
      watch_paths_seen *contains* str(project) as a substring, rather than whether str(project) is an
      exact member of the list. A longer path that includes the project path (e.g. a git subdirectory)
      would satisfy the assertion even if the wrong path was passed to watchfiles. The intent is to
      confirm that watchfiles is monitoring precisely the project root.
    decision: fixed
    fix: "Changed assertion to `resolved = str(Path(str(project)).resolve()); assert resolved in watch_paths_seen` — uses exact list membership against the resolved project path, matching the value that watch_all passes to watchfiles."

  - id: F-2
    title: "_classify_watch_root has no direct unit tests for edge cases"
    severity: info
    location: "mempalace_code/watcher.py:576"
    claim: |
      `_classify_watch_root` is tested indirectly through TestWatchAllInitializedRoot but has no
      direct unit tests. Edge cases that are not covered: a directory with only glob-pattern markers
      (e.g. *.sln), an empty directory, and a directory that raises OSError (permission denied). The
      OSError fallback returns "parent", which causes watch_all to proceed to detect_projects — this
      is acceptable behavior but is untested.
    decision: dismissed

  - id: F-3
    title: "No test for on_commit=True (default) with initialized root"
    severity: info
    location: "tests/test_watcher.py:1515"
    claim: |
      All four new TestWatchAllInitializedRoot tests use on_commit=False. The default is on_commit=True,
      which switches watchfiles to monitor .git/refs/heads/ instead of the project root. The code path
      for on_commit=True with an initialized root is structurally identical to the parent-directory case
      (project_map is built the same way; _resolve_git_watch_paths operates identically). REG-1 regression
      tests cover this code path for the parent-directory setup.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "Strengthened AC-1 watch-path assertion from substring check to exact list membership using resolved path (tests/test_watcher.py:1546)"

new_backlog: []
