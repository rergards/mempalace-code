---
slug: MINE-MULTI-INCLUDE-IGNORED-TEST
goal: "Add a TestMineAllCommand test proving mine-all splits comma-separated --include-ignored values before forwarding them to mine()"
risk: low
risk_note: "Test-only change in existing CLI test class; no production behavior changes"
files:
  - path: tests/test_cli.py
    change: "Add one mine-all test with an initialized temp project, patched store, and fake mine() that asserts include_ignored is forwarded as a split list"
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_cli.py::TestMineAllCommand::test_mine_all_include_ignored_comma_splits_to_mine -q` runs with `--include-ignored ignored/a.py, ignored/b.py`"
    then: "the test passes because the recorded mine() kwargs include `include_ignored == [\"ignored/a.py\", \"ignored/b.py\"]`"
  - id: AC-2
    when: "the same targeted test is run against a regression that forwards `args.include_ignored` without comma splitting"
    then: "the test fails with an assertion showing the unsplit value differs from `[\"ignored/a.py\", \"ignored/b.py\"]`"
  - id: AC-3
    when: "the targeted test input includes whitespace after the comma"
    then: "the forwarded include_ignored list contains trimmed path strings and no leading-space path entry"
out_of_scope:
  - "Any production changes to mempalace_code/cli.py or miner behavior"
  - "Testing the single-project `mine` command's --include-ignored parsing"
  - "End-to-end filesystem scanning of ignored files"
---

## Design Notes

- Add the test inside `TestMineAllCommand`, near the existing pass-through/dispatch tests.
- Reuse `_make_initialized_project()` and `_run_mine_all()` so argument setup matches the rest of the mine-all tests.
- Patch `mempalace_code.storage.open_store` with `count_by.return_value = {}` so the project is not skipped as an existing wing.
- Patch `mempalace_code.miner.mine` with a side effect that records kwargs; assert exactly one call and inspect `mine_calls[0]["include_ignored"]`.
- Use one CLI value such as `["--include-ignored", "ignored/a.py, ignored/b.py"]` to cover comma splitting and whitespace trimming without adding a second test.
