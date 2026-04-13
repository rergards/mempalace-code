"""
test_storage_lance.py — Direct unit tests for LanceStore edge cases.

Covers:
  - CRUD roundtrip (add/get)                         AC-1
  - create=False guard on add/upsert                 AC-2
  - Upsert update semantics                          AC-3
  - Upsert mixed new/existing                        AC-4
  - get() empty ids                                  AC-5
  - get() where $and/$or/operator dicts              AC-6
  - get() limit/offset                               AC-7
  - query() include keys, distances ≥0               AC-8
  - query() n_results cap                            AC-9
  - query() where filter                             AC-10
  - delete() nonexistent IDs no-op                   AC-11
  - _table is None guards                            AC-12
  - _meta_defaults() unknown keys dropped            AC-13
  - _meta_defaults() missing keys filled             AC-14
  - _meta_defaults() numeric coercion                AC-15
  - _where_to_sql() equality/$and/$or/operators/quotes AC-16
  - _where_to_sql() empty dict                       AC-17
  - iter_all() multi-batch                           AC-18
  - iter_all() include_vectors                       AC-19
  - iter_all() where filter                          AC-20
  - _detect_backend() lance dir                      AC-21
  - _detect_backend() chroma file                    AC-22
  - _detect_backend() empty dir                      AC-23
  - open_store() invalid backend ValueError          AC-24
"""

import pytest

from mempalace.storage import LanceStore, _META_DEFAULTS, _META_KEYS, _detect_backend, open_store


# ─── TestAddGet ───────────────────────────────────────────────────────────────


