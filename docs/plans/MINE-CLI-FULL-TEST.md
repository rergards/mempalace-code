---
slug: MINE-CLI-FULL-TEST
goal: "Add two tests to test_cli.py verifying that --full wires incremental=False and default wires incremental=True"
risk: low
risk_note: "Read-only test addition; mocks the mine() function so no storage or file system side effects"
files:
  - path: tests/test_cli.py
    change: "Add TestMineCommand class with test_mine_full_flag and test_mine_default_incremental"
acceptance:
  - id: AC-1
    when: "main() is invoked with ['mempalace', '--palace', ..., 'mine', dir, '--full']"
    then: "mempalace.miner.mine is called with incremental=False"
  - id: AC-2
    when: "main() is invoked with ['mempalace', '--palace', ..., 'mine', dir] (no --full)"
    then: "mempalace.miner.mine is called with incremental=True"
  - id: AC-3
    when: "pytest tests/test_cli.py -x -q is run"
    then: "all existing and new tests pass with no failures"
out_of_scope:
  - "Testing other mine flags (--dry-run, --limit, --no-gitignore, --wing, --agent)"
  - "Testing the convo_miner path (--mode convos)"
  - "Any changes to cli.py or miner.py"
---

## Design Notes

- The indirection being tested is: `args.full` (bool from argparse) → `incremental=not args.full` (kwarg to `mine()`). A mock assertion is the right tool — no need to run actual mining.
- Patch target: `mempalace.miner.mine`. `cmd_mine` does `from .miner import mine` inside the function, so patching at the module level (`mempalace.miner.mine`) will intercept the call correctly. Using `patch("mempalace.miner.mine")` is sufficient.
- The `dir` argument to `mine` CLI requires a path that exists (argparse itself doesn't validate this, but `cmd_mine` passes it directly to `mine()` which is mocked, so any string works — use `str(tmp_path)` for clarity).
- Palace path is passed via `--palace` to avoid touching the default config path during tests.
- Both tests live in a new `TestMineCommand` class following the existing class-per-subcommand pattern in `test_cli.py`.
- No assertion on return value of `main()` needed — the mock prevents `SystemExit`; just verify the kwarg.
- Use `mock.call_args.kwargs["incremental"]` (Python 3.8+ `kwargs` attribute on `call_args`) to extract the specific kwarg.
