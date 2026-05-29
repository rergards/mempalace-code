slug: WATCH-LANCE-MISSING-FRAGMENT-ROLLBACK
round: 1
date: 2026-05-29
commit_range: 4809a3e..HEAD
findings:
  - id: F-1
    title: "Non-Lance FileNotFoundError triggers unnecessary Lance rollback"
    severity: high
    location: "mempalace_code/watcher.py:464"
    claim: >
      _is_mine_missing_fragment() matched any exception whose message contained
      "no such file", "object not found", "io error", or "not found". A Python
      FileNotFoundError raised when the miner reads a source file that was deleted
      (e.g. project/src.py) would match "no such file" and trigger a live Lance
      rollback even though the palace was intact. This could roll back valid palace
      data unnecessarily.
    decision: fixed
    fix: >
      Added a FileNotFoundError guard: when exc is a Python FileNotFoundError with
      a filename attribute pointing outside <palace>/lance/, the function returns
      False and no rollback is triggered. Lance errors from lancedb internals do not
      carry a filename outside the lance directory, so the guard does not create
      false negatives for real Lance fragment errors. Added test
      TestWatchInitialMineRecovery::test_non_lance_file_not_found_does_not_trigger_rollback.

  - id: F-2
    title: "Same-second watcher restarts overwrite the pre-watch backup archive"
    severity: medium
    location: "mempalace_code/backup.py:168"
    claim: >
      Managed backup filenames were generated with second-resolution timestamps
      (%Y%m%d_%H%M%S). Two watcher starts in the same second (e.g. in a retry
      loop after a degraded startup) produced the same pre_watch_YYYYMMDD_HHMMSS.tar.gz
      filename, and os.replace() silently overwrote the earlier archive. In a retry
      scenario, the known-good pre-run archive could be destroyed before the operator
      used the printed restore command.
    decision: fixed
    fix: >
      Changed the timestamp format to %Y%m%d_%H%M%S_%f (microseconds), making
      same-second collisions astronomically unlikely. Updated the sort-key comment
      in prune_managed_backups to reflect the new format. Added test
      TestPreWatchBackups::test_concurrent_pre_watch_backups_produce_distinct_filenames.

  - id: F-3
    title: "Recovery commands are not shell-safe for palace/archive paths with spaces"
    severity: low
    location: "mempalace_code/watcher.py:478"
    claim: >
      _print_recovery_commands() interpolated raw palace_path and pre_watch_archive
      into the printed commands without quoting. A palace path or archive path
      containing spaces (e.g. /home/user/my projects/palace) produced a command
      that would silently split on the space when copy-pasted into a shell, making
      the documented "operator-safe" commands unreliable.
    decision: fixed
    fix: >
      Applied shlex.quote() to both palace_path and pre_watch_archive before
      interpolation. Added import shlex. Added test
      TestWatchInitialMineRecovery::test_recovery_commands_quote_paths_with_spaces
      which asserts shlex.quote(str(palace)) appears in the recovery command output.

totals:
  fixed: 3
  backlogged: 0
  dismissed: 0

fixes_applied:
  - "F-1: _is_mine_missing_fragment now accepts palace_path; excludes Python FileNotFoundError for paths outside <palace>/lance/"
  - "F-2: managed backup timestamp format changed from %Y%m%d_%H%M%S to %Y%m%d_%H%M%S_%f (microsecond precision)"
  - "F-3: _print_recovery_commands uses shlex.quote() for both palace_path and pre_watch_archive"

new_backlog: []
