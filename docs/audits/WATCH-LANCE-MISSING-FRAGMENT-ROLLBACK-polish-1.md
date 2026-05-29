slug: WATCH-LANCE-MISSING-FRAGMENT-ROLLBACK
phase: polish
date: 2026-05-29
commit_range: 699c49c..HEAD
reverted: false
findings:
  - id: P-1
    title: "Test comment restates method name, docstring, and assertion"
    category: verbal
    location: "tests/test_watcher.py:1503"
    evidence: >
      `# Palace path with spaces must be shell-quoted in recovery commands`
      appeared immediately before `assert shlex.quote(str(palace)) in all_output`.
      The test method is named `test_recovery_commands_quote_paths_with_spaces` and
      its docstring says "Palace or archive paths containing spaces are shell-quoted
      in recovery output." — the comment added no information.
    decision: fixed
    fix: "Removed the redundant comment line."

  - id: P-2
    title: "_is_mine_missing_fragment docstring paragraph duplicates internal comment"
    category: verbal
    location: "mempalace_code/watcher.py:462"
    evidence: >
      Docstring: "Excludes Python FileNotFoundError raised for paths outside the
      palace's lance directory — those come from source files the miner tried to
      read, not from Lance internals."
      Internal comment: "# A Python FileNotFoundError whose filename is outside
      <palace>/lance/ is a source-file read failure, not a Lance fragment error —
      don't roll back the palace."
      Both describe the same exclusion rule.
    decision: dismissed
    reason: >
      The docstring serves callers scanning the function's contract; the inline
      comment serves readers of the implementation where the isinstance guard lives.
      The two framings are complementary (docstring: what is excluded; comment: why
      the consequence is "don't roll back"). Not worth churning.

totals:
  fixed: 1
  dismissed: 1
fixes_applied:
  - "P-1: removed redundant comment at tests/test_watcher.py:1503"
