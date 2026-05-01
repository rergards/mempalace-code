slug: FUT-MULTI-REPO
phase: polish
date: 2026-05-02
commit_range: 2dc8388..28678ba
reverted: false
findings:
  - id: P-1
    title: "config_errors list stores values that are never read back"
    category: volume
    location: "mempalace_code/cli.py:354 and mempalace_code/watcher.py:430"
    evidence: >
      cli.py: `config_errors.append((Path(proj["path"]).name, str(exc)))` — tuple
      elements are never accessed; only `if config_errors:` and `len(config_errors)`
      are used. watcher.py: same pattern with `config_errors.append(proj_path)`.
    decision: fixed
    fix: "Replaced config_errors list with config_error_count integer counter in both cli.py and watcher.py"

  - id: P-2
    title: "getattr(args, 'new_only', False) defensive fallback on always-present argparse attribute"
    category: defensive
    location: "mempalace_code/cli.py:414"
    evidence: >
      `new_only = getattr(args, "new_only", False)` — the `--new-only` argument is
      unconditionally added to the `mine-all` argparse subparser, so `args.new_only`
      is always present when cmd_mine_all is invoked through the CLI.
    decision: fixed
    fix: "Changed to `new_only = args.new_only`"

totals:
  fixed: 2
  dismissed: 0
fixes_applied:
  - "cli.py: config_errors list → config_error_count counter"
  - "watcher.py: config_errors list → config_error_count counter"
  - "cli.py: getattr(args, 'new_only', False) → args.new_only"
