slug: MINE-APP-SCAN-EXCLUDES-PR4
round: 1
date: "2026-05-01"
commit_range: f91b067..d59b19c
findings:
  - id: F-1
    title: "_normalize_scan_list silently coerces non-strings via str()"
    severity: medium
    location: "mempalace/config.py:287"
    claim: >
      When a user's config contains non-string entries (e.g. ``[None, 123]``), the original
      implementation coerced each item with ``str()``, producing bogus skip entries like
      ``"None"`` and ``"123"``. These would silently exclude any file or directory that
      happened to be named ``None`` or ``123``. This violates the principle of least surprise
      for malformed config — better to drop non-strings entirely so users notice the typo.
    decision: fixed
    fix: >
      Replaced the ``str()`` coercion fallback with an ``isinstance(item, str)`` skip. Non-
      string list items are now dropped rather than coerced. The function still falls back
      to the default when the top-level value is not a list/tuple.
  - id: F-2
    title: "Test for invalid scan_skip_* values used weak assertions and asserted coercion"
    severity: low
    location: "tests/test_config.py:191"
    claim: >
      ``test_scan_skip_invalid_values_fall_back_safely`` asserted ``"workspace.json" in
      cfg2.scan_skip_files`` rather than checking the full list. It also documented (but did
      not assert) the silent str() coercion of ``None`` and ``123`` to ``"None"`` and
      ``"123"``. A regression that broke or changed coercion behavior would not have failed
      this test.
    decision: fixed
    fix: >
      Strengthened to ``assert cfg2.scan_skip_files == ["workspace.json"]`` and added explicit
      negative assertions that ``"None"`` and ``"123"`` are NOT present. The test now pins the
      drop-non-strings behavior set in F-1.
  - id: F-3
    title: "skip_globs do not prune the matched directory at walk time"
    severity: low
    location: "mempalace/miner.py:367"
    claim: >
      ``is_scan_excluded(path, ..., is_dir=True)`` only matches directories by basename
      (``skip_dirs``); a glob like ``build/**`` does not prune the ``build`` directory at
      ``os.walk`` time because ``fnmatch.fnmatch("build", "build/**")`` is False. The walker
      still descends into ``build/`` and filters individual files. Correct, but wastes IO on
      large generated trees.
    decision: backlogged
    backlog_slug: MINE-SCAN-GLOB-DIR-PRUNE
  - id: F-4
    title: "Watcher loads scan_rules once at start; config edits require restart"
    severity: low
    location: "mempalace/watcher.py:162"
    claim: >
      ``watch_and_mine()`` and ``watch_all()`` call ``get_scan_filter_rules()`` once before
      the watch loop. Editing ``~/.mempalace/config.json`` while a watcher is running has no
      effect until the user restarts the daemon. For long-running watchers this is
      surprising — users expect config edits to take effect on the next event batch.
    decision: backlogged
    backlog_slug: MINE-SCAN-RULES-LIVE-RELOAD
  - id: F-5
    title: "fnmatch-based _glob_match treats * as matching path separators"
    severity: info
    location: "mempalace/miner.py:351"
    claim: >
      ``_glob_match`` uses Python's ``fnmatch``, where ``*`` matches any character including
      ``/``. As a result, a pattern like ``*.tmp`` matches ``foo/bar.tmp`` at any depth, not
      just the project root. This differs from gitignore semantics (where ``*`` does not
      cross ``/``). The ``**`` zero-segment workaround handles the most common
      ``a/**/b`` case correctly.
    decision: dismissed
    fix: >
      Behavior is intentional and consistent with fnmatch. README and docs already describe
      ``scan_skip_globs`` as "POSIX glob"; tightening to gitignore semantics would be a
      breaking change for the few users who already configure these patterns. No change.
totals:
  fixed: 2
  backlogged: 2
  dismissed: 1
fixes_applied:
  - "Dropped str() coercion in _normalize_scan_list — non-string config entries are now skipped instead of silently turned into bogus skip names."
  - "Strengthened test_scan_skip_invalid_values_fall_back_safely with exact-list assertions and explicit negative checks for the dropped non-string entries."
new_backlog:
  - slug: MINE-SCAN-GLOB-DIR-PRUNE
    summary: "Prune directories at walk-time when fully covered by skip_globs"
  - slug: MINE-SCAN-RULES-LIVE-RELOAD
    summary: "Live-reload scan_skip_* config in watcher loops without restart"
