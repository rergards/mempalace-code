slug: STORE-BACKUP-CLI-TEST
round: 1
date: 2026-05-01
commit_range: 240acf7..529dc0e
findings:
  - id: F-1
    title: "test_restore_cli_force_flag has a weak post-condition (lance/ already exists)"
    severity: medium
    location: "tests/test_backup_cli.py:96"
    claim: "The original test only asserted os.path.isdir(lance/) after the second --force restore. But lance/ was already created by the prior non-force restore, so the assertion would still pass even if --force silently did nothing (e.g. rmtree+re-extract regressed to a no-op or to a partial extraction that left an empty lance/). The only real signal was the implicit absence of a SystemExit, which catches outright failure but not partial regression."
    decision: fixed
    fix: "After the --force restore, open the LanceStore and assert restored.count() == 4 — a regression where --force fails to re-extract the archived rows now fails the test."
  - id: F-2
    title: "test_restore_cli_happy did not assert the printed metadata block"
    severity: low
    location: "tests/test_backup_cli.py:73"
    claim: "cmd_restore prints 'Restored palace to:', 'Drawers: N', 'Wings: …', 'Backup timestamp: …' when metadata is present in the archive. The test only checked the first line, so a regression that dropped the metadata-display branch (line 1082-1085 of cli.py) would not be caught."
    decision: fixed
    fix: "Added assertions for 'Drawers: 4' and 'Wings: notes, project' in the captured stdout."
  - id: F-3
    title: "Generic exception path of cmd_restore (non-FileExistsError) is untested"
    severity: low
    location: "mempalace_code/cli.py:1077"
    claim: "cmd_restore has two exit-1 branches: FileExistsError (covered by test_restore_cli_error_exit) and the generic 'except Exception' that handles missing or corrupt archives. A regression that drops the second branch — letting tracebacks escape to the terminal instead of producing 'Error: …' on stderr and exit 1 — would not be caught."
    decision: fixed
    fix: "Added test_restore_cli_missing_archive_exits_1: passes a non-existent archive path, asserts SystemExit.code == 1 and 'Error:' on stderr."
  - id: F-4
    title: "Backup-CLI tests did not verify the printed drawer / wing summary"
    severity: low
    location: "tests/test_backup_cli.py:36"
    claim: "cmd_backup_create prints 'Backed up N drawers from M wing(s).' and 'Wings: …' before the 'Archive:' line. The test only verified the Archive: line, so a regression that dropped or re-ordered the summary lines (a real risk since cmd_backup falls through to cmd_backup_create for back-compat) would not be detected."
    decision: fixed
    fix: "Added 'Backed up 4 drawers from 2 wing(s).' and 'Wings: notes, project' assertions to test_backup_cli_default_out, plus the drawer-count assertion to test_backup_cli_explicit_out (the seeded fixture has 4 drawers across project + notes wings)."
  - id: F-5
    title: "Back-compat top-level 'backup --out X' (no verb) is not separately tested"
    severity: info
    location: "tests/test_backup_cli.py"
    claim: "Argparse wires --out at both the backup parser and the backup-create subparser. The no-verb default-out path is tested, and the create-with-out path is tested, but the back-compat 'backup --out X' (top-level --out, no verb) is only implicitly covered by the same fall-through dispatch in cmd_backup."
    decision: dismissed
totals:
  fixed: 4
  backlogged: 0
  dismissed: 1
fixes_applied:
  - "Strengthened test_restore_cli_force_flag: open the restored store and assert count() == 4, so a silent --force regression no longer slips past."
  - "Strengthened test_restore_cli_happy: assert the 'Drawers: 4' and 'Wings: notes, project' metadata-display lines, not just the 'Restored palace to:' header."
  - "Added test_restore_cli_missing_archive_exits_1 to cover the generic exception → exit 1 branch in cmd_restore."
  - "Strengthened test_backup_cli_default_out / test_backup_cli_explicit_out: assert the 'Backed up N drawers from M wing(s).' summary line so the pre-Archive output is verified."
new_backlog: []
