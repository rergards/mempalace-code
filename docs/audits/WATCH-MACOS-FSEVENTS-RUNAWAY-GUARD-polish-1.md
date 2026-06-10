slug: WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD
phase: polish
date: 2026-06-11
commit_range: 2c2716f..2819d8b
reverted: false
findings:
  - id: P-1
    title: "Dead mine_calls capture in TestWatchAllHighChurnPrune"
    category: volume
    location: "tests/test_watcher.py:744"
    evidence: |
      mine_calls = []
      def fake_mine(**kwargs):
          mine_calls.append(kwargs)
          return {}
      # ... (mine_calls never asserted)
    decision: fixed
    fix: >
      Removed mine_calls list and fake_mine function; replaced
      patch(..., side_effect=fake_mine) with patch(..., return_value={}).
      No assertions used mine_calls, so the capture was dead state.
totals:
  fixed: 1
  dismissed: 0
fixes_applied:
  - "Removed dead mine_calls capture variable and fake_mine function in TestWatchAllHighChurnPrune.test_on_save_prunes_skip_dirs_and_warns"
