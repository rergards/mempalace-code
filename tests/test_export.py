"""
test_export.py — Tests for export/import JSONL round-trip (CORE-EXPORT-IMPORT).

Covers:
  - Full round-trip with --only-manual filter (AC-5)
  - KG round-trip with --with-kg (AC-7)
  - Import dedup prevents double-count (AC-6)
  - Dry-run leaves palace unchanged (AC-4 / dry-run)
  - Wing/room/since filters scope output (AC-3)
  - Export without embeddings: embedding field is null (AC-8)
  - Export header is first line with version + counts (AC-2)
  - Version mismatch warning on import (AC-4)
"""

import json
import os
import shutil

from mempalace_code.export import import_jsonl, read_jsonl, write_jsonl
from mempalace_code.knowledge_graph import KnowledgeGraph
from mempalace_code.storage import open_store

# ── Helpers ───────────────────────────────────────────────────────────────────


def _store(palace_path):
    os.makedirs(palace_path, exist_ok=True)
    return open_store(palace_path, create=True)


def _add_code_drawer(store, wing="project", room="backend"):
    """Simulate a miner-style drawer (regex_structural_v1)."""
    store.add(
        ids=[f"miner_{wing}_{room}_001"],
        documents=["def authenticate(token): validate JWT token in request headers"],
        metadatas=[
            {
                "wing": wing,
                "room": room,
                "source_file": "auth.py",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
                "chunker_strategy": "regex_structural_v1",
                "extractor_version": "3.0.0",
            }
        ],
    )


def _add_manual_drawer(
    store, wing="notes", room="general", content="Manual note about the architecture decision."
):
    """Simulate a manual drawer (manual_v1, as written by tool_add_drawer)."""
    import hashlib
    from datetime import datetime

    drawer_id = f"drawer_{wing}_{room}_{hashlib.md5((content[:100] + datetime.now().isoformat()).encode()).hexdigest()[:16]}"
    store.add(
        ids=[drawer_id],
        documents=[content],
        metadatas=[
            {
                "wing": wing,
                "room": room,
                "source_file": "",
                "chunk_index": 0,
                "added_by": "mcp",
                "filed_at": "2026-02-01T00:00:00",
                "chunker_strategy": "manual_v1",
                "extractor_version": "3.0.0",
            }
        ],
    )
    return drawer_id


def _add_diary_drawer(
    store, wing="wing_claude", room="diary", content="Diary: finished feature X today."
):
    """Simulate a diary drawer (diary_v1, as written by diary write)."""
    import hashlib
    from datetime import datetime

    drawer_id = f"diary_{wing}_{hashlib.md5((content[:100] + datetime.now().isoformat()).encode()).hexdigest()[:16]}"
    store.add(
        ids=[drawer_id],
        documents=[content],
        metadatas=[
            {
                "wing": wing,
                "room": room,
                "source_file": "",
                "chunk_index": 0,
                "added_by": "diary",
                "filed_at": "2026-02-02T00:00:00",
                "chunker_strategy": "diary_v1",
                "extractor_version": "3.0.0",
            }
        ],
    )
    return drawer_id


# ── AC-5: Full round-trip, --only-manual ──────────────────────────────────────


class TestExportImportRoundtripManualOnly:
    def test_roundtrip(self, tmp_path):
        """Mine simulated code, add manual + diary drawers, export --only-manual,
        nuke, re-add code-only, import, assert manual+diary restored, no duplicates."""
        palace = str(tmp_path / "palace")
        store = _store(palace)
        export_file = str(tmp_path / "backup.jsonl")

        # Seed: 1 code drawer + 1 manual + 1 diary
        _add_code_drawer(store)
        manual_id = _add_manual_drawer(store)
        diary_id = _add_diary_drawer(store)
        assert store.count() == 3

        # Export only manual
        write_jsonl(
            path=export_file,
            store=store,
            only_manual=True,
            palace_path=palace,
        )

        # Verify exported JSONL has exactly 2 drawers
        records = list(read_jsonl(export_file))
        header = records[0]
        assert header["type"] == "export_header"
        drawer_records = [r for r in records if r["type"] == "drawer"]
        assert len(drawer_records) == 2
        exported_strategies = {r["chunker_strategy"] for r in drawer_records}
        assert exported_strategies <= {"manual_v1", "diary_v1"}
        assert "regex_structural_v1" not in exported_strategies

        # Nuke palace and re-create with only code drawers
        shutil.rmtree(palace)
        os.makedirs(palace)
        store2 = _store(palace)
        _add_code_drawer(store2)
        assert store2.count() == 1

        # Import the backup
        summary = import_jsonl(path=export_file, store=store2, skip_kg=True)

        assert summary["imported_drawers"] == 2
        assert summary["skipped_duplicates"] == 0
        assert store2.count() == 3

        # Verify manual and diary IDs exist
        result = store2.get(ids=[manual_id, diary_id], include=["documents"])
        assert len(result["ids"]) == 2


