slug: STORE-BACKUP-RESTORE
round: 1
date: "2026-04-14"
commit_range: 1b4bafc..HEAD
findings:
  - id: F-1
    title: "Non-atomic backup write leaves corrupt archive on interruption"
    severity: medium
    location: "mempalace/backup.py:79"
    claim: >
      create_backup() opened out_path directly with tarfile.open("w:gz").
      An interrupted write (disk full, SIGKILL, exception) leaves a partial
      .tar.gz at the destination. Since this is a backup tool, silent data
      corruption of the output file is a correctness failure.
    decision: fixed
    fix: >
      Write archive to a temp file in the same directory (tempfile.mkstemp),
      then os.replace() atomically into out_path. On any exception the temp
      file is unlinked before re-raising, so no corrupt artifact is left.

  - id: F-2
    title: "Non-atomic KG overwrite corrupts existing database on interruption"
    severity: medium
    location: "mempalace/backup.py:218"
    claim: >
      restore_backup() used shutil.copy2(extracted_kg, kg_path) to overwrite
      an existing KG file. If copy2 is interrupted mid-transfer the existing
      SQLite database is left partially written and becomes corrupt.
    decision: fixed
    fix: >
      Copy to kg_path + ".tmp" first, then os.replace() kg_tmp → kg_path
      atomically. The existing file is only replaced after the new copy is
      fully written.

  - id: F-3
    title: "TarInfo for metadata.json has mtime=0 (epoch)"
    severity: low
    location: "mempalace/backup.py:98"
    claim: >
      tarfile.TarInfo() defaults mtime to 0 (1970-01-01). Listing the archive
      with tar -tvf shows metadata.json dated to epoch, which is confusing and
      inconsistent with the other entries.
    decision: fixed
    fix: >
      Added `info.mtime = int(time.time())` immediately before tar.addfile(),
      so metadata.json carries the same creation timestamp as the archive itself.

  - id: F-4
    title: "cmd_backup prints placeholder path when --out is omitted"
    severity: low
    location: "mempalace/cli.py:502"
    claim: >
      When no --out is given, cmd_backup displayed the literal string
      "mempalace_backup_*.tar.gz (in CWD)" instead of the actual timestamped
      filename. The user had no way to know the real path from the output.
    decision: fixed
    fix: >
      Changed create_backup() return type from dict to (dict, str) — the tuple
      now includes the resolved out_path. cmd_backup unpacks it as
      `meta, out_path = create_backup(...)` and prints the real path.
      Tests updated to unpack accordingly; test_backup_default_out_path also
      asserts that default_out basename matches the file found in CWD.

  - id: F-5
    title: "No CLI-level integration tests for backup/restore commands"
    severity: info
    location: "tests/test_backup.py"
    claim: >
      All tests invoke create_backup() and restore_backup() directly. The
      argparse wiring (cmd_backup, cmd_restore), the sys.exit(1) on error path,
      and the new out_path display are not exercised through the CLI layer.
    decision: backlogged
    backlog_slug: STORE-BACKUP-CLI-TEST

totals:
  fixed: 4
  backlogged: 1
  dismissed: 0

fixes_applied:
  - "Atomic backup write: write to .tar.gz.tmp then os.replace() into out_path"
  - "Atomic KG restore: copy to kg_path.tmp then os.replace() atomically"
  - "TarInfo mtime set to int(time.time()) for metadata.json entry"
  - "create_backup returns (metadata, out_path) tuple; cmd_backup prints real path"

new_backlog:
  - slug: STORE-BACKUP-CLI-TEST
    summary: "Add CLI-level integration tests for backup and restore commands"
