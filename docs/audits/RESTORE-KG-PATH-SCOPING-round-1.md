slug: RESTORE-KG-PATH-SCOPING
round: 1
date: 2026-05-29
commit_range: 8fb7202..0ccef25
findings:
  - id: F-1
    title: "Falsy vs is-not-None inconsistency for args.palace in cmd_restore"
    severity: low
    location: "mempalace_code/cli_commands/backup_restore.py:134,141"
    claim: >
      palace_path derivation uses `if args.palace` (falsy check, treats "" as absent)
      while the kg_path branch uses `args.palace is not None` (truthy for "").
      For `--palace ""`, palace_path falls back to config but kg_path still scopes to
      os.path.join(config_palace, "knowledge_graph.sqlite3") — consistent outcome,
      inconsistent intent. Empty-string --palace is not a realistic invocation (argparse
      default is None and such a value would fail everywhere else), so this has no
      observable impact on production use.
    decision: dismissed

  - id: F-2
    title: "AC-1 and AC-2 tests write raw-bytes sentinels to DEFAULT_KG_PATH without per-test cleanup"
    severity: low
    location: "tests/test_backup_cli.py:201,241"
    claim: >
      test_restore_cli_explicit_palace_scopes_kg and test_restore_cli_refusal_does_not_touch_kg
      each write a raw-bytes sentinel to DEFAULT_KG_PATH and leave it there after the test.
      Because conftest redirects HOME to an isolated session-scoped temp directory before any
      mempalace import, DEFAULT_KG_PATH always resolves to a throwaway path. Tests that write
      the real KG to DEFAULT_KG_PATH afterward (e.g. AC-4) do so via restore_backup, which
      atomically replaces whatever is present. No test failure was observed with any run order.
    decision: dismissed

  - id: F-3
    title: "No test for --kg-path used without top-level --palace"
    severity: low
    location: "tests/test_backup_cli.py"
    claim: >
      The docs table and help text explicitly list `mempalace-code restore FILE --kg-path PATH`
      (without --palace) as a valid invocation. The code handles this correctly — the
      `if getattr(args, "kg_path", None) is not None` branch fires unconditionally on --kg-path
      presence — but no test exercised this combination. A regression that gated the --kg-path
      branch on `args.palace is not None` would go undetected.
    decision: fixed
    fix: >
      Added test_restore_cli_kg_path_without_palace to tests/test_backup_cli.py. The test
      invokes `mempalace-code restore FILE --kg-path <explicit>` without --palace, plants a
      sentinel at DEFAULT_KG_PATH, and asserts the KG lands at the explicit path, the sentinel
      is unchanged, and the restored KG contains the expected data.

totals:
  fixed: 1
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "Added test_restore_cli_kg_path_without_palace to tests/test_backup_cli.py to cover the --kg-path-without---palace code path"

new_backlog: []
