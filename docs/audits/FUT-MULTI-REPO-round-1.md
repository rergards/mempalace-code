slug: FUT-MULTI-REPO
round: 1
date: "2026-05-02"
commit_range: 2dc8388..555b3c9
findings:
  - id: F-1
    title: "mine-all duplicate-wing check fires on uninitialized projects, blocking the whole batch"
    severity: high
    location: "mempalace_code/cli.py:391-406"
    claim: >
      cmd_mine_all() built wing_to_paths from every detected project (including
      uninitialized ones) and exited 1 if any wing collided. Uninitialized
      projects are skipped later at cli.py:423 and never call mine(), so they
      cannot corrupt the palace. Under the previous logic, a parent directory
      with one initialized project plus one uninitialized folder/clone whose
      derived name happened to match exit-1'd the entire batch, regressing the
      documented "sync initialized repos" behavior. The duplicate guard must
      consider only projects that will actually be mined.
    decision: fixed
    fix: >
      Restricted wing_to_paths construction to entries where
      entry["initialized"] is True, so only colliding initialized projects
      trigger the fatal duplicate error. Also moved the duplicate check above
      the dry-run branch so dry-run reflects what a real run would do.
      Regression covered by tests/test_cli.py::TestMineAllCommand::
      test_mine_all_uninit_wing_collision_does_not_block_initialized.

  - id: F-2
    title: "AC-5 only verified mocked mine() calls — no proof of distinct stored data across repos"
    severity: medium
    location: "tests/test_cli.py:1314, tests/test_miner.py:2822"
    claim: >
      The plan's AC-5 promised that two repos containing the same relative
      filename (src/settings.py) produce search hits with distinct wing names
      and full source_file paths. The CLI test only patched mine() and asserted
      kwargs differed; the miner test only compared two manually constructed
      path strings. A regression in drawer ID derivation, stored metadata, or
      search filtering would have passed both. The acceptance contract was not
      actually being verified end-to-end.
    decision: fixed
    fix: >
      Added test_mine_all_same_relative_filenames_distinct_in_storage which
      runs the real mine-all CLI (no mine() or open_store mocks) on two repos
      with src/settings.py, then queries the resulting LanceDB store and
      asserts: count_by("wing") contains both "alpha" and "beta"; search
      metadata for each wing points at its own repo's source_file; the two
      sets of source_file values are disjoint (no cross-repo aliasing).
totals:
  fixed: 2
  backlogged: 0
  dismissed: 0
fixes_applied:
  - "Restrict mine-all duplicate-wing check to initialized projects so uninit folders cannot abort the batch (cli.py)."
  - "Move mine-all duplicate-wing check above the dry-run branch so dry-run reflects real-run gating."
  - "Replace the mock-only AC-5 test with a real mine-all + LanceDB query integration test verifying distinct wings and source_file paths."
new_backlog: []
