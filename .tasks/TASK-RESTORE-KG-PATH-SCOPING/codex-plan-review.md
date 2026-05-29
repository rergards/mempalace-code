verdict: READY

## Summary

The plan is implementable as written. The fix surgically targets `cmd_restore()` in
`mempalace_code/cli_commands/backup_restore.py` to resolve a KG destination
(`--kg-path` wins; otherwise an explicit top-level `--palace` scopes KG to
`<palace>/knowledge_graph.sqlite3`; no explicit palace preserves the historical
`restore_backup(kg_path=None)` default). I verified every load-bearing claim against
the codebase:

- `restore_backup(archive, palace, force, kg_path=None)` already accepts `kg_path` and
  defaults to `DEFAULT_KG_PATH` (backup.py:252-287), so INV-1 needs no library change.
- The non-empty-palace `FileExistsError` refusal (backup.py:291-296) fires before the
  tarfile is opened and before any Lance/KG copy — INV-2 ("refuse before mutation") is
  already satisfied; the change only adds a path argument upstream in the CLI handler.
- Top-level `--palace` has `default=None` (cli.py:79-82), so `args.palace is not None`
  is a correct, unambiguous signal for explicit palace scoping.
- The restore parser exists (cli.py:523-533) and `cmd_restore` is dispatched (cli.py:650);
  adding `--kg-path` to that parser is self-contained.
- Test scaffolding the plan relies on already exists: `seeded_kg`/`kg` fixtures
  (conftest.py:268-289), HOME isolation at import time (conftest.py:20-30, so
  `DEFAULT_KG_PATH` already resolves to a throwaway dir), and the exact
  `KnowledgeGraph(db_path=...).query_entity(...)` round-trip pattern
  (test_backup.py:209-235). The new `-k` selector names map cleanly to planned tests.
- `docs/BACKUP_RESTORE.md` exists (15.8K) — the listed change is an edit, not a create.
- No other callers depend on the touched signature: `test_cli_command_modules.py` only
  asserts `cmd_restore` is callable/registered, not its call shape; MCP/watcher are
  explicitly out of scope.

Contract canvas review (standard / full_spdd):
- `task_contract:` present (mode standard).
- No backlog metadata (BACKLOG.yaml / archive files) appears in files, surfaces, or edits.
- Every `acceptance:` id maps to a `verification:` row via `acceptance_ids`
  (AC-1→VER-1, AC-2→VER-2, AC-3→VER-3, AC-4→VER-4).
- All `verification:` and `regression_plan.checks` commands are runnable shell commands
  (`python -m pytest ... -q`); none are prose/placeholder. verification_path is automated
  and every row is executable, as required.
- `regression_plan.applies: true`; REG-1 links all four ACs.
- `contract_policy:` present with `flow: full_spdd` and `sync_gate: required`.

All four acceptance criteria are observable and SQLite/exit-code testable, all affected
files are identified and present, there is no TBD/deferred design, and there are no
architectural contradictions. No verification gaps.

gaps:
  - severity: low
    claim: "The module-level CLI usage docstring still advertises `restore FILE [--force]` without the new `--kg-path` option, leaving help text inconsistent with the added flag."
    evidence: "mempalace_code/cli.py:27 (usage banner) vs. plan files entry for cli.py which only mentions the argparse option + its --help text"
    suggested_fix: "Optionally update the usage banner at cli.py:27 to include `[--kg-path PATH]` alongside the argparse help text so the two stay in sync. Non-blocking."
  - severity: low
    claim: "Using `args.palace is not None` as the scoping signal leaves a residual mismatch: a user whose config.json sets a non-default palace_path but who does NOT pass --palace will still restore Lance into the configured palace while writing KG to the global DEFAULT_KG_PATH — the same surprising split the task targets, just via the config path rather than the flag."
    evidence: "mempalace_code/cli_commands/backup_restore.py:134 (palace resolves from config when --palace absent) + plan Design Notes line 122 and RISK-1 (lines 82-84)"
    suggested_fix: "No change required for this task — the plan deliberately scopes to explicit --palace (matching the backlog's `--palace <custom>` framing), documents the tradeoff in RISK-1/AC-4, and the --kg-path escape hatch covers the config-palace user. Noted only so the residual case is a conscious, recorded decision rather than an oversight."
