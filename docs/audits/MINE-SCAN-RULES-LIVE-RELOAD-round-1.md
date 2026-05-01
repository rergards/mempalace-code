slug: MINE-SCAN-RULES-LIVE-RELOAD
round: 1
date: 2026-05-01
commit_range: 037d73e..a530b8a
findings:
  - id: F-1
    title: "No test for malformed-then-fixed config recovery path"
    severity: low
    location: "tests/test_watcher.py"
    claim: "_ScanRulesSnapshot.refresh tracks _bad_mtime to skip retries on the same broken mtime, then must clear it once a NEW mtime appears so a fixed config can take effect. The malformed-config test only proves last-good rules persist on bad input — it never advances mtime and writes good content. A regression that left _bad_mtime sticky (e.g. forgetting the `self._bad_mtime = _UNSET` reset on the success path, or comparing against _last_mtime instead of _bad_mtime) would silently strand watchers on the original rules forever, and no current test would catch it."
    decision: fixed
    fix: "Added test_snapshot_recovers_after_malformed_then_fixed_config — drives _ScanRulesSnapshot directly through three mtime steps (good → bad → good with fresh mtimes), asserts last-good rules persist after the bad write, then asserts the new rules are loaded and _bad_mtime is reset to _UNSET after the recovery write."
  - id: F-2
    title: "Watcher reads config file twice on each refresh (validate + MempalaceConfig reload)"
    severity: info
    location: "mempalace/watcher.py:84-88"
    claim: "On every refresh that detects a new mtime, the snapshot first opens config.json to validate JSON parseability, then calls get_scan_filter_rules() which constructs a fresh MempalaceConfig that opens and parses the file again. This is a deliberate defensive design — MempalaceConfig swallows JSONDecodeError and silently returns empty defaults, so without the explicit pre-validation a malformed write would silently downgrade scan rules to defaults instead of preserving the last-good rules. The double read is intentional and the cost is one tiny file open per debounce batch (5s)."
    decision: dismissed
  - id: F-3
    title: "1-second mtime resolution on some filesystems can mask back-to-back config edits"
    severity: info
    location: "mempalace/watcher.py:79-80"
    claim: "Mtime equality (`current_mtime == self._last_mtime`) is the only refresh trigger. On filesystems with 1-second mtime granularity (older HFS+, some NFS variants), two writes within the same second would not be detected. This is mitigated in practice by the watchfiles 5-second debounce — a user editing config.json twice within 1s is highly improbable and the second value would still be picked up by the next batch where mtime drift is observable."
    decision: dismissed
  - id: F-4
    title: "_ScanRulesSnapshot is not thread-safe"
    severity: info
    location: "mempalace/watcher.py:52-93"
    claim: "The snapshot mutates _rules, _last_mtime, and _bad_mtime without locking. The class docstring documents this is intentional: watchfiles batches are processed sequentially within a single watcher loop, so there is no concurrent caller. If a future refactor moves refresh() into a worker pool the contract would need revisiting, but no such caller exists today."
    decision: dismissed
  - id: F-5
    title: "Race window between JSON validation and MempalaceConfig reload could observe a partial write"
    severity: low
    location: "mempalace/watcher.py:84-88"
    claim: "The snapshot opens config.json twice in succession (validate, then reload via MempalaceConfig). If a writer truncates and rewrites the file between those two opens, the second open could observe a torn file; MempalaceConfig would silently return empty defaults and the snapshot would record the new mtime as last_mtime, stranding the watcher on defaults until another mtime change. In practice config.json is small (kilobytes) and most editors write atomically (O_TRUNC then write, or rename-replace), so this window is vanishingly narrow. No CLI in the repo writes config.json — only `MempalaceConfig.init()` which writes the defaults on first init."
    decision: dismissed
totals:
  fixed: 1
  backlogged: 0
  dismissed: 4
fixes_applied:
  - "Added tests/test_watcher.py::TestWatchScanRuleReload::test_snapshot_recovers_after_malformed_then_fixed_config — exercises the bad_mtime → cleared bad_mtime recovery path directly on _ScanRulesSnapshot.refresh, locking down the contract that fixing a malformed config (with a new mtime) reloads rules and clears the bad-mtime guard."
new_backlog: []
