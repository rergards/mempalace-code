slug: WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD
round: 1
date: 2026-06-11
commit_range: 2c2716f..b187593
findings:
  - id: F-1
    title: "test_uninitialized_parent_root_refused only checks 'initialized' substring, missing root path and root shapes"
    severity: low
    location: "tests/test_watcher.py:684"
    claim: "AC-2 requires the error message to name the refused root path and the supported root shapes. The test asserted only match='initialized', which passes for any message containing that word. If the error message were refactored to drop the root path or the 'Supported watch roots' enumeration, the test would still pass but the requirement would be silently broken."
    decision: fixed
    fix: "Replaced the single match='initialized' assertion with an explicit check that str(tmp_path) appears in the message (root named) and that 'Supported watch roots' appears (shapes listed), using pytest.raises as a context manager."

  - id: F-2
    title: "VER-7 verification command fails in environments where 'rg' resolves to BSD grep"
    severity: info
    location: "docs/plans/WATCH-MACOS-FSEVENTS-RUNAWAY-GUARD.md"
    claim: "The plan's VER-7 uses 'rg -q \"launchctl (bootout|unload)\"' which relies on alternation grouping. In this environment 'rg' is aliased to BSD grep, which requires -E for extended regex; without it the grouping is treated as a literal match and the command returns exit 1 even though the content is present. Manually confirmed: launchctl unload at README.md:285,304 and launchctl bootout at README.md:301. 'watch status' appears at README.md:276."
    decision: dismissed

  - id: F-3
    title: "Test assertion on private '_ignore_dirs' attribute of watchfiles.DefaultFilter"
    severity: low
    location: "tests/test_watcher.py:763"
    claim: "The AC-5 test asserts 'all(d in filt._ignore_dirs for d in SKIP_DIRS)' using a private/internal compiled attribute. The attribute currently exists (confirmed with watchfiles 0.24+) but would silently break if watchfiles renames it. The production code does not use _ignore_dirs; only the test does."
    decision: dismissed

totals:
  fixed: 1
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "Strengthened test_uninitialized_parent_root_refused to assert the error message names the refused root path (str(tmp_path)) and lists 'Supported watch roots', fully covering AC-2's requirement."

new_backlog: []