# ── AC-7: KG round-trip ───────────────────────────────────────────────────────


class TestExportWithKG:
    def test_kg_roundtrip(self, tmp_path):
        """Add KG triples with validity windows, export --with-kg, nuke, import, assert roundtrip."""
        palace = str(tmp_path / "palace")
        store = _store(palace)
        kg_src = KnowledgeGraph(db_path=str(tmp_path / "kg_src.sqlite3"))
        export_file = str(tmp_path / "kg_backup.jsonl")

        # Add a drawer and KG triples
        _add_manual_drawer(store)
        kg_src.add_triple("Alice", "works_on", "mempalace", valid_from="2026-01-01")
        kg_src.add_triple(
            "Bob", "child_of", "Alice", valid_from="2015-06-15", valid_to="2099-01-01"
        )

        write_jsonl(
            path=export_file,
            store=store,
            kg=kg_src,
            include_kg=True,
            palace_path=palace,
        )

        # Verify header counts
        records = list(read_jsonl(export_file))
        header = records[0]
        assert header["kg_count"] == 2
        kg_records = [r for r in records if r["type"] == "kg_triple"]
        assert len(kg_records) == 2
        predicates = {r["predicate"] for r in kg_records}
        assert "works_on" in predicates or "child_of" in predicates

        # Import into new KG
        kg_dst = KnowledgeGraph(db_path=str(tmp_path / "kg_dst.sqlite3"))
        summary = import_jsonl(path=export_file, store=store, kg=kg_dst)
        assert summary["imported_triples"] == 2

        # Verify triples exist
        stats = kg_dst.stats()
        assert stats["triples"] == 2

    def test_kg_since_filter_includes_triples_with_no_valid_from(self, tmp_path):
        """Triples with NULL valid_from are always valid and must NOT be excluded by --since."""
        palace = str(tmp_path / "palace")
        store = _store(palace)
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
        export_file = str(tmp_path / "since_kg.jsonl")

        _add_manual_drawer(store)
        # Triple with no valid_from — always valid
        kg.add_triple("Alice", "uses", "mempalace")
        # Triple with valid_from before since — should be excluded
        kg.add_triple("Bob", "owns", "project", valid_from="2025-01-01")

        write_jsonl(
            path=export_file,
            store=store,
            kg=kg,
            include_kg=True,
            since="2026-01-01",
            palace_path=palace,
        )

        records = list(read_jsonl(export_file))
        kg_records = [r for r in records if r["type"] == "kg_triple"]
        predicates = {r["predicate"] for r in kg_records}
        # "uses" (no valid_from) must be included; "owns" (2025-01-01 < 2026-01-01) must be excluded
        assert "uses" in predicates
        assert "owns" not in predicates


# ── AC-6: Import dedup prevents double-count ─────────────────────────────────


class TestImportDedupPreventsDoubleCount:
    def test_no_duplicates_on_reimport(self, tmp_path):
        """Export all drawers, import on top (dedup on), assert row count unchanged."""
        palace = str(tmp_path / "palace")
        store = _store(palace)
        export_file = str(tmp_path / "all.jsonl")

        _add_code_drawer(store)
        _add_manual_drawer(store)
        initial_count = store.count()
        assert initial_count == 2

        write_jsonl(path=export_file, store=store, palace_path=palace)

        summary = import_jsonl(path=export_file, store=store, skip_kg=True)

        assert store.count() == initial_count
        assert summary["skipped_duplicates"] > 0 or summary["imported_drawers"] == 0


# ── Dry-run leaves palace unchanged ──────────────────────────────────────────


