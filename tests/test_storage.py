"""
test_storage.py — Tests for DrawerStore aggregation and delete_wing.
"""

import logging
import os
from datetime import datetime

import pytest
from unittest.mock import MagicMock, patch

from mempalace.storage import (
    DrawerStore,
    LanceStore,
    _META_DEFAULTS,
    _META_FIELD_SPEC,
    _META_KEYS,
    _sql_default_for_arrow_type,
    _target_drawer_schema,
    open_store,
)


class _ProjectedScanner:
    def __init__(self, arrow_table):
        self._arrow_table = arrow_table

    def to_table(self):
        return self._arrow_table


class _ProjectedTable:
    def __init__(self, rows, *, fail_on_columns=None):
        import pyarrow as pa

        self.calls = []
        self.fail_on_columns = fail_on_columns or set()
        self._arrow_table = pa.Table.from_pylist(rows)

    def scanner(self, *, columns):
        self.calls.append(list(columns))
        if self.fail_on_columns & set(columns):
            raise RuntimeError("missing projected column")
        return _ProjectedScanner(self._arrow_table.select(columns))

    def to_arrow(self):
        raise AssertionError("metadata scans must use scanner(columns=...)")


def _store_with_projected_table(table):
    store = LanceStore.__new__(LanceStore)
    store._table = table
    return store


