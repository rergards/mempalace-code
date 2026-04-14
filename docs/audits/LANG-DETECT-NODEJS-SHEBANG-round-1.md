slug: LANG-DETECT-NODEJS-SHEBANG
round: 1
date: 2026-04-14
commit_range: 8aef861..04dc17c
findings:
  - id: F-1
    title: "No nodejs+flags case in test_shebang_with_interpreter_flags"
    severity: info
    location: "tests/test_lang_detect.py:96"
    claim: >
      test_shebang_with_interpreter_flags covers python and shell with trailing
      flags (e.g. #!/usr/bin/python3 -u, #!/bin/bash -e) but does not include a
      nodejs variant (e.g. #!/usr/bin/nodejs -u). The flag-stripping code is
      language-agnostic (extracts parts[0] or parts[1], never further parts) so
      the gap is cosmetic — the code path for nodejs+flags is identical to the
      already-tested paths. No regression risk.
    decision: dismissed

totals:
  fixed: 0
  backlogged: 0
  dismissed: 1

fixes_applied: []

new_backlog: []
