"""Regressions for source-exact mined content and line ranges."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mempalace_code.mining import chunkers, orchestrator
from mempalace_code.reader import read_slice
from mempalace_code.storage import open_store
from mempalace_code.treesitter import get_parser

if TYPE_CHECKING:
    from pathlib import Path


def _python_source(*, final_newline: bool = True) -> str:
    source = (
        "\n\n"
        "def first(value):\n"
        "    total = value + 1  \n"
        "    label = 'first function keeps enough representative text'\n"
        "    return total, label\n"
        " \t \n"
        "\n"
        "def later(value):\n"
        "\tmessage = 'later declaration must retain its original source line'  \n"
        "\tresult = value * 2\n"
        "\treturn result, message"
    )
    return source + ("\n" if final_newline else "")


def _collect(path: Path) -> list[dict]:
    return orchestrator._collect_specs_for_file(
        path,
        path.parent,
        None,
        "source_exact",
        [{"name": "general", "description": "All source"}],
        "test",
        mined_files=set(),
        source_hash="fixed-source-hash",
    )


def _expected_lines(source: str, start: int, end: int) -> list[dict[str, object]]:
    lines = source.split("\n")
    return [{"line": number, "text": lines[number - 1]} for number in range(start, end + 1)]


def test_forced_regex_persists_exact_lines_and_read_slice_roundtrips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _python_source()
    source_path = tmp_path / "source.py"
    source_path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(chunkers, "get_parser", lambda _language: None)

    specs = _collect(source_path)

    assert len(specs) == 1
    spec = specs[0]
    assert spec["content"] == source.split("\n", 2)[2].removesuffix("\n")
    assert spec["metadata"]["line_start"] == 3
    assert spec["metadata"]["line_end"] == 12
    assert spec["metadata"]["chunk_index"] == 0
    assert spec["metadata"]["chunker_strategy"] == "regex_structural_v1"
    assert spec["metadata"]["symbol_name"] == "first"

    store = open_store(str(tmp_path / "palace"), create=True)
    assert orchestrator.add_drawers_batch(store, specs) == 1
    later_start = source.split("\n").index("def later(value):") + 1
    result = read_slice(store, str(source_path), later_start, 12)
    assert result["lines"] == _expected_lines(source, later_start, 12)

    repeated_specs = _collect(source_path)
    stable_metadata = {key: value for key, value in spec["metadata"].items() if key != "filed_at"}
    assert repeated_specs[0]["id"] == spec["id"]
    assert repeated_specs[0]["content"] == spec["content"]
    assert {
        key: value for key, value in repeated_specs[0]["metadata"].items() if key != "filed_at"
    } == stable_metadata
    assert orchestrator.add_drawers_batch(store, repeated_specs) == 1
    assert store.count() == 1


def test_real_python_treesitter_restores_merged_source_lines(tmp_path: Path) -> None:
    if get_parser("python") is None:
        pytest.skip("tree-sitter-python not installed")
    source = _python_source(final_newline=False)
    source_path = tmp_path / "source.py"
    source_path.write_text(source, encoding="utf-8")

    specs = _collect(source_path)

    assert len(specs) == 1
    assert specs[0]["content"] == source.split("\n", 2)[2]
    assert specs[0]["metadata"]["line_start"] == 3
    assert specs[0]["metadata"]["line_end"] == 12
    assert specs[0]["metadata"]["chunker_strategy"] == "treesitter_v1"


def test_whitespace_and_repeated_chunks_map_in_source_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repeated = "\tvalue = 'same text with enough content for controlled mapping'  "
    source = f"\n\n{repeated}\n \t \n{repeated}\n"
    source_path = tmp_path / "repeated.txt"
    source_path.write_text(source, encoding="utf-8")
    normalized = repeated.strip()
    chunks = [
        {"content": normalized, "chunk_index": 0, "chunker_strategy": "controlled_v1"},
        {"content": normalized, "chunk_index": 1, "chunker_strategy": "controlled_v1"},
    ]
    monkeypatch.setattr(orchestrator, "chunk_file", lambda *_args, **_kwargs: chunks)

    specs = _collect(source_path)

    assert [spec["content"] for spec in specs] == [repeated, repeated]
    assert [spec["metadata"]["line_start"] for spec in specs] == [3, 5]
    assert [spec["metadata"]["line_end"] for spec in specs] == [3, 5]
    assert [spec["metadata"]["chunk_index"] for spec in specs] == [0, 1]
    assert [spec["metadata"]["chunker_strategy"] for spec in specs] == [
        "controlled_v1",
        "controlled_v1",
    ]


def test_unmappable_chunk_keeps_original_and_does_not_advance_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    valid_line = "    valid = 'the later controlled chunk remains discoverable in source'  "
    source = f"header text that makes this fixture long enough for mining\n{valid_line}\n"
    source_path = tmp_path / "controlled.txt"
    source_path.write_text(source, encoding="utf-8")
    chunks = [
        {
            "content": "missing controlled chunk",
            "chunk_index": 0,
            "symbol_name": "missing",
            "symbol_type": "controlled",
        },
        {
            "content": valid_line.strip(),
            "chunk_index": 1,
            "symbol_name": "valid",
            "symbol_type": "controlled",
        },
    ]
    monkeypatch.setattr(orchestrator, "chunk_file", lambda *_args, **_kwargs: chunks)

    specs = _collect(source_path)

    assert specs[0]["content"] == "missing controlled chunk"
    assert specs[0]["metadata"]["line_start"] == 0
    assert specs[0]["metadata"]["line_end"] == 0
    assert specs[0]["metadata"]["symbol_name"] == "missing"
    assert specs[1]["content"] == valid_line
    assert specs[1]["metadata"]["line_start"] == 2
    assert specs[1]["metadata"]["line_end"] == 2
    assert specs[1]["metadata"]["symbol_name"] == "valid"

    store = open_store(str(tmp_path / "palace"), create=True)
    orchestrator.add_drawers_batch(store, [specs[0]])
    assert read_slice(store, str(source_path), 1, 2)["error"] == "stale_pointer"


@pytest.mark.parametrize("final_newline", [False, True])
def test_eof_mapping_does_not_invent_an_extra_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_newline: bool
) -> None:
    final_line = "final value with enough content to satisfy the mining size threshold"
    source = "opening value with enough content to form the source fixture\n" + final_line
    if final_newline:
        source += "\n"
    source_path = tmp_path / "eof.txt"
    source_path.write_text(source, encoding="utf-8")
    chunks = [{"content": final_line, "chunk_index": 0}]
    monkeypatch.setattr(orchestrator, "chunk_file", lambda *_args, **_kwargs: chunks)

    specs = _collect(source_path)

    assert specs[0]["content"] == final_line
    assert specs[0]["metadata"]["line_start"] == 2
    assert specs[0]["metadata"]["line_end"] == 2
    assert specs[0]["content"].split("\n") == [final_line]
