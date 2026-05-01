---
slug: FUT-MULTI-REPO
goal: "Finish multi-project palace sync so initialized repos mine into one palace with unique wings and incremental re-mining"
risk: medium
risk_note: "Touches existing mine-all and watch_all behavior, but keeps storage schema and single-project mine() unchanged; risk is limited to multi-project CLI/watch routing and mitigated by targeted tests."
files:
  - path: mempalace_code/miner.py
    change: "Add a safe wing-resolution helper for multi-project callers: prefer explicit wing from mempalace.yaml/mempal.yaml, otherwise derive from git origin remote, otherwise normalized folder name. Preserve derive_wing_name() as the git/folder auto-name helper for existing callers."
  - path: mempalace_code/cli.py
    change: "Update cmd_mine_all() to use the shared wing resolver, detect unresolved duplicate wings before mining, mine existing wings incrementally by default, add --new-only for the previous skip-existing behavior, and keep --force accepted as a deprecated compatibility flag."
  - path: mempalace_code/watcher.py
    change: "Use the same wing resolver and duplicate-wing guard in watch_all() before initial mining or watch registration so two repos cannot be silently watched into one wing."
  - path: tests/test_miner.py
    change: "Add unit coverage for wing resolution order, normalization, malformed config handling, and drawer-id/source_file isolation for same relative file names in different repos."
  - path: tests/test_cli.py
    change: "Extend TestMineAllCommand for default incremental sync of existing wings, --new-only skip behavior, configured wing overrides, duplicate-wing failure output, and same-basename cross-repo mining."
  - path: tests/test_watcher.py
    change: "Add watch_all tests proving configured wings are used and duplicate wings fail before initial mine/watch registration."
  - path: README.md
    change: "Document mine-all as an incremental multi-project sync command, describe wing naming/override order, explain duplicate-wing resolution, and show --new-only for initial-add-only runs."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_cli.py::TestMineAllCommand::test_mine_all_syncs_existing_wings_incrementally_by_default -q` runs with the palace already containing wing `alpha`"
    then: "the recorded mine() call includes `wing_override == \"alpha\"` and `incremental is True`; output does not contain a skip-existing message for `alpha`"
  - id: AC-2
    when: "`python -m pytest tests/test_cli.py::TestMineAllCommand::test_mine_all_new_only_skips_existing_wings -q` runs with `--new-only` and the palace already containing wing `alpha`"
    then: "mine() is not called for `alpha`, another new project is still mined, and output contains the skip-existing message"
  - id: AC-3
    when: "`python -m pytest tests/test_miner.py::TestMultiProjectWingResolution::test_resolution_prefers_config_then_git_remote_then_folder -q` runs"
    then: "the observed wing names come from explicit config first, git origin repo name second, and normalized folder name when no remote is available"
  - id: AC-4
    when: "`python -m pytest tests/test_cli.py::TestMineAllCommand::test_mine_all_duplicate_wings_fail_before_mining -q` runs with two initialized projects resolving to the same wing"
    then: "the command exits 1, output names the duplicate wing and both project paths, and mine() is never called for the colliding projects"
  - id: AC-5
    when: "`python -m pytest tests/test_cli.py::TestMineAllCommand::test_mine_all_same_relative_filenames_stay_separate_by_wing -q` mines two repos that both contain `src/settings.py`"
    then: "the resulting search/code-search output includes two hits with distinct wing names and full source_file paths, with no duplicate drawer-id collision"
  - id: AC-6
    when: "`python -m pytest tests/test_watcher.py::TestWatchAll::test_watch_all_duplicate_wings_exit_before_initial_mine -q` runs"
    then: "watch_all exits 1 before calling mine() or watchfiles.watch(), and stderr reports the duplicate wing conflict"
out_of_scope:
  - "Recursive discovery of nested projects beyond immediate children of the parent directory"
  - "Workspace/monorepo package discovery such as npm workspaces, Cargo workspaces, or Lerna packages"
  - "Parallel mining or background job orchestration"
  - "Automatically running mempalace-code init for uninitialized projects"
  - "A new MCP tool for mine-all"
  - "Storage schema changes or embedding model changes"
  - "Conversation export mining across multiple roots"
---

## Design Notes

- Start from the existing `mine-all`/`watch_all` implementation. Do not recreate project scanning, file scanning, chunking, storage, or search plumbing.
- Keep `derive_wing_name(project_dir)` focused on automatic git-remote/folder naming. Add a separate resolver for multi-project callers so configured `wing:` values in `mempalace.yaml` can resolve collisions as the current warning text already suggests.
- Resolver order:
  - If `mempalace.yaml` or legacy `mempal.yaml` has a non-empty `wing`, normalize and use it.
  - Otherwise call `derive_wing_name(project_dir)` for git origin repo name with folder fallback.
  - If config exists but cannot be parsed, report that project as an error; do not silently fall back to a different wing.
- Duplicate-wing handling should happen before any mining starts. Treat duplicate resolved wings as a batch error and skip all projects in the colliding wing, rather than relying on first-wins ordering.
- Change `mine-all` from "initial add only" to "sync all initialized projects incrementally" by default. This matches `mine()` already being content-hash incremental and makes repeated multi-repo sync useful without a special flag.
- Add `--new-only` for callers that want the old behavior of skipping wings already present in the palace. Keep `--force` accepted for compatibility, but document that it is no longer required for incremental updates.
- `watch_all()` should reuse the same resolver and duplicate guard before its initial quiet mine and before registering watch paths.
- Same relative filenames are already protected by full `source_file` metadata plus wing-scoped drawer ids. Add regression coverage so this remains explicit while multi-repo behavior changes.