class TestAddGet:
    def test_add_and_get_roundtrip(self, tmp_path):
        """AC-1: Documents, metadata (including numeric fields), and IDs roundtrip exactly."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["r1", "r2"],
            documents=["authentication module uses JWT tokens", "database migration with Alembic"],
            metadatas=[
                {"wing": "proj", "room": "backend", "chunk_index": 3, "compression_ratio": 1.5},
                {"wing": "proj", "room": "db", "original_tokens": 42},
            ],
        )
        assert store.count() == 2

        result = store.get(ids=["r1"], include=["documents", "metadatas"])
        assert result["ids"] == ["r1"]
        assert result["documents"] == ["authentication module uses JWT tokens"]
        m = result["metadatas"][0]
        assert m["wing"] == "proj"
        assert m["room"] == "backend"
        assert m["chunk_index"] == 3
        assert abs(m["compression_ratio"] - 1.5) < 0.01

        result2 = store.get(ids=["r2"], include=["metadatas"])
        assert result2["metadatas"][0]["original_tokens"] == 42


# ─── TestUpsert ───────────────────────────────────────────────────────────────


class TestUpsert:
    def test_upsert_existing_updates_in_place(self, tmp_path):
        """AC-3: upsert() updates an existing row — count stays the same, content changes."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["u1"],
            documents=["original content for upsert test"],
            metadatas=[{"wing": "w", "room": "r", "added_by": "original"}],
        )
        assert store.count() == 1

        store.upsert(
            ids=["u1"],
            documents=["updated content after upsert replaces original"],
            metadatas=[{"wing": "w", "room": "r", "added_by": "updated"}],
        )
        assert store.count() == 1

        result = store.get(ids=["u1"], include=["documents", "metadatas"])
        assert result["documents"][0] == "updated content after upsert replaces original"
        assert result["metadatas"][0]["added_by"] == "updated"

    def test_upsert_mixed_new_and_existing(self, tmp_path):
        """AC-4: upsert() inserts new rows and updates existing rows; count reflects net adds only."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["m1"],
            documents=["existing drawer content here"],
            metadatas=[{"wing": "w", "room": "r"}],
        )
        assert store.count() == 1

        store.upsert(
            ids=["m1", "m2"],
            documents=[
                "existing drawer updated by mixed upsert",
                "brand new drawer inserted by mixed upsert",
            ],
            metadatas=[
                {"wing": "w", "room": "r", "added_by": "upserted"},
                {"wing": "w", "room": "r", "added_by": "new"},
            ],
        )
        assert store.count() == 2

        r1 = store.get(ids=["m1"], include=["documents"])
        assert "updated" in r1["documents"][0]

        r2 = store.get(ids=["m2"])
        assert r2["ids"] == ["m2"]


# ─── TestGetFilters ───────────────────────────────────────────────────────────


class TestGetFilters:
    def test_get_empty_ids_returns_empty(self, tmp_path):
        """AC-5: get() with ids=[] returns empty result immediately."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["e1"],
            documents=["some content in the store"],
            metadatas=[{"wing": "w", "room": "r"}],
        )
        result = store.get(ids=[])
        assert result == {"ids": [], "documents": [], "metadatas": []}

    def test_get_where_and(self, tmp_path):
        """AC-6: get() with $and filter returns only matching rows."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["a1", "a2", "a3"],
            documents=["backend auth module", "backend database module", "frontend react module"],
            metadatas=[
                {"wing": "proj", "room": "backend"},
                {"wing": "proj", "room": "backend"},
                {"wing": "proj", "room": "frontend"},
            ],
        )
        result = store.get(
            where={"$and": [{"wing": "proj"}, {"room": "backend"}]},
            include=["metadatas"],
        )
        assert len(result["ids"]) == 2
        for m in result["metadatas"]:
            assert m["room"] == "backend"

    def test_get_where_or(self, tmp_path):
        """AC-6: get() with $or filter returns rows matching either condition."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["o1", "o2", "o3"],
            documents=[
                "alpha wing document here",
                "beta wing document here",
                "gamma wing document",
            ],
            metadatas=[
                {"wing": "alpha", "room": "r"},
                {"wing": "beta", "room": "r"},
                {"wing": "gamma", "room": "r"},
            ],
        )
        result = store.get(
            where={"$or": [{"wing": "alpha"}, {"wing": "beta"}]},
            include=["metadatas"],
        )
        assert len(result["ids"]) == 2
        returned_wings = {m["wing"] for m in result["metadatas"]}
        assert returned_wings == {"alpha", "beta"}

    def test_get_where_operators(self, tmp_path):
        """AC-6: get() with operator dicts ($gt, $gte, $lt, $lte) filters on numeric fields."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["op1", "op2", "op3", "op4"],
            documents=[
                "chunk index zero content",
                "chunk index one content",
                "chunk index two content",
                "chunk index three content",
            ],
            metadatas=[
                {"wing": "w", "room": "r", "chunk_index": 0},
                {"wing": "w", "room": "r", "chunk_index": 1},
                {"wing": "w", "room": "r", "chunk_index": 2},
                {"wing": "w", "room": "r", "chunk_index": 3},
            ],
        )
        # $gt: chunk_index > 1 → rows with chunk_index 2 and 3
        gt_result = store.get(where={"chunk_index": {"$gt": 1}}, include=["metadatas"])
        assert len(gt_result["ids"]) == 2
        for m in gt_result["metadatas"]:
            assert m["chunk_index"] > 1

        # $lte: chunk_index <= 1 → rows with chunk_index 0 and 1
        lte_result = store.get(where={"chunk_index": {"$lte": 1}}, include=["metadatas"])
        assert len(lte_result["ids"]) == 2
        for m in lte_result["metadatas"]:
            assert m["chunk_index"] <= 1

        # $gte: chunk_index >= 2 → rows with chunk_index 2 and 3
        gte_result = store.get(where={"chunk_index": {"$gte": 2}}, include=["metadatas"])
        assert len(gte_result["ids"]) == 2

        # $lt: chunk_index < 2 → rows with chunk_index 0 and 1
        lt_result = store.get(where={"chunk_index": {"$lt": 2}}, include=["metadatas"])
        assert len(lt_result["ids"]) == 2

    def test_get_limit_offset(self, tmp_path):
        """AC-7: get() with limit and offset returns the correct slice."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["l1", "l2", "l3", "l4", "l5"],
            documents=[
                "first drawer for limit test",
                "second drawer for limit test",
                "third drawer for limit test",
                "fourth drawer for limit test",
                "fifth drawer for limit test",
            ],
            metadatas=[{"wing": "w", "room": "r"}] * 5,
        )
        page1 = store.get(limit=2, offset=0)
        assert len(page1["ids"]) == 2

        page2 = store.get(limit=2, offset=2)
        assert len(page2["ids"]) == 2

        # No overlap between the two pages
        assert set(page1["ids"]).isdisjoint(set(page2["ids"]))

    def test_get_offset_beyond_rows(self, tmp_path):
        """AC-7: offset beyond row count returns empty."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["x1", "x2"],
            documents=["first row for offset test", "second row for offset test"],
            metadatas=[{"wing": "w", "room": "r"}] * 2,
        )
        result = store.get(limit=10, offset=100)
        assert result["ids"] == []


# ─── TestQuery ────────────────────────────────────────────────────────────────


class TestQuery:
    def test_query_include_keys(self, tmp_path):
        """AC-8: query() with all include keys returns documents, metadatas, distances."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["q1"],
            documents=["vector search with semantic embeddings"],
            metadatas=[{"wing": "w", "room": "r"}],
        )
        result = store.query(
            query_texts=["semantic search"],
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )
        assert "documents" in result
        assert "metadatas" in result
        assert "distances" in result
        assert len(result["distances"][0]) == 1
        assert result["distances"][0][0] >= 0.0

    def test_query_n_results_cap(self, tmp_path):
        """AC-9: query() result length does not exceed n_results."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["n1", "n2", "n3", "n4", "n5"],
            documents=[
                "machine learning gradient descent optimization",
                "deep learning neural network architecture",
                "natural language processing transformer model",
                "computer vision convolutional neural network",
                "reinforcement learning policy gradient agent",
            ],
            metadatas=[{"wing": "w", "room": "r"}] * 5,
        )
        result = store.query(
            query_texts=["machine learning"],
            n_results=2,
            include=["documents"],
        )
        assert len(result["ids"][0]) <= 2

    def test_query_where_filter(self, tmp_path):
        """AC-10: query() with where filter returns only matching rows."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["wf1", "wf2", "wf3"],
            documents=[
                "backend authentication service with tokens",
                "backend database connection pooling",
                "frontend user interface components",
            ],
            metadatas=[
                {"wing": "proj", "room": "backend"},
                {"wing": "proj", "room": "backend"},
                {"wing": "proj", "room": "frontend"},
            ],
        )
        result = store.query(
            query_texts=["backend service"],
            n_results=5,
            where={"room": "backend"},
            include=["metadatas"],
        )
        for meta_list in result["metadatas"]:
            for m in meta_list:
                assert m["room"] == "backend"


