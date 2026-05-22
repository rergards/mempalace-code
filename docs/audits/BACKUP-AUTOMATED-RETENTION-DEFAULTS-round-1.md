slug: BACKUP-AUTOMATED-RETENTION-DEFAULTS
round: 1
date: 2026-05-22
commit_range: 1629504..HEAD
findings:
  - id: F-1
    title: "_backup_retain_count_explicit skips value validation for file config"
    severity: medium
    location: "mempalace_code/config.py:216"
    claim: >
      The file-config branch of `_backup_retain_count_explicit` checked only key
      presence (`"backup_retain_count" in self._file_config`) without validating
      the value. A negative or non-numeric `backup_retain_count` in the config
      file (e.g., `backup_retain_count: -5`) caused `_backup_retain_count_explicit`
      to return True even though `backup_retain_count` fell back to 0. This made
      `retain_count_for_kind` return 0 instead of the implicit 14 (scheduled) or
      5 (pre_optimize), silently suppressing the retention defaults the task was
      designed to enforce. The env-var path already validated correctly; the file
      path did not, violating RISK-2's stated mitigation ("treat only valid
      nonnegative values as explicit").
    decision: fixed
    fix: >
      Replaced `return "backup_retain_count" in self._file_config` with a value-
      aware check: retrieve `self._file_config.get("backup_retain_count")`, attempt
      `int()`, and return `v >= 0`. Invalid or negative file values now return False
      (not explicit), preserving implicit per-kind defaults. Added
      `test_negative_file_config_retain_count_is_not_explicit` in tests/test_config.py
      to cover this path.

  - id: F-2
    title: "Plan VER-8/REG-4 test node IDs missing class qualifier"
    severity: low
    location: "docs/plans/BACKUP-AUTOMATED-RETENTION-DEFAULTS.md:176-202"
    claim: >
      The VER-8 and REG-4 verification commands reference
      `tests/test_cli.py::test_backup_schedule_daily_darwin` and
      `tests/test_cli.py::test_backup_schedule_daily_linux`, but both tests live
      inside the `TestBackupCommand` class. Pytest collects 0 tests with the
      unqualified node IDs, so a raw copy-paste of those commands fails with
      "no tests collected". The tests themselves are correct and pass when invoked
      as `tests/test_cli.py::TestBackupCommand::test_backup_schedule_daily_*`.
    decision: dismissed
    fix: ~

  - id: F-3
    title: "VER-9/REG-5 chained rg command unreliable through Claude Code rg wrapper"
    severity: info
    location: "docs/plans/BACKUP-AUTOMATED-RETENTION-DEFAULTS.md:180-205"
    claim: >
      The plan's VER-9/REG-5 verification command uses `! rg --quiet ...` chained
      with `&&`. When run as a single Bash invocation, the Claude Code `rg` shell
      wrapper (ARGV0 aliased to the Claude binary) caused the chain to return a
      non-zero exit even though every individual check passed. Each step was
      verified individually and passed; `grep -q` equivalents passed the full chain.
      The docs content itself is correct — all three files contain `newest 14` and
      the stale "unbounded" claim is absent.
    decision: dismissed
    fix: ~

totals:
  fixed: 1
  backlogged: 0
  dismissed: 2
fixes_applied:
  - "mempalace_code/config.py: validate file-config backup_retain_count value in
    _backup_retain_count_explicit — negative or non-numeric values no longer suppress
    implicit per-kind retention defaults"
  - "tests/test_config.py: add test_negative_file_config_retain_count_is_not_explicit
    covering the fixed file-config validation path"
new_backlog: []
