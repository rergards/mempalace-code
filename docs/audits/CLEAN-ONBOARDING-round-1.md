slug: CLEAN-ONBOARDING
round: 1
date: 2026-05-01
commit_range: 09f83be..HEAD
findings:
  - id: F-1
    title: "AC-1/AC-4/AC-6 tests asserted config shape but not derived wing value"
    severity: low
    location: "tests/test_cli.py:172"
    claim: "Three new init tests asserted only `'wing' in cfg` and `'rooms' in cfg`. The plan's AC-1 explicitly requires the wing be 'derived' from the directory name, and AC-6 requires the same shape as the default path. Without value assertions, a regression that produced an empty/incorrect wing or zero rooms could pass the tests."
    decision: fixed
    fix: "Tightened assertions in test_init_default_writes_config_without_prompt, test_init_flat_project_generates_general_room_without_prompt, and test_init_yes_compatibility_is_non_interactive to check the derived wing name and that rooms is a non-empty list with named entries."
  - id: F-2
    title: "Redundant directory existence check in detect_rooms_local"
    severity: info
    location: "mempalace/room_detector_local.py:324"
    claim: "cli.cmd_init now validates the directory with the stricter `is_dir()` before any side effects, so the `not project_path.exists()` guard inside detect_rooms_local is unreachable from the CLI path. Function remains a public entry point so the guard is defensive-in-depth, not dead code."
    decision: dismissed
  - id: F-3
    title: "--yes combined with --interactive is contradictory but allowed"
    severity: info
    location: "mempalace/cli.py:132"
    claim: "Both flags can be passed together. cmd_init forwards both into detect_rooms_local but only the interactive flag affects behavior, so --interactive wins. This matches the documented semantics ('--yes' is a backward-compatible no-op for room prompts) and is not a regression."
    decision: dismissed
  - id: F-4
    title: "cmd_onboarding does not validate the directory exists"
    severity: info
    location: "mempalace/cli.py:152"
    claim: "Unlike cmd_init, cmd_onboarding passes args.dir straight into run_onboarding without an `is_dir()` precheck. run_onboarding's only path-sensitive call is the optional auto-detect entity scan, which already swallows exceptions. Inconsistency with cmd_init but not a bug."
    decision: dismissed
totals:
  fixed: 1
  backlogged: 0
  dismissed: 3
fixes_applied:
  - "Tightened init test assertions to verify the derived wing name and the room list shape, not just key presence."
new_backlog: []