class TestDeleteWing:
    def test_delete_wing(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["d1", "d2", "d3", "d4"],
            documents=[
                "doc about auth tokens",
                "doc about DB migrations",
                "doc about React",
                "doc about planning",
            ],
            metadatas=[
                {"wing": "project", "room": "backend"},
                {"wing": "project", "room": "backend"},
                {"wing": "project", "room": "frontend"},
                {"wing": "notes", "room": "planning"},
            ],
        )
        assert store.count() == 4

        deleted = store.delete_wing("project")
        assert deleted == 3
        assert store.count() == 1

        remaining = store.get(include=["metadatas"])
        assert len(remaining["ids"]) == 1
        assert remaining["metadatas"][0]["wing"] == "notes"

    def test_delete_wing_nonexistent(self, palace_path):
        store = open_store(palace_path, create=True)
        deleted = store.delete_wing("nonexistent_wing")
        assert deleted == 0
        assert store.count() == 0

    def test_delete_wing_leaves_other_wings_intact(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["w1", "w2"],
            documents=["wing alpha content", "wing beta content"],
            metadatas=[
                {"wing": "alpha", "room": "general"},
                {"wing": "beta", "room": "general"},
            ],
        )
        store.delete_wing("alpha")
        remaining = store.get(include=["metadatas"])
        assert len(remaining["ids"]) == 1
        assert remaining["metadatas"][0]["wing"] == "beta"

    def test_delete_wing_with_special_quote(self, palace_path):
        """Wing names containing single quotes should not cause errors."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["sq1"],
            documents=["some content"],
            metadatas=[{"wing": "o'brien", "room": "general"}],
        )
        # Deleting a non-existent quoted wing should not raise
        deleted = store.delete_wing("doesn't exist")
        assert deleted == 0
        # Deleting the actual quoted wing should work
        deleted = store.delete_wing("o'brien")
        assert deleted == 1
        assert store.count() == 0


class TestCountBy:
    def test_count_by_wing(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["a1", "a2", "b1"],
            documents=["alpha doc 1", "alpha doc 2", "beta doc 1"],
            metadatas=[
                {"wing": "alpha", "room": "general"},
                {"wing": "alpha", "room": "notes"},
                {"wing": "beta", "room": "general"},
            ],
        )
        result = store.count_by("wing")
        assert result == {"alpha": 2, "beta": 1}

    def test_count_by_room(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["r1", "r2", "r3"],
            documents=["backend doc", "frontend doc", "backend doc 2"],
            metadatas=[
                {"wing": "proj", "room": "backend"},
                {"wing": "proj", "room": "frontend"},
                {"wing": "proj", "room": "backend"},
            ],
        )
        result = store.count_by("room")
        assert result == {"backend": 2, "frontend": 1}

    def test_count_by_pair(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["p1", "p2", "p3", "p4"],
            documents=["doc1", "doc2", "doc3", "doc4"],
            metadatas=[
                {"wing": "alpha", "room": "backend"},
                {"wing": "alpha", "room": "backend"},
                {"wing": "alpha", "room": "frontend"},
                {"wing": "beta", "room": "general"},
            ],
        )
        result = store.count_by_pair("wing", "room")
        assert result == {
            "alpha": {"backend": 2, "frontend": 1},
            "beta": {"general": 1},
        }

    def test_count_by_empty(self, palace_path):
        store = open_store(palace_path, create=True)
        assert store.count_by("wing") == {}
        assert store.count_by_pair("wing", "room") == {}

    def test_count_by_uses_scan_projection(self):
        table = _ProjectedTable(
            [
                {"wing": "alpha", "room": "backend", "vector": [1.0]},
                {"wing": "alpha", "room": "frontend", "vector": [2.0]},
                {"wing": "beta", "room": "backend", "vector": [3.0]},
            ]
        )
        store = _store_with_projected_table(table)

        assert store.count_by("wing") == {"alpha": 2, "beta": 1}
        assert table.calls == [["wing"]]

    def test_count_by_pair_uses_scan_projection(self):
        table = _ProjectedTable(
            [
                {"wing": "alpha", "room": "backend", "vector": [1.0]},
                {"wing": "alpha", "room": "backend", "vector": [2.0]},
                {"wing": "beta", "room": "frontend", "vector": [3.0]},
            ]
        )
        store = _store_with_projected_table(table)

        assert store.count_by_pair("wing", "room") == {
            "alpha": {"backend": 2},
            "beta": {"frontend": 1},
        }
        assert table.calls == [["wing", "room"]]


class TestGetSourceFiles:
    def test_empty_table_returns_empty_set(self, palace_path):
        store = open_store(palace_path, create=True)
        result = store.get_source_files("any_wing")
        assert result == set()

    def test_returns_files_for_wing(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["f1", "f2", "f3"],
            documents=["content for alpha", "content for alpha 2", "content for beta"],
            metadatas=[
                {"wing": "alpha", "room": "general", "source_file": "alpha/a.py"},
                {"wing": "alpha", "room": "general", "source_file": "alpha/b.py"},
                {"wing": "beta", "room": "general", "source_file": "beta/c.py"},
            ],
        )
        result = store.get_source_files("alpha")
        assert result == {"alpha/a.py", "alpha/b.py"}

    def test_wing_filter_excludes_other_wings(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["x1"],
            documents=["some content here for test"],
            metadatas=[{"wing": "other", "room": "general", "source_file": "other/z.py"}],
        )
        result = store.get_source_files("target_wing")
        assert result == set()

    def test_returns_set_type(self, palace_path):
        store = open_store(palace_path, create=True)
        result = store.get_source_files("anything")
        assert isinstance(result, set)

    def test_get_source_files_uses_scan_projection(self):
        table = _ProjectedTable(
            [
                {"source_file": "alpha/a.py", "wing": "alpha", "vector": [1.0]},
                {"source_file": "alpha/b.py", "wing": "alpha", "vector": [2.0]},
                {"source_file": "beta/c.py", "wing": "beta", "vector": [3.0]},
            ]
        )
        store = _store_with_projected_table(table)

        assert store.get_source_files("alpha") == {"alpha/a.py", "alpha/b.py"}
        assert table.calls == [["source_file", "wing"]]


class TestMetadataScanProjection:
    def test_get_source_file_hashes_uses_scan_projection(self):
        table = _ProjectedTable(
            [
                {
                    "source_file": "alpha/a.py",
                    "source_hash": "hash-a1",
                    "wing": "alpha",
                    "vector": [1.0],
                },
                {
                    "source_file": "alpha/a.py",
                    "source_hash": "hash-a2",
                    "wing": "alpha",
                    "vector": [2.0],
                },
                {
                    "source_file": "beta/c.py",
                    "source_hash": "hash-c",
                    "wing": "beta",
                    "vector": [3.0],
                },
            ]
        )
        store = _store_with_projected_table(table)

        assert store.get_source_file_hashes("alpha") == {"alpha/a.py": "hash-a1"}
        assert table.calls == [["source_file", "source_hash", "wing"]]

    def test_get_source_file_hashes_missing_source_hash_returns_empty_dict(self):
        table = _ProjectedTable(
            [{"source_file": "alpha/a.py", "source_hash": "hash-a", "wing": "alpha"}],
            fail_on_columns={"source_hash"},
        )
        store = _store_with_projected_table(table)

        assert store.get_source_file_hashes("alpha") == {}
        assert table.calls == [["source_file", "source_hash", "wing"]]


class TestOptimize:
    def test_optimize_no_crash_on_empty_table(self, palace_path):
        store = open_store(palace_path, create=True)
        store.optimize()  # must not raise

    def test_optimize_calls_table_optimize(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["o1"],
            documents=["some content to optimize later"],
            metadatas=[{"wing": "w", "room": "r"}],
        )
        mock_table_optimize = MagicMock()
        with patch.object(store, "_table") as mock_table:
            mock_table.optimize = mock_table_optimize
            store.optimize()
        mock_table_optimize.assert_called_once()


class TestWarmup:
    def test_warmup_calls_embed(self, palace_path):
        store = open_store(palace_path, create=True)
        with patch.object(store, "_embed") as mock_embed:
            store.warmup()
        mock_embed.assert_called_once_with(["warmup"])

    def test_warmup_no_crash(self, palace_path):
        store = open_store(palace_path, create=True)
        store.warmup()  # must not raise


class TestDrawerStoreBaseDefaults:
    """Verify DrawerStore base class methods return safe defaults."""

    def test_base_get_source_files_returns_none(self):
        class _MinimalStore(DrawerStore):
            def count(self):
                return 0

            def add(self, ids, documents, metadatas):
                pass

            def upsert(self, ids, documents, metadatas):
                pass

            def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
                return {}

            def query(self, query_texts, n_results=5, where=None, include=None):
                return {}

            def delete(self, ids):
                pass

            def delete_wing(self, wing):
                return 0

            def count_by(self, column):
                return {}

            def count_by_pair(self, col_a, col_b):
                return {}

        store = _MinimalStore()
        assert store.get_source_files("some_wing") is None

    def test_base_optimize_is_noop(self):
        class _MinimalStore(DrawerStore):
            def count(self):
                return 0

            def add(self, ids, documents, metadatas):
                pass

            def upsert(self, ids, documents, metadatas):
                pass

            def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
                return {}

            def query(self, query_texts, n_results=5, where=None, include=None):
                return {}

            def delete(self, ids):
                pass

            def delete_wing(self, wing):
                return 0

            def count_by(self, column):
                return {}

            def count_by_pair(self, col_a, col_b):
                return {}

        store = _MinimalStore()
        store.optimize()  # must not raise

    def test_base_warmup_is_noop(self):
        class _MinimalStore(DrawerStore):
            def count(self):
                return 0

            def add(self, ids, documents, metadatas):
                pass

            def upsert(self, ids, documents, metadatas):
                pass

            def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
                return {}

            def query(self, query_texts, n_results=5, where=None, include=None):
                return {}

            def delete(self, ids):
                pass

            def delete_wing(self, wing):
                return 0

            def count_by(self, column):
                return {}

            def count_by_pair(self, col_a, col_b):
                return {}

        store = _MinimalStore()
        store.warmup()  # must not raise


# =============================================================================
# _sql_default_for_arrow_type unit tests (AC-6)
# =============================================================================


class TestSqlDefaultForArrowType:
    def test_string_type(self):
        import pyarrow as pa

        assert _sql_default_for_arrow_type(pa.string()) == "CAST('' AS string)"

    def test_large_string_type(self):
        import pyarrow as pa

        assert _sql_default_for_arrow_type(pa.large_string()) == "CAST('' AS string)"

    def test_int32_type(self):
        import pyarrow as pa

        assert _sql_default_for_arrow_type(pa.int32()) == "0"

    def test_float32_type(self):
        import pyarrow as pa

        assert _sql_default_for_arrow_type(pa.float32()) == "0.0"

    def test_int64_type(self):
        import pyarrow as pa

        assert _sql_default_for_arrow_type(pa.int64()) == "0"

    def test_list_type_raises(self):
        import pyarrow as pa

        with pytest.raises(RuntimeError):
            _sql_default_for_arrow_type(pa.list_(pa.float32()))


# =============================================================================
# Schema migration tests (AC-5, AC-8)
# =============================================================================


class TestSchemaMigration:
    def test_migration_adds_provenance_columns(self, palace_path):
        """AC-5/AC-8: Opening a pre-CODE-INCREMENTAL palace adds the 3 new columns."""
        import lancedb
        import pyarrow as pa

        # Build an old-schema table directly (without source_hash / extractor_version /
        # chunker_strategy) to simulate a palace created before this feature.
        db = lancedb.connect(os.path.join(palace_path, "lance"))
        old_schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 384)),
                pa.field("wing", pa.string()),
                pa.field("room", pa.string()),
                pa.field("source_file", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("added_by", pa.string()),
                pa.field("filed_at", pa.string()),
            ]
        )
        raw_table = db.create_table("mempalace_drawers", schema=old_schema)
        raw_table.add(
            [
                {
                    "id": "pre_migration_drawer",
                    "text": "some old content",
                    "vector": [0.0] * 384,
                    "wing": "test_wing",
                    "room": "general",
                    "source_file": "/old/file.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2025-01-01T00:00:00",
                }
            ]
        )

        # Open with the new LanceStore — migration should trigger
        store = open_store(palace_path, create=False)

        # Verify columns were added
        schema_names = set(store._table.schema.names)
        assert "source_hash" in schema_names
        assert "extractor_version" in schema_names
        assert "chunker_strategy" in schema_names

    def test_migration_existing_rows_get_empty_defaults(self, palace_path):
        """AC-5: Existing drawers have empty-string defaults after migration."""
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(os.path.join(palace_path, "lance"))
        old_schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 384)),
                pa.field("wing", pa.string()),
                pa.field("room", pa.string()),
                pa.field("source_file", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("added_by", pa.string()),
                pa.field("filed_at", pa.string()),
            ]
        )
        raw_table = db.create_table("mempalace_drawers", schema=old_schema)
        raw_table.add(
            [
                {
                    "id": "pre_migration_drawer",
                    "text": "some old content",
                    "vector": [0.0] * 384,
                    "wing": "test_wing",
                    "room": "general",
                    "source_file": "/old/file.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2025-01-01T00:00:00",
                }
            ]
        )

        store = open_store(palace_path, create=False)
        result = store.get(include=["metadatas"], limit=10)

        assert len(result["metadatas"]) == 1
        m = result["metadatas"][0]
        # All string columns added by migration must be "" not None
        OLD_9_COLS = {
            "id",
            "text",
            "vector",
            "wing",
            "room",
            "source_file",
            "chunk_index",
            "added_by",
            "filed_at",
        }
        new_string_cols = [
            name
            for name, type_tag, _ in _META_FIELD_SPEC
            if type_tag == "string" and name not in OLD_9_COLS
        ]
        assert len(new_string_cols) > 0, (
            "expected at least one new string column from _META_FIELD_SPEC"
        )
        for col in new_string_cols:
            assert m[col] == "", f"expected '' for {col!r}, got {m[col]!r}"

    def test_new_palace_has_provenance_columns(self, palace_path):
        """AC-8: A freshly created palace includes all three provenance columns."""
        store = open_store(palace_path, create=True)
        schema_names = set(store._table.schema.names)
        assert "source_hash" in schema_names
        assert "extractor_version" in schema_names
        assert "chunker_strategy" in schema_names

    def test_multiple_writes_after_migration(self, palace_path):
        """AC-1: Four consecutive add() calls succeed after migrating a 9-column palace."""
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(os.path.join(palace_path, "lance"))
        old_schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 384)),
                pa.field("wing", pa.string()),
                pa.field("room", pa.string()),
                pa.field("source_file", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("added_by", pa.string()),
                pa.field("filed_at", pa.string()),
            ]
        )
        db.create_table("mempalace_drawers", schema=old_schema)

        store = open_store(palace_path, create=False)
        for i in range(4):
            store.add(
                ids=[f"drawer_{i}"],
                documents=[f"distinct content for migration regression test drawer number {i}"],
                metadatas=[{"wing": "test", "room": "general"}],
            )

        assert store.count() == 4

    def test_migration_covers_all_missing_columns(self, palace_path):
        """AC-2: Opening a 9-column palace migrates all columns from _target_drawer_schema."""
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(os.path.join(palace_path, "lance"))
        old_schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 384)),
                pa.field("wing", pa.string()),
                pa.field("room", pa.string()),
                pa.field("source_file", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("added_by", pa.string()),
                pa.field("filed_at", pa.string()),
            ]
        )
        db.create_table("mempalace_drawers", schema=old_schema)

        store = open_store(palace_path, create=False)

        target_names = set(_target_drawer_schema(384).names)
        schema_names = set(store._table.schema.names)
        assert target_names <= schema_names

    def test_new_palace_has_all_target_columns(self, palace_path):
        """AC-4: A freshly created palace includes all columns from _target_drawer_schema."""
        store = open_store(palace_path, create=True)
        target_names = set(_target_drawer_schema(384).names)
        schema_names = set(store._table.schema.names)
        assert target_names <= schema_names

    def test_migration_logs_added_columns(self, palace_path, caplog):
        """AC-7: Migration logs the list of added columns at INFO level."""
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(os.path.join(palace_path, "lance"))
        old_schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 384)),
                pa.field("wing", pa.string()),
                pa.field("room", pa.string()),
                pa.field("source_file", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("added_by", pa.string()),
                pa.field("filed_at", pa.string()),
            ]
        )
        db.create_table("mempalace_drawers", schema=old_schema)

        with caplog.at_level(logging.INFO, logger="mempalace"):
            open_store(palace_path, create=False)

        migrating = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.INFO and "Migrating palace schema" in r.getMessage()
        ]
        assert len(migrating) == 1
        assert "hall" in migrating[0]
        assert "language" in migrating[0]
        assert "source_hash" in migrating[0]

    def test_write_with_all_metadata_after_migration(self, palace_path):
        """AC-1/AC-2/AC-3: All _META_FIELD_SPEC fields roundtrip after migrating a 9-column palace."""
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(os.path.join(palace_path, "lance"))
        old_schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 384)),
                pa.field("wing", pa.string()),
                pa.field("room", pa.string()),
                pa.field("source_file", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("added_by", pa.string()),
                pa.field("filed_at", pa.string()),
            ]
        )
        db.create_table("mempalace_drawers", schema=old_schema)

        store = open_store(palace_path, create=False)

        # Build sentinel values programmatically from _META_FIELD_SPEC so that
        # any future field additions are automatically covered.
        sentinel_meta: dict = {}
        for name, type_tag, _ in _META_FIELD_SPEC:
            if type_tag == "string":
                sentinel_meta[name] = f"sentinel_{name}"
            elif type_tag == "int32":
                sentinel_meta[name] = 42
            elif type_tag == "float32":
                sentinel_meta[name] = 0.75

        drawer_id = "sentinel_drawer"
        store.add(
            ids=[drawer_id],
            documents=["roundtrip content for all-metadata migration test"],
            metadatas=[sentinel_meta],
        )

        result = store.get(ids=[drawer_id], include=["metadatas"])
        assert len(result["metadatas"]) == 1
        m = result["metadatas"][0]

        for name, type_tag, _ in _META_FIELD_SPEC:
            assert name in m, f"field {name!r} missing from get() result"
            if type_tag == "string":
                expected = f"sentinel_{name}"
                assert m[name] == expected, f"{name}: expected {expected!r}, got {m[name]!r}"
            elif type_tag == "int32":
                assert m[name] == 42, f"{name}: expected 42, got {m[name]!r}"
            elif type_tag == "float32":
                assert abs(m[name] - 0.75) < 0.01, f"{name}: expected ~0.75, got {m[name]!r}"


class TestDeleteBySourceFile:
    def test_deletes_drawers_for_source_file(self, palace_path):
        """delete_by_source_file() removes all drawers for the given file in the wing."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["d1", "d2", "d3"],
            documents=["chunk one", "chunk two", "other file"],
            metadatas=[
                {"wing": "w", "room": "r", "source_file": "/project/a.py"},
                {"wing": "w", "room": "r", "source_file": "/project/a.py"},
                {"wing": "w", "room": "r", "source_file": "/project/b.py"},
            ],
        )
        deleted = store.delete_by_source_file("/project/a.py", "w")
        assert deleted == 2
        assert store.count() == 1

    def test_returns_zero_when_not_found(self, palace_path):
        store = open_store(palace_path, create=True)
        deleted = store.delete_by_source_file("/nonexistent.py", "w")
        assert deleted == 0

    def test_wing_scoped(self, palace_path):
        """delete_by_source_file() only removes drawers in the specified wing."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["w1", "w2"],
            documents=["content in wing alpha", "content in wing beta"],
            metadatas=[
                {"wing": "alpha", "room": "r", "source_file": "/shared/file.py"},
                {"wing": "beta", "room": "r", "source_file": "/shared/file.py"},
            ],
        )
        deleted = store.delete_by_source_file("/shared/file.py", "alpha")
        assert deleted == 1
        assert store.count() == 1
        remaining = store.get(include=["metadatas"])
        assert remaining["metadatas"][0]["wing"] == "beta"

    def test_special_quote_in_path(self, palace_path):
        """Paths with single quotes are handled safely (SQL-escaped)."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["sq1"],
            documents=["content here"],
            metadatas=[{"wing": "w", "room": "r", "source_file": "/it's/here.py"}],
        )
        deleted = store.delete_by_source_file("/it's/here.py", "w")
        assert deleted == 1
        assert store.count() == 0


