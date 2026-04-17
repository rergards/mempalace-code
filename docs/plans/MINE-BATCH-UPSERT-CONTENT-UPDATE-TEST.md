---
slug: MINE-BATCH-UPSERT-CONTENT-UPDATE-TEST
goal: "Add test_add_drawers_batch_updates_content verifying that add_drawers_batch overwrites stored content when the same ID is re-upserted with different content"
risk: low
risk_note: "Test-only change; no production code modified"
files:
  - path: tests/test_miner.py
    change: "Add test_add_drawers_batch_updates_content after test_add_drawers_batch_is_idempotent, in the same section block"
acceptance:
  - id: AC-1
    when: "test_add_drawers_batch_updates_content is run"
    then: "Passes with the current implementation (merge_insert + when_matched_update_all)"
  - id: AC-2
    when: "when_matched_update_all() is removed from LanceStore.upsert() and the test is re-run"
    then: "Test fails (i.e. the test would detect a silent no-op on match)"
  - id: AC-3
    when: "All miner tests are run"
    then: "All existing tests continue to pass (no regressions)"
  - id: AC-4
    when: "ruff check and ruff format --check are run"
    then: "No linting or formatting errors"
out_of_scope:
  - "Changes to mempalace/miner.py or mempalace/storage.py"
  - "Changes to test_add_drawers_batch_is_idempotent"
  - "Any metadata-field update assertions"
---

## Design Notes

- **Test location**: append immediately after `test_add_drawers_batch_is_idempotent` (line 1099),
  inside the `# add_drawers_batch idempotency (MINE-BATCH-EMBED-DEDUP-UPSERT)` section block.

- **Pattern**: follow `test_add_drawers_batch_is_idempotent` exactly —
  `tempfile.mkdtemp()` + `open_store(palace_path, create=True)` + `shutil.rmtree` in `finally`.

- **Spec structure**: use the same shape as the idempotency test. Only `content` changes between
  calls; `id` and `metadata` remain identical. This isolates the assertion to content update only.

- **Reading back content**: `store.get(ids=[drawer_id], include=["documents"])` returns
  `{"ids": [...], "documents": [...]}`. The document text lives at `result["documents"][0]`.
  This is confirmed by `LanceStore.get()` (storage.py:381-382): `out["documents"] = [r["text"] for r in results]`.

- **Assertion**: `assert result["documents"][0] == "content version 2"` — explicit string match,
  not just "different from v1", so a silent no-op (returning v1) is caught.

- **No embeddings involved in the assertion**: the test does not call `store.query()` (semantic
  search). It uses `store.get(ids=...)` which does a filter scan without vector comparison.
  This keeps the test fast and deterministic.

- **Suggested implementation**:
  ```python
  def test_add_drawers_batch_updates_content():
      """add_drawers_batch() re-upserted with changed content must overwrite the stored text."""
      tmpdir = tempfile.mkdtemp()
      try:
          palace_path = os.path.join(tmpdir, "palace")
          store = open_store(palace_path, create=True)

          drawer_id = "drawer_test_general_abc123"
          metadata = {
              "wing": "test",
              "room": "general",
              "source_file": "/fake/file.py",
              "added_by": "test",
              "filed_at": "2026-01-01T00:00:00",
          }

          add_drawers_batch(store, [{"id": drawer_id, "content": "content version 1", "metadata": metadata}])
          add_drawers_batch(store, [{"id": drawer_id, "content": "content version 2", "metadata": metadata}])

          result = store.get(ids=[drawer_id], include=["documents"])
          assert result["documents"][0] == "content version 2", (
              f"Expected 'content version 2' after re-upsert, got {result['documents'][0]!r}"
          )
      finally:
          shutil.rmtree(tmpdir)
  ```
