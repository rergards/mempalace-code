slug: MINE-MULTI-INCLUDE-IGNORED-TEST
round: 1
date: 2026-05-01
commit_range: d0328ea..HEAD
findings:
  - id: F-1
    title: "Test does not cover multiple --include-ignored flags accumulating across the appended list"
    severity: info
    location: "tests/test_cli.py:1190-1210"
    claim: >
      The new test passes a single --include-ignored argument with a
      comma-separated value. The CLI uses `action="append"` (cli.py:1287-1290),
      so users may pass --include-ignored multiple times; the cmd_mine_all
      loop at cli.py:404-406 iterates over each raw value and extends. A
      regression that only consumed args.include_ignored[0] would still pass
      this test. The task scope explicitly says "Add one test in
      TestMineAllCommand ... that passes --include-ignored with a
      comma-separated value" — multi-flag accumulation is out of the stated
      acceptance criteria, and existing test_cli.py coverage for the same
      argparse wiring elsewhere in the file is comparable in shape. Left as
      an info-level coverage gap rather than a fix.
    decision: dismissed

  - id: F-2
    title: "Test does not exercise the empty-token filter branch (`if part.strip()`)"
    severity: info
    location: "tests/test_cli.py:1190-1210"
    claim: >
      The CLI's split logic (cli.py:406) drops empty/whitespace-only tokens:
      `extend(part.strip() for part in raw.split(",") if part.strip())`. The
      test input "ignored/a.py, ignored/b.py" produces no empty tokens after
      split, so the filter branch is not exercised. A regression that removed
      the `if part.strip()` filter would silently start passing empty strings
      to mine() but this test would still pass. Out of scope per the task's
      single-test constraint; the verbatim acceptance criterion only requires
      ['pathA', 'pathB'] from 'pathA,pathB'.
    decision: dismissed

  - id: F-3
    title: "Equivalent comma-splitting logic in cmd_mine (single-project) is also untested at CLI level"
    severity: info
    location: "mempalace_code/cli.py:235-237"
    claim: >
      cmd_mine performs the same comma-split + strip on
      args.include_ignored as cmd_mine_all. The single-project path has no
      analogous CLI-level test. This is the same regression risk noted in the
      task description but for `mine` rather than `mine-all`. Strictly
      out of scope for this slug; not promoted to backlog because the value
      add (one duplicated test of trivial argparse glue) is small and
      coverage at the miner layer in tests/test_miner.py already pins the
      include_ignored behavior end-to-end.
    decision: dismissed

totals:
  fixed: 0
  backlogged: 0
  dismissed: 3

fixes_applied: []

new_backlog: []
