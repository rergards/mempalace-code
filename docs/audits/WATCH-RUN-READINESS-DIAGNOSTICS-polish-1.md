slug: WATCH-RUN-READINESS-DIAGNOSTICS
phase: polish
date: 2026-06-16
commit_range: 85af2c7..HEAD
reverted: false
findings:
  - id: P-1
    title: "Single-use `now` temporary in `_make_run_id`"
    category: volume
    location: "mempalace_code/watcher.py:211"
    evidence: |
      now = datetime.now(UTC)
      return f"{now.strftime('%Y%m%dT%H%M%SZ')}-p{os.getpid()}"
    decision: fixed
    fix: "Inlined datetime.now(UTC) directly into the f-string, removing the needless one-use binding."
  - id: P-2
    title: "Inline comment restates the loop purpose in AC-3 test"
    category: verbal
    location: "tests/test_watcher.py"
    evidence: "# Locate the latest watch-ready line and extract its run_id"
    decision: dismissed
    reason: "Test code carries more explanatory latitude; the comment maps directly to the AC-3 acceptance criterion name and aids comprehension without full code tracing."
totals:
  fixed: 1
  dismissed: 1
fixes_applied:
  - "Removed single-use `now` temp in `_make_run_id`; inlined datetime.now(UTC) into return f-string."
