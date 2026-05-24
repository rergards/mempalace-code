slug: CLI-READONLY-NON-SEARCH-CALLERS
round: 1
date: 2026-05-24
commit_range: e288a4f..74652b6
findings:
  - id: F-1
    title: "TestCompressLiveRemainsWritable uses >= instead of == for drawer count assertion"
    severity: low
    location: "tests/test_cli.py:2368"
    claim: >
      `assert store2.count() >= count_before` is weaker than necessary. `upsert` updates
      existing rows in-place and should not change the total row count. Using `>=` would
      allow a buggy compress that inserts additional rows instead of updating to pass silently.
      The existing repair test at line 682 uses the correct `== count_before` pattern.
    decision: fixed
    fix: "Changed `>= count_before` to `== count_before` to match the established pattern from the repair test."

  - id: F-2
    title: "test_delete_wing_storage_failure requires class-level patch after create=True change"
    severity: info
    location: "tests/test_mcp_server.py:511"
    claim: >
      When `tool_delete_wing` was changed to call `_get_store(create=True)`, it can discard a
      cached read-only instance and open a fresh LanceStore. An instance-level patch on the
      old handle would be silently ignored. The implementation already correctly updated to a
      class-level `monkeypatch.setattr(LanceStore, "delete_wing", explode)` with the matching
      `def explode(self_store, wing)` signature. No action needed — noting as observation.
    decision: dismissed

  - id: F-3
    title: "test_compress_dry_run_readonly_non_search_no_embedder asserts only dry-run text marker"
    severity: info
    location: "tests/test_cli.py:2259"
    claim: >
      The test asserts `"dry run" in captured.out.lower() or "nothing stored" in captured.out.lower()`
      but does not directly verify that no write was made to the store. This is acceptable because
      (a) the store is opened with `read_only=True` which causes `upsert` to raise immediately, and
      (b) `cmd_compress` skips the write block entirely when `args.dry_run=True`, providing two
      independent guards. The embedder patch provides defence against compute-only accidental calls.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "tests/test_cli.py:2368 — changed `store2.count() >= count_before` to `== count_before` in TestCompressLiveRemainsWritable to precisely assert upsert does not change row count"

new_backlog: []
