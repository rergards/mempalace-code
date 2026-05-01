---
slug: STORE-BACKUP-CLI-TEST
goal: "Add focused CLI dispatch tests for backup and restore commands"
risk: low
risk_note: "Test-only plan for existing backup/restore CLI paths; no production behavior changes intended."
files:
  - path: tests/test_backup_cli.py
    change: "Add focused pytest coverage for backup and restore CLI dispatch via main() argv patching, including default output, explicit output, restore success, --force overwrite, and non-force exit handling."
acceptance:
  - id: AC-1
    when: "`mempalace-code --palace <seeded_palace> backup` is invoked without a subcommand or --out"
    then: "stdout contains exactly one `Archive: <path>` line, `<path>` exists, ends with `.tar.gz`, and is under `<palace_parent>/backups/`."
  - id: AC-2
    when: "`mempalace-code --palace <seeded_palace> backup create --out <tmp>/explicit.tar.gz` is invoked"
    then: "`<tmp>/explicit.tar.gz` exists and stdout's `Archive:` line displays that exact path."
  - id: AC-3
    when: "`mempalace-code --palace <empty_restore_palace> restore <archive>` is invoked with an archive made from a seeded palace"
    then: "`<empty_restore_palace>/lance` exists and stdout contains `Restored palace to:` plus restored drawer metadata."
  - id: AC-4
    when: "`mempalace-code --palace <non_empty_restore_palace> restore <archive> --force` is invoked"
    then: "the command completes without `SystemExit` and `<non_empty_restore_palace>/lance` remains present after overwrite."
  - id: AC-5
    when: "`mempalace-code --palace <non_empty_restore_palace> restore <archive>` is invoked without --force"
    then: "the command raises `SystemExit` with code 1 and stderr contains `Use --force`."
out_of_scope:
  - "Production changes to mempalace_code/cli.py or mempalace_code/backup.py."
  - "Additional backup list or backup schedule coverage; existing tests already cover those subcommands."
  - "Changing the current default backup location from `<palace_parent>/backups/`."
  - "Testing custom knowledge-graph restore paths; cmd_restore uses the default KG location."
---

## Design Notes

- Put the coverage in a new `tests/test_backup_cli.py` module so backup/restore CLI dispatch tests stay focused and do not further expand the already broad `tests/test_cli.py`.
- Drive the CLI through `mempalace_code.cli.main()` with `patch.object(sys, "argv", ...)`. This covers argparse wiring, command-table dispatch to `cmd_backup` / `cmd_restore`, printed output, and `sys.exit(1)` behavior.
- Reuse the deterministic test storage path from existing tests: seed a temporary palace with `open_store(..., create=True).add(...)` and keep all paths under `tmp_path`.
- Parse the `Archive:` stdout line rather than predicting the timestamped filename. Assert the parsed path exists and has the expected directory/suffix.
- The backlog text mentions CWD for the default backup archive, but current `create_backup()` behavior and `tests/test_backup.py::test_backup_default_out_path` use `<palace_parent>/backups/`. Assert the current behavior.
- For restore tests, create one archive from the seeded palace, then restore into separate temporary target palaces via top-level `--palace <target> restore <archive>`.
- For the non-force failure test, first restore once to make the target palace non-empty, then invoke restore again without `--force` and assert `SystemExit.code == 1` plus the user-facing `Use --force` message on stderr.
