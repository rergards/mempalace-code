---
slug: STORAGE-AUTO-BACKUP
status: completed
authority: non_authoritative
goal: "Make pre-optimize auto-backup the default, add `backup list`, and add `backup schedule` snippet-emit for daily/weekly scheduling."
risk: medium
risk_note: "Changes a default that affects every mining run (backup_before_optimize False → True). The safe_optimize() fail-closed path is already hardened, so the worst-case failure mode is 'mine reports optimize skipped due to backup error' rather than silent data loss. Scheduled backup only emits a snippet — no system files are modified."
files:
  - path: mempalace/config.py
    change: "Flip DEFAULT_BACKUP_BEFORE_OPTIMIZE False → True. Add `auto_backup_before_optimize` property that reads MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE env or `auto_backup_before_optimize` file key, falling back to `backup_before_optimize` (back-compat). Add `backup_schedule` property (off|daily|weekly|hourly) reading MEMPALACE_BACKUP_SCHEDULE env / `backup_schedule` file key, default 'off'. The existing `backup_before_optimize` property remains the single source of truth consumed by miner.py / convo_miner.py — callers do not need to change."
  - path: mempalace/backup.py
    change: "(1) Change `create_backup()` default out_path from `os.getcwd()/mempalace_backup_<ts>.tar.gz` to `<palace_parent>/backups/mempalace_backup_<ts>.tar.gz` (auto-mkdir); this aligns the manual-backup default with safe_optimize()'s pre_optimize location so `backup list` discovery is coherent. Explicit `--out` still wins, preserving the existing override path. (2) Add `list_backups(palace_path: str, extra_dir: Optional[str] = None) -> list[dict]`: scans only `<palace_parent>/backups/` for `*.tar.gz` (plus `extra_dir` when given, for the CLI `--dir` flag), opens each tar to parse mempalace_backup/metadata.json (tolerate missing/corrupted metadata — fall back to filesystem mtime/size), returns sorted-newest-first list of {path, size_bytes, mtime, timestamp, drawer_count, wings, kind}. `kind` is 'pre_optimize' for pre_optimize_*.tar.gz, 'manual' for mempalace_backup_*.tar.gz, 'scheduled' for scheduled_*.tar.gz, 'other' otherwise. (3) Add `render_schedule(freq: str, palace_path: str, platform: str, mempalace_bin: Optional[str] = None) -> str`: current implementation emits managed `backup create --kind scheduled --palace <path>` snippets rather than explicit `--out` paths. The backup command itself creates timestamp-unique `scheduled_*.tar.gz` archives in `<palace_parent>/backups/` and applies scheduled retention. Returns launchd plist XML (platform='darwin') or cron line (platform='linux'); raises ValueError on unsupported freq/platform. For darwin daily/weekly uses `StartCalendarInterval` (Hour=3, Minute=0 / +Weekday=0); for darwin hourly uses `StartInterval=3600` (canonical choice; see design notes). Cron: `0 3 * * *` daily, `0 3 * * 0` weekly, `0 * * * *` hourly."
  - path: mempalace/cli.py
    change: "Refactor `backup` parser to a sub-subparser with verbs `create`, `list`, `schedule`, plus no-verb back-compat. Parser shape: `p_backup.add_subparsers(dest='backup_command', required=False)`; keep the existing top-level `--out` on `p_backup` itself for no-verb back-compat (AC-6), AND add `--out` to the `create` subparser explicitly so `mempalace backup create --out X` works as a first-class verb (AC-11). `p_backup_list` adds `--dir PATH` (optional: include an extra directory in discovery, e.g. a legacy CWD backup location). `p_backup_schedule` adds `--freq {daily,weekly,hourly}` (required) and `--install` (accepts, then rejects with exit 2 and an 'owner action required' message pointing at the printed snippet). `cmd_backup(args)` dispatches on `args.backup_command`: None → cmd_backup_create (back-compat); 'create' → cmd_backup_create; 'list' → cmd_backup_list; 'schedule' → cmd_backup_schedule. cmd_backup_list prints 'No backups found.' or a formatted fixed-width table (TIMESTAMP SIZE DRAWERS KIND PATH). cmd_backup_schedule prints render_schedule() output to stdout (with the resolved absolute backup dir), then a short trailing hint telling the user how to install it (launchctl load / crontab -e)."
  - path: tests/test_backup.py
    change: "Add TestAutoBackupDefault (config flip; env override via MEMPALACE_BACKUP_BEFORE_OPTIMIZE=0; file-key back-compat for backup_before_optimize=false; auto_backup_before_optimize alias override; env precedence — when both MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE and MEMPALACE_BACKUP_BEFORE_OPTIMIZE are set to conflicting values, the auto_ env wins). Add TestCreateBackupDefaultLocation (no --out → archive lands in `<palace_parent>/backups/`, not CWD; explicit --out still honored). Add TestListBackups (empty dir → []; seeded pre_optimize_*.tar.gz + mempalace_backup_*.tar.gz + scheduled_*.tar.gz → all three listed with correct kind; missing metadata.json tolerated — entry still present with drawer_count=None; corrupted/unreadable tar tolerated — logged+skipped; newest-first ordering; extra_dir merges results and dedupes by path). Add TestRenderSchedule (darwin daily/weekly emit valid plist with StartCalendarInterval; darwin hourly emits plist with StartInterval=3600; current outputs call managed `backup create --kind scheduled --palace <path>` without explicit `--out`; linux emits cron line with correct minute/hour and binary path; invalid freq raises ValueError; invalid platform raises ValueError)."
  - path: tests/test_cli.py
    change: "Add test_backup_list_empty (no backups/ dir → stdout contains 'No backups found' exit 0), test_backup_list_populated (seeded palace with pre_optimize archive → stdout shows archive name and drawer count), test_backup_list_extra_dir (--dir flag picks up archives outside <palace_parent>/backups/), test_backup_schedule_daily_darwin (monkeypatch sys.platform='darwin' → stdout contains '<?xml', 'StartCalendarInterval', and managed `backup create --kind scheduled --palace`), test_backup_schedule_hourly_darwin (stdout contains 'StartInterval' and '3600' — asserts canonical hourly choice), test_backup_schedule_daily_linux (monkeypatch sys.platform='linux' → stdout matches cron minute/hour pattern and contains `backup create --kind scheduled --palace`), test_backup_schedule_install_rejected (`backup schedule --freq daily --install` exits non-zero with an 'owner action required' message and does NOT touch launchctl/crontab), test_backup_no_verb_creates (back-compat: `mempalace backup --out X` with no verb still creates archive), test_backup_create_verb_with_out (`mempalace backup create --out X` creates archive at X — first-class verb path), test_mine_default_calls_safe_optimize_backup_first (integration: mine() on a fresh MempalaceConfig() calls safe_optimize(backup_first=True) because of the flipped default)."
  - path: tests/test_convo_miner.py
    change: "Add test_mine_convos_default_calls_safe_optimize_backup_first — parallel to the miner test: mine_convos() on a fresh MempalaceConfig() passes backup_first=True into the store's safe_optimize() (mocked). Protects the convo-miner optimize path, which is a separate call-site from miner.mine()."
  - path: README.md
    change: "Update the 'Storage Safety' / 'backup_before_optimize' section to note auto-backup is ON by default, document the new `auto_backup_before_optimize` alias, document the changed default output location for `mempalace backup` (now `<palace_parent>/backups/` instead of CWD) and the new `mempalace backup list` / `mempalace backup create` / `mempalace backup schedule --freq {daily,weekly,hourly}` verbs. Replace the hand-rolled cron snippet in the existing 'Scheduled backups' example with `mempalace backup schedule --freq daily` and note that the subcommand emits a snippet the user must install themselves (launchctl load / crontab -e)."
