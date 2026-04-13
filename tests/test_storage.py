"""
test_storage.py — Tests for DrawerStore aggregation and delete_wing.
"""

import logging
import os

import pytest
from unittest.mock import MagicMock, patch

from mempalace.storage import (
    DrawerStore,
    _META_DEFAULTS,
    _META_FIELD_SPEC,
    _META_KEYS,
    _sql_default_for_arrow_type,
    _target_drawer_schema,
    open_store,
)


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
        new_string_cols = [
            "hall",
            "topic",
            "type",
            "agent",
            "date",
            "ingest_mode",
            "extract_mode",
            "language",
            "symbol_name",
            "symbol_type",
            "source_hash",
            "extractor_version",
            "chunker_strategy",
        ]
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