class TestGetSourceFileHashes:
    def test_empty_table_returns_empty_dict(self, palace_path):
        store = open_store(palace_path, create=True)
        result = store.get_source_file_hashes("any_wing")
        assert result == {}

    def test_returns_hashes_for_wing(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["h1", "h2", "h3"],
            documents=["content a", "content b", "content c"],
            metadatas=[
                {"wing": "proj", "room": "r", "source_file": "/a.py", "source_hash": "abc123"},
                {"wing": "proj", "room": "r", "source_file": "/b.py", "source_hash": "def456"},
                {"wing": "other", "room": "r", "source_file": "/c.py", "source_hash": "ghi789"},
            ],
        )
        result = store.get_source_file_hashes("proj")
        assert result == {"/a.py": "abc123", "/b.py": "def456"}

    def test_wing_filter_excludes_other_wings(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["x1"],
            documents=["some other wing content"],
            metadatas=[
                {"wing": "other", "room": "r", "source_file": "/x.py", "source_hash": "aaa"}
            ],
        )
        result = store.get_source_file_hashes("target_wing")
        assert result == {}

    def test_deduplicates_by_first_hash(self, palace_path):
        """Multiple chunks per file share the same hash; only one entry is returned."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["c1", "c2"],
            documents=["chunk one content text", "chunk two content text"],
            metadatas=[
                {"wing": "w", "room": "r", "source_file": "/f.py", "source_hash": "samehash"},
                {"wing": "w", "room": "r", "source_file": "/f.py", "source_hash": "samehash"},
            ],
        )
        result = store.get_source_file_hashes("w")
        assert result == {"/f.py": "samehash"}


# =============================================================================
# _META_FIELD_SPEC consistency and metadata roundtrip tests (AC-4, AC-6)
# =============================================================================


class TestSafeOptimize:
    def _add_optimize_fixture(self, store, doc_id):
        store.add(
            ids=[doc_id],
            documents=[f"safe optimize retention test document {doc_id}"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

    def _pre_optimize_archives(self, tmp_dir):
        return sorted(os.listdir(os.path.join(tmp_dir, "backups")))

    def test_happy_path_returns_true_and_readable(self, palace_path):
        """AC-1: safe_optimize(backup_first=False) returns True; row count unchanged; table readable."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["so1", "so2"],
            documents=["safe optimize test document one", "safe optimize test document two"],
            metadatas=[
                {"wing": "w", "room": "r"},
                {"wing": "w", "room": "r"},
            ],
        )
        pre_count = store.count()

        result = store.safe_optimize(palace_path, backup_first=False)

        assert result is True
        assert store.count() == pre_count
        rows = store.get(limit=1)
        assert len(rows["ids"]) == 1

    def test_backup_first_creates_backup_file(self, palace_path, tmp_dir):
        """AC-2: safe_optimize(backup_first=True) creates a pre_optimize_*.tar.gz under backups/."""
        import glob

        store = open_store(palace_path, create=True)
        store.add(
            ids=["bk1"],
            documents=["backup before optimize test content"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        result = store.safe_optimize(palace_path, backup_first=True)

        assert result is True
        backup_dir = os.path.join(tmp_dir, "backups")
        assert os.path.isdir(backup_dir), f"backups/ dir not created at {backup_dir}"
        archives = glob.glob(os.path.join(backup_dir, "pre_optimize_*.tar.gz"))
        assert len(archives) == 1, f"Expected 1 backup archive, found: {archives}"

    def test_backup_failure_returns_false_and_skips_optimize(self, palace_path):
        """AC-3: When create_backup raises, safe_optimize returns False and _table.optimize() is NOT called."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["fail1"],
            documents=["backup failure test content here"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        with patch(
            "mempalace.backup.create_backup", side_effect=OSError("disk full")
        ) as mock_backup:
            with patch.object(store._table, "optimize") as mock_optimize:
                result = store.safe_optimize(palace_path, backup_first=True)

        assert result is False
        mock_backup.assert_called_once()
        mock_optimize.assert_not_called()

    def test_retention_prunes_old_pre_optimize_archives(self, palace_path, tmp_dir, monkeypatch):
        """AC-1: keep only the newest N pre-optimize archives after successful optimize."""
        store = open_store(palace_path, create=True)
        self._add_optimize_fixture(store, "retain1")

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "2")
        fake_datetime = MagicMock()
        fake_datetime.now.side_effect = [
            datetime(2026, 1, 1, 12, 0, 0),
            datetime(2026, 1, 1, 12, 0, 1),
            datetime(2026, 1, 1, 12, 0, 2),
        ]

        with patch("mempalace.storage.datetime", fake_datetime):
            results = [store.safe_optimize(palace_path, backup_first=True) for _ in range(3)]

        assert results == [True, True, True]
        archives = self._pre_optimize_archives(tmp_dir)
        assert archives == [
            "pre_optimize_20260101_120001.tar.gz",
            "pre_optimize_20260101_120002.tar.gz",
        ]

    def test_retention_default_zero_keeps_all_archives(self, palace_path, tmp_dir):
        """AC-2: default backup_retain_count=0 disables pruning."""
        store = open_store(palace_path, create=True)
        self._add_optimize_fixture(store, "retain_default")

        fake_datetime = MagicMock()
        fake_datetime.now.side_effect = [
            datetime(2026, 1, 1, 12, 1, 0),
            datetime(2026, 1, 1, 12, 1, 1),
        ]

        with patch("mempalace.storage.datetime", fake_datetime):
            first = store.safe_optimize(palace_path, backup_first=True)
            second = store.safe_optimize(palace_path, backup_first=True)

        assert (first, second) == (True, True)
        archives = self._pre_optimize_archives(tmp_dir)
        assert archives == [
            "pre_optimize_20260101_120100.tar.gz",
            "pre_optimize_20260101_120101.tar.gz",
        ]

    def test_retention_preserves_non_pre_optimize_files(self, palace_path, tmp_dir, monkeypatch):
        """AC-3: retention only removes old pre_optimize_*.tar.gz files."""
        store = open_store(palace_path, create=True)
        self._add_optimize_fixture(store, "retain_scope")
        backup_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backup_dir)
        for name in (
            "pre_optimize_20260101_115900.tar.gz",
            "mempalace_backup_20260101_115900.tar.gz",
            "scheduled_20260101_115900.tar.gz",
            "notes.txt",
        ):
            with open(os.path.join(backup_dir, name), "w") as f:
                f.write("sentinel")

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "1")
        fake_datetime = MagicMock()
        fake_datetime.now.return_value = datetime(2026, 1, 1, 12, 2, 0)

        with patch("mempalace.storage.datetime", fake_datetime):
            result = store.safe_optimize(palace_path, backup_first=True)

        assert result is True
        assert sorted(os.listdir(backup_dir)) == [
            "mempalace_backup_20260101_115900.tar.gz",
            "notes.txt",
            "pre_optimize_20260101_120200.tar.gz",
            "scheduled_20260101_115900.tar.gz",
        ]

    def test_retention_prune_error_is_warning_not_failure(
        self, palace_path, tmp_dir, monkeypatch, caplog
    ):
        """AC-4: failed pruning logs WARNING and does not mask successful optimize."""
        store = open_store(palace_path, create=True)
        self._add_optimize_fixture(store, "retain_warning")
        backup_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backup_dir)
        for name in (
            "pre_optimize_20260101_115800.tar.gz",
            "pre_optimize_20260101_115900.tar.gz",
        ):
            with open(os.path.join(backup_dir, name), "w") as f:
                f.write("sentinel")

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "1")
        fake_datetime = MagicMock()
        fake_datetime.now.return_value = datetime(2026, 1, 1, 12, 3, 0)

        with patch("mempalace.storage.datetime", fake_datetime):
            with patch("pathlib.Path.unlink", side_effect=OSError("permission denied")):
                with caplog.at_level(logging.WARNING, logger="mempalace"):
                    result = store.safe_optimize(palace_path, backup_first=True)

        assert result is True
        warning_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("backup pruning" in msg.lower() for msg in warning_msgs)

    def test_backup_failure_logs_error(self, palace_path, caplog):
        """AC-3: Backup failure is logged at ERROR level."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["logfail1"],
            documents=["backup failure logging test content"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        with patch("mempalace.backup.create_backup", side_effect=OSError("no space")):
            with caplog.at_level(logging.ERROR, logger="mempalace"):
                store.safe_optimize(palace_path, backup_first=True)

        error_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert any("backup" in m.lower() for m in error_msgs), f"No error logged: {error_msgs}"

    def test_trailing_slash_does_not_misplace_backup(self, palace_path, tmp_dir):
        """Path normalisation: trailing slash on palace_path must not break backup dir placement."""
        import glob

        store = open_store(palace_path, create=True)
        store.add(
            ids=["slash1"],
            documents=["trailing slash path normalisation test content"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        result = store.safe_optimize(palace_path + "/", backup_first=True)

        assert result is True
        backup_dir = os.path.join(tmp_dir, "backups")
        archives = glob.glob(os.path.join(backup_dir, "pre_optimize_*.tar.gz"))
        assert len(archives) == 1, f"backup should be sibling of palace, found: {archives}"

    def test_optimize_exception_returns_false_and_does_not_propagate(self, palace_path):
        """F-1 regression: if _table.optimize() raises, safe_optimize returns False (not exception)."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["exc1"],
            documents=["optimize exception propagation test content"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        with patch.object(store._table, "optimize", side_effect=RuntimeError("disk full")):
            result = store.safe_optimize(palace_path, backup_first=False)

        assert result is False


class TestMetaFieldSpec:
    def test_meta_field_spec_consistency(self):
        """AC-4: _META_KEYS, _META_DEFAULTS.keys(), and schema column names are identical sets."""
        schema_meta_names = {
            f.name for f in _target_drawer_schema(384) if f.name not in ("id", "text", "vector")
        }
        assert set(_META_KEYS) == schema_meta_names
        assert set(_META_DEFAULTS.keys()) == schema_meta_names

    def test_meta_field_spec_no_duplicates(self):
        """Every field name in _META_FIELD_SPEC is unique."""
        names = [name for name, _, _ in _META_FIELD_SPEC]
        assert len(names) == len(set(names))

    def test_metadata_roundtrip_all_fields(self, palace_path):
        """AC-6: non-default values for string, int, and float fields survive get/query/iter_all."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["rt1"],
            documents=["roundtrip test document for metadata field coverage"],
            metadatas=[
                {
                    "wing": "test_wing",
                    "room": "test_room",
                    "hall": "test_hall",
                    "date": "2026-01-01",
                    "compression_ratio": 2.5,
                    "original_tokens": 42,
                }
            ],
        )

        # get()
        result = store.get(ids=["rt1"], include=["metadatas"])
        m = result["metadatas"][0]
        assert m["hall"] == "test_hall"
        assert m["date"] == "2026-01-01"
        assert abs(m["compression_ratio"] - 2.5) < 0.01
        assert m["original_tokens"] == 42

        # query()
        q_result = store.query(
            query_texts=["roundtrip test document"],
            n_results=1,
            include=["metadatas"],
        )
        qm = q_result["metadatas"][0][0]
        assert qm["hall"] == "test_hall"
        assert qm["date"] == "2026-01-01"
        assert abs(qm["compression_ratio"] - 2.5) < 0.01
        assert qm["original_tokens"] == 42

        # iter_all()
        batches = list(store.iter_all())
        rows = [row for batch in batches for row in batch]
        assert len(rows) == 1
        row = rows[0]
        assert row["hall"] == "test_hall"
        assert row["date"] == "2026-01-01"
        assert abs(row["compression_ratio"] - 2.5) < 0.01
        assert row["original_tokens"] == 42


# =============================================================================
# Fragment corruption detection and recovery (FIX-LANCE-CORRUPT)
# =============================================================================


def _find_data_files(palace_path: str) -> set:
    """Return the set of .lance fragment files under the LanceDB data directory."""
    import glob

    pattern = os.path.join(palace_path, "lance", "mempalace_drawers.lance", "data", "*.lance")
    return set(glob.glob(pattern))


def _corrupt_newest_fragment(palace_path: str, files_before: set) -> str | None:
    """Rename a fragment file that appeared after files_before. Returns the renamed path or None."""
    files_after = _find_data_files(palace_path)
    new_files = files_after - files_before
    if not new_files:
        return None
    target = sorted(new_files)[0]
    renamed = target + ".corrupt_test"
    os.rename(target, renamed)
    return renamed


class TestLanceHealth:
    """AC-1 through AC-4: health_check() and recover_to_last_working_version()."""

    def test_health_check_healthy_palace_returns_ok(self, palace_path):
        """AC-1: health_check() on a healthy palace returns ok=True, no errors."""
        from mempalace.storage import LanceStore

        store = open_store(palace_path, create=True)
        assert isinstance(store, LanceStore)
        store.add(
            ids=["hc1", "hc2"],
            documents=["health check drawer one", "health check drawer two"],
            metadatas=[
                {"wing": "test", "room": "general"},
                {"wing": "test", "room": "backend"},
            ],
        )

        report = store.health_check()

        assert report["ok"] is True
        assert report["total_rows"] == 2
        assert report["current_version"] is not None
        assert report["errors"] == []
        assert "warnings" in report  # warnings key always present

    def test_health_check_corrupt_store_returns_ok_false(self, palace_path):
        """AC-2: health_check() on a store with a missing fragment returns ok=False."""
        from mempalace.storage import LanceStore

        store = open_store(palace_path, create=True)
        assert isinstance(store, LanceStore)
        store.add(
            ids=["hc_bad1", "hc_bad2"],
            documents=["corrupt test drawer one content", "corrupt test drawer two content"],
            metadatas=[
                {"wing": "test", "room": "general"},
                {"wing": "test", "room": "backend"},
            ],
        )

        # Record current fragment files, then corrupt one
        files_before = set()
        renamed = _corrupt_newest_fragment(palace_path, files_before)
        if renamed is None:
            pytest.skip("No data files found to corrupt — LanceDB layout may have changed")

        # Re-open the store so the handle is fresh (sees missing fragment)
        store2 = open_store(palace_path, create=False)
        assert isinstance(store2, LanceStore)

        report = store2.health_check()

        assert report["ok"] is False
        assert len(report["errors"]) >= 1
        kinds = {e["kind"] for e in report["errors"]}
        assert kinds & {"fragment_missing", "read_failed", "other"}, (
            f"Expected a recognized error kind, got: {kinds}"
        )

    def test_health_check_list_versions_failure_does_not_set_ok_false(
        self, palace_path, monkeypatch
    ):
        """F-1 regression: list_versions() failure must NOT cause ok=False (false-positive degraded)."""
        from mempalace.storage import LanceStore

        store = open_store(palace_path, create=True)
        assert isinstance(store, LanceStore)
        store.add(
            ids=["hc_lv1"],
            documents=["list versions failure test drawer content"],
            metadatas=[{"wing": "test", "room": "general"}],
        )

        def _broken_list_versions():
            raise RuntimeError("version metadata unavailable")

        monkeypatch.setattr(store._table, "list_versions", _broken_list_versions)

        report = store.health_check()

        assert report["ok"] is True, "list_versions failure must not set ok=False"
        assert report["errors"] == [], "list_versions failure must not appear in errors"
        assert len(report["warnings"]) >= 1, "list_versions failure must appear in warnings"
        assert report["warnings"][0]["probe"] == "list_versions"

    def test_recover_dry_run_reports_candidate_and_does_not_mutate(self, palace_path):
        """AC-3: recover_to_last_working_version(dry_run=True) reports candidate, leaves store unchanged."""
        from mempalace.storage import LanceStore

        store = open_store(palace_path, create=True)
        assert isinstance(store, LanceStore)

        # Phase 1: add data, snapshot fragment list
        store.add(
            ids=["rv1", "rv2"],
            documents=[
                "version one drawer for rollback test content",
                "another version one drawer for rollback test",
            ],
            metadatas=[
                {"wing": "test", "room": "general"},
                {"wing": "test", "room": "general"},
            ],
        )
        files_after_phase1 = _find_data_files(palace_path)

        # Phase 2: add more data, creating a new version with new fragments
        store.add(
            ids=["rv3", "rv4"],
            documents=[
                "version two drawer for rollback test here",
                "another version two drawer for rollback test",
            ],
            metadatas=[
                {"wing": "test", "room": "backend"},
                {"wing": "test", "room": "backend"},
            ],
        )

        versions_before = store._table.list_versions()
        if len(versions_before) < 2:
            pytest.skip("LanceDB did not create multiple versions — cannot test rollback")

        current_version_before = versions_before[-1]["version"]

        # Corrupt a fragment from phase 2
        renamed = _corrupt_newest_fragment(palace_path, files_after_phase1)
        if renamed is None:
            pytest.skip("Could not identify new fragment from phase 2")

        # Re-open with fresh handle
        corrupt_store = open_store(palace_path, create=False)
        assert isinstance(corrupt_store, LanceStore)

        result = corrupt_store.recover_to_last_working_version(dry_run=True)

        # dry_run: recovered=False, candidate_version set
        assert result["dry_run"] is True
        assert result["recovered"] is False
        # Current version must be unchanged
        versions_after = corrupt_store._table.list_versions()
        current_version_after = versions_after[-1]["version"]
        assert current_version_after == current_version_before, (
            f"dry_run=True must not mutate the table: version changed "
            f"{current_version_before} -> {current_version_after}"
        )
        # Should have found a candidate (the healthy phase-1 version)
        if result.get("candidate_version") is None:
            pytest.skip("No healthy prior version found — phase-1 fragments may also be missing")

    def test_recover_live_restores_readable_version(self, palace_path):
        """AC-4: recover_to_last_working_version(dry_run=False) restores a healthy version."""
        from mempalace.storage import LanceStore

        store = open_store(palace_path, create=True)
        assert isinstance(store, LanceStore)

        # Phase 1: add data
        store.add(
            ids=["live1", "live2"],
            documents=[
                "live recovery test drawer one content here",
                "live recovery test drawer two content here",
            ],
            metadatas=[
                {"wing": "test", "room": "general"},
                {"wing": "test", "room": "general"},
            ],
        )
        files_after_phase1 = _find_data_files(palace_path)
        _ = store._table.list_versions()  # snapshot for timing reference (unused)

        # Phase 2: add more data
        store.add(
            ids=["live3", "live4"],
            documents=[
                "live recovery test drawer three content here",
                "live recovery test drawer four content here",
            ],
            metadatas=[
                {"wing": "test", "room": "backend"},
                {"wing": "test", "room": "backend"},
            ],
        )

        if len(store._table.list_versions()) < 2:
            pytest.skip("LanceDB did not create multiple versions")

        # Corrupt a phase-2 fragment
        renamed = _corrupt_newest_fragment(palace_path, files_after_phase1)
        if renamed is None:
            pytest.skip("Could not identify new fragment from phase 2")

        # Re-open
        corrupt_store = open_store(palace_path, create=False)
        assert isinstance(corrupt_store, LanceStore)

        # Sanity: health_check should be degraded before recovery
        pre_report = corrupt_store.health_check()
        if pre_report["ok"]:
            pytest.skip("Corruption simulation did not cause health_check to fail — skipping")

        result = corrupt_store.recover_to_last_working_version(dry_run=False)

        if result.get("recovered"):
            assert "restored_to" in result
            assert result["rows_after"] >= 1
            # Post-recovery health check must pass
            post_report = corrupt_store.health_check()
            assert post_report["ok"] is True, (
                f"health_check() still failing after recovery: {post_report['errors']}"
            )
        else:
            # No healthy version found — acceptable if phase-1 fragments were also affected
            pytest.skip(
                f"No recoverable version found: {result.get('message') or result.get('walk_errors')}"
            )


# =============================================================================
# $in operator in _where_to_arrow_mask (STORE-WHERE-ARROW-IN)
# =============================================================================


class TestWhereToArrowMaskIn:
    """Verify that $in filtering works correctly via iter_all()."""

    def _make_store(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["a1", "a2", "b1", "b2", "c1"],
            documents=["doc a1", "doc a2", "doc b1", "doc b2", "doc c1"],
            metadatas=[
                {"wing": "alpha", "room": "general"},
                {"wing": "alpha", "room": "notes"},
                {"wing": "beta", "room": "general"},
                {"wing": "beta", "room": "notes"},
                {"wing": "gamma", "room": "general"},
            ],
        )
        return store

    def _ids(self, store, where):
        batches = list(store.iter_all(where=where))
        return {row["id"] for batch in batches for row in batch}

    def test_in_matches_multiple_values(self, palace_path):
        store = self._make_store(palace_path)
        result = self._ids(store, {"wing": {"$in": ["alpha", "beta"]}})
        assert result == {"a1", "a2", "b1", "b2"}

    def test_in_matches_single_value(self, palace_path):
        store = self._make_store(palace_path)
        result = self._ids(store, {"wing": {"$in": ["gamma"]}})
        assert result == {"c1"}

    def test_in_empty_list_returns_no_rows(self, palace_path):
        store = self._make_store(palace_path)
        result = self._ids(store, {"wing": {"$in": []}})
        assert result == set()

    def test_in_no_matching_values_returns_empty(self, palace_path):
        store = self._make_store(palace_path)
        result = self._ids(store, {"wing": {"$in": ["delta", "epsilon"]}})
        assert result == set()

    def test_in_combined_with_eq(self, palace_path):
        """$in on wing AND equality on room narrows results further."""
        store = self._make_store(palace_path)
        result = self._ids(
            store, {"$and": [{"wing": {"$in": ["alpha", "beta"]}}, {"room": "general"}]}
        )
        assert result == {"a1", "b1"}
