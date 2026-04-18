slug: MINE-WATCH
round: 1
date: 2026-04-18
commit_range: 526c0c4..21b48a7
findings:
  - id: F-1
    title: "CLI ImportError guard won't catch missing watchfiles"
    severity: low
    location: "mempalace/cli.py:163"
    claim: >
      The try/except ImportError block around `from .watcher import watch_and_mine`
      is intended to guide users to install mempalace[watch], but watchfiles is
      imported lazily inside watch_and_mine() (not at watcher module import time).
      The guard will never fire for the missing-watchfiles case. The error message
      "Error importing watcher: {exc}" also does not mention mempalace[watch], so
      if it did trigger due to some other module-level failure it would be unhelpful.
      The actual "watchfiles not installed" path IS handled correctly inside
      watch_and_mine() with a clear, actionable error. The guard is vestigial.
    decision: dismissed

  - id: F-2
    title: "matcher_cache not invalidated when .gitignore changes during watch"
    severity: low
    location: "mempalace/watcher.py:157"
    claim: >
      The matcher_cache dict is built once per watch_and_mine() invocation and
      is never cleared or partially invalidated. If a .gitignore file is added,
      modified, or deleted while the watcher is running, the cached GitignoreMatcher
      instances become stale. Consequence: files that should now be gitignored
      continue to trigger re-mine cycles; files that should no longer be ignored
      may not trigger re-mines on next change. Severity is low — .gitignore edits
      during an active watch session are rare, and restarting the watcher is a
      reasonable workaround.
    decision: backlogged
    backlog_slug: MINE-WATCH-GITIGNORE-CACHE

totals:
  fixed: 0
  backlogged: 1
  dismissed: 1

fixes_applied: []

new_backlog:
  - slug: MINE-WATCH-GITIGNORE-CACHE
    summary: >
      Invalidate gitignore matcher_cache in --watch mode when .gitignore files
      change so stale ignore rules don't cause spurious or missed re-mine cycles.
