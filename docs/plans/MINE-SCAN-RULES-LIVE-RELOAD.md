---
slug: MINE-SCAN-RULES-LIVE-RELOAD
goal: "Reload scan_skip_* rules at watcher batch boundaries so config edits affect the next project event without restart"
risk: low
risk_note: "Watcher-only change that swaps immutable scan-rule snapshots; no storage or mining semantics change."
files:
  - path: mempalace/watcher.py
    change: "Add config mtime snapshot/reload helper and call it once per watchfiles debounce batch in watch_and_mine() and watch_all() file-save mode before relevance filtering."
  - path: tests/test_watcher.py
    change: "Add focused watcher tests for live scan-rule reload, malformed config fallback, missing-to-created config boundary, and one refresh check per batch."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_watcher.py::TestWatchAndMine::test_watch_reload_scan_rules_after_config_edit -q` is run"
    then: "a fake mid-watch config edit adding workspace.json to scan_skip_files makes the following workspace.json change irrelevant, so only the initial mine call is recorded."
  - id: AC-2
    when: "`python -m pytest tests/test_watcher.py::TestWatchAll::test_watch_all_on_save_reload_scan_rules_after_config_edit -q` is run"
    then: "watch_all(..., on_commit=False) observes the same config edit before grouping file events and does not re-mine the project for the now-skipped file."
  - id: AC-3
    when: "`python -m pytest tests/test_watcher.py::TestWatchScanRuleReload::test_malformed_config_keeps_last_good_rules -q` is run"
    then: "a malformed config.json written before the next event batch does not raise and the previous ScanFilterRules still decide relevance for that batch."
  - id: AC-4
    when: "`python -m pytest tests/test_watcher.py::TestWatchScanRuleReload::test_config_created_after_watch_start_reloads_rules -q` is run"
    then: "a watcher started with no config.json switches from defaults to the newly-created scan_skip_files rules on the next batch."
  - id: AC-5
    when: "`python -m pytest tests/test_watcher.py::TestWatchScanRuleReload::test_reload_check_runs_once_per_batch -q` is run"
    then: "a batch containing multiple changed source files performs one config freshness check before filtering all paths."
out_of_scope:
  - "Watching ~/.mempalace/config.json with a separate watchfiles stream or background thread."
  - "Reloading unrelated config settings such as palace_path, backup settings, spellcheck, or entity detection."
  - "Triggering a mine cycle solely because config.json changed with no project file event."
  - "Changing scan_skip_* defaults, normalization, glob semantics, or include_ignored precedence."
  - "Changing watch_all on-commit behavior beyond preserving its existing commit-triggered mine path."
---

## Design Notes

- Prefer mtime polling at the existing debounce batch boundary because the config file normally lives outside the watched project tree. Do not add config.json to watchfiles paths.
- Add a small watcher-local snapshot helper, for example `_ScanRulesSnapshot`, containing the current immutable `ScanFilterRules`, the resolved `~/.mempalace/config.json` path, and the last observed mtime value.
- Resolve the config path lazily from `Path(os.path.expanduser("~/.mempalace/config.json"))` so tests can isolate behavior by monkeypatching `HOME`.
- Startup should still perform one `get_scan_filter_rules()` load. Recording the initial mtime is acceptable; do not perform extra scans or watch setup before the initial mine.
- At the top of each `watchfiles.watch(...)` batch, refresh the snapshot once before `_is_relevant_change()` is called. Use the returned local `scan_rules` for every path in that batch.
- In `watch_and_mine()`, refresh before the `relevant = [...]` comprehension. In `watch_all(..., on_commit=False)`, refresh before grouping events by project. On-commit mode has no relevance filtering; normal mine calls can keep loading current config through `mine()`.
- Treat missing/deleted config as a valid state that reloads to defaults. Treat unreadable or malformed JSON as a failed refresh: keep the last good rules and do not crash the watcher.
- To avoid repeated warnings or parse attempts for the same malformed write, the helper may record the observed bad mtime while retaining the previous rule object. A later fixed write will have a new mtime and can reload normally.
- Atomicity is just local assignment: `ScanFilterRules` is immutable, and each event loop processes one batch at a time, so swapping the snapshot before filtering avoids torn reads without locks.
- Tests should use temporary `HOME` directories and fake `watchfiles.watch` batches that edit config immediately before yielding the next project event. Avoid depending on the developer's real `~/.mempalace/config.json`.
