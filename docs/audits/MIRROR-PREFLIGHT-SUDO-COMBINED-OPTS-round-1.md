slug: MIRROR-PREFLIGHT-SUDO-COMBINED-OPTS
round: 1
date: 2026-05-29
commit_range: ccc1cb4..1d953fe
findings:
  - id: F-1
    title: "consumed_next=True path in compact bundle has no regression test"
    severity: medium
    location: "tests/test_cli.py:1406"
    claim: >
      The compact-bundle parser in _skip_wrapper_flags has a branch where a one-arg
      flag occupies the last character of a bundle and the following token is consumed
      as its argument value (e.g. sudo -nu root rsync ...). This branch is exercised by
      real sudo invocations but no test case covers it, leaving the path unprotected
      against regression.
    decision: fixed
    fix: >
      Added "sudo -nu root rsync -a --delete ~/.mempalace/ user@host:.mempalace/" to the
      destructive cases list in test_sudo_combined_option_delete_mode_state_mirror_missing_excludes_exits_nonzero,
      and "sudo -nu root rsync -a ~/.mempalace/ user@host:.mempalace/" to the safe cases
      list in test_sudo_combined_option_safe_mirror_remains_ok. Both new entries target
      the consumed_next=True code path and pass.

  - id: F-2
    title: "no_arg_chars / one_arg_chars are recomputed on every _skip_wrapper_flags call"
    severity: info
    location: "mempalace_code/mirror_preflight.py:161"
    claim: >
      The frozensets no_arg_chars and one_arg_chars are derived from the constant module-level
      sets _SUDO_FLAGS_NO_ARG / _SUDO_FLAGS_ONE_ARG on each invocation. The sets are tiny
      (~14 entries each) and the function is called at most once per classify_mirror_command
      call, so there is no observable performance impact.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 0
  dismissed: 1

fixes_applied:
  - "Added consumed_next=True test cases (sudo -nu root rsync ...) to both the destructive and safe combined-option test methods"

new_backlog: []
