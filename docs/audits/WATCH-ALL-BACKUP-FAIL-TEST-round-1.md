slug: WATCH-ALL-BACKUP-FAIL-TEST
round: 1
date: 2026-06-19
commit_range: b63c3c3..aa5e788
findings:
  - id: F-1
    title: "Docstrings in renamed and new tests exceed 100-char line limit"
    severity: low
    location: "tests/test_watcher.py:2015,2116"
    claim: >
      Two docstrings introduced by this PR violated the project's 100-character line limit
      (E501): the renamed watch_and_mine test docstring was 117 chars and the new watch_all
      test docstring was 124 chars. Ruff check fails on these lines.
    decision: fixed
    fix: "Shortened both docstrings to under 100 chars while preserving the AC reference and key facts."
  - id: F-2
    title: "watch_loop and mine assertions are vacuously true given sys.exit(1) ordering"
    severity: info
    location: "tests/test_watcher.py:2146-2147"
    claim: >
      The assertions `mock_mine.assert_not_called()` and `assert not watch_entered` both
      pass trivially because sys.exit(1) is called at watcher.py:792 before either mine or
      watchfiles.watch is ever reached. They provide no regression protection beyond the
      `pytest.raises(SystemExit)` assertion already present. The sentinel pattern is still
      correct if the production ordering ever changes, so the assertions are harmless but
      not exercising a distinct code path.
    decision: dismissed
totals:
  fixed: 1
  backlogged: 0
  dismissed: 1
fixes_applied:
  - "Shortened two E501-violating docstrings in tests/test_watcher.py (lines 2015 and 2116) to stay within the 100-char line limit."
new_backlog: []
