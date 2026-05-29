slug: RESTORE-KG-PATH-SCOPING
phase: polish
date: 2026-05-29
commit_range: 55b53cc..HEAD
reverted: false
findings:
  - id: P-1
    title: "Defensive getattr() fallback for a always-present argparse attribute"
    category: defensive
    location: "mempalace_code/cli_commands/backup_restore.py:139"
    evidence: "getattr(args, \"kg_path\", None) is not None"
    decision: fixed
    fix: "Replaced with args.kg_path is not None — --kg-path is always registered via add_argument, so the getattr fallback can never fire"

  - id: P-2
    title: "Needless alias variable for DEFAULT_KG_PATH"
    category: volume
    location: "tests/test_backup_cli.py:240"
    evidence: "default_sentinel = DEFAULT_KG_PATH — alias used 3 times in place of the constant itself"
    decision: fixed
    fix: "Removed the alias; replaced all uses with DEFAULT_KG_PATH directly"

totals:
  fixed: 2
  dismissed: 0
fixes_applied:
  - "backup_restore.py: getattr(args, 'kg_path', None) -> args.kg_path"
  - "test_backup_cli.py: removed default_sentinel alias, use DEFAULT_KG_PATH directly"
