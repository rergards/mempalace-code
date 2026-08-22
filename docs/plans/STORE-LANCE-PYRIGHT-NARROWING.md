---
slug: STORE-LANCE-PYRIGHT-NARROWING
status: completed
authority: non_authoritative
goal: "Make LanceStore lazy LanceDB handles explicit and Pyright-clean without changing open/read behavior"
risk: medium
risk_note: "Touches shared storage internals and dynamic LanceDB/Arrow APIs; behavior should remain unchanged, but typed helper boundaries must preserve read_only and create=False semantics."
files:
  - path: mempalace_code/storage.py
    change: "Add internal typed protocols/accessors for LanceDB connection, table, and embedder handles; replace direct optional member access with local narrowed variables; contain dynamic LanceDB/Arrow API gaps behind narrow helpers so storage.py passes Pyright."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_storage_lance.py::TestAddGet::test_add_and_get_roundtrip tests/test_storage_lance.py::TestReadOnlyStore::test_ac26_metadata_reads_skip_embedder -q` is run"
    then: "write-mode add/get still roundtrips rows and read_only=True metadata reads still return count/count_by/count_by_pair without calling _get_embedder"
  - id: AC-2
    when: "`python -m pytest tests/test_storage_lance.py::TestNoneTableGuards::test_add_raises_on_no_table tests/test_storage_lance.py::TestNoneTableGuards::test_upsert_raises_on_no_table tests/test_storage_lance.py::TestNoneTableGuards::test_query_no_table -q` is run"
    then: "create=False with no table still raises RuntimeError for writes and returns the existing empty nested query result for reads"
  - id: AC-3
    when: "`python -m pytest tests/test_storage_lance.py::TestReadOnlyStore::test_ac25_missing_palace_no_directory_created tests/test_storage_lance.py::TestReadOnlyStore::test_ac29_pre_migration_schema_read_only_taxonomy -q` is run"
    then: "read_only=True still avoids creating a missing palace and still opens pre-migration Lance tables for taxonomy reads without schema migration"
  - id: AC-4
    when: "`python -m pytest tests/test_storage_lance.py::TestIterAll::test_where_filter tests/test_storage_lance.py::TestIterAll::test_include_vectors tests/test_storage_lance.py::TestIterAll::test_where_operator_in_empty -q` is run"
    then: "iter_all still filters with Arrow masks, includes vectors only when requested, and treats an empty $in filter as no matches"
  - id: AC-5
    when: "`python -m pytest tests/test_storage.py::TestLanceHealth::test_health_check_uses_projected_scan_for_metadata_probe tests/test_storage.py::TestLanceHealth::test_recover_dry_run_uses_projected_scan_for_version_probe tests/test_storage.py::TestCleanupStaleFragments::test_none_table_returns_ok_false -q` is run"
    then: "health/recovery still use projected scans, dry-run recovery still checks out and returns latest, and cleanup on a None table still returns ok=False without raising"
  - id: AC-6
    when: "`python -m pyright mempalace_code/storage.py --pythonpath \"$(python -c 'import sys; print(sys.executable)')\"` is run"
    then: "0 errors are reported for `mempalace_code/storage.py`. Scope is `mempalace_code/storage.py` only; tests/ are explicitly out of scope (matches the non-gating CI baseline noted in CLAUDE.md)."
out_of_scope:
  - "Changing LanceStore persistence, schema migration, cleanup, health, or recovery behavior beyond typed handle narrowing."
  - "Replacing LanceDB or sentence-transformers APIs."
  - "Changing ChromaStore or legacy Chroma backend typing."
  - "Suppressing Pyright globally, disabling reportOptionalMemberAccess, or adding broad file-level ignores."
---

## Design Notes

- Add private structural types near the LanceDB backend section:
  - `_EmbedderProtocol` with `ndims()` and `compute_source_embeddings(list[str]) -> list[list[float]]`.
  - `_LanceDBConnectionProtocol` with `open_table()` and `create_table()`.
  - `_LanceTableProtocol` / small query protocol(s) for the methods this file calls: schema, search, add, merge_insert, delete, count_rows, to_arrow, add_columns, optimize, list_versions, checkout, checkout_latest, restore, and head.
- Type instance attributes in `LanceStore.__init__` as optional protocol handles:
  - `_db: _LanceDBConnectionProtocol | None`
  - `_table: _LanceTableProtocol | None`
  - `_embedder: _EmbedderProtocol | None`
- Introduce narrow accessors instead of repeated `if self._table is None` plus direct member access:
  - `_require_db() -> _LanceDBConnectionProtocol`
  - `_require_table(message: str = "Table does not exist and create=False") -> _LanceTableProtocol`
  - `_embedder_handle() -> _EmbedderProtocol`, which calls `_ensure_embedder()` and asserts the helper invariant locally.
- Keep read methods that already tolerate absent tables returning current empty/zero results. Use local variables after guards:
  - `table = self._table`; `if table is None: return ...`; then use `table`.
  - For write paths, use `_require_table()` so current error text remains compatible with tests.
- Apply `_require_db()` at every non-read-only `self._db` access site — including `_open_or_create` and `recover_to_last_working_version`'s post-restore `self._db.open_table(...)` reopen (storage.py:1147). Bind `db = self._require_db()` before non-read-only open/create calls. In read-only mode, keep the current `None` return for absent `_db`.
- External callers in `mempalace_code/mcp_server.py` access `_table` / `_db` only via `is None` checks (mcp_server.py:88-89). Optional[Protocol] typing keeps these checks valid; no cross-module changes required.
- In `_embed`, bind `embedder = self._embedder_handle()` and return a concrete `list[list[float]]`. If the LanceDB embedder returns a sequence-like value, normalize with `list(...)` at the boundary rather than widening the public return type.
- In `_scan_columns`, pass or bind a non-optional table handle first. Use `getattr(table, "scanner", None)` for LanceDB versions that expose `scanner()` but whose stubs do not know it; keep the existing `search().select(...).to_arrow()` fallback.
- Current targeted Pyright output also reports PyArrow compute functions (`pc.equal`, `pc.and_`, `pc.is_in`, etc.) as unknown. Contain that dynamic-stub gap behind a tiny helper such as `_pc(name: str)` / local `getattr(pc, name)` map inside `_where_to_arrow_mask`; do not add global ignores.
- Re-run `python -m pyright mempalace_code/storage.py --pythonpath "$(python -c 'import sys; print(sys.executable)')"` after implementation. Expected result: `0 errors` for `mempalace_code/storage.py`.
- Re-run the focused pytest commands from the acceptance criteria. They cover happy path, failure path, read-only edge cases, Arrow filtering, and health/recovery maintenance surfaces.