# ─── TestDelete ───────────────────────────────────────────────────────────────


class TestDelete:
    def test_delete_nonexistent_ids_noop(self, tmp_path):
        """AC-11: delete() with nonexistent IDs raises no error; count is unchanged."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["keep1"],
            documents=["content that should remain after delete noop"],
            metadatas=[{"wing": "w", "room": "r"}],
        )
        assert store.count() == 1

        store.delete(["does_not_exist", "also_missing"])  # must not raise
        assert store.count() == 1

    def test_delete_empty_list_noop(self, tmp_path):
        """AC-11: delete([]) must not raise; count is unchanged.

        Regression guard: empty id_list generates ``id IN ()`` which is invalid SQL
        in DataFusion (lance error). The implementation must short-circuit before
        issuing the DELETE statement.
        """
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["keep2"],
            documents=["content that should survive empty delete call"],
            metadatas=[{"wing": "w", "room": "r"}],
        )
        assert store.count() == 1

        store.delete([])  # must not raise
        assert store.count() == 1


# ─── TestNoneTableGuards ──────────────────────────────────────────────────────


class TestNoneTableGuards:
    def test_add_raises_on_no_table(self, tmp_path):
        """AC-2: add() raises RuntimeError when create=False and no prior table exists."""
        store = open_store(str(tmp_path), create=False)
        with pytest.raises(RuntimeError, match="Table does not exist"):
            store.add(
                ids=["bad"],
                documents=["should not be added"],
                metadatas=[{"wing": "w", "room": "r"}],
            )

    def test_upsert_raises_on_no_table(self, tmp_path):
        """AC-2: upsert() raises RuntimeError when create=False and no prior table exists."""
        store = open_store(str(tmp_path), create=False)
        with pytest.raises(RuntimeError, match="Table does not exist"):
            store.upsert(
                ids=["bad"],
                documents=["should not be upserted"],
                metadatas=[{"wing": "w", "room": "r"}],
            )

    def test_count_no_table(self, tmp_path):
        """AC-12: count() returns 0 when _table is None."""
        store = open_store(str(tmp_path), create=False)
        assert store.count() == 0

    def test_get_no_table(self, tmp_path):
        """AC-12: get() returns empty result dict when _table is None."""
        store = open_store(str(tmp_path), create=False)
        result = store.get()
        assert result == {"ids": [], "documents": [], "metadatas": []}

    def test_query_no_table(self, tmp_path):
        """AC-12: query() returns empty nested lists when _table is None."""
        store = open_store(str(tmp_path), create=False)
        result = store.query(query_texts=["anything"], n_results=5)
        assert result == {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    def test_delete_no_table(self, tmp_path):
        """AC-12: delete() is a no-op when _table is None."""
        store = open_store(str(tmp_path), create=False)
        result = store.delete(["any_id"])  # must not raise
        assert result is None


# ─── TestMetaDefaults ─────────────────────────────────────────────────────────


class TestMetaDefaults:
    def test_unknown_keys_dropped(self):
        """AC-13: Unknown metadata keys are dropped; only _META_KEYS keys survive."""
        result = LanceStore._meta_defaults(
            {"wing": "w", "room": "r", "unknown_field": "should_be_dropped", "another_bad": 99}
        )
        assert "unknown_field" not in result
        assert "another_bad" not in result
        assert set(result.keys()) == set(_META_KEYS)

    def test_missing_keys_filled(self):
        """AC-14: Missing metadata keys are filled with defaults from _META_DEFAULTS."""
        result = LanceStore._meta_defaults({"wing": "myproject", "room": "backend"})
        assert set(result.keys()) == set(_META_KEYS)
        assert result["wing"] == "myproject"
        assert result["room"] == "backend"
        assert result["source_file"] == _META_DEFAULTS["source_file"]
        assert result["added_by"] == _META_DEFAULTS["added_by"]

    def test_string_coercion(self):
        """AC-15: String-typed chunk_index, compression_ratio, and original_tokens are coerced."""
        result = LanceStore._meta_defaults(
            {
                "wing": "w",
                "room": "r",
                "chunk_index": "7",
                "compression_ratio": "2.5",
                "original_tokens": "100",
            }
        )
        assert result["chunk_index"] == 7
        assert isinstance(result["chunk_index"], int)
        assert abs(result["compression_ratio"] - 2.5) < 0.001
        assert isinstance(result["compression_ratio"], float)
        assert result["original_tokens"] == 100
        assert isinstance(result["original_tokens"], int)


# ─── TestWhereToSql ───────────────────────────────────────────────────────────


class TestWhereToSql:
    def test_simple_eq(self):
        """AC-16: Simple string equality generates correct SQL."""
        assert LanceStore._where_to_sql({"wing": "myproject"}) == "wing = 'myproject'"

    def test_and(self):
        """AC-16: $and generates AND-joined parenthesised clauses."""
        sql = LanceStore._where_to_sql({"$and": [{"wing": "proj"}, {"room": "backend"}]})
        assert "(wing = 'proj')" in sql
        assert "(room = 'backend')" in sql
        assert " AND " in sql

    def test_or(self):
        """AC-16: $or generates OR-joined parenthesised clauses."""
        sql = LanceStore._where_to_sql({"$or": [{"wing": "alpha"}, {"wing": "beta"}]})
        assert "(wing = 'alpha')" in sql
        assert "(wing = 'beta')" in sql
        assert " OR " in sql

    def test_nested_operators(self):
        """AC-16: Operator dicts ($eq, $ne, $gt, $gte, $lt, $lte) generate correct SQL."""
        assert LanceStore._where_to_sql({"wing": {"$eq": "foo"}}) == "wing = 'foo'"
        assert LanceStore._where_to_sql({"wing": {"$ne": "foo"}}) == "wing != 'foo'"
        assert LanceStore._where_to_sql({"chunk_index": {"$gt": 2}}) == "chunk_index > 2"
        assert LanceStore._where_to_sql({"chunk_index": {"$gte": 2}}) == "chunk_index >= 2"
        assert LanceStore._where_to_sql({"chunk_index": {"$lt": 5}}) == "chunk_index < 5"
        assert LanceStore._where_to_sql({"chunk_index": {"$lte": 5}}) == "chunk_index <= 5"

    def test_numeric_eq_ne_no_quotes(self):
        """Regression: numeric $eq/$ne must not wrap the value in single quotes.

        ``chunk_index = '2'`` fails in DataFusion — int32 columns reject quoted
        literals without implicit coercion.  The correct SQL is ``chunk_index = 2``.
        """
        assert LanceStore._where_to_sql({"chunk_index": {"$eq": 2}}) == "chunk_index = 2"
        assert LanceStore._where_to_sql({"chunk_index": {"$ne": 0}}) == "chunk_index != 0"
        assert (
            LanceStore._where_to_sql({"compression_ratio": {"$eq": 1.5}})
            == "compression_ratio = 1.5"
        )

    def test_single_quote_escape(self):
        """AC-16: Single quotes in string values are escaped via ''."""
        sql = LanceStore._where_to_sql({"wing": "o'brien"})
        assert sql == "wing = 'o''brien'"

    def test_empty_dict(self):
        """AC-17: Empty where dict returns '1=1'."""
        assert LanceStore._where_to_sql({}) == "1=1"

    # ── $in operator (HARDEN-WHERE-SQL-IN) ───────────────────────────────────

    def test_in_strings(self):
        """AC-1: $in with multiple strings produces IN ('a', 'b') SQL."""
        assert LanceStore._where_to_sql({"wing": {"$in": ["a", "b"]}}) == "wing IN ('a', 'b')"

    def test_in_empty(self):
        """AC-2: $in with empty list produces '1 = 0' (no empty IN clause)."""
        assert LanceStore._where_to_sql({"wing": {"$in": []}}) == "1 = 0"

    def test_in_single_element(self):
        """AC-3: $in with one element produces equality SQL (optimisation)."""
        assert LanceStore._where_to_sql({"wing": {"$in": ["a"]}}) == "wing = 'a'"

    def test_in_numbers(self):
        """AC-4: $in with numeric values produces unquoted IN list."""
        assert LanceStore._where_to_sql({"count": {"$in": [1, 2, 3]}}) == "count IN (1, 2, 3)"

    def test_in_string_escape(self):
        """AC-5: Single quotes inside $in string values are doubled (SQL-safe)."""
        sql = LanceStore._where_to_sql({"wing": {"$in": ["it's"]}})
        assert sql == "wing = 'it''s'"

    def test_in_multi_string_escape(self):
        """F-1 fix: Multi-element $in with embedded single-quotes are doubled in each element."""
        sql = LanceStore._where_to_sql({"wing": {"$in": ["it's", "can't"]}})
        assert sql == "wing IN ('it''s', 'can''t')"

    def test_in_mixed_types_raises(self):
        """AC-6: Mixed str+int in $in list raises ValueError."""
        import pytest

        with pytest.raises(ValueError, match="mixed"):
            LanceStore._where_to_sql({"x": {"$in": ["a", 1]}})

    def test_in_end_to_end(self, tmp_path):
        """AC-7: LanceStore.query with $in filter returns only matching wings."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["d-alpha-1", "d-beta-1", "d-gamma-1"],
            documents=["alpha content here", "beta content here", "gamma content here"],
            metadatas=[
                {"wing": "alpha", "room": "r"},
                {"wing": "beta", "room": "r"},
                {"wing": "gamma", "room": "r"},
            ],
        )
        results = store.query(
            query_texts=["content"],
            where={"wing": {"$in": ["alpha", "beta"]}},
            n_results=10,
        )
        returned_ids = set(results["ids"][0])
        assert "d-alpha-1" in returned_ids
        assert "d-beta-1" in returned_ids
        assert "d-gamma-1" not in returned_ids


