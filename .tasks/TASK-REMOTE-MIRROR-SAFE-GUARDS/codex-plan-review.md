verdict: NEEDS_CHANGES

# Plan Review — REMOTE-MIRROR-SAFE-GUARDS

## Summary
The plan is well-structured: the `task_contract` canvas is present and complete, `contract_policy` is `full_spdd` with `sync_gate: required` and `verification_path: automated`, every acceptance criterion has a linked `verification` row and a linked `regression_plan.checks` row, no backlog/archive files are listed as edits, and the code design (new `preflight mirror` subcommand routed through `cli_commands/preflight.py`, non-executing `shlex`-based classifier in `mirror_preflight.py`) matches the existing `diary`/`watch` nested-subcommand and dispatch patterns in `mempalace_code/cli.py`. The claimed state paths are accurate (`~/.mempalace/knowledge_graph.sqlite3`, `~/.mempalace/palace`, `~/.mempalace/config.json`, `<palace_parent>/backups/`). The file list is complete — `cli_commands/__init__.py` is doc-only and needs no edit; `cli.py` covers import + parser + dispatch.

The blocking issue is the documentation verification (AC-5 / VER-5 / REG-3): the proving command already passes against the unmodified repository, so it cannot detect whether the required mirror guidance was actually written.

gaps:
  - severity: high
    claim: "AC-5 / VER-5 / REG-3 already pass against the unmodified tree, so they cannot prove the new backup-vs-mirror guidance or safe rsync excludes were added. The regex is an OR-alternation and rg exits 0 on the first match in either file; several alternatives (knowledge_graph.sqlite3, backups/, config.json, .log) are already present in both docs today. An implementer could ship without writing any mirror guidance and AC-5 + REG-3 would still be green, missing REQ-1/REQ-2."
    evidence: "Plan AC-5/VER-5/REG-3 (REMOTE-MIRROR-SAFE-GUARDS.md:33-34, 126, 142). Pre-existing matches: README.md:296 and README.md:543 (config.json, backups/), docs/BACKUP_RESTORE.md:15 (knowledge_graph.sqlite3), docs/BACKUP_RESTORE.md:153/258 (backups/, config.json), README.md:274 (.log). Verified via Grep — the command returns matches now."
    suggested_fix: "Anchor verification on genuinely new, mirror-specific content that does not exist pre-implementation, and check each file separately so both must be updated. e.g. run one command per file asserting the mirror/delete-mode warning (a unique sentinel phrase the implementer must add) AND the rsync exclude guidance, rather than OR-ing tokens that already appear. Confirm the chosen command FAILS on the current HEAD before implementation begins."
  - severity: medium
    claim: "Even setting aside the pre-match problem, VER-5 passes README.md and docs/BACKUP_RESTORE.md as two positional args to a single rg; rg exits 0 if any one pattern matches in either file. It does not enforce that BOTH docs were updated nor that ALL five exclude families (palace, KG, config, logs, backups) are present. The AC-5 'then' text claims 'both docs distinguish... and show safe exclude guidance for palace, KG, config, logs, and backups' — the command proves far less."
    evidence: "Plan AC-5 then-clause (REMOTE-MIRROR-SAFE-GUARDS.md:33-34) vs VER-5 command (REMOTE-MIRROR-SAFE-GUARDS.md:126)."
    suggested_fix: "Split into per-file, per-family assertions (or a small grep loop / test) so each required exclude family and the backup-vs-mirror distinction is verified in each document independently."
  - severity: low
    claim: "The 'logs' exclude family is required for a delete-mode ~/.mempalace mirror to be classified safe (AC-1, AC-2), but the only log path in the codebase is /tmp/mempalace-watch.log — logs are not written under ~/.mempalace by default. Requiring a logs exclude for a state-dir mirror is defensive but speculative, and docs should not imply logs live in the palace state dir."
    evidence: "mempalace_code/watcher.py:1026-1028 (log path is /tmp/mempalace-watch.log). Plan design note (REMOTE-MIRROR-SAFE-GUARDS.md:152) and AC-1/AC-2 (lines 21-25)."
    suggested_fix: "Either keep logs as an optional/advisory family (not required for the safe verdict) or have the docs explicitly note logs are excluded only if an operator has configured logging into the state dir. Keep tests/docs consistent with whichever choice is made."
  - severity: low
    claim: "INV-1 (the preflight command must never execute/shell out to/install the inspected command string) has no dedicated verification row; it is only implicitly exercised by the safe/blocked/parse-error classification tests. INV-2 is covered (REG-2 runs health/backup), but INV-1 — the core safety invariant of this task — is not directly asserted."
    evidence: "Plan invariants INV-1 (REMOTE-MIRROR-SAFE-GUARDS.md:83-85); verification rows VER-1..VER-5 contain no execution/no-subprocess assertion."
    suggested_fix: "Add a verification (or a test in the planned TestMirrorPreflightCommand) that asserts no subprocess is spawned and the working tree/remote is untouched when a dangerous command string is inspected (e.g. patch subprocess.run/os.system and assert not called)."

## Notes (non-blocking, verified OK)
- Exit-code convention (0 safe / 1 blocked / 2 malformed) is consistent with existing CLI usage; exit 2 is already used for the missing-subcommand case in cli.py:635 and will not collide.
- The version-check auto-hook runs after normal-return commands; the safe (exit 0) path would also trigger it, but this is pre-existing opt-in behavior for all commands and does not violate INV-1 (the PyPI call is unrelated to the inspected string). No action needed.
- Test invocation pattern (patch sys.argv + call main(), pytest.raises(SystemExit) for nonzero) is established (tests/test_cli.py:634, 661-667); the planned tests are feasible.
- TestHealthCommand (test_cli.py:622) and TestBackupCommand (test_cli.py:967) referenced by REG-2 both exist.
