"""UAT regressions for search, code_search, read, and file_context behaviour.

Each class names the UAT issue ids it covers.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

import pytest

from mempalace_code import cli_invocation
from mempalace_code.cli import main
from mempalace_code.cli_invocation import cli_command, cli_prefix
from mempalace_code.mcp import runtime
from mempalace_code.mcp.tools.search import (
    tool_check_duplicate,
    tool_file_context,
    tool_search,
)
from mempalace_code.reader import read_slice
from mempalace_code.searcher import (
    MAX_SEARCH_RESULTS,
    code_search,
    search,
    search_memories,
)
from mempalace_code.storage import open_store
from mempalace_code.taxonomy_filters import (
    format_cli_lines,
    validate_wing_room_against_taxonomy,
)


def _meta(source_file, **extra):
    meta = {
        "wing": "proj",
        "room": "backend",
        "source_file": source_file,
        "chunk_index": 0,
        "added_by": "miner",
        "filed_at": "2026-01-01T00:00:00",
    }
    meta.update(extra)
    return meta


def _run_cli(argv, capsys):
    code = 0
    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        try:
            main()
        except SystemExit as exc:
            code = exc.code or 0
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ── agent-3: code_search filters narrow rows before ranking ──────────────────


@pytest.fixture
def crowded_palace(palace_path):
    """200 near-identical filler drawers plus one target that ranks far below them."""
    store = open_store(palace_path, create=True)
    filler = "alpha beta gamma delta"
    ids = [f"filler_{i}" for i in range(200)] + ["target"]
    documents = [filler] * 200 + ["completely unrelated words about kiwis"]
    metadatas = [
        _meta(
            f"/src/other/mod_{i}.py",
            symbol_name=f"filler_{i}",
            symbol_type="function",
            language="python",
            chunk_index=i,
        )
        for i in range(200)
    ] + [
        _meta(
            "/src/pkg/target_module.py",
            symbol_name="TargetSymbol",
            symbol_type="function",
            language="python",
        )
    ]
    store.add(ids=ids, documents=documents, metadatas=metadatas)
    return palace_path


class TestCodeSearchPrefilters:
    def test_symbol_name_finds_chunk_outside_top_vector_candidates(self, crowded_palace):
        result = code_search(
            crowded_palace, "alpha beta gamma delta", symbol_name="targetsymbol", n_results=5
        )
        assert [hit["symbol_name"] for hit in result["results"]] == ["TargetSymbol"]
        assert result["results"][0]["id"] == "target"
        assert result["results"][0]["ranking"]["storage_rank"] == 1

    def test_file_glob_finds_chunk_outside_top_vector_candidates(self, crowded_palace):
        result = code_search(
            crowded_palace, "alpha beta gamma delta", file_glob="*/pkg/target_*.py"
        )
        assert [hit["source_file"] for hit in result["results"]] == ["/src/pkg/target_module.py"]

    def test_filters_combine_and_hybrid_sees_only_matching_rows(self, crowded_palace):
        result = code_search(
            crowded_palace,
            "alpha beta gamma delta",
            symbol_name="Target",
            file_glob="*.py",
            rerank="hybrid",
        )
        assert [hit["id"] for hit in result["results"]] == ["target"]

    def test_filter_without_matching_value_is_an_empty_success(self, crowded_palace):
        result = code_search(crowded_palace, "alpha", symbol_name="does_not_exist_anywhere")
        assert "error" not in result
        assert result["results"] == []


# ── agent-6 / agent-23 / gap-14: shared hit projection ───────────────────────


@pytest.fixture
def mixed_palace(palace_path):
    store = open_store(palace_path, create=True)
    store.add(
        ids=["code_1", "doc_1"],
        documents=[
            "def render_graph(): return mermaid",
            "## Request flow\n```mermaid\ngraph TD\n```",
        ],
        metadatas=[
            _meta(
                "/src/app.py",
                symbol_name="render_graph",
                symbol_type="function",
                language="python",
                line_start=1,
                line_end=1,
            ),
            _meta(
                "/docs/architecture.md",
                language="markdown",
                heading="Request flow",
                heading_level=2,
                heading_path="Platform > Request flow",
                doc_section_type="architecture",
                contains_mermaid=1,
                contains_code=1,
                line_start=3,
                line_end=5,
            ),
        ],
    )
    return palace_path


class TestSearchHitShape:
    def test_every_hit_carries_its_drawer_id(self, mixed_palace):
        for result in (
            search_memories("mermaid graph", mixed_palace),
            code_search(mixed_palace, "mermaid graph"),
        ):
            assert {hit["id"] for hit in result["results"]} == {"code_1", "doc_1"}

    def test_markdown_fields_only_on_markdown_hits_for_both_apis(self, mixed_palace):
        for result in (
            search_memories("mermaid graph", mixed_palace),
            code_search(mixed_palace, "mermaid graph"),
        ):
            hits = {hit["id"]: hit for hit in result["results"]}
            assert "heading" not in hits["code_1"]
            assert "contains_mermaid" not in hits["code_1"]
            doc = hits["doc_1"]
            assert doc["heading_path"] == "Platform > Request flow"
            assert doc["heading_level"] == 2
            assert doc["doc_section_type"] == "architecture"
            assert doc["contains_mermaid"] is True
            assert doc["contains_table"] is False

    def test_hybrid_scores_are_rounded(self):
        from mempalace_code.search_reranker import hybrid_rerank

        ranked = hybrid_rerank(
            "alpha beta gamma", [{"text": "alpha"}, {"text": "zzz"}, {"text": "beta gamma"}]
        )
        scores = [candidate["ranking"] for candidate in ranked]
        for ranking in scores:
            for key in ("lexical_score", "input_rank_score", "hybrid_score"):
                assert ranking[key] == round(ranking[key], 3)
        assert {ranking["input_rank_score"] for ranking in scores} == {1.0, 0.667, 0.333}


# ── agent-7 / search-1: plain search is in descending similarity ─────────────


@pytest.fixture
def camelcase_palace(palace_path, pin_cosine):
    query = pin_cosine("FooBar lookup", 1.0, axis=1)
    close = pin_cosine("alpha text", 0.8, axis=2)
    boosted = pin_cosine("beta text", 0.7, axis=3)
    store = open_store(palace_path, create=True)
    store.add(
        ids=["close", "boosted"],
        documents=[close, boosted],
        metadatas=[
            _meta("/src/alpha.py", symbol_name="alpha"),
            _meta("/src/foobar.py", symbol_name="foobar"),
        ],
    )
    return palace_path, store, query


class TestSearchOrderIsCosine:
    def test_store_intent_rerank_still_reorders_for_code_retrieval(self, camelcase_palace):
        palace, store, query = camelcase_palace
        reranked = store.query([query], n_results=2, include=["distances"])
        assert reranked["ids"][0] == ["boosted", "close"]
        plain = store.query([query], n_results=2, include=["distances"], intent_rerank=False)
        assert plain["ids"][0] == ["close", "boosted"]
        assert [h["id"] for h in code_search(palace, query, n_results=2)["results"]] == [
            "boosted",
            "close",
        ]

    def test_search_memories_is_sorted_by_similarity(self, camelcase_palace):
        palace, _store, query = camelcase_palace
        sims = [hit["similarity"] for hit in search_memories(query, palace)["results"]]
        assert sims == [0.8, 0.7]

    def test_check_duplicate_is_sorted_by_similarity(self, camelcase_palace, monkeypatch):
        _palace, store, query = camelcase_palace
        monkeypatch.setattr(runtime, "_get_store", lambda create=False: store)
        matches = tool_check_duplicate(query, threshold=0.0)["matches"]
        assert [match["id"] for match in matches] == ["close", "boosted"]

    def test_cli_search_prints_descending_match(self, camelcase_palace, capsys):
        palace, _store, query = camelcase_palace
        search(query, palace)
        matches = [
            line.split()[-1] for line in capsys.readouterr().out.splitlines() if "Match:" in line
        ]
        assert matches == ["0.8", "0.7"]


# ── search-2 / agent-10: machine-readable, bounded search ────────────────────


class TestSearchCliJsonAndBounds:
    def test_json_output_has_ids_ranges_and_scores(self, mixed_palace, capsys):
        code, out, err = _run_cli(
            ["--palace", mixed_palace, "search", "mermaid graph", "--json"], capsys
        )
        assert code == 0, err
        payload = json.loads(out)
        hits = {hit["id"]: hit for hit in payload["results"]}
        assert hits["doc_1"]["line_range"] == {"start": 3, "end": 5}
        assert hits["doc_1"]["source_file"] == "/docs/architecture.md"
        assert isinstance(hits["code_1"]["similarity"], float)

    def test_json_errors_are_json(self, mixed_palace, tmp_path, capsys):
        code, out, _err = _run_cli(
            ["--palace", mixed_palace, "search", "x", "--wing", "nope", "--json"], capsys
        )
        assert code == 2
        assert json.loads(out)["error"] == "unknown_wing"

        code, out, _err = _run_cli(
            ["--palace", str(tmp_path / "absent"), "search", "x", "--json"], capsys
        )
        assert code == 1
        assert json.loads(out)["error"] == "No palace found"

    def test_results_upper_bound_is_rejected_before_search(self, mixed_palace, capsys):
        code, out, err = _run_cli(
            ["--palace", mixed_palace, "search", "x", "--results", str(MAX_SEARCH_RESULTS + 1)],
            capsys,
        )
        assert code == 2
        assert out == ""
        assert f"must be at most {MAX_SEARCH_RESULTS}" in err

    def test_default_mode_prints_line_ranges(self, mixed_palace, capsys):
        search("mermaid graph", mixed_palace)
        out = capsys.readouterr().out
        assert "Lines:  3-5" in out
        assert "Lines:  1-1" in out

    def test_search_memories_and_mcp_limit_are_clamped(self, monkeypatch):
        calls = []

        class Store:
            def query(self, **kwargs):
                calls.append(kwargs)
                return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_a, **_k: Store())
        monkeypatch.setattr(runtime, "_config", type("C", (), {"palace_path": "/fake"})())
        tool_search("a", limit=5000)
        # Below 1 is an argument error on every surface (MCP answers -32602 via its schema).
        with pytest.raises(ValueError, match="n_results"):
            search_memories("a", "/fake", n_results=0)
        assert [call["n_results"] for call in calls] == [MAX_SEARCH_RESULTS]
        assert all(call["intent_rerank"] is False for call in calls)

    def test_unknown_pair_lists_the_wing_rooms(self):
        taxonomy = {"w1": {"backend": 1, "frontend": 2}, "w2": {"zzz": 1}}
        payload = validate_wing_room_against_taxonomy(taxonomy, wing="w1", room="zzz")
        assert payload is not None
        assert payload["suggestions"] == []
        assert payload["wing_rooms"] == ["backend", "frontend"]
        assert "  Rooms in wing 'w1': backend, frontend" in format_cli_lines(payload)


# ── search-3 / convos-25 / convos-30: printed commands ───────────────────────


class TestPrintedCommands:
    def test_console_script_path_is_reused(self, tmp_path, monkeypatch):
        script = tmp_path / "venv bin" / "mempalace-code"
        script.parent.mkdir()
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
        monkeypatch.setattr(sys, "argv", [str(script), "search"])
        assert cli_prefix() == [str(script)]
        assert cli_command("status", palace="/p q").startswith(f"'{script}' --palace '/p q'")

    def test_sibling_console_script_is_used_by_the_mcp_server(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name in ("mempalace-code", "mempalace-code-mcp"):
            (bin_dir / name).write_text("#!/bin/sh\n")
            (bin_dir / name).chmod(0o755)
        monkeypatch.setattr(sys, "argv", [str(bin_dir / "mempalace-code-mcp")])
        assert cli_prefix() == [str(bin_dir / "mempalace-code")]

    def test_module_invocation_uses_the_running_interpreter(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["/src/mempalace_code/cli.py"])
        monkeypatch.setattr(sys, "orig_argv", [sys.executable, "-P", "-m", "mempalace_code.cli"])
        assert cli_prefix() == [sys.executable, "-m", "mempalace_code.cli"]
        monkeypatch.setattr(sys, "orig_argv", [sys.executable, "-m", "pytest", "-m", "x"])
        assert cli_invocation.cli_prefix() == [sys.executable, "-m", "mempalace_code"]

    def test_compact_recovery_uses_running_install_and_explains_unavailable(
        self, palace_path, capsys
    ):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["code", "convo"],
            documents=["def pgvector_rollout(): pass", "> when is pgvector rollout\nMarch"],
            metadatas=[
                _meta("/src/rollout.py", line_start=4, line_end=4),
                _meta("/chats/session.jsonl", ingest_mode="convos", room="planning"),
            ],
        )
        search("pgvector rollout", palace_path, compact=True)
        out = capsys.readouterr().out
        expected = cli_command(
            "read",
            "/src/rollout.py",
            "--start",
            "4",
            "--end",
            "4",
            "--wing",
            "proj",
            palace=palace_path,
        )
        assert f"Recovery: {expected}" in out
        assert "Recovery: unavailable (conversation drawers have no line range" in out


# ── agent-5 / read-1 / convos-25: precise read results ───────────────────────


@pytest.fixture
def gapped_store(palace_path):
    store = open_store(palace_path, create=True)
    store.add(
        ids=["c0", "c1", "c2"],
        documents=["line a\nline b\nline c", "line f\nline g", "unplaced chunk"],
        metadatas=[
            _meta("/src/gapped.py", line_start=1, line_end=3),
            _meta("/src/gapped.py", chunk_index=1, line_start=6, line_end=7),
            _meta("/src/gapped.py", chunk_index=2),
        ],
    )
    return store


class TestReadPrecision:
    def test_gap_between_chunks_is_reported(self, gapped_store):
        result = read_slice(gapped_store, "/src/gapped.py", 2, 7)
        assert [entry["line"] for entry in result["lines"]] == [2, 3, 6, 7]
        assert result["gaps"] == [{"start": 4, "end": 5}]
        assert result["last_indexed_line"] == 7
        assert result["unplaced_chunks"] == 1

    def test_range_inside_a_gap_is_a_success_with_the_gap(self, gapped_store):
        result = read_slice(gapped_store, "/src/gapped.py", 4, 5)
        assert "error" not in result
        assert result["lines"] == []
        assert result["gaps"] == [{"start": 4, "end": 5}]

    def test_end_past_last_indexed_line_is_clamped(self, gapped_store):
        result = read_slice(gapped_store, "/src/gapped.py", 6, 400)
        assert result["end"] == 7
        assert [entry["text"] for entry in result["lines"]] == ["line f", "line g"]
        assert result["gaps"] == []

    def test_start_past_last_indexed_line_is_out_of_range(self, gapped_store):
        result = read_slice(gapped_store, "/src/gapped.py", 500, 999)
        assert result["error"] == "out_of_range"
        assert result["last_indexed_line"] == 7

    def test_conversation_source_has_no_line_metadata(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["t0", "t1"],
            documents=["> q one\nanswer", "> q two\nanswer"],
            metadatas=[
                _meta("/chats/session-atlas.jsonl", ingest_mode="convos"),
                _meta("/chats/session-atlas.jsonl", ingest_mode="convos", chunk_index=1),
            ],
        )
        result = read_slice(store, "session-atlas.jsonl", 1, 5)
        assert result["error"] == "no_line_metadata"
        assert result["conversation"] is True
        assert result["chunks"] == 2

    def test_cli_prints_gap_marker_and_never_advises_remine(
        self, gapped_store, palace_path, capsys
    ):
        palace = palace_path
        code, out, err = _run_cli(
            ["--palace", palace, "read", "/src/gapped.py", "--start", "2", "--end", "9"], capsys
        )
        assert code == 0, err
        assert "lines 4-5 not stored; usually blank lines between indexed chunks" in out
        assert "end of line-addressed content at line 7" in out
        assert "1 stored chunk(s) of this file carry no line range" in out

        code, _out, err = _run_cli(
            ["--palace", palace, "read", "/src/gapped.py", "--start", "50", "--end", "60"], capsys
        )
        assert code == 1
        assert "Out of range" in err
        assert "mine" not in err
        assert "1 more stored chunk(s) of this file carry no line range" in err

    def test_cli_out_of_range_offers_the_last_indexed_lines(self, palace_path, capsys):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["only"],
            documents=["a\nb\nc"],
            metadatas=[_meta("/src/whole.py", line_start=1, line_end=3)],
        )
        code, _out, err = _run_cli(
            ["--palace", palace_path, "read", "/src/whole.py", "--start", "9", "--end", "12"],
            capsys,
        )
        assert code == 1
        assert "starts after the last indexed line 3" in err
        expected = cli_command(
            "read", "/src/whole.py", "--start", "1", "--end", "3", palace=palace_path
        )
        assert f"for the last lines run {expected}" in err

    def test_out_of_range_names_chunks_without_line_ranges(self, palace_path, capsys):
        """agent-5 (a): lines 1-54 mapped, the rest of the file in two unmapped chunks."""
        store = open_store(palace_path, create=True)
        hook = "/proj/hooks/save_hook.sh"
        store.add(
            ids=["h0", "h1", "h2"],
            documents=["\n".join(f"l{i}" for i in range(1, 55)), "tail one", "tail two"],
            metadatas=[
                _meta(hook, line_start=1, line_end=54),
                _meta(hook, chunk_index=1, line_start=0, line_end=0),
                _meta(hook, chunk_index=2, line_start=0, line_end=0),
            ],
        )
        result = read_slice(store, hook, 100, 105)
        assert result["error"] == "out_of_range"
        assert result["last_indexed_line"] == 54
        assert result["unplaced_chunks"] == 2
        assert "2 more stored chunk(s) of this file carry no line range" in result["detail"]
        assert "mempalace_file_context" in result["detail"]

        code, _out, err = _run_cli(
            ["--palace", palace_path, "read", hook, "--start", "100", "--end", "105"], capsys
        )
        assert code == 1
        assert "lines 1-54 are readable by line number; to see the other 2 chunk(s)" in err
        assert cli_command("search", "<query>", palace=palace_path) in err
        assert "for the last lines" not in err
        assert "--start 35" not in err

    def test_leading_gap_is_reported_as_not_stored_by_mining(self, palace_path, capsys):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["crc"],
            documents=["body 7\nbody 8\nbody 9"],
            metadatas=[_meta("/src/crc32.c", line_start=7, line_end=9)],
        )
        result = read_slice(store, "/src/crc32.c", 1, 9)
        assert result["first_indexed_line"] == 7
        assert result["gaps"] == [{"start": 1, "end": 6}]

        code, out, err = _run_cli(
            ["--palace", palace_path, "read", "/src/crc32.c", "--start", "1", "--end", "9"],
            capsys,
        )
        assert code == 0, err
        assert "(lines 1-6 not stored; mining stored nothing before line 7)" in out
        assert "blank lines" not in out

    def test_cli_conversation_read_points_to_search(self, palace_path, capsys):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["t0"],
            documents=["> q\nanswer"],
            metadatas=[_meta("/chats/s.jsonl", ingest_mode="convos", wing="convos")],
        )
        code, _out, err = _run_cli(
            [
                "--palace",
                palace_path,
                "read",
                "s.jsonl",
                "--start",
                "1",
                "--end",
                "5",
                "--wing",
                "convos",
            ],
            capsys,
        )
        assert code == 1
        assert "conversation drawers have no line ranges" in err
        assert cli_command("search", "<query>", "--wing", "convos", palace=palace_path) in err
        assert "Stale pointer" not in err
        assert "mine" not in err


class _BrokenStore:
    """A palace whose reads fail, as a degraded LanceDB table does."""

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        raise OSError("lance fragment missing")

    def get_source_files(self, wing):
        raise OSError("lance fragment missing")

    def count_by(self, column):
        raise OSError("lance fragment missing")


class _LanceLikeDegradedStore(_BrokenStore):
    """LanceStore.get() returns no rows on a damaged table; the metadata scans raise."""

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        return {"ids": [], "documents": [], "metadatas": []}


class TestStoreErrors:
    def test_read_reports_store_error_not_missing_file(self):
        result = read_slice(_BrokenStore(), "/src/app.py", 1, 2)
        assert result == {
            "error": "store_error",
            "source_file": "/src/app.py",
            "detail": "lance fragment missing",
        }

    @pytest.mark.parametrize("wing", [None, "proj"])
    def test_degraded_scan_is_store_error_not_not_found(self, wing, monkeypatch):
        # Taxonomy validation skips an unreadable taxonomy, as it does for a real palace.
        monkeypatch.setattr(
            "mempalace_code.reader._validate_wing_against_store", lambda _store, _wing: None
        )
        result = read_slice(_LanceLikeDegradedStore(), "app.py", 1, 2, wing=wing)
        assert result["error"] == "store_error"
        assert result["detail"] == "lance fragment missing"

    def test_mcp_read_and_file_context_add_the_degraded_hint(self, monkeypatch):
        monkeypatch.setattr(runtime, "_get_store", lambda create=False: _BrokenStore())
        from mempalace_code.mcp.tools.search import tool_read

        for result in (tool_read("/src/app.py", 1, 2), tool_file_context("/src/app.py")):
            assert result["error"] == "store_error"
            assert result["detail"] == "lance fragment missing"
            assert result["hint"] == runtime._degraded_hint()

    def test_cli_read_names_health_and_rollback(self, palace_path, capsys, monkeypatch):
        open_store(palace_path, create=True)
        monkeypatch.setattr("mempalace_code.storage.open_store", lambda *_a, **_k: _BrokenStore())
        code, out, err = _run_cli(
            ["--palace", palace_path, "read", "/src/app.py", "--start", "1", "--end", "2"],
            capsys,
        )
        assert code == 1
        assert out == ""
        assert "Read error: lance fragment missing" in err
        assert "Not found" not in err
        assert cli_command("health", palace=palace_path) in err
        assert cli_command("repair", "--rollback", "--dry-run", palace=palace_path) in err

    def test_search_json_on_a_dir_without_a_palace_keeps_the_palace(self, tmp_path, capsys):
        empty = tmp_path / "empty-dir"
        empty.mkdir()
        code, out, _err = _run_cli(["--palace", str(empty), "search", "x", "--json"], capsys)
        assert code == 1
        payload = json.loads(out)
        assert payload["error"] == "No palace found"
        assert cli_command("init", "<dir>", palace=str(empty)) in payload["hint"]
        assert cli_command("mine", "<dir>", palace=str(empty)) in payload["hint"]

    def test_search_json_error_names_health_and_rollback(self, palace_path, capsys, monkeypatch):
        monkeypatch.setattr(
            "mempalace_code.searcher.search_memories",
            lambda *_a, **_k: {"error": "Search error: lance fragment missing"},
        )
        open_store(palace_path, create=True)
        code, out, _err = _run_cli(["--palace", palace_path, "search", "x", "--json"], capsys)
        assert code == 1
        payload = json.loads(out)
        assert payload["error"] == "Search error: lance fragment missing"
        assert cli_command("health", palace=palace_path) in payload["hint"]

    def test_search_on_an_unreadable_palace_prints_one_next_line(
        self, palace_path, capsys, monkeypatch
    ):
        from mempalace_code import searcher
        from mempalace_code.storage import PalaceReadError

        def unreadable(*_a, **_k):
            raise PalaceReadError(palace_path, OSError("lance fragment missing"))

        open_store(palace_path, create=True)
        monkeypatch.setattr(searcher, "_query_rows", unreadable)
        code, _out, err = _run_cli(["--palace", palace_path, "search", "x"], capsys)
        assert code == 1
        assert err.count("Next:") == 1
        assert cli_command("repair", "--rollback", "--dry-run", palace=palace_path) in err

        monkeypatch.setattr(
            searcher,
            "search_memories",
            lambda *_a, **_k: {
                "error": f"Search error: {PalaceReadError(palace_path, OSError('gone'))}"
            },
        )
        code, out, _err = _run_cli(["--palace", palace_path, "search", "x", "--json"], capsys)
        assert code == 1
        assert "hint" not in json.loads(out)


def test_placeholders_are_printed_unquoted():
    command = cli_command("init", "<dir>", "a b", palace="/p")
    assert command.endswith(" --palace /p init <dir> 'a b'")
    assert cli_command("search", "<not a placeholder>").endswith(" search '<not a placeholder>'")


# ── read-2 / agent-13: path resolution and exact lookup cost ─────────────────


class _RecordingStore:
    def __init__(self, store):
        self._store = store
        self.calls = []

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        self.calls.append(("get", where))
        return self._store.get(ids=ids, where=where, include=include, limit=limit, offset=offset)

    def get_source_files(self, wing):
        self.calls.append(("get_source_files", wing))
        return self._store.get_source_files(wing)

    def count_by(self, column):
        self.calls.append(("count_by", column))
        return self._store.count_by(column)

    def count_by_pair(self, col_a, col_b):
        return self._store.count_by_pair(col_a, col_b)


class TestReadPathResolution:
    @pytest.fixture
    def linked_store(self, palace_path, tmp_path):
        real = tmp_path / "real" / "pkg"
        real.mkdir(parents=True)
        source = real / "mod.py"
        source.write_text("x = 1\ny = 2\n")
        link = tmp_path / "link"
        link.symlink_to(tmp_path / "real")
        stored = os.path.realpath(source)
        store = open_store(palace_path, create=True)
        store.add(
            ids=["m0"],
            documents=["x = 1\ny = 2"],
            metadatas=[_meta(stored, line_start=1, line_end=2)],
        )
        return store, stored, link

    def test_symlinked_path_resolves_to_the_stored_path(self, linked_store):
        store, stored, link = linked_store
        result = read_slice(store, str(link / "pkg" / "mod.py"), 1, 2)
        assert result["source_file"] == stored
        assert [entry["text"] for entry in result["lines"]] == ["x = 1", "y = 2"]

    def test_non_normalized_relative_path_resolves(self, linked_store):
        store, stored, _link = linked_store
        result = read_slice(store, "real/pkg/../pkg/mod.py", 1, 1)
        assert result["source_file"] == stored

    def test_relative_symlinked_path_resolves_against_the_working_dir(
        self, linked_store, tmp_path, monkeypatch
    ):
        store, stored, _link = linked_store
        monkeypatch.chdir(tmp_path / "real")
        result = read_slice(store, "../link/pkg/mod.py", 1, 1)
        assert result["source_file"] == stored
        assert result["lines"] == [{"line": 1, "text": "x = 1"}]

    def test_exact_path_read_without_wing_does_not_scan_every_source(self, linked_store):
        store, stored, _link = linked_store
        recording = _RecordingStore(store)
        result = read_slice(recording, stored, 1, 2)
        assert "error" not in result
        assert all(name == "get" for name, _arg in recording.calls)
        assert all(where is not None for _name, where in recording.calls)


# ── agent-18 / agent-10: file_context resolution and paging ──────────────────


class TestFileContext:
    @pytest.fixture
    def context_store(self, palace_path, monkeypatch):
        store = open_store(palace_path, create=True)
        ids = [f"fc_{i}" for i in range(5)] + ["other_init", "pkg_init"]
        documents = [f"def f{i}(): pass" for i in range(5)] + ["", "x = 1"]
        metadatas = [
            _meta("/proj/src/storage.py", chunk_index=i, line_start=i + 1, line_end=i + 1)
            for i in range(5)
        ] + [_meta("/proj/a/__init__.py"), _meta("/proj/b/__init__.py")]
        store.add(ids=ids, documents=documents, metadatas=metadatas)
        monkeypatch.setattr(runtime, "_get_store", lambda create=False: store)
        return store

    def test_unknown_file_is_not_found(self, context_store):
        assert tool_file_context("does/not/exist.py") == {
            "error": "not_found",
            "source_file": "does/not/exist.py",
        }

    def test_basename_resolves_like_read(self, context_store):
        result = tool_file_context("storage.py", wing="proj")
        assert result["source_file"] == "/proj/src/storage.py"
        assert result["total"] == 5
        assert [chunk["id"] for chunk in result["chunks"]] == [f"fc_{i}" for i in range(5)]

    def test_shared_basename_is_ambiguous(self, context_store):
        result = tool_file_context("__init__.py")
        assert result["error"] == "ambiguous_source"
        assert result["candidates"] == ["/proj/a/__init__.py", "/proj/b/__init__.py"]

    def test_chunks_are_paged(self, context_store):
        first = tool_file_context("/proj/src/storage.py", limit=2)
        assert [chunk["chunk_index"] for chunk in first["chunks"]] == [0, 1]
        assert (first["total"], first["offset"], first["limit"], first["next_offset"]) == (
            5,
            0,
            2,
            2,
        )
        last = tool_file_context("/proj/src/storage.py", limit=2, offset=4)
        assert [chunk["chunk_index"] for chunk in last["chunks"]] == [4]
        assert last["next_offset"] is None
        assert tool_file_context("/proj/src/storage.py", offset=-1)["error"] == "invalid_page"