# ─── TestIterAll ──────────────────────────────────────────────────────────────


class TestIterAll:
    def test_multi_batch(self, tmp_path):
        """AC-18: iter_all() with batch_size=1 yields all rows across multiple batches."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["b1", "b2", "b3"],
            documents=[
                "first batch document content",
                "second batch document content",
                "third batch document content",
            ],
            metadatas=[{"wing": "w", "room": "r"}] * 3,
        )
        batches = list(store.iter_all(batch_size=1))
        all_rows = [row for batch in batches for row in batch]
        assert len(all_rows) == 3
        assert {row["id"] for row in all_rows} == {"b1", "b2", "b3"}

    def test_include_vectors(self, tmp_path):
        """AC-19: iter_all() with include_vectors=True yields rows with a 'vector' key."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["v1"],
            documents=["vector embedding test document"],
            metadatas=[{"wing": "w", "room": "r"}],
        )
        batches = list(store.iter_all(include_vectors=True))
        all_rows = [row for batch in batches for row in batch]
        assert len(all_rows) == 1
        row = all_rows[0]
        assert "vector" in row
        assert isinstance(row["vector"], list)
        assert len(row["vector"]) > 0
        assert isinstance(row["vector"][0], float)

    def test_where_filter(self, tmp_path):
        """AC-20: iter_all() with where filter yields only matching rows."""
        store = open_store(str(tmp_path), create=True)
        store.add(
            ids=["iw1", "iw2", "iw3"],
            documents=[
                "alpha wing first document",
                "alpha wing second document",
                "beta wing document here",
            ],
            metadatas=[
                {"wing": "alpha", "room": "r"},
                {"wing": "alpha", "room": "r"},
                {"wing": "beta", "room": "r"},
            ],
        )
        batches = list(store.iter_all(where={"wing": "alpha"}))
        all_rows = [row for batch in batches for row in batch]
        assert len(all_rows) == 2
        for row in all_rows:
            assert row["wing"] == "alpha"


# ─── TestDetectBackend ────────────────────────────────────────────────────────


class TestDetectBackend:
    def test_lance_dir(self, tmp_path):
        """AC-21: _detect_backend() returns 'lance' when a 'lance/' subdir exists."""
        (tmp_path / "lance").mkdir()
        assert _detect_backend(str(tmp_path)) == "lance"

    def test_chroma_file(self, tmp_path):
        """AC-22: _detect_backend() returns 'chroma' when 'chroma.sqlite3' exists."""
        (tmp_path / "chroma.sqlite3").touch()
        assert _detect_backend(str(tmp_path)) == "chroma"

    def test_empty_dir(self, tmp_path):
        """AC-23: _detect_backend() returns 'lance' (default) for an empty directory."""
        assert _detect_backend(str(tmp_path)) == "lance"


# ─── TestOpenStoreFactory ─────────────────────────────────────────────────────


class TestOpenStoreFactory:
    def test_invalid_backend(self, tmp_path):
        """AC-24: open_store() with backend='invalid' raises ValueError."""
        with pytest.raises(ValueError, match="Unknown storage backend"):
            open_store(str(tmp_path), backend="invalid")
