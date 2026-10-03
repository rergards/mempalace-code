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
        "if __name__ == '__main__':\n"
        "\tmessage = 'later top-level code must retain its original source line'  \n"
        "\tresult = first(2)\n"
        "\tprint(result, message)"
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


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("data_key", ["data", "stringData"])
@pytest.mark.parametrize("kind_space,data_space", [(" ", ""), ("", " "), ("  ", "  ")])
def test_secret_spacing_is_excluded_before_chunking(
    tmp_path, newline, data_key, kind_space, data_space
):
    import yaml

    from mempalace_code.mining.source_text import SKIP_SECRET, decode_source

    canonical = f"apiVersion: v1\nkind: Secret\n{data_key}:\n  example: fixture-only\n"
    text = (
        canonical.replace("kind:", f"kind{kind_space}:")
        .replace(f"{data_key}:", f"{data_key}{data_space}:")
        .replace("\n", newline)
    )
    assert yaml.safe_load(text) == yaml.safe_load(canonical)
    path = tmp_path / "manifest.yaml"
    path.write_bytes(text.encode())
    assert decode_source(text.encode(), path.name).skip_reason == SKIP_SECRET
    assert _collect(path) == []
    assert decode_source(text.encode(), path.name, force_include=True).skip_reason is None
    ordinary = text.replace("Secret", "ConfigMap")
    assert decode_source(ordinary.encode(), path.name).skip_reason is None
    separate = f"kind {kind_space}: Secret{newline}---{newline}{data_key} {data_space}:{newline}  example: fixture-only{newline}"
    assert decode_source(separate.encode(), path.name).skip_reason is None


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
    assert spec["metadata"]["chunker_strategy"] == chunkers.STRATEGY_REGEX_STRUCTURAL
    assert spec["metadata"]["symbol_name"] == "first"

    store = open_store(str(tmp_path / "palace"), create=True)
    assert orchestrator.add_drawers_batch(store, specs) == 1
    later_start = source.split("\n").index("if __name__ == '__main__':") + 1
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
    assert specs[0]["metadata"]["chunker_strategy"] == chunkers.STRATEGY_TREESITTER


def test_whitespace_and_repeated_blocks_map_in_source_order(tmp_path: Path) -> None:
    repeated = "\tvalue = '" + "same text " * 140 + "'  "
    source = f"\n\n{repeated}\n \t \n{repeated}\n"
    source_path = tmp_path / "repeated.txt"
    source_path.write_text(source, encoding="utf-8")

    specs = _collect(source_path)

    assert [spec["content"] for spec in specs] == [repeated, repeated]
    assert [spec["metadata"]["line_start"] for spec in specs] == [3, 5]
    assert [spec["metadata"]["line_end"] for spec in specs] == [3, 5]
    assert [spec["metadata"]["chunk_index"] for spec in specs] == [0, 1]


def test_every_chunk_is_the_exact_slice_its_line_range_names(tmp_path: Path) -> None:
    source = (
        "#!/bin/sh\n"
        "set -eu\n"
        "\n"
        "INPUT=$(cat)\n"
        "\n"
        "log() {\n"
        '  echo "$@" >&2\n'
        "}\n"
        "\n"
        "main() {\n"
        '  log "starting the main routine of this script with a long message line"\n'
        '  echo "$INPUT" | wc -c\n'
        "}\n"
        "\n"
        'main "$@"\n'
    )
    source_path = tmp_path / "run.sh"
    source_path.write_text(source, encoding="utf-8")

    specs = _collect(source_path)

    lines = source.split("\n")
    covered: set[int] = set()
    for spec in specs:
        start, end = spec["metadata"]["line_start"], spec["metadata"]["line_end"]
        assert spec["content"] == "\n".join(lines[start - 1 : end])
        covered.update(range(start, end + 1))
    non_blank = {number for number, line in enumerate(lines, 1) if line.strip()}
    assert non_blank <= covered


@pytest.mark.parametrize("final_newline", [False, True])
def test_eof_mapping_does_not_invent_an_extra_line(tmp_path: Path, final_newline: bool) -> None:
    final_line = "final value with enough content to satisfy the mining size threshold"
    source = "opening value with enough content to form the source fixture\n" + final_line
    if final_newline:
        source += "\n"
    source_path = tmp_path / "eof.txt"
    source_path.write_text(source, encoding="utf-8")

    specs = _collect(source_path)

    assert len(specs) == 1
    assert specs[0]["content"].split("\n")[-1] == final_line
    assert specs[0]["metadata"]["line_start"] == 1
    assert specs[0]["metadata"]["line_end"] == 2