acceptance:
  - id: AC-1
    when: "MempalaceConfig() is instantiated on a clean config dir (no config.json, no env vars)"
    then: "config.backup_before_optimize is True AND config.auto_backup_before_optimize is True AND config.backup_schedule == 'off'"
  - id: AC-2
    when: "MEMPALACE_BACKUP_BEFORE_OPTIMIZE=0 is set in the environment"
    then: "MempalaceConfig().backup_before_optimize is False (env opt-out overrides flipped default)"
  - id: AC-3
    when: "A user's config.json contains {\"backup_before_optimize\": false} (explicit opt-out from pre-flip era)"
    then: "MempalaceConfig().backup_before_optimize is False (file value honored; flipped default does not override explicit opt-out)"
  - id: AC-4
    when: "list_backups(palace_path) is called on a palace whose <palace_parent>/backups/ contains two pre_optimize_*.tar.gz archives seeded via create_backup()"
    then: "returns a length-2 list ordered newest-first; each entry has correct drawer_count from metadata.json and kind='pre_optimize'"
  - id: AC-5
    when: "`mempalace backup list` is run on a palace with no backups/ directory"
    then: "exit code 0; stdout contains 'No backups found.'"
  - id: AC-6
    when: "`mempalace backup --out /tmp/x.tar.gz` is run (no verb, back-compat path)"
    then: "exit code 0; /tmp/x.tar.gz exists and is a valid backup archive"
  - id: AC-7
    when: "`mempalace backup schedule --freq daily` is run with sys.platform='darwin'"
    then: "exit code 0; stdout contains '<?xml', 'StartCalendarInterval' (Hour 3 / Minute 0), the mempalace binary path, and a managed `backup create --kind scheduled --palace <path>` command"
  - id: AC-8
    when: "`mempalace backup schedule --freq daily` is run with sys.platform='linux'"
    then: "exit code 0; stdout contains a line matching the daily cron schedule and a managed `backup create --kind scheduled --palace <path>` command"
  - id: AC-9
    when: "miner.mine() is invoked with default MempalaceConfig() (no overrides) on a LanceDB palace"
    then: "the store's safe_optimize is called with backup_first=True (verified via mock)"
  - id: AC-10
    when: "`ruff check mempalace/ tests/` and `ruff format --check mempalace/ tests/` are run"
    then: "both exit 0; `python -m pytest tests/ -x -q` still passes (no regressions in the 570+ existing tests)"
  - id: AC-11
    when: "`mempalace backup create --out /tmp/x.tar.gz` is run (first-class verb path)"
    then: "exit code 0; /tmp/x.tar.gz exists and is a valid backup archive"
  - id: AC-12
    when: "Both MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE=1 and MEMPALACE_BACKUP_BEFORE_OPTIMIZE=0 are set in the environment simultaneously"
    then: "MempalaceConfig().backup_before_optimize is True (auto_ alias takes precedence — documented as the preferred key)"
  - id: AC-13
    when: "convo_miner.mine_convos() is invoked with default MempalaceConfig() (no overrides) on a LanceDB palace"
    then: "the store's safe_optimize is called with backup_first=True (verified via mock — separate call-site from miner.mine())"
  - id: AC-14
    when: "create_backup(palace_path) is called with no `out_path`"
    then: "the archive is written under `<palace_parent>/backups/mempalace_backup_<ts>.tar.gz` (not CWD); the directory is created if missing; explicit `out_path` still overrides this default"
  - id: AC-15
    when: "`mempalace backup schedule --freq daily --install` is run on any platform"
    then: "exit code is non-zero; stderr contains an 'owner action required' message; no launchctl, crontab, or filesystem side-effect occurs"
