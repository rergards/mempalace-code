slug: MIRROR-PREFLIGHT-WRAPPER-DETECTION
round: 1
date: 2026-05-29
commit_range: 4f6be24..ac24c3e
findings:
  - id: F-1
    title: "test_malformed_wrapper_shell_text_reports_parse_error only checks exit code, not error message"
    severity: low
    location: "tests/test_cli.py:1371"
    claim: >
      The test asserts exit code 2 but does not verify that a parse error message is printed to
      stderr. AC-6 requires both exit code 2 and that the error is reported. Without the stderr
      assertion, a regression that silently exits 2 with no output would still pass.
    decision: fixed
    fix: "Added `captured = capsys.readouterr()` and asserted 'ERROR' in captured.err after the exit code check."

  - id: F-2
    title: "test_simple_shell_wrapped_delete_mode_state_mirror_is_classified uses overly weak exit-code assertion"
    severity: low
    location: "tests/test_cli.py:1337"
    claim: >
      The test only asserts `exc.value.code != 0`. A parse error (exit 2) would satisfy this
      condition even though the command was not classified as a dangerous mirror (exit 1). The
      test does not distinguish between classification (blocked) and a tokenisation failure,
      so a regression where the sh/bash -c wrapper produces a spurious parse error instead of
      a blocking verdict would pass undetected.
    decision: fixed
    fix: >
      Changed assertion to `exc.value.code == 1` and added check that 'delete-mode-state-mirror'
      appears in stdout, confirming the command was classified (not errored) by the guard.

  - id: F-3
    title: "Combined sudo short options (-uroot) bypass wrapper detection"
    severity: medium
    location: "mempalace_code/mirror_preflight.py:152"
    claim: >
      `_skip_wrapper_flags` matches only exact tokens from `_SUDO_FLAGS_ONE_ARG` (e.g. '-u').
      Combined short-option forms such as `-uroot` are not matched, so `_skip_wrapper_flags`
      breaks at the `-uroot` token and returns it as the first element of effective_tokens.
      The classifier then sees cmd_basename='-uroot', which is not 'rsync', and returns ok=True.
      `sudo -uroot rsync --delete ~/.mempalace/ user@host:.mempalace/` is therefore classified
      as safe even though it executes a destructive state-dir mirror.
    decision: backlogged
    backlog_slug: MIRROR-PREFLIGHT-SUDO-COMBINED-OPTS

  - id: F-4
    title: "env -S 'rsync ...' gives misleading parse error instead of detecting danger"
    severity: info
    location: "mempalace_code/mirror_preflight.py:198"
    claim: >
      `_ENV_FLAGS_ONE_ARG` includes `-S/--split-string`. The env branch consumes `-S` and its
      argument token (the full rsync command string) and returns empty tokens. This produces
      "empty command after wrapper resolution" (exit 2, parse error) rather than detecting the
      dangerous mirror. The behaviour is fail-safe (no false OK), but the error message is
      misleading — the user gets a parse error instead of a blocking verdict. Handling `-S`
      like `sh -c` (splitting the string) would improve accuracy without changing security posture.
    decision: dismissed

totals:
  fixed: 2
  backlogged: 1
  dismissed: 1

fixes_applied:
  - "Strengthened test_malformed_wrapper_shell_text_reports_parse_error: added stderr assertion verifying ERROR message is present (F-1)"
  - "Strengthened test_simple_shell_wrapped_delete_mode_state_mirror_is_classified: tightened to exit code 1 and added stdout assertion for delete-mode-state-mirror pattern_id (F-2)"

new_backlog:
  - slug: MIRROR-PREFLIGHT-SUDO-COMBINED-OPTS
    summary: "Detect combined sudo short-option forms (e.g. -uroot) in preflight mirror wrapper detection"
