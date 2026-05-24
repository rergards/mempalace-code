slug: CLI-BACKUP-PARENT-OUT-IGNORED
round: 1
date: 2026-05-24
commit_range: d320804..a2f3248
findings:
  - id: F-1
    title: "Duplicate AC label in test docstrings — two tests claim AC-1"
    severity: low
    location: "tests/test_backup_cli.py:37"
    claim: >
      test_backup_cli_default_out carried an "AC-1" docstring label from before the
      plan was written. After the implementation added test_backup_parent_out_compat
      (which correctly tests plan AC-1), both tests claimed "AC-1" while covering
      different acceptance criteria. Future readers diffing against the plan contract
      would be confused about which test covers which requirement.
    decision: fixed
    fix: "Updated test_backup_cli_default_out docstring to reference AC-3 (the correct plan AC ID for the no-verb, no-out path)."

  - id: F-2
    title: "Missing regression test for 'backup create' (verb, no --out) after SUPPRESS change"
    severity: low
    location: "tests/test_backup_cli.py"
    claim: >
      Changing p_backup_create's --out default from None to argparse.SUPPRESS is
      correct: when --out is not provided to the subparser, SUPPRESS leaves
      args.out untouched (inheriting the parent's None default). But no explicit
      test exercised 'backup create' (with the verb, without --out) after this
      change, leaving a regression gap for that dispatch path.
    decision: fixed
    fix: "Added test_backup_create_default_out, which runs 'backup create' (no --out) and asserts the archive lands in <palace_parent>/backups/."

totals:
  fixed: 2
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "Updated test_backup_cli_default_out docstring from AC-1 to AC-3 to match plan contract."
  - "Added test_backup_create_default_out to regression-guard 'backup create' (no --out) path after argparse.SUPPRESS change."

new_backlog: []
