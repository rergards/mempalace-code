slug: CLI-EXPORT-STDOUT-CLEAN
round: 1
date: 2026-05-24
commit_range: d93c3ee..HEAD
findings:
  - id: F-1
    title: "Pipe test only asserts 'no crash', not actual drawer count"
    severity: medium
    location: "tests/test_cli.py:2152"
    claim: >
      test_export_stdout_pipe_to_import_dry_run called import main() and checked for no
      exception but never asserted that import counted the expected 1 drawer. A regression
      that made export produce valid-but-empty JSONL (header only, no drawer records) would
      have passed this test silently.
    decision: fixed
    fix: >
      Added `import_captured = capsys.readouterr()` after the import main() call and
      asserted `"Imported drawers:   1" in import_captured.out` to confirm the drawer
      actually traversed the full export → import pipeline.

totals:
  fixed: 1
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "tests/test_cli.py: strengthen test_export_stdout_pipe_to_import_dry_run to assert import counted 1 drawer"

new_backlog: []
