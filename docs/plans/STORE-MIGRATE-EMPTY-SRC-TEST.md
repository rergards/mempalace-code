---
slug: STORE-MIGRATE-EMPTY-SRC-TEST
goal: "Add test_migrate_empty_src to test_migrate.py covering the src_total==0 early-exit path"
risk: low
risk_note: "Test-only change; no production code modified"
files:
  - path: tests/test_migrate.py
    change: "Add test_migrate_empty_src — seeds ChromaStore, deletes all rows, asserts migrate_chroma_to_lance returns (0,0) without creating dst"
acceptance:
  - id: AC-1
    when: "test_migrate_empty_src runs against a ChromaDB palace where the collection exists but all drawers have been deleted"
    then: "migrate_chroma_to_lance returns (0, 0)"
  - id: AC-2
    when: "test_migrate_empty_src completes"
    then: "the destination directory has not been created (early exit fires before os.makedirs)"
  - id: AC-3
    when: "pytest tests/test_migrate.py -v"
    then: "all six tests (5 pre-existing + 1 new) pass; no regressions"
out_of_scope:
  - "Changes to migrate.py production code"
  - "Changes to _chroma_store.py"
  - "The _col is None path (distinct early-exit, already effectively covered by ChromaStore.count returning 0 when col is None)"
---

## Design Notes

- **Why seed-then-delete?** ChromaDB only creates the internal collection object when `add()` is called (or `get_or_create_collection` runs during `__init__`). When `migrate_chroma_to_lance` opens the source with `ChromaStore(src_path, create=False)`, it calls `client.get_collection(name)` — this succeeds only if the collection was previously created. Seeding ensures the collection exists so `_col is not None`; deleting all rows ensures `count() == 0`, which is the exact condition for the early-exit at `migrate.py:65`.
- **Deleting all rows:** Use `store.get(include=["documents"])` to fetch all IDs, then `store.delete(ids)`. The `_seed_chroma` helper returns the total count; after deletion `store.count()` must be asserted to be 0 before calling migrate.
- **Destination assertion:** After the early exit `migrate.py:65-67` returns immediately before `os.makedirs(dst_path)` at line 70. Assert `not os.path.isdir(dst)` to prove no destination was created — this is the strongest signal that the correct code path fired.
- **`no_backup=True`** — required as in all other tests; avoids writing tar.gz files in tmp_path.
- **Test placement:** Add after `test_migrate_verify_catches_mismatch` (the last existing test) with the AC-6 label comment pattern used by the file.
- **Imports already present:** `ChromaStore`, `LanceStore`, `migrate_chroma_to_lance`, `os`, and `tmp_path` are all available; no new imports needed.
