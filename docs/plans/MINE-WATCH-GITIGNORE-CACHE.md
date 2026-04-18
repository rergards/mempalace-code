---
slug: MINE-WATCH-GITIGNORE-CACHE
goal: "Invalidate matcher_cache entries when .gitignore files change during --watch, so newly-ignored files stop triggering re-mines"
risk: low
risk_note: "Additive-only change; cache miss just reloads from disk. No new deps. Non-gitignore events are unaffected."
files:
  - path: mempalace/watcher.py
    change: "Add module-level _invalidate_gitignore_cache() helper; call it inside the watch loop before the relevant= comprehension"
  - path: tests/test_watcher.py
    change: "Add unit tests for _invalidate_gitignore_cache() covering eviction and no-op cases"
acceptance:
  - id: AC-1
    when: ".gitignore is modified while --watch is running"
    then: "matcher_cache entry for that directory is evicted before _is_relevant_change() runs for other files in the same batch"
  - id: AC-2
    when: ".gitignore is added (created) while --watch is running"
    then: "matcher_cache entry (previously None, no-rules) is evicted; rebuilt from new file on next _is_relevant_change() call"
  - id: AC-3
    when: ".gitignore is deleted while --watch is running"
    then: "matcher_cache entry (previously stale GitignoreMatcher) is evicted; rebuilt to None on next call"
  - id: AC-4
    when: "a non-.gitignore file event fires"
    then: "matcher_cache is not modified"
  - id: AC-5
    when: "existing tests run"
    then: "all pass unchanged"
out_of_scope:
  - "Global gitignore (~/.gitignore_global, ~/.config/git/ignore) — not cached by matcher_cache"
  - "Repo-level .git/info/exclude — not cached by matcher_cache"
  - ".gitignore events triggering a re-mine (they correctly remain irrelevant to miner output)"
  - "Recursive eviction of child-dir cache entries when a parent .gitignore changes (child matchers are independent; the child's dir entry is still valid)"
---

## Design Notes

- **Extract helper for testability.** Add `_invalidate_gitignore_cache(changes, matcher_cache: dict) -> None` at module level in `watcher.py`. The function iterates `changes`, checks `Path(path).name == ".gitignore"`, and calls `matcher_cache.pop(Path(path).parent, None)`. Inline logic would be untestable since `matcher_cache` is local to `watch_and_mine()`.

- **Call site.** Insert `_invalidate_gitignore_cache(changes, matcher_cache)` as the **first** statement inside `for changes in watchfiles.watch(...)`, before the `relevant = [...]` list comprehension. Order matters: the invalidation must precede `_is_relevant_change()` calls so that a same-batch event (`.gitignore` change + affected file change) uses fresh matcher state.

- **Cache key alignment.** `matcher_cache` is keyed by directory `Path` (the dir that owns the `.gitignore`, not the `.gitignore` file path). `load_gitignore_matcher(dir_path, cache)` in `miner.py` uses the same key. So `Path(path).parent` is the correct key to pop.

- **`load_gitignore_matcher` handles None correctly.** `GitignoreMatcher.from_dir()` returns `None` when no `.gitignore` exists. `load_gitignore_matcher` caches `None` too. After a delete event, the next call will re-cache `None` — correct, no rules active.

- **Only immediate parent dir.** A `.gitignore` event pops only its own dir's cache entry. Child-dir cache entries remain valid (they own separate `.gitignore` files). Parent-dir entries also remain valid — the parent's rules didn't change. This is intentional and correct.

- **`.gitignore` events do not trigger re-mines.** `_is_relevant_change()` filters out `.gitignore` because: no extension (`suffix == ""`), not in `READABLE_EXTENSIONS`, not in `KNOWN_FILENAMES`, not in `SKIP_FILENAMES`. The invalidation still fires (from raw `changes`) even though `relevant` will drop the event. No behavioral change to re-mine triggering.

- **Test approach.** Directly call `_invalidate_gitignore_cache()` with a controlled `dict` and `set` of fake changes. Two unit tests suffice:
  1. `.gitignore` modified event → dir key evicted from cache.
  2. Non-`.gitignore` event → cache unchanged.
  Import `Change` from `watchfiles` for realistic change tuples.
