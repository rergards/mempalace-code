slug: STORE-WATCHER-BACKUP-BOUNDED-DEFAULTS
round: 1
date: 2026-05-12
commit_range: 76064a7..HEAD
findings:
  - id: F-1
    title: "Empty or invalid MEMPALACE_BACKUP_RETAIN_COUNT env var bypasses implicit pre_optimize bound"
    severity: medium
    location: "mempalace_code/config.py:198-203"
    claim: >
      _backup_retain_count_explicit checked only `is not None`, so an empty string
      (e.g. from `export MEMPALACE_BACKUP_RETAIN_COUNT=` in a shell profile) or a
      non-numeric value would set the flag True while backup_retain_count fell back
      to 0 (keep-all). This silently suppressed the implicit pre_optimize bound of 5
      — the exact disk-fill scenario the task is meant to prevent.
    decision: fixed
    fix: >
      Rewrote _backup_retain_count_explicit to attempt int() parsing; only returns
      True when the env var is present AND parses as an integer. Empty strings and
      non-numeric values now return False, allowing the implicit pre_optimize bound
      to apply. Added tests: test_empty_env_retain_count_is_not_explicit and
      test_invalid_env_retain_count_is_not_explicit in tests/test_config.py.

  - id: F-2
    title: "list_backups stale flag uses global backup_retain_count, not kind-aware retention"
    severity: info
    location: "mempalace_code/backup.py:442"
    claim: >
      list_backups marks entries stale using config.backup_retain_count (default 0)
      rather than retain_count_for_kind(kind). In the default config, no pre_optimize
      archives are ever shown as stale in the listing, even though the implicit bound
      of 5 is enforced during creation. A user migrating from an older install with
      >5 pre_optimize archives would see no stale markers and have no visual hint that
      the next backup will prune. This is a display inconsistency, not a correctness
      issue — archives are always pruned eagerly at creation time.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 0
  dismissed: 1

fixes_applied:
  - "config.py: _backup_retain_count_explicit now treats empty/unparseable MEMPALACE_BACKUP_RETAIN_COUNT as not set, preserving the implicit pre_optimize bound"
  - "test_config.py: added test_empty_env_retain_count_is_not_explicit and test_invalid_env_retain_count_is_not_explicit"

new_backlog: []