out_of_scope:
  - "Historical for this plan: retention/pruning of old backup archives was handled later. Current defaults keep newest 5 pre_optimize archives and newest 14 scheduled archives; manual archives remain unbounded unless explicitly configured."
  - "Actually installing launchd plists or writing crontab entries — the subcommand only emits the snippet; the user is responsible for installation (owner_prereq)."
  - "Incremental / differential backups using Lance table versioning — full-tar backup is fast enough for realistic palace sizes (< 500 MB typical). Post-v1 optimization; would need its own design + benchmark."
  - "ChromaStore backup — ChromaDB is deprecated; backup.py already targets LanceDB only."
  - "Migrating existing users' config.json to add auto_backup_before_optimize key — alias is read-only; users who explicitly set backup_before_optimize=false keep their setting (AC-3)."
  - "Changing the pre_optimize_*.tar.gz file naming / directory layout — safe_optimize() already standardized it."
  - "A `mempalace backup restore <name>` shorthand that looks up archives by name in the backups/ dir — the existing `mempalace restore <path>` already works."
  - "A `backup verify` subcommand that opens the archive and validates contents — out of scope; would need a separate plan."
---

## Design Notes

- **Why flip the default.** The backlog incident summary ("Lost 39 drawers in Apr 2026") points at the same root cause as STORAGE-SAFE-OPTIMIZE: the safety machinery exists but is off. Flipping the default is the single largest safety win here. Explicit opt-out is still honored (AC-2 env, AC-3 file).

- **Why the alias, not a rename.** Renaming `backup_before_optimize` → `auto_backup_before_optimize` would break every existing config.json and every env-var override in user setups. Instead: `auto_backup_before_optimize` is a preferred alias that reads first; `backup_before_optimize` remains the canonical key consumed by miner.py / convo_miner.py. No caller in the code base needs to change.

