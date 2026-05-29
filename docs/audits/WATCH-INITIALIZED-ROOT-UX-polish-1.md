slug: WATCH-INITIALIZED-ROOT-UX
phase: polish
date: 2026-05-29
commit_range: da45f89..HEAD
reverted: false
findings:
  - id: P-1
    title: "Redundant Path roundtrip in test assertion"
    category: volume
    location: "tests/test_watcher.py:1546"
    evidence: "resolved = str(Path(str(project)).resolve())"
    decision: fixed
    fix: "Simplified to str(project.resolve()) — project is already a Path object"
totals:
  fixed: 1
  dismissed: 0
fixes_applied:
  - "Simplified str(Path(str(project)).resolve()) to str(project.resolve()) in test_initialized_root_is_watched_as_single_project"
