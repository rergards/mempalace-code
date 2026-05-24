---
slug: CLI-BACKUP-PARENT-OUT-IGNORED
goal: "Honor documented backup --out FILE create compatibility form"
risk: low
risk_note: "A narrow CLI dispatch fix with one parser path and regression tests; no storage format or data migration changes."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: single CLI parsing bug, no auth/data/migration/provider/pipeline boundary, no remote or destructive operation, and behavior is fully observable through local CLI output and files."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
files:
  - path: mempalace_code/cli_commands/backup_restore.py
    change: "Preserve the parent-level --out value for the back-compat no-verb path, or otherwise reconcile parent/subparser parsing so backup --out FILE create targets FILE."
  - path: tests/test_backup_cli.py
    change: "Add regression coverage for backup --out FILE create, keep backup create --out FILE working, and cover the explicit default/no-verb case."
acceptance:
  - id: AC-1
    when: "Running `mempalace-code --palace <temp-palace> backup --out /tmp/expected.tar.gz create` on a small palace"
    then: "The archive is written to `/tmp/expected.tar.gz`, and the CLI prints that same archive path."
  - id: AC-2
    when: "Running `mempalace-code --palace <temp-palace> backup create --out /tmp/expected.tar.gz` on a small palace"
    then: "The archive is written to `/tmp/expected.tar.gz`, and the CLI prints that same archive path."
  - id: AC-3
    when: "Running `mempalace-code --palace <temp-palace> backup` with no verb and no explicit out path"
    then: "The archive is created under `<palace_parent>/backups/`, not at an arbitrary caller-supplied path."
  - id: AC-4
    when: "Running `mempalace-code --palace <temp-palace> backup --out /tmp/expected.tar.gz create` with the out path parent directory missing"
    then: "The command still succeeds by creating the parent directory and writing the archive there."
out_of_scope:
  - "Any backup filename policy changes beyond the compatibility fix."
  - "Backup retention, scheduling, or restore behavior."
  - "Backlog metadata edits or archive/bookkeeping tasks."
---

## Design Notes

- Prefer a minimal parser-dispatch reconciliation over changing the documented CLI shape.
- Keep both accepted spellings working if the back-compat path is retained; do not regress `backup create --out FILE`.
- Regression tests should assert both file existence and printed `Archive:` output so the path used by the CLI is observable.
- Preserve the current default behavior for no-verb `backup` so only the documented compatibility form changes.