class TestImportDryRun:
    def test_dry_run_no_changes(self, tmp_path):
        """--dry-run prints plan but palace is unchanged."""
        palace = str(tmp_path / "palace")
        src_palace = str(tmp_path / "src_palace")
        export_file = str(tmp_path / "export.jsonl")

        src_store = _store(src_palace)
        _add_manual_drawer(src_store, content="Dry run test content unique XYZ 12345.")
        write_jsonl(path=export_file, store=src_store, palace_path=src_palace)

        dst_store = _store(palace)
        before_count = dst_store.count()

        summary = import_jsonl(path=export_file, store=dst_store, skip_kg=True, dry_run=True)

        assert dst_store.count() == before_count
        assert summary["imported_drawers"] == 1  # counted but not written


# ── AC-3: Export filters ─────────────────────────────────────────────────────


class TestExportFilters:
    def test_wing_filter(self, tmp_path):
        palace = str(tmp_path / "palace")
        store = _store(palace)
        export_file = str(tmp_path / "wing_export.jsonl")

        _add_manual_drawer(store, wing="wing_a", content="Content in wing A for filtering test.")
        _add_manual_drawer(store, wing="wing_b", content="Content in wing B for filtering test.")

        write_jsonl(path=export_file, store=store, wing="wing_a", palace_path=palace)

        records = list(read_jsonl(export_file))
        drawers = [r for r in records if r["type"] == "drawer"]
        assert len(drawers) == 1
        assert drawers[0]["wing"] == "wing_a"

    def test_room_filter(self, tmp_path):
        palace = str(tmp_path / "palace")
        store = _store(palace)
        export_file = str(tmp_path / "room_export.jsonl")

        _add_manual_drawer(
            store, wing="wing_x", room="room_one", content="Content in room one for test."
        )
        _add_manual_drawer(
            store, wing="wing_x", room="room_two", content="Content in room two for test."
        )

        write_jsonl(path=export_file, store=store, room="room_one", palace_path=palace)

        records = list(read_jsonl(export_file))
        drawers = [r for r in records if r["type"] == "drawer"]
        assert len(drawers) == 1
        assert drawers[0]["room"] == "room_one"

    def test_since_filter(self, tmp_path):
        palace = str(tmp_path / "palace")
        store = _store(palace)
        export_file = str(tmp_path / "since_export.jsonl")

        # filed_at values are embedded in the test helpers (2026-02-01 and 2026-01-01)
        _add_code_drawer(store)  # filed_at: 2026-01-01
        _add_manual_drawer(store)  # filed_at: 2026-02-01

        write_jsonl(path=export_file, store=store, since="2026-02-01", palace_path=palace)

        records = list(read_jsonl(export_file))
        drawers = [r for r in records if r["type"] == "drawer"]
        # Only the 2026-02-01 drawer should be included
        for d in drawers:
            assert d.get("filed_at", "") >= "2026-02-01"


# ── AC-8: No-embeddings export ────────────────────────────────────────────────


class TestExportWithoutEmbeddings:
    def test_embedding_is_null_by_default(self, tmp_path):
        palace = str(tmp_path / "palace")
        store = _store(palace)
        export_file = str(tmp_path / "no_embed.jsonl")

        _add_manual_drawer(store)
        write_jsonl(path=export_file, store=store, include_vectors=False, palace_path=palace)

        records = list(read_jsonl(export_file))
        drawers = [r for r in records if r["type"] == "drawer"]
        assert len(drawers) == 1
        assert drawers[0]["embedding"] is None


# ── AC-2: Header is first line with correct counts ────────────────────────────


class TestExportHeaderIsFirstLine:
    def test_header_first_line(self, tmp_path):
        palace = str(tmp_path / "palace")
        store = _store(palace)
        export_file = str(tmp_path / "header_test.jsonl")

        _add_manual_drawer(store, content="First manual drawer for header count test.")
        _add_manual_drawer(
            store, wing="wing_x", room="general", content="Second drawer for header count test."
        )

        write_jsonl(path=export_file, store=store, palace_path=palace)

        with open(export_file) as f:
            first_line = json.loads(f.readline())

        assert first_line["type"] == "export_header"
        assert "version" in first_line
        assert first_line["drawer_count"] == 2
        assert first_line["kg_count"] == 0

    def test_header_includes_filters(self, tmp_path):
        palace = str(tmp_path / "palace")
        store = _store(palace)
        export_file = str(tmp_path / "header_filter_test.jsonl")

        _add_manual_drawer(store)
        write_jsonl(
            path=export_file, store=store, only_manual=True, wing="notes", palace_path=palace
        )

        with open(export_file) as f:
            header = json.loads(f.readline())

        assert header["filters"].get("only_manual") is True
        assert header["filters"].get("wing") == "notes"