- **One canonical backup directory.** All three entry points (safe_optimize's pre_optimize archives, manual `mempalace backup`, scheduled backups) write under `<palace_parent>/backups/`. This was previously split: pre_optimize went there, manual went to CWD. The plan unifies them by changing `create_backup()`'s default `out_path` when `None` is passed (AC-14). Rationale: (a) `backup list` can now have a single coherent discovery rule; (b) the review's open question "where do scheduled backups go" has an obvious answer; (c) users who want CWD behavior still have `--out $(pwd)/foo.tar.gz`. This is a user-visible default change — called out in the README update.

- **`backup list` discovery rule (explicit).** `list_backups()` scans exactly one directory: `<palace_parent>/backups/`. Optional `--dir PATH` on the CLI adds one extra directory to the scan (deduped by absolute path). It does NOT scan CWD — too surprising. It does NOT walk subdirectories — flat scan only. `kind` classification by filename prefix: `pre_optimize_` → `pre_optimize`, `scheduled_` → `scheduled`, `mempalace_backup_` → `manual`, anything else → `other`. Legacy manual backups sitting in an old CWD are reachable via `--dir`.

- **List parsing tolerance.** Corrupted/partial archives should not crash `backup list`. Each tar open is wrapped in a try/except; a missing or unparseable `metadata.json` yields `drawer_count=None, wings=[]` but the entry still appears (with mtime/size from filesystem). A tar that fails to open at all is logged (warning) and skipped. This matches the failure mode of the very incident that motivated the feature (FIX-LANCE-CORRUPT fragment-missing recovery).

- **Schedule command emits, does not install.** Writing a launchd plist or editing crontab is a destructive system-level action. Per CLAUDE.md "Ask Before Acting" and the executing-actions-with-care rule, the subcommand prints the snippet and tells the user to install it (owner_prereq). `--install` is accepted by the parser specifically so we can produce a clear 'owner action required' rejection (AC-15) rather than an unhelpful `unrecognized argument` error. The acceptance tests are platform-patched so they run deterministically in CI.

- **Schedule content — execution-safe by construction.** Current emitted snippets call managed `backup create --kind scheduled --palace <path>` rather than using an explicit `--out` path. `create_backup()` creates the timestamp-unique `scheduled_*.tar.gz` archive under `<palace_parent>/backups/`, so every scheduled run is locatable by `backup list` and participates in scheduled retention.

- **Schedule content — schedule keys.** Darwin: `StartCalendarInterval {Hour=3, Minute=0}` for daily; add `Weekday=0` (Sunday) for weekly; hourly uses `StartInterval=3600` (canonical — a single key is simpler than `StartCalendarInterval` with wildcarded Hour, and launchd's scheduler behavior around wildcards has edge cases we don't need to defend). Linux cron: `0 3 * * *` daily, `0 3 * * 0` weekly, `0 * * * *` hourly. Darwin-hourly using `StartInterval=3600` is the single canonical output; earlier versions of this plan mentioned both `StartCalendarInterval` and `StartInterval` for hourly — `StartInterval=3600` is the one the implementation and tests must match.

- **Binary path resolution.** The resolved binary path comes from `shutil.which('mempalace')` with a fallback to `sys.executable + ' -m mempalace'` when not on PATH. The `mempalace_bin` parameter on `render_schedule()` is optional and mostly exists for tests to inject a deterministic path.

- **Env var precedence when both are set.** If `MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE` is set, it wins — even over `MEMPALACE_BACKUP_BEFORE_OPTIMIZE` with a conflicting value (AC-12). The auto_ alias is the preferred, documented key; the legacy env var is honored only as the sole source. The same rule applies to the file keys: `auto_backup_before_optimize` wins over `backup_before_optimize` when both appear in config.json.

- **`backup list` output shape.** Columns: `TIMESTAMP  SIZE  DRAWERS  KIND  PATH`. Fixed-width columns (not JSON) — matches the existing CLI aesthetic in `status` / `diary read`. JSON output is explicitly not in this plan's scope; add later if an agent needs it.

- **Back-compat verb dispatch.** `p_backup.add_subparsers(dest="backup_command")` with `required=False` lets `mempalace backup --out X` keep working (args.backup_command=None → dispatch to create path). This mirrors the existing `diary` pattern but relaxes the required=True gate `diary` uses, because `backup` already had a working no-verb form pre-this-plan.

- **Why `auto_backup_before_optimize` has MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE env.** Consistency: the backlog AC specifies the file key name, and env-var naming follows the `MEMPALACE_<UPPER_SNAKE>` convention used throughout config.py. Both env vars work; the auto_ variant is read first if set.
