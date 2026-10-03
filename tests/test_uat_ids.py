"""
test_uat_ids.py — Filter injection and drawer-id integrity (UAT group "ids").

Covers:
  - every LanceDB filter value goes through one quoting helper (sql_literal)
  - adversarial ids/values (quotes, backslashes, unicode, OR payloads) round-trip
    through add/get/delete and every field-filter path without matching extra rows
  - LanceStore.add refuses duplicate ids before writing
  - MCP delete_drawer cannot be widened by a crafted id and deletes quoted ids
  - a full repair rebuilds palaces that hold repeated or empty ids without losing text
  - import validation, dry-run counts, and a recovery command that keeps every option
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from mempalace_code.storage import (
    DuplicateDrawerIdError,
    LanceStore,
    open_store,
    sql_literal,
    unique_drawer_rows,
)

OR_PAYLOAD = "nonexistent') OR ('1'='1"
ADVERSARIAL_VALUES = [
    "it's",
    "O'Brien",
    "a''b",
    "back\\slash",
    "back\\'quote",
    "trailing\\",
    "unicode-日本語-é-😀",
    "new\nline",
    'double"quote',
    "pct%_under",
    OR_PAYLOAD,
    "x' OR 1=1 --",
    "'; DROP TABLE mempalace_drawers; --",
]


def _store(tmp_path, name: str = "palace") -> LanceStore:
    store = open_store(str(tmp_path / name), create=True)
    assert isinstance(store, LanceStore)
    return store


def _seed(store: LanceStore, values: list[str]) -> list[str]:
    """Add one control drawer plus one drawer per value (value used as id/wing/room/source)."""
    ids = ["control"] + [f"id-{value}" for value in values]
    store.add(
        ids=ids,
        documents=[f"document number {i} about topic {i}" for i in range(len(ids))],
        metadatas=[{"wing": "control", "room": "control", "source_file": "control.py"}]
        + [{"wing": f"w-{v}", "room": f"r-{v}", "source_file": f"src/{v}.py"} for v in values],
    )
    return ids


# ── The quoting helper ──────────────────────────────────────────────────────


class TestSqlLiteral:
    def test_strings_double_single_quotes_only(self):
        assert sql_literal("plain") == "'plain'"
        assert sql_literal("it's") == "'it''s'"
        assert sql_literal(OR_PAYLOAD) == "'nonexistent'') OR (''1''=''1'"
        assert sql_literal("back\\slash") == "'back\\slash'"
        assert sql_literal("") == "''"

    def test_numbers_and_bools_unquoted(self):
        assert sql_literal(3) == "3"
        assert sql_literal(-2) == "-2"
        assert sql_literal(1.5) == "1.5"
        assert sql_literal(True) == "TRUE"
        assert sql_literal(False) == "FALSE"

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_numbers_rejected(self, bad):
        with pytest.raises(ValueError, match="non-finite"):
            sql_literal(bad)

    @pytest.mark.parametrize("bad", [None, b"bytes", ["list"], {"a": 1}])
    def test_other_types_rejected(self, bad):
        with pytest.raises(TypeError):
            sql_literal(bad)


class TestWhereToSqlHardening:
    @pytest.mark.parametrize("value", ADVERSARIAL_VALUES)
    def test_every_operator_quotes_values(self, value):
        quoted = sql_literal(value)
        assert LanceStore._where_to_sql({"wing": value}) == f"wing = {quoted}"
        for op, sql_op in (("$eq", "="), ("$ne", "!="), ("$gt", ">"), ("$lte", "<=")):
            assert LanceStore._where_to_sql({"wing": {op: value}}) == f"wing {sql_op} {quoted}"
        assert LanceStore._where_to_sql({"wing": {"$in": [value]}}) == f"wing = {quoted}"
        assert (
            LanceStore._where_to_sql({"wing": {"$in": [value, "b"]}}) == f"wing IN ({quoted}, 'b')"
        )

    def test_string_range_comparison_is_quoted(self):
        assert (
            LanceStore._where_to_sql({"filed_at": {"$gte": "2026-01-01"}})
            == "filed_at >= '2026-01-01'"
        )

    @pytest.mark.parametrize(
        "key", ["wing = 'x' OR 1=1 --", "wing)", "", "1wing", "wing name", "wing;"]
    )
    def test_injected_column_names_rejected(self, key):
        with pytest.raises(ValueError, match="column name"):
            LanceStore._where_to_sql({key: "x"})

    def test_unknown_operator_rejected_instead_of_dropped(self):
        with pytest.raises(ValueError, match="unsupported where operator"):
            LanceStore._where_to_sql({"wing": {"$nin": ["a"]}})


# ── Store paths with adversarial values ─────────────────────────────────────


class TestAdversarialStorePaths:
    def test_or_payload_id_matches_nothing(self, tmp_path):
        store = _store(tmp_path)
        _seed(store, ["alpha"])
        before = store.count()

        assert store.get(ids=[OR_PAYLOAD])["ids"] == []
        assert store.delete([OR_PAYLOAD]) == 0
        assert store.count() == before

    @pytest.mark.parametrize("value", ADVERSARIAL_VALUES)
    def test_id_round_trip_get_and_delete_exact(self, tmp_path, value):
        store = _store(tmp_path)
        ids = _seed(store, [value, "neighbour"])
        drawer_id = f"id-{value}"

        got = store.get(ids=[drawer_id], include=["documents", "metadatas"])
        assert got["ids"] == [drawer_id]
        assert got["metadatas"][0]["wing"] == f"w-{value}"

        assert store.delete([drawer_id]) == 1
        remaining = set(store.get(limit=100)["ids"])
        assert remaining == set(ids) - {drawer_id}

    @pytest.mark.parametrize("value", ADVERSARIAL_VALUES)
    def test_field_filters_match_only_exact_rows(self, tmp_path, value):
        store = _store(tmp_path)
        _seed(store, [value, "neighbour"])
        drawer_id = f"id-{value}"

        assert store.get(where={"wing": f"w-{value}"})["ids"] == [drawer_id]
        both = {"$and": [{"wing": f"w-{value}"}, {"room": f"r-{value}"}]}
        assert store.get(where=both)["ids"] == [drawer_id]
        assert store.get(where={"room": {"$in": [f"r-{value}", "nope"]}})["ids"] == [drawer_id]
        hits = store.query(query_texts=["document"], n_results=10, where={"wing": f"w-{value}"})
        assert hits["ids"][0] == [drawer_id]

    @pytest.mark.parametrize("value", ADVERSARIAL_VALUES)
    def test_scoped_deletes_touch_only_exact_rows(self, tmp_path, value):
        store = _store(tmp_path)
        _seed(store, [value, "neighbour"])
        total = store.count()

        assert store.delete_by_source_file(f"src/{value}.py", f"w-{value}") == 1
        assert store.count() == total - 1
        assert store.delete_by_source_files([f"src/{value}.py"], f"w-{value}") == 0
        assert store.delete_wing(f"w-{value}") == 0
        assert store.delete_wing("w-neighbour") == 1
        assert store.count() == total - 2
        assert store.get(ids=["control"])["ids"] == ["control"]

    def test_bulk_source_delete_with_payloads(self, tmp_path):
        store = _store(tmp_path)
        _seed(store, ADVERSARIAL_VALUES)
        total = store.count()
        deleted = 0
        for value in ADVERSARIAL_VALUES:
            deleted += store.delete_by_source_files([f"src/{value}.py", OR_PAYLOAD], f"w-{value}")
        assert deleted == len(ADVERSARIAL_VALUES)
        assert store.count() == total - len(ADVERSARIAL_VALUES)
        assert store.get(ids=["control"])["ids"] == ["control"]

    def test_replace_source_scope_with_quotes(self, tmp_path):
        store = _store(tmp_path)
        # replace_source replaces only rows of its own ingest_mode.
        store.add(
            ids=["id-it's", "id-it"],
            documents=["document about it's", "document about it"],
            metadatas=[
                {"wing": f"w-{v}", "room": "r", "source_file": f"src/{v}.py", "ingest_mode": "file"}
                for v in ("it's", "it")
            ],
        )
        store.replace_source(
            "src/it's.py",
            "w-it's",
            ids=["replacement"],
            documents=["replacement text"],
            metadatas=[
                {"wing": "w-it's", "room": "r", "source_file": "src/it's.py", "ingest_mode": "file"}
            ],
        )
        assert store.get(where={"wing": "w-it's"})["ids"] == ["replacement"]
        assert store.get(ids=["id-it"])["ids"] == ["id-it"]

    def test_delete_refuses_when_filter_matches_unrequested_rows(self, tmp_path, monkeypatch):
        """Exact-id verification: a filter that widens is detected before any row is deleted."""
        import mempalace_code.storage as storage

        store = _store(tmp_path)
        _seed(store, ["alpha", "beta"])
        before = store.count()
        monkeypatch.setattr(storage, "_sql_in", lambda column, values: "1 = 1")

        with pytest.raises(ValueError, match="refusing to delete"):
            store.delete(["id-alpha"])
        assert store.count() == before

    def test_get_by_ids_raises_on_lookup_failure(self, tmp_path):
        store = _store(tmp_path)
        _seed(store, ["alpha"])

        class _BrokenTable:
            def search(self, *args: Any, **kwargs: Any):
                raise RuntimeError("lance read failed")

        store._table = _BrokenTable()  # type: ignore[assignment]  # reason: fault injection
        with pytest.raises(RuntimeError, match="lance read failed"):
            store.get(ids=["id-alpha"])

    def test_invalid_ids_rejected(self, tmp_path):
        store = _store(tmp_path)
        _seed(store, [])
        for bad in ([""], [None], [3]):
            with pytest.raises(ValueError, match="non-empty string"):
                store.get(ids=cast("Any", bad))
            with pytest.raises(ValueError, match="non-empty string"):
                store.delete(cast("Any", bad))
        with pytest.raises(TypeError, match="not a single string"):
            store.delete(cast("Any", "control"))


class TestAddUniqueIds:
    def test_add_rejects_stored_id_without_writing(self, tmp_path):
        store = _store(tmp_path)
        _seed(store, ["alpha"])
        before = store.count()

        with pytest.raises(DuplicateDrawerIdError, match="already stored") as exc:
            store.add(
                ids=["fresh", "id-alpha"],
                documents=["fresh text", "replacement text"],
                metadatas=[{"wing": "w", "room": "r"}] * 2,
            )
        assert exc.value.ids == ["id-alpha"]
        assert store.count() == before
        assert store.get(ids=["fresh"])["ids"] == []

    def test_add_rejects_repeat_within_call(self, tmp_path):
        store = _store(tmp_path)
        with pytest.raises(DuplicateDrawerIdError, match="within one add call"):
            store.add(
                ids=["dupid", "dupid"],
                documents=["one", "two"],
                metadatas=[{"wing": "w", "room": "r"}] * 2,
            )
        assert store.count() == 0

    def test_add_quoted_id_duplicate_detected(self, tmp_path):
        store = _store(tmp_path)
        _seed(store, ["O'Brien"])
        with pytest.raises(DuplicateDrawerIdError):
            store.add(ids=["id-O'Brien"], documents=["x"], metadatas=[{"wing": "w", "room": "r"}])

    def test_duplicate_error_matches_legacy_add_drawer_contract(self, tmp_path):
        """mining.orchestrator.add_drawer treats 'duplicate' errors as already filed."""
        from mempalace_code.mining.orchestrator import add_drawer

        store = _store(tmp_path)

        def file_once() -> bool:
            return add_drawer(store, "w", "r", "some content", "a.py", 0, "test")

        assert file_once() is True
        assert file_once() is False
        assert store.count() == 1

    def test_add_rejects_empty_id_and_length_mismatch(self, tmp_path):
        store = _store(tmp_path)
        with pytest.raises(ValueError, match="non-empty string"):
            store.add(ids=[""], documents=["x"], metadatas=[{"wing": "w", "room": "r"}])
        with pytest.raises(ValueError, match="equal lengths"):
            store.add(ids=["a", "b"], documents=["x"], metadatas=[{"wing": "w", "room": "r"}])
        assert store.count() == 0


# ── Full repair of palaces written before ids were unique ──────────────────


class TestRepairLegacyIds:
    def test_unique_drawer_rows_drops_exact_copies_and_renames_the_rest(self):
        meta = {"wing": "w", "room": "r"}
        other = {"wing": "w", "room": "other"}
        ids = ["a", "b", "a", "a", "a", "", "", "a__dup1"]
        docs = ["x", "y", "x", "x2", "x", "e", "e", "z"]
        metas = [meta, meta, meta, meta, other, meta, meta, meta]

        out_ids, out_docs, out_metas, dropped, renamed = unique_drawer_rows(ids, docs, metas)

        assert dropped == 2  # the second a/x/meta row and the second ''/e/meta row
        assert out_ids == ["a", "b", "a__dup2", "a__dup3", "drawer__dup1", "a__dup1"]
        assert out_docs == ["x", "y", "x2", "x", "e", "z"]
        assert out_metas[3] == other  # same text, different metadata is kept
        assert renamed == [("a", "a__dup2"), ("a", "a__dup3"), ("", "drawer__dup1")]

    def test_full_repair_keeps_every_text_when_ids_repeat_or_are_empty(self, tmp_path, capsys):
        """A palace holding repeated or empty ids (older --skip-dedup imports, concurrent
        writers, id-less import records) is rebuilt instead of crashing after the rmtree."""
        palace = str(tmp_path / "palace")
        store = _store(tmp_path)
        store.add(
            ids=["base_cache", "alpha"],
            documents=["cache text one", "alpha text"],
            metadatas=[{"wing": "w", "room": "r"}] * 2,
        )
        table = cast("Any", store._require_table())
        row = next(r for r in table.to_arrow().to_pylist() if r["id"] == "base_cache")
        # Written the way releases before unique-id enforcement could write them.
        table.add(
            [dict(row), {**row, "text": "cache text two"}, {**row, "id": "", "text": "orphan"}]
        )
        assert store.count() == 5
        del store, table

        code = _run_cli(["--palace", palace, "repair"])

        out = capsys.readouterr().out
        assert code == 0
        assert "Dropped 1 exact duplicate row(s)" in out
        assert "'base_cache' -> 'base_cache__dup1'" in out
        assert "'' -> 'drawer__dup1'" in out
        assert "Repair complete. 4 of 5 drawers rebuilt." in out
        assert _stored_rows(cast("LanceStore", open_store(palace, create=False))) == {
            "base_cache": ["cache text one"],
            "alpha": ["alpha text"],
            "base_cache__dup1": ["cache text two"],
            "drawer__dup1": ["orphan"],
        }


# ── MCP delete_drawer ───────────────────────────────────────────────────────


def _patch_runtime(monkeypatch, config, kg):
    from mempalace_code.mcp import runtime

    monkeypatch.setattr(runtime, "_config", config)
    monkeypatch.setattr(runtime, "_kg", kg)
    monkeypatch.setattr(runtime, "_store", None)


class TestMcpDeleteDrawer:
    def test_or_payload_deletes_nothing(self, monkeypatch, config, seeded_collection, kg):
        _patch_runtime(monkeypatch, config, kg)
        from mempalace_code.mcp_server import tool_delete_drawer, tool_status

        before = tool_status()["total_drawers"]
        result = tool_delete_drawer(OR_PAYLOAD)
        assert result == {"success": False, "error": f"Drawer not found: {OR_PAYLOAD}"}
        assert tool_status()["total_drawers"] == before == 4

    def test_quoted_ids_from_add_drawer_and_diary_can_be_deleted(
        self, monkeypatch, config, seeded_collection, kg
    ):
        _patch_runtime(monkeypatch, config, kg)
        from mempalace_code.mcp_server import (
            tool_add_drawer,
            tool_delete_drawer,
            tool_diary_write,
            tool_status,
        )

        added = tool_add_drawer(wing="O'Brien", room="r'oom", content="espresso machine notes")
        diary = tool_diary_write(agent_name="O'Hara", entry="diary entry with a quote")
        assert "'" in added["drawer_id"]
        assert "'" in diary["entry_id"]
        assert tool_status()["total_drawers"] == 6

        assert tool_delete_drawer(added["drawer_id"])["success"] is True
        assert tool_delete_drawer(diary["entry_id"])["success"] is True
        assert tool_status()["total_drawers"] == 4


# ── JSONL import/export ─────────────────────────────────────────────────────


def _header(**extra: Any) -> dict[str, Any]:
    from mempalace_code.version import __version__

    return {"type": "export_header", "version": __version__, **extra}


def _drawer(drawer_id: Any, text: Any, wing: Any = "notes", room: Any = "general") -> dict:
    record = {"type": "drawer", "id": drawer_id, "text": text, "wing": wing, "room": room}
    return {key: value for key, value in record.items() if value is not None}


def _triple(subject: Any, predicate: Any, obj: Any, **extra: Any) -> dict[str, Any]:
    record = {"type": "kg_triple", "subject": subject, "predicate": predicate, "object": obj}
    record.update(extra)
    return {key: value for key, value in record.items() if value is not None}


def _stored_rows(store: LanceStore) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    got = store.get(limit=1000, include=["documents"])
    for drawer_id, text in zip(got["ids"], got["documents"]):
        rows.setdefault(drawer_id, []).append(text)
    return rows


def _run_cli(argv: list[str]) -> int:
    import sys
    from unittest.mock import patch

    from mempalace_code.cli import main

    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        try:
            main()
        except SystemExit as exc:
            return int(exc.code or 0)
    return 0


def _printed_rerun(err: str) -> list[str]:
    """Return the argv of the recovery command printed after "then run: "."""
    import shlex

    line = err.split("then run: ", 1)[1].splitlines()[0]
    return shlex.split(line.split(" (its KG", 1)[0])


def _write_jsonl(path, records: list[dict]) -> str:
    import json

    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return str(path)


class TestImportIdIntegrity:
    def test_quoted_id_in_batch_keeps_same_id_dedup(self, tmp_path):
        """import-3: an apostrophe id no longer disables the stored-id check for its batch."""
        from mempalace_code.export import import_jsonl

        store = _store(tmp_path)
        store.add(
            ids=["base_cache", "base_oncall"],
            documents=["cache notes", "on-call notes"],
            metadatas=[{"wing": "notes", "room": "general"}] * 2,
        )
        records = [
            _header(),
            _drawer("base_cache", "NEW TEXT gardening tomatoes"),
            _drawer("base_oncall", "NEW TEXT raised beds"),
            _drawer("drawer_o'brien_note", "Brand new note about O'Brien's espresso machine"),
        ]

        summary = import_jsonl(path="unused", store=store, skip_kg=True, records=records)

        assert (summary["imported_drawers"], summary["skipped_duplicates"]) == (1, 2)
        assert _stored_rows(store) == {
            "base_cache": ["cache notes"],
            "base_oncall": ["on-call notes"],
            "drawer_o'brien_note": ["Brand new note about O'Brien's espresso machine"],
        }

    def test_skip_dedup_still_enforces_unique_ids(self, tmp_path):
        """import-4: --skip-dedup skips only similarity, never creates a second row per id."""
        from mempalace_code.export import import_jsonl

        store = _store(tmp_path)
        store.add(ids=["base_cache"], documents=["cache notes"], metadatas=[{"wing": "notes"}])
        records = [
            _header(),
            _drawer("base_cache", "Gardening tomatoes in raised beds with compost"),
            _drawer("dupid", "dup one: sailing boats on the lake"),
            _drawer("dupid", "dup two: knitting scarves in winter"),
        ]

        summary = import_jsonl(
            path="unused", store=store, skip_kg=True, skip_dedup=True, records=records
        )

        assert (summary["imported_drawers"], summary["skipped_duplicates"]) == (1, 2)
        assert _stored_rows(store) == {
            "base_cache": ["cache notes"],
            "dupid": ["dup one: sailing boats on the lake"],
        }

    def test_id_stored_by_concurrent_writer_is_skipped_not_overwritten(self, tmp_path, monkeypatch):
        """A duplicate-id add failure counts as a skipped duplicate; it never upserts."""
        import mempalace_code.export as export

        store = _store(tmp_path)
        store.add(ids=["race"], documents=["original text"], metadatas=[{"wing": "notes"}])
        monkeypatch.setattr(export, "_existing_ids", lambda _store, _ids: set())

        summary = export.import_jsonl(
            path="unused",
            store=store,
            skip_kg=True,
            skip_dedup=True,
            records=[_header(), _drawer("race", "replacement text")],
        )

        assert (summary["imported_drawers"], summary["skipped_duplicates"]) == (0, 1)
        assert _stored_rows(store) == {"race": ["original text"]}


class TestImportRecordValidation:
    def test_invalid_drawers_are_counted_and_named(self, tmp_path):
        """import-5: missing id/wing/room or empty text is reported, never stored."""
        from mempalace_code.export import import_jsonl

        store = _store(tmp_path)
        records = [
            _header(drawer_count=7),
            _drawer(None, "only text one about bicycles", wing=None, room=None),
            _drawer("e1", ""),
            _drawer("e2", None),
            _drawer("no-wing", "text", wing=None),
            _drawer("blank-room", "text", room="  "),
            _drawer(7, "numeric id"),
            {"type": "mystery", "x": 1},
            _drawer("ok1", "valid drawer about volcanoes"),
        ]

        summary = import_jsonl(path="unused", store=store, skip_kg=True, records=records)

        assert summary["imported_drawers"] == 1
        assert summary["skipped_invalid"] == 6
        assert summary["rejected"] == 6
        assert summary["ignored_records"] == 1
        assert summary["imported_drawers"] + summary["skipped_invalid"] == 7
        assert list(_stored_rows(store)) == ["ok1"]
        text = "\n".join(summary["warnings"])
        assert "record 2: missing or blank 'id'" in text
        assert "record 3 (id 'e1'): missing or empty 'text'" in text
        assert "record 5 (id 'no-wing'): missing or blank 'wing'" in text
        assert "unknown type 'mystery' (records 8)" in text

    def test_wing_override_supplies_missing_wing(self, tmp_path):
        from mempalace_code.export import import_jsonl

        store = _store(tmp_path)
        summary = import_jsonl(
            path="unused",
            store=store,
            skip_kg=True,
            wing_override="archive",
            records=[_header(), _drawer("no-wing", "text about kites", wing=None)],
        )
        assert (summary["imported_drawers"], summary["skipped_invalid"]) == (1, 0)
        assert store.get(ids=["no-wing"], include=["metadatas"])["metadatas"][0]["wing"] == (
            "archive"
        )

    def test_invalid_kg_triples_rejected_in_dry_run_and_live(self, tmp_path):
        """imp-1: dry run validates KG records; live import rejects the same records."""
        from mempalace_code.export import import_jsonl
        from mempalace_code.knowledge_graph import KnowledgeGraph

        store = _store(tmp_path)
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
        records = [
            _header(),
            _triple("Good", "is", "fine"),
            _triple("Bad", "is", "x", valid_from="2026-13-01"),
            _triple("Inv", "is", "x", valid_from="2026-05-01", valid_to="2026-01-01"),
            _triple(None, "nosubject", "x"),
            _triple("Blank", " ", "x"),
            _triple("Conf", "is", "x", confidence="high"),
            _triple("Good2", "is", "fine"),
        ]

        for dry_run in (True, False):
            summary = import_jsonl(
                path="unused", store=store, kg=kg, dry_run=dry_run, records=records
            )
            assert summary["imported_triples"] == 2
            assert summary["invalid_triples"] == 5
            assert summary["rejected"] == 5
            text = "\n".join(summary["warnings"])
            assert "record 3: Invalid temporal value '2026-13-01'" in text
            assert "record 4: Inverted validity window" in text
            assert "record 5: missing or blank 'subject'" in text

        subjects = {row["subject"] for batch in kg.iter_all_triples() for row in batch}
        assert subjects == {"Good", "Good2"}


class TestImportDryRunKgCounts:
    RECORDS = [
        _triple("Existing Subject", "relates to", "Existing Object"),
        _triple("existing subject", "relates_to", "existing object"),  # same normalized fact
        _triple("O'Brien", "works_on", "Payments"),
        _triple("OBrien", "works_on", "payments"),  # add_triple strips apostrophes
        _triple("Marco", "on_call_for", "payments", valid_from="2026-02-01", valid_to="2026-06-30"),
        _triple("Fresh", "uses", "Redis"),
    ]

    def _kg(self, tmp_path):
        from mempalace_code.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph(db_path=str(tmp_path / "palace" / "knowledge_graph.sqlite3"))
        kg.add_triple("Existing Subject", "relates_to", "Existing Object")
        return kg

    def test_dry_run_prediction_matches_live_import(self, tmp_path):
        """import-6: dry-run KG counts reflect dedup exactly as a live import does."""
        from mempalace_code.export import import_jsonl
        from mempalace_code.knowledge_graph import LazyKnowledgeGraph

        store = _store(tmp_path)
        kg = self._kg(tmp_path)
        records = [_header(), *self.RECORDS]
        lazy = LazyKnowledgeGraph(str(tmp_path / "palace"))

        preview = import_jsonl(path="unused", store=store, kg=lazy, dry_run=True, records=records)
        live = import_jsonl(path="unused", store=store, kg=kg, records=records)

        predicted = (preview["imported_triples"], preview["skipped_kg_duplicates"])
        assert predicted == (live["imported_triples"], live["skipped_kg_duplicates"]) == (3, 3)
        assert kg.stats()["triples"] == 4
        again = import_jsonl(path="unused", store=store, kg=lazy, dry_run=True, records=records)
        # A replay, closed facts included, stores nothing again; the preview must agree.
        replay = import_jsonl(path="unused", store=store, kg=kg, records=records)
        assert (again["imported_triples"], again["skipped_kg_duplicates"]) == (0, 6)
        assert (replay["imported_triples"], replay["skipped_kg_duplicates"]) == (0, 6)

    def test_dry_run_reads_kg_without_creating_side_files(self, tmp_path):
        from mempalace_code.export import import_jsonl
        from mempalace_code.knowledge_graph import LazyKnowledgeGraph

        store = _store(tmp_path)
        self._kg(tmp_path)
        palace = tmp_path / "palace"
        before = sorted(p.name for p in palace.iterdir())
        kg_bytes = (palace / "knowledge_graph.sqlite3").read_bytes()

        summary = import_jsonl(
            path="unused",
            store=store,
            kg=LazyKnowledgeGraph(str(palace)),
            dry_run=True,
            records=[_header(), *self.RECORDS],
        )

        assert summary["skipped_kg_duplicates"] == 3
        assert sorted(p.name for p in palace.iterdir()) == before
        assert (palace / "knowledge_graph.sqlite3").read_bytes() == kg_bytes


class TestImportCli:
    def test_version_warning_printed_once(self, tmp_path, capsys):
        """imp-2: the version-mismatch warning appears exactly once."""
        jsonl = _write_jsonl(
            tmp_path / "old.jsonl", [_header(version="1.14.2"), _drawer("a", "alpha text")]
        )
        code = _run_cli(["--palace", str(tmp_path / "palace"), "import", jsonl, "--dry-run"])
        captured = capsys.readouterr()
        assert code == 0
        assert (captured.out + captured.err).count("Version mismatch") == 1

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_rejected_records_exit_nonzero_with_rerun_command(self, tmp_path, capsys, dry_run):
        palace = str(tmp_path / "palace")
        jsonl = _write_jsonl(
            tmp_path / "bad.jsonl",
            [
                _header(),
                _drawer("ok", "valid text about sailing"),
                _drawer("", "no id"),
                _triple("", "is", "x"),
            ],
        )
        argv = ["--palace", palace, "import", jsonl] + (["--dry-run"] if dry_run else [])

        code = _run_cli(argv)

        captured = capsys.readouterr()
        assert code == 1
        assert "Imported drawers:   1" in captured.out
        assert "Skipped invalid:    1" in captured.out
        assert "Invalid KG triples:    1" in captured.out
        assert "Traceback" not in captured.err
        assert "2 record(s)" in captured.err
        # A KG triple was rejected, so the rerun replays the KG (no --skip-kg added).
        assert _printed_rerun(captured.err) == ["mempalace-code", *argv]

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_rerun_command_keeps_every_import_option(self, tmp_path, capsys, dry_run):
        """Following the printed command after a fix keeps --wing-override and the rest."""
        palace = str(tmp_path / "palace")
        path = tmp_path / "odd.jsonl"
        records = [_header(), _drawer("ok", "valid text about sailing", wing=None)]
        jsonl = _write_jsonl(path, [*records, _drawer("bad", "")])
        argv = ["--palace", palace, "import", jsonl, "--wing-override", "archive"]
        argv += ["--skip-dedup", "--skip-kg"] + (["--dry-run"] if dry_run else [])

        assert _run_cli(argv) == 1
        command = _printed_rerun(capsys.readouterr().err)

        assert command == ["mempalace-code", *argv]
        _write_jsonl(path, [*records, _drawer("bad", "fixed text about harbours", wing=None)])
        assert _run_cli(command[1:]) == 0
        if not dry_run:
            got = open_store(palace, create=False).get(ids=["ok", "bad"], include=["metadatas"])
            assert {m["wing"] for m in got["metadatas"]} == {"archive"}
            assert len(got["ids"]) == 2

    def test_rerun_after_imported_kg_skips_kg(self, tmp_path, capsys):
        """Every triple landed, so the rerun replays only the corrected drawers."""
        from mempalace_code.knowledge_graph import KnowledgeGraph, palace_kg_path

        palace = str(tmp_path / "palace")
        path = tmp_path / "mixed.jsonl"
        kg_records = [
            _triple("Marco", "on_call_for", "payments", valid_to="2026-06-30"),
            _triple("Marco", "works_on", "payments"),
        ]
        jsonl = _write_jsonl(path, [_header(), _drawer("bad", ""), *kg_records])

        assert _run_cli(["--palace", palace, "import", jsonl]) == 1
        err = capsys.readouterr().err
        command = _printed_rerun(err)

        assert command == ["mempalace-code", "--palace", palace, "import", jsonl, "--skip-kg"]
        assert "(its KG triples are already imported)" in err
        _write_jsonl(path, [_header(), _drawer("bad", "fixed text"), *kg_records])
        assert _run_cli(command[1:]) == 0
        assert KnowledgeGraph(db_path=palace_kg_path(palace)).stats()["triples"] == 2

    def test_live_import_refused_while_exclusive_operation_runs(
        self, tmp_path, capsys, exclusive_install_lease_elsewhere
    ):
        palace = tmp_path / "palace"
        jsonl = _write_jsonl(tmp_path / "in.jsonl", [_header(), _drawer("a", "alpha text")])
        with exclusive_install_lease_elsewhere():
            argv = ["--palace", str(palace), "import", jsonl, "--wing-override", "o'brien"]
            code = _run_cli(argv)
            captured = capsys.readouterr()
            assert code == 1
            assert "import did not start" in captured.err
            assert _printed_rerun(captured.err) == ["mempalace-code", *argv]
            assert not palace.exists()
            # A dry run takes no lease and still previews.
            assert _run_cli(["--palace", str(palace), "import", jsonl, "--dry-run"]) == 0
        assert _run_cli(["--palace", str(palace), "import", jsonl]) == 0
        assert "Imported drawers:   1" in capsys.readouterr().out

    def test_live_import_refused_while_another_writer_holds_the_palace(
        self, tmp_path, capsys, monkeypatch
    ):
        import threading

        from mempalace_code import operation_lock

        palace = tmp_path / "palace"
        jsonl = _write_jsonl(tmp_path / "in.jsonl", [_header(), _drawer("a", "alpha text")])
        monkeypatch.setattr(operation_lock, "DEFAULT_PALACE_WRITE_WAIT_SECONDS", 0.2)
        held, release = threading.Event(), threading.Event()

        def hold() -> None:
            with operation_lock.palace_write_lease(str(palace), "mine", wait=0):
                held.set()
                release.wait(10)

        holder = threading.Thread(target=hold)
        holder.start()
        try:
            assert held.wait(10)
            argv = ["--palace", str(palace), "import", jsonl]
            code = _run_cli(argv)
            captured = capsys.readouterr()
            assert code == 1
            assert "import did not start: Another MemPalace writer" in captured.err
            assert _printed_rerun(captured.err) == ["mempalace-code", *argv]
            assert "Traceback" not in captured.err
            assert not palace.exists()
            # A dry run takes no lease and still previews.
            assert _run_cli([*argv, "--dry-run"]) == 0
        finally:
            release.set()
            holder.join(10)
        assert _run_cli(["--palace", str(palace), "import", jsonl]) == 0
        assert "Imported drawers:   1" in capsys.readouterr().out


class TestExportCli:
    @pytest.mark.parametrize(
        "since", ["2026-9-1", "2026/09/01", "20260901", "2026-13-45", "yesterday"]
    )
    def test_invalid_since_rejected(self, tmp_path, capsys, since):
        """export-2: --since must be an ISO date; bad spellings no longer export nothing."""
        from mempalace_code.export import write_jsonl

        store = _store(tmp_path)
        _seed(store, [])
        out = tmp_path / "out.jsonl"
        code = _run_cli(
            ["--palace", str(tmp_path / "palace"), "export", "--out", str(out), "--since", since]
        )
        captured = capsys.readouterr()
        assert code == 1
        assert f"invalid --since value {since!r}" in captured.err
        assert not out.exists()
        with pytest.raises(ValueError, match="invalid --since"):
            write_jsonl(path=str(out), store=store, since=since)
        assert not out.exists()

    def test_valid_since_still_filters(self, tmp_path, capsys):
        store = _store(tmp_path)
        store.add(
            ids=["old", "new"],
            documents=["old drawer text", "new drawer text"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": "1999-12-31T23:59:59"},
                {"wing": "w", "room": "r", "filed_at": "2026-09-26T10:00:00"},
            ],
        )
        code = _run_cli(
            ["--palace", str(tmp_path / "palace"), "export", "--out", "-", "--since", "2000-01-01"]
        )
        assert code == 0
        assert '"drawer_count": 1' in capsys.readouterr().out

    def test_out_into_missing_directory_is_created(self, tmp_path, capsys):
        """export-3: parent directories are created, as backup create --out does."""
        store = _store(tmp_path)
        _seed(store, [])
        out = tmp_path / "nope" / "dir" / "a.jsonl"
        assert _run_cli(["--palace", str(tmp_path / "palace"), "export", "--out", str(out)]) == 0
        assert out.is_file()

    def test_unwritable_out_is_one_line_error(self, tmp_path, capsys):
        store = _store(tmp_path)
        _seed(store, [])
        target = tmp_path / "a-directory"
        target.mkdir()
        code = _run_cli(["--palace", str(tmp_path / "palace"), "export", "--out", str(target)])
        captured = capsys.readouterr()
        assert code == 1
        assert f"cannot write export to {target}" in captured.err
        assert "Traceback" not in captured.err

    def test_existing_out_is_refused_and_left_untouched(self, tmp_path, capsys):
        import stat

        store = _store(tmp_path)
        _seed(store, [])
        out = tmp_path / "out.jsonl"
        argv = ["--palace", str(tmp_path / "palace"), "export", "--out", str(out)]
        assert _run_cli(argv) == 0
        assert stat.S_IMODE(out.stat().st_mode) == 0o600
        out.write_text("earlier export\n", encoding="utf-8")
        capsys.readouterr()

        code = _run_cli(argv)
        err = capsys.readouterr().err
        assert code == 1
        assert f"cannot write export to {out}: it already exists" in err
        assert "Next: rerun with --out set to a new file path" in err
        assert out.read_text(encoding="utf-8") == "earlier export\n"

    def test_failed_export_removes_its_partial_file(self, tmp_path, monkeypatch):
        from mempalace_code import export

        store = _store(tmp_path)
        _seed(store, [])
        out = tmp_path / "out.jsonl"

        def broken(*_args, **_kwargs):
            raise RuntimeError("read failed")
            yield  # pragma: no cover

        monkeypatch.setattr(export, "export_drawers", broken)
        with pytest.raises(RuntimeError, match="read failed"):
            export.write_jsonl(path=str(out), store=store)
        assert not out.exists()

    def test_open_failure_hint_names_the_palace(self, tmp_path, capsys, monkeypatch):
        import sys
        from unittest.mock import patch

        from mempalace_code import storage
        from mempalace_code.cli_invocation import cli_command

        palace = tmp_path / "palace root"
        palace.mkdir()

        def fail(*_args, **_kwargs):
            raise RuntimeError("table is damaged")

        monkeypatch.setattr(storage, "open_store", fail)
        code = _run_cli(["--palace", str(palace), "export", "--out", str(tmp_path / "o.jsonl")])
        err = capsys.readouterr().err
        assert code == 1
        with patch.object(sys, "argv", ["mempalace-code"]):
            expected = cli_command("repair", "--rollback", "--dry-run", palace=str(palace))
        assert expected in err

    def test_chroma_palace_gets_the_retirement_message_not_the_rollback_hint(
        self, tmp_path, capsys, monkeypatch
    ):
        from mempalace_code import storage

        palace = tmp_path / "palace"
        palace.mkdir()

        def retired(*_args, **_kwargs):
            raise storage.ChromaRuntimeRetiredError(storage.CHROMA_RUNTIME_RETIRED_MESSAGE)

        monkeypatch.setattr(storage, "open_store", retired)
        code = _run_cli(["--palace", str(palace), "export", "--out", str(tmp_path / "o.jsonl")])
        err = capsys.readouterr().err
        assert code != 0
        assert "migrate-storage" in err
        assert "repair --rollback" not in err
        assert "Traceback" not in err