# ── Streaming: large palace export batches ───────────────────────────────────


class TestExportStreamsLargePalace:
    def test_export_streams_large_palace(self, tmp_path, monkeypatch):
        """5k-drawer export: iter_all must yield >1 batch, proving streaming not one-shot load."""
        palace = str(tmp_path / "palace")
        store = _store(palace)
        export_file = str(tmp_path / "large_export.jsonl")

        # Skip real embeddings — AC: "No model loading required". The store still
        # loads the embedder once via open_store() to read ndims(), but we bypass
        # the per-document embed cost during the 5k-drawer seed.
        ndims = store._embedder.ndims()  # type: ignore[attr-defined]
        monkeypatch.setattr(store, "_embed", lambda texts: [[0.0] * ndims for _ in texts])

        n = 5000
        ids = [f"stream_{i:04d}" for i in range(n)]
        documents = [
            f"Synthetic drawer document number {i:04d} for streaming test." for i in range(n)
        ]
        metadatas = [
            {
                "wing": "stream_test",
                "room": "general",
                "source_file": "",
                "chunk_index": i,
                "added_by": "test",
                "filed_at": "2026-01-01T00:00:00",
                "chunker_strategy": "manual_v1",
                "extractor_version": "3.0.0",
            }
            for i in range(n)
        ]
        store.add(ids=ids, documents=documents, metadatas=metadatas)
        assert store.count() == n

        # Instrument iter_all on the store instance to record per-call batch sizes.
        per_call_batch_sizes = []
        original_iter_all = store.iter_all

        def instrumented_iter_all(*args, **kwargs):
            batch_sizes = []
            for batch in original_iter_all(*args, **kwargs):
                batch_sizes.append(len(batch))
                yield batch
            per_call_batch_sizes.append(batch_sizes)

        monkeypatch.setattr(store, "iter_all", instrumented_iter_all)

        summary = write_jsonl(path=export_file, store=store, palace_path=palace)

        # AC-1: all count surfaces agree on 5000
        assert summary["drawer_count"] == n

        records = list(read_jsonl(export_file))
        header = records[0]
        assert header["type"] == "export_header"
        assert header["drawer_count"] == n

        drawer_records = [r for r in records if r["type"] == "drawer"]
        assert len(drawer_records) == n

        # AC-4: default export omits vectors
        for dr in drawer_records:
            assert dr["embedding"] is None

        # AC-2 / AC-3: at least one iter_all call must have produced >1 batch and
        # the batches must sum to n (proves no rows lost in streaming).
        assert per_call_batch_sizes, "iter_all was never invoked — export skipped streaming path"
        multi_batch_calls = [sizes for sizes in per_call_batch_sizes if len(sizes) > 1]
        assert multi_batch_calls, (
            f"No iter_all call observed more than one batch — batching is broken. "
            f"Per-call batch sizes: {per_call_batch_sizes}"
        )
        for sizes in multi_batch_calls:
            assert sum(sizes) == n, (
                f"Batched iter_all yielded {sum(sizes)} rows, expected {n}: {sizes}"
            )
            assert max(sizes) <= 1000, (
                f"At least one batch exceeded default batch_size=1000: {sizes}"
            )


# ── Version mismatch warning ─────────────────────────────────────────────────


class TestImportVersionMismatchWarns:
    def test_version_mismatch_warns_but_proceeds(self, tmp_path):
        palace = str(tmp_path / "palace")
        store = _store(palace)
        export_file = str(tmp_path / "old_version.jsonl")

        _add_manual_drawer(store, content="Version mismatch test content unique ABC 99999.")
        write_jsonl(path=export_file, store=store, palace_path=palace)

        # Patch the version in the header
        lines = open(export_file).readlines()
        header = json.loads(lines[0])
        header["version"] = "0.0.1"  # fake old version
        lines[0] = json.dumps(header) + "\n"
        with open(export_file, "w") as f:
            f.writelines(lines)

        # Import into a fresh palace
        dst_palace = str(tmp_path / "dst_palace")
        dst_store = _store(dst_palace)
        summary = import_jsonl(path=export_file, store=dst_store, skip_kg=True)

        # Should proceed despite mismatch
        assert summary["imported_drawers"] == 1
        assert len(summary["warnings"]) == 1
        assert "0.0.1" in summary["warnings"][0]
