slug: REMOTE-MIRROR-SAFE-GUARDS
round: 1
date: 2026-05-29
commit_range: 0e50e3a..HEAD
findings:
  - id: F-1
    title: "--delete-excluded with all required excludes incorrectly classified as safe"
    severity: high
    location: "mempalace_code/mirror_preflight.py:119"
    claim: >
      When a command uses --delete-excluded, rsync deletes destination-side files that are
      locally excluded by --exclude. So --exclude=palace/ combined with --delete-excluded
      causes rsync to DELETE palace/ from the remote rather than preserve it. The classifier
      computed missing required excludes (which were all present) and returned ok=True, letting
      a command that would destroy live palace data pass the guard. The Codex hardening review
      identified this as P1/High.
    decision: fixed
    fix: >
      Added a DELETE_EXCLUDED_PATTERN_ID constant and an early-return check immediately before
      the exclude-family coverage computation. When --delete-excluded appears in a delete-mode
      state-dir mirror command, classify_mirror_command() now returns ok=False, dangerous=True
      with pattern_id="delete-excluded-state-mirror" and a warning explaining why excludes
      cannot protect palace data. Added three regression tests:
      test_delete_excluded_always_blocked_even_with_all_excludes (full-excludes, human output),
      test_delete_excluded_json_output (JSON path), and
      test_delete_excluded_non_state_dir_remains_ok (boundary: non-state dir remains OK).

  - id: F-2
    title: "Wrapper commands (sudo rsync, env FOO=1 rsync) bypass the guard"
    severity: medium
    location: "mempalace_code/mirror_preflight.py:108"
    claim: >
      The classifier identifies rsync by checking tokens[0].split('/')[-1] == 'rsync'.
      A command like 'sudo rsync -a --delete ~/.mempalace/ host:.mempalace/' has tokens[0]='sudo',
      so cmd_basename='sudo' != 'rsync' and the function returns ok=True without inspection.
      This is a plausible operator command shape that escapes the guard. Identified as P2/Medium
      by the Codex hardening review.
    decision: backlogged
    backlog_slug: MIRROR-PREFLIGHT-WRAPPER-DETECTION

totals:
  fixed: 1
  backlogged: 1
  dismissed: 0

fixes_applied:
  - "mirror_preflight.py: block --delete-excluded for MemPalace state-dir mirrors unconditionally (DELETE_EXCLUDED_PATTERN_ID); added early-return before exclude-family check"
  - "tests/test_cli.py: add three --delete-excluded regression tests covering human output, JSON output, and non-state-dir boundary"

new_backlog:
  - slug: MIRROR-PREFLIGHT-WRAPPER-DETECTION
    summary: "Extend mirror preflight to detect rsync wrapped in sudo/env/sh -c"
