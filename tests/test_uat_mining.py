"""UAT regressions for project mining (group "mining").

Each test names the UAT issue it pins. The coverage checker at the top is the
verbatim-first invariant: every non-blank source line of a polyglot fixture must
be recoverable, byte for byte, from the stored drawers and their line ranges.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from mempalace_code.cli_invocation import cli_prefix
from mempalace_code.mining import chunkers, orchestrator
from mempalace_code.mining.chunkers import HARD_MAX, chunk_file
from mempalace_code.mining.projects import detect_room, load_config
from mempalace_code.mining.symbols import extract_symbol
from mempalace_code.reader import read_slice
from mempalace_code.storage import open_store

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def _init_project(root: Path, wing: str = "uat", rooms: list | None = None) -> None:
    config = {"wing": wing, "rooms": rooms or [{"name": "general", "description": "All"}]}
    _write(root / "mempalace.yaml", yaml.safe_dump(config))


def _mine(project: Path, palace: Path, **kwargs) -> dict:
    kwargs.setdefault("skip_optimize", True)
    return orchestrator.mine(str(project), str(palace), **kwargs)


def _rows(palace: Path, wing: str | None = None) -> list[dict]:
    store = open_store(str(palace), create=False, read_only=True)
    rows: list[dict] = []
    for batch in store.iter_all():
        rows.extend(batch)
    if wing is not None:
        rows = [row for row in rows if row["wing"] == wing]
    return sorted(rows, key=lambda row: (row["source_file"], row["chunk_index"]))


@pytest.mark.parametrize("failure", ["embedding", "upsert", "interrupt"])
@pytest.mark.parametrize("empty_source", [False, True])
def test_failed_changed_source_batch_preserves_previous_drawers(
    tmp_path, monkeypatch, failure, empty_source
):
    """Retain old rows on failure; a retry replaces them once and keeps unrelated rows."""
    project = tmp_path / "project"
    palace = tmp_path / "palace"
    _init_project(project)
    changed = _write(project / "a.py", "def old():\n    return 'original source content'\n")
    other = _write(project / "b.py", "def other():\n    return 'other original content'\n")
    untouched = _write(project / "c.py", "def stable():\n    return 'unchanged source content'\n")
    _mine(project, palace)
    before = _rows(palace)
    store = open_store(str(palace), create=False)
    _write(changed, "" if empty_source else "def new():\n    return 'replacement content'\n")
    _write(other, "def changed_other():\n    return 'other replacement content'\n")

    def fail(*args, **kwargs):
        if failure == "interrupt":
            raise KeyboardInterrupt("injected interrupt failure")
        raise RuntimeError(f"injected {failure} failure")

    with monkeypatch.context() as injected:
        # Force one batch and source order so the empty source precedes the failing write.
        injected.setattr(
            orchestrator, "scan_project", lambda *args, **kwargs: [changed, other, untouched]
        )
        injected.setattr(orchestrator, "get_batch_size", lambda: 10_000)
        if failure in {"embedding", "interrupt"}:
            injected.setattr(store, "_embed", fail)
        else:
            injected.setattr(store._table, "merge_insert", fail)
        expected_error = KeyboardInterrupt if failure == "interrupt" else RuntimeError
        with pytest.raises(expected_error, match=f"injected {failure} failure"):
            _mine(project, palace, collection=store, warmup=False)

    assert _rows(palace) == before
    retried = _mine(project, palace, collection=store)
    assert retried["drawers_filed"] > 0
    after = _rows(palace)
    assert [row for row in after if row["source_file"] == str(untouched)] == [
        row for row in before if row["source_file"] == str(untouched)
    ]
    changed_rows = [row for row in after if row["source_file"] == str(changed)]
    if empty_source:
        assert changed_rows == []
        assert retried["stale_files_removed"] == 1
        assert retried["stale_drawers_removed"] == len(
            [row for row in before if row["source_file"] == str(changed)]
        )
    else:
        assert changed_rows
        assert all("replacement content" in row["text"] for row in changed_rows)
    assert len({row["id"] for row in after}) == len(after)
    assert _mine(project, palace, collection=store)["drawers_filed"] == 0
    assert _rows(palace) == after


# =============================================================================
# Room routing (mine-8) and mine guards (mine-14)
# =============================================================================


def test_mine8_folder_that_is_only_part_of_a_room_name_does_not_claim_it(tmp_path):
    rooms = [
        {"name": "acme_web", "description": ""},
        {"name": "acme_data", "description": ""},
        {"name": "general", "description": ""},
    ]
    java = tmp_path / "jvm/src/main/java/com/acme/OrderRepository.java"
    assert detect_room(java, "class OrderRepository {}", rooms, tmp_path) == "general"
    web = tmp_path / "web/handler.py"
    assert detect_room(web, "def handle(): pass", rooms, tmp_path) == "general"
    exact = tmp_path / "src/Acme.Web/Startup.cs"
    assert detect_room(exact, "class Startup {}", rooms, tmp_path) == "acme_web"


def test_mine8_exact_folder_match_beats_an_earlier_partial_room(tmp_path):
    rooms = [
        {"name": "mempalace_code", "description": ""},
        {"name": "mempalace", "description": ""},
    ]
    shim = tmp_path / "mempalace/__init__.py"
    assert detect_room(shim, "", rooms, tmp_path) == "mempalace"
    package = tmp_path / "mempalace_code/cli.py"
    assert detect_room(package, "", rooms, tmp_path) == "mempalace_code"
    keyword_rooms = [{"name": "frontend", "description": "", "keywords": ["components"]}]
    widget = tmp_path / "ui_components/button.tsx"
    assert detect_room(widget, "", keyword_rooms, tmp_path) == "frontend"


def test_mine14_missing_directory_and_file_paths_get_accurate_guards(tmp_path, capsys):
    with pytest.raises(SystemExit) as missing:
        load_config(str(tmp_path / "doesnotexist"))
    assert missing.value.code == 1
    err = capsys.readouterr().err
    assert "directory not found" in err
    assert "No mempalace.yaml" not in err

    project = tmp_path / "proj"
    _init_project(project)
    source = _write(project / "api" / "invoice.py", "x = 1\n")
    with pytest.raises(SystemExit) as file_path:
        load_config(str(source))
    assert file_path.value.code == 1
    err = capsys.readouterr().err
    assert "not a directory" in err
    assert str(project) in err


def test_mine14_negative_limit_is_rejected_by_the_cli(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "mempalace_code.cli", "mine", str(tmp_path), "--limit", "-1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
    )
    assert result.returncode == 2
    assert "--limit" in result.stderr
    assert "must be >= 0" in result.stderr
    with pytest.raises(ValueError, match="limit must be >= 0"):
        orchestrator.mine(str(tmp_path), str(tmp_path / "palace"), limit=-1)


# =============================================================================
# Verbatim coverage invariant (mine-1, agent-2, mine-2, mine-7, gap-9)
# =============================================================================

_BIG_PY_BODY = "".join(
    f"    value_{i} = compute_step({i}, value_{i - 1 if i else 0})\n" for i in range(70)
)

POLYGLOT = {
    "setup.sh": (
        "#!/bin/sh\nexport SMALL_MARKER_ONE=1\n\n# " + "x" * 110 + "\n"
        'echo "configuring the build environment for the whole project"\n\n'
        "export SMALL_MARKER_TWO=2\n"
    ),
    "app.ini": (
        "[database]\nhost=localhost\nport=5432\n\n[cache]\nbackend=memcached_SMALL_MARKER_THREE\n\n"
        "[logging]\nlevel=info\nformat=%(asctime)s %(levelname)s %(message)s " + "y" * 60 + "\n"
    ),
    "queries.sql": (
        "-- small marker\nDROP TABLE SMALL_MARKER_FIVE;\n\nCREATE TABLE orders (\n"
        "  id INTEGER PRIMARY KEY, customer TEXT NOT NULL, total NUMERIC(10, 2)\n);\n"
    ),
    "lib.rb": (
        'require "json"\n\nSMALL_MARKER_SIX = 6\n\nclass Parser\n  def parse(text)\n'
        "    JSON.parse(text) # parse the input text into a hash for the caller\n  end\nend\n"
    ),
    "crc32.c": (
        "#include <stdint.h>\n#include <stddef.h>\n#include <stdio.h>\n\n"
        "uint32_t crc32(const uint8_t *buf, size_t len) {\n  uint32_t crc = 0xFFFFFFFF;\n"
        "  for (size_t i = 0; i < len; i++) { crc ^= buf[i]; }\n  return ~crc;\n}\n"
    ),
    "pyproject.toml": (
        '[project]\nname = "demo"\nversion = "1.0"\n\n[build-system]\n'
        'requires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'
    ),
    "big.py": (
        "import os\n\nAPI_VERSION = 'v2'\n\n\ndef long_function(value_0):\n"
        + _BIG_PY_BODY
        + "    return value_69\n\n\ndef tail_probe(x):\n    return x + 1\n"
    ),
    "version.py": (
        '"""Version helper.\n\nReads from pyproject.toml in a source checkout.\n"""\n\ntry:\n'
        "    import tomllib\n    from pathlib import Path\n\n"
        '    _pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"\n'
        "    if _pyproject.exists():\n"
        '        __version__ = tomllib.loads(_pyproject.read_text())["project"]["version"]\n'
        "except Exception:\n"
        '    __version__ = "0.0.0-dev"\n'
    ),
    "deploy/k8s.yaml": (
        "---\napiVersion: v1\nkind: Namespace\nmetadata:\n  name: shop\n---\n"
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\nspec:\n  replicas: 2\n"
    ),
    "docs/guide.md": (
        "Intro line before any heading.\n\n# Guide\n\nShort.\n\n## Install\n\n"
        "```bash\npip install demo\n```\n\n## Usage\n\nRun it.\n"
    ),
    "config/settings.json": '{"cache": {"ttl_seconds": 300, "backend": "redis"}}',
    "infra/workers.tf": "".join(
        f'resource "aws_instance" "{name}_worker" {{\n  ami           = "ami-123"\n'
        f'  instance_type = "t3.micro"\n  tags = {{\n    Name = "{name}"\n  }}\n}}\n\n'
        for name in ("alpha", "beta")
    ),
    "tools/report.pl": (
        "#!/usr/bin/perl\nuse strict;\nuse warnings;\n\npackage Report;\n\n"
        'sub render {\n    my ($rows) = @_;\n    return join("\\n", @$rows);\n}\n\n'
        "print render([1, 2]);\n"
    ),
    "config/web.config": (
        '<?xml version="1.0"?>\n<configuration>\n  <appSettings>\n'
        '    <add key="Mode" value="Production" />\n  </appSettings>\n</configuration>\n'
    ),
    "bin/emu-restart": "#!/usr/bin/env bash\nset -eu\nsystemctl restart emu.service\n",
    "crlf.txt": "first line\r\nsecond line\r\n\r\nthird paragraph line\r\n",
    "long_line.js": (
        "// generated fixture with one long literal among normal lines\n"
        "const table = '"
        + "abcdefghij" * 600
        + "';\n"
        + "".join(f"function f{i}() {{ return table.length + {i}; }}\n" for i in range(40))
    ),
}


def _write_polyglot(root: Path) -> None:
    for relative, text in POLYGLOT.items():
        _write(root / relative, text)
    (root / "bin" / "emu-restart").chmod(0o755)
    _write(
        root / "bom.py", b"\xef\xbb\xbfdef bom_prefixed_function(value):\n    return value * 3\n"
    )


def _assert_verbatim_coverage(path: Path, specs: list[dict]) -> None:
    text = path.read_bytes().decode("utf-8-sig")
    lines = text.split("\n")
    covered: set[int] = set()
    split_lines: dict[int, list[str]] = {}
    for spec in specs:
        meta = spec["metadata"]
        start, end = meta["line_start"], meta["line_end"]
        assert start >= 1, f"{path.name}: chunk without line metadata"
        assert len(spec["content"]) <= HARD_MAX, f"{path.name}: chunk over HARD_MAX"
        expected = "\n".join(lines[start - 1 : end])
        if spec["content"] != expected:
            assert start == end, f"{path.name}: chunk is not an exact slice of {start}-{end}"
            assert spec["content"] in lines[start - 1], f"{path.name}: piece not in line {start}"
            split_lines.setdefault(start, []).append(spec["content"])
        covered.update(range(start, end + 1))
    for number, pieces in split_lines.items():
        assert "".join(pieces) == lines[number - 1]
    missing = [n for n, line in enumerate(lines, 1) if line.strip() and n not in covered]
    assert not missing, f"{path.name}: non-blank lines missing from drawers: {missing}"


@pytest.mark.parametrize("tree_sitter", [True, False], ids=["treesitter", "regex"])
def test_every_source_line_is_recoverable_from_drawers(tmp_path, monkeypatch, tree_sitter):
    """Coverage checker: each drawer is an exact slice and all non-blank lines are stored."""
    if not tree_sitter:
        monkeypatch.setattr(chunkers, "get_parser", lambda _language: None)
    project = tmp_path / "poly"
    _write_polyglot(project)
    _init_project(project)
    from mempalace_code.mining.scanner import scan_project

    files = scan_project(str(project))
    names = {path.relative_to(project).as_posix() for path in files}
    assert {"tools/report.pl", "config/web.config", "bin/emu-restart", "bom.py"} <= names
    rooms = [{"name": "general", "description": "All"}]
    for path in files:
        specs = orchestrator._collect_specs_for_file(
            path, project, None, "poly", rooms, "test", mined_files=set(), source_hash="0" * 32
        )
        assert specs, f"{path.name} produced no drawers"
        _assert_verbatim_coverage(path, specs)


def test_mine1_small_blocks_are_stored_and_readable(tmp_path):
    project = tmp_path / "loss"
    for name in ("setup.sh", "app.ini", "queries.sql", "lib.rb", "big.py"):
        _write(project / name, POLYGLOT[name])
    _init_project(project, wing="loss")
    palace = tmp_path / "palace"
    stats = _mine(project, palace)
    assert stats["drawers_filed"] >= 5

    store = open_store(str(palace), create=False)
    ini = read_slice(store, str(project / "app.ini"), 1, 6, wing="loss")
    assert [line["text"] for line in ini["lines"]] == POLYGLOT["app.ini"].split("\n")[:6]
    head = read_slice(store, str(project / "big.py"), 1, 3, wing="loss")
    assert [line["text"] for line in head["lines"]] == ["import os", "", "API_VERSION = 'v2'"]
    texts = "\n".join(row["text"] for row in _rows(palace))
    for marker in ("SMALL_MARKER_ONE", "SMALL_MARKER_TWO", "SMALL_MARKER_FIVE", 'require "json"'):
        assert marker in texts


def test_mine7_no_chunk_exceeds_hard_max():
    block = "def f():\n    a = 1\n\n" + "\n".join(f"    x_{i} = {i} * 7" for i in range(900))
    minified = "var a=" + "1," * 3000 + "0;"
    for content, ext in ((block, ".py"), (minified, ".txt"), (block, ".sh")):
        chunks = chunk_file(content, ext, "f" + ext)
        assert max(len(chunk["content"]) for chunk in chunks) <= HARD_MAX
        assert all(chunk["line_start"] >= 1 for chunk in chunks)


# =============================================================================
# Symbol attribution (agent-4, mine-15, mine-6, gap-15)
# =============================================================================

_SEARCH_TOOLS_PY = "".join(
    f"def {name}(query, limit=10):\n"
    f'    """{name} docstring explaining the tool in enough words to be substantial."""\n'
    + "".join(f"    step_{i} = run_{name}(query, {i})\n" for i in range(12))
    + "    return step_11\n\n\n"
    for name in ("tool_search", "tool_code_search", "tool_check_duplicate")
)


@pytest.mark.parametrize("tree_sitter", [True, False], ids=["treesitter", "regex"])
def test_agent4_each_declaration_is_findable_by_symbol(tmp_path, monkeypatch, tree_sitter):
    if not tree_sitter:
        monkeypatch.setattr(chunkers, "get_parser", lambda _language: None)
    rooms = [{"name": "general", "description": "All"}]
    tools = _write(tmp_path / "search.py", _SEARCH_TOOLS_PY)
    specs = orchestrator._collect_specs_for_file(
        tools, tmp_path, None, "w", rooms, "t", mined_files=set(), source_hash="0" * 32
    )
    assert [s["metadata"]["symbol_name"] for s in specs] == [
        "tool_search",
        "tool_code_search",
        "tool_check_duplicate",
    ]

    budget = _write(
        tmp_path / "disk_budget.py",
        "def check_backup_budget(path):\n"
        + "".join(f"    limit_{i} = measure(path, {i})\n" for i in range(40))
        + "    return limit_39\n\n\ndef uat_quokka_budget_probe(x):\n    return x * 2\n",
    )
    specs = orchestrator._collect_specs_for_file(
        budget, tmp_path, None, "w", rooms, "t", mined_files=set(), source_hash="0" * 32
    )
    assert specs[-1]["metadata"]["symbol_name"] == "uat_quokka_budget_probe"
    assert specs[-1]["content"].startswith("def uat_quokka_budget_probe")


def test_mine15_primary_symbol_is_the_first_definition_and_pieces_inherit_it(tmp_path):
    rooms = [{"name": "general", "description": "All"}]
    tokens = _write(
        tmp_path / "tokens.py",
        "class TokenSigner:\n    def __init__(self, key):\n        self.key = key\n\n"
        "    def sign(self, payload):\n        return hmac(self.key, payload)\n\n\n"
        "def rotate_signing_key(signer):\n    return TokenSigner(new_key())\n",
    )
    specs = orchestrator._collect_specs_for_file(
        tokens, tmp_path, None, "w", rooms, "t", mined_files=set(), source_hash="0" * 32
    )
    assert specs[0]["metadata"]["symbol_name"] == "TokenSigner"
    assert (
        extract_symbol("type TokenBucket struct {}\n\nfunc (b *TokenBucket) Allow() bool {", "go")[
            0
        ]
        == "TokenBucket"
    )

    big_class = "class Registry:\n" + "".join(
        f"    entry_{i} = build_entry_value({i}, 'padding text for size')\n" for i in range(160)
    )
    big = _write(tmp_path / "registry.py", big_class)
    specs = orchestrator._collect_specs_for_file(
        big, tmp_path, None, "w", rooms, "t", mined_files=set(), source_hash="0" * 32
    )
    assert len(specs) > 1
    assert {s["metadata"]["symbol_name"] for s in specs} == {"Registry"}


@pytest.mark.parametrize("tree_sitter", [True, False], ids=["treesitter", "regex"])
def test_mine6_bom_file_is_stored_verbatim_with_lines_and_symbol(
    tmp_path, monkeypatch, tree_sitter
):
    if not tree_sitter:
        monkeypatch.setattr(chunkers, "get_parser", lambda _language: None)
    body = 'def bom_prefixed_function(value):\n    """BOM file."""\n    return value * 3\n'
    bom = _write(tmp_path / "bom.py", b"\xef\xbb\xbf" + body.encode())
    specs = orchestrator._collect_specs_for_file(
        bom, tmp_path, None, "w", [{"name": "general"}], "t", mined_files=set()
    )
    assert len(specs) == 1
    assert specs[0]["content"] == body.rstrip("\n")
    assert (specs[0]["metadata"]["line_start"], specs[0]["metadata"]["line_end"]) == (1, 3)
    assert specs[0]["metadata"]["symbol_name"] == "bom_prefixed_function"


def test_gap15_terraform_blocks_carry_resource_symbols(tmp_path):
    workers = "".join(
        f'resource "aws_instance" "{name}_worker" {{\n'
        + "".join(f'  tag_{i} = "{name}-{i}-value-for-the-worker-instance"\n' for i in range(8))
        + "}\n\n"
        for name in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
    )
    path = _write(tmp_path / "terraform" / "workers.tf", workers)
    specs = orchestrator._collect_specs_for_file(
        path, tmp_path, None, "w", [{"name": "general"}], "t", mined_files=set()
    )
    assert [(s["metadata"]["symbol_name"], s["metadata"]["symbol_type"]) for s in specs] == [
        (f"aws_instance.{name}_worker", "resource")
        for name in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
    ]
    assert extract_symbol('module "vpc" {\n  source = "x"\n}', "terraform") == (
        "module.vpc",
        "module",
    )
    assert extract_symbol('variable "region" {\n}', "hcl") == ("var.region", "variable")
    assert extract_symbol('data "aws_ami" "ubuntu" {\n}', "terraform") == (
        "data.aws_ami.ubuntu",
        "data",
    )


# =============================================================================
# Reading policy (mine-4, mine-9, mine-12, gap-5)
# =============================================================================


def test_mine4_binary_files_with_source_extensions_are_skipped_and_named(tmp_path, capsys):
    project = tmp_path / "proj"
    _write(project / "app.py", "def app():\n    return 1\n")
    _write(project / "blob.py", bytes(range(256)) * 12)
    _init_project(project)
    palace = tmp_path / "palace"

    stats = _mine(project, palace)

    out = capsys.readouterr().out
    assert stats["files_skipped_by_reason"] == {"binary": 1}
    assert "Files skipped (binary content): 1" in out
    assert "- blob.py" in out
    assert {Path(row["source_file"]).name for row in _rows(palace)} == {"app.py"}


def test_mine9_coding_cookie_is_honoured_and_lossy_decodes_warn(tmp_path, capsys):
    project = tmp_path / "proj"
    _write(
        project / "latin1.py",
        b'# -*- coding: latin-1 -*-\ndef grue\xdf_funktion():\n    """Gr\xfc\xdfe"""\n',
    )
    _write(project / "broken.txt", b"caf\xe9 without any declared encoding in this file\n")
    _init_project(project)
    palace = tmp_path / "palace"

    stats = _mine(project, palace)

    captured = capsys.readouterr()
    rows = {Path(row["source_file"]).name: row for row in _rows(palace)}
    assert "grueß_funktion" in rows["latin1.py"]["text"]
    assert rows["latin1.py"]["symbol_name"] == "grueß_funktion"
    assert stats["files_lossy_decoded"] == 1
    assert "broken.txt: not valid UTF-8" in captured.err
    assert "- broken.txt" in captured.out


def test_mine12_small_files_are_indexed_and_empty_files_counted(tmp_path, capsys):
    project = tmp_path / "proj"
    _write(project / "config" / "settings.json", POLYGLOT["config/settings.json"])
    _write(project / "pkg" / "__init__.py", "\n")
    _init_project(project)
    palace = tmp_path / "palace"

    stats = _mine(project, palace)

    assert stats["files_processed"] == 1
    assert stats["files_skipped_by_reason"] == {"empty": 1}
    assert "Files skipped (empty): 1" in capsys.readouterr().out
    assert [row["text"] for row in _rows(palace)] == [POLYGLOT["config/settings.json"]]


def test_gap5_oversized_and_minified_files_are_skipped_unless_force_included(tmp_path, capsys):
    project = tmp_path / "big"
    _write(project / "app.py", "def load_customers():\n    return read('customers.json')\n")
    _write(project / "static" / "bundle.min.js", "function a(){return 1}" * 2000)
    _write(project / "static" / "vendor.js", "var x=" + "[1,2,3]," * 1200 + "0;")
    _write(
        project / "fixtures" / "customers.json",
        json.dumps([{"id": i, "tags": ["a", "b"]} for i in range(1000)], indent=2),
    )
    _init_project(project)
    config = yaml.safe_load((project / "mempalace.yaml").read_text())
    config["max_file_bytes"] = 50_000
    (project / "mempalace.yaml").write_text(yaml.safe_dump(config))
    palace = tmp_path / "palace"

    stats = _mine(project, palace)

    out = capsys.readouterr().out
    assert stats["files_skipped_by_reason"] == {"too_large": 1, "minified": 2}
    assert "Files skipped (too large, over 50,000 bytes): 1" in out
    assert "Files skipped (minified or generated): 2" in out
    assert "--include-ignored" in out
    assert {Path(row["source_file"]).name for row in _rows(palace)} == {"app.py"}

    forced = _mine(project, palace, include_ignored=["static/bundle.min.js"])
    assert forced["files_processed"] == 1
    bundle_rows = [row for row in _rows(palace) if row["source_file"].endswith("bundle.min.js")]
    assert bundle_rows
    assert all(row["line_start"] == 1 for row in bundle_rows)
    assert all(len(row["text"]) <= HARD_MAX for row in bundle_rows)


# =============================================================================
# Scanning (gap-9, mine-13)
# =============================================================================


def test_gap9_shebang_scripts_perl_and_xml_are_indexed(tmp_path, capsys):
    project = tmp_path / "misc"
    _write(project / "report.pl", POLYGLOT["tools/report.pl"])
    _write(project / "settings.xml", POLYGLOT["config/web.config"])
    _write(project / "bin" / "emu-report", "#!/usr/bin/env perl\nprint 'report';\n")
    _write(project / "bin" / "emu-restart", POLYGLOT["bin/emu-restart"])
    _write(project / "logo.png", b"\x89PNG\r\n\x1a\n")
    _write(project / "LICENSE", "MIT License\n")
    _init_project(project)
    palace = tmp_path / "palace"

    stats = _mine(project, palace)

    languages = {Path(row["source_file"]).name: row["language"] for row in _rows(palace)}
    assert languages == {
        "report.pl": "perl",
        "settings.xml": "xml",
        "emu-report": "perl",
        "emu-restart": "shell",
    }
    assert stats["files_unsupported"] == 2
    assert "Files not scanned (unsupported type): 2" in capsys.readouterr().out


def test_mine13_include_ignored_absolute_and_missing_paths(tmp_path, capsys):
    project = tmp_path / "inc"
    _write(project / ".gitignore", "build/\n")
    _write(project / "app.py", "def app():\n    return 1\n")
    bundle = _write(project / "build" / "out" / "bundle.js", "function bundle() { return 42; }\n")
    _init_project(project)
    palace = tmp_path / "palace"

    stats = _mine(project, palace, include_ignored=[str(bundle), "nope/missing.js"])

    err = capsys.readouterr().err
    assert "nope/missing.js: no such file or directory" in err
    assert stats["files_processed"] == 2
    assert str(bundle) in {row["source_file"] for row in _rows(palace)}

    outside = tmp_path / "elsewhere.js"
    _write(outside, "x = 1\n")
    _mine(project, palace, include_ignored=[str(outside)])
    assert "not inside the project" in capsys.readouterr().err


# =============================================================================
# Incremental state, sweep, and interruption (mine-10, mine-11, gap-6, mine-dir,
# gap-1, sig-1, chunker strategy bump)
# =============================================================================


def _t1_project(root: Path) -> None:
    _write(root / "docs" / "one.md", "# One\n\nThe first document about osprey ledger totals.\n")
    _write(root / "notes" / "n.md", "# Notes\n\nA note about osprey ledger totals.\n")
    _write(root / "src" / "x.py", "def osprey_ledger_totals(rows):\n    return sum(rows)\n")
    _write(root / "tiny.sh", "#!/bin/sh\necho hi\n")
    _write(root / "empty.py", "\n")
    _init_project(
        root,
        wing="t1",
        rooms=[
            {"name": "documentation", "description": "", "keywords": ["docs"]},
            {"name": "general", "description": ""},
        ],
    )


def test_mine11_dry_run_matches_the_real_run(tmp_path, capsys):
    project = tmp_path / "t1"
    _t1_project(project)
    palace = tmp_path / "palace"

    dry = _mine(project, palace, dry_run=True)
    dry_out = capsys.readouterr().out
    real = _mine(project, palace)
    real_out = capsys.readouterr().out

    for key in ("files_processed", "files_skipped", "files_tiny", "drawers_filed"):
        assert dry[key] == real[key], key
    assert not (palace / "lance").exists() or dry["drawers_filed"] == real["drawers_filed"]

    def rooms(out: str) -> list[str]:
        return [line.strip() for line in out.split("By room:")[1].splitlines() if "files" in line]

    assert rooms(dry_out) == rooms(real_out)
    assert _mine(project, palace, dry_run=True)["files_skipped"] == real["files_processed"]


def test_mine10_and_mine_dir_deleted_and_renamed_directories_are_swept(tmp_path, capsys):
    project = tmp_path / "t1"
    _t1_project(project)
    palace = tmp_path / "palace"
    _mine(project, palace)
    capsys.readouterr()

    import shutil

    shutil.rmtree(project / "notes")
    removed = _mine(project, palace)
    assert removed["stale_files_removed"] == 1
    assert removed["stale_drawers_removed"] == 1
    out = capsys.readouterr().out
    assert "Stale drawers removed: 1 (1 deleted, excluded or now-skipped file(s))" in out
    assert "By room:" not in out

    (project / "src").rename(project / "lib")
    _mine(project, palace)
    _mine(project, palace, incremental=False)
    sources = {Path(row["source_file"]).relative_to(project).as_posix() for row in _rows(palace)}
    assert sources == {"docs/one.md", "lib/x.py", "tiny.sh"}


def test_gap1_mining_never_deletes_manual_drawers_that_cite_a_mined_file(tmp_path):
    project = tmp_path / "t1"
    _t1_project(project)
    palace = tmp_path / "palace"
    _mine(project, palace)
    source = project / "src" / "x.py"
    store = open_store(str(palace), create=False)
    store.add(
        ids=["drawer_t1_decisions_manual"],
        documents=["DECISION: osprey_ledger_totals must stay synchronous."],
        metadatas=[
            {
                "wing": "t1",
                "room": "decisions",
                "source_file": str(source),
                "chunk_index": 0,
                "added_by": "mcp",
                "chunker_strategy": "manual_v1",
            }
        ],
    )

    def manual_ids() -> set[str]:
        return {row["id"] for row in _rows(palace) if row["chunker_strategy"] == "manual_v1"}

    source.write_text(source.read_text() + "# edited\n")
    assert _mine(project, palace)["files_processed"] == 1
    assert manual_ids() == {"drawer_t1_decisions_manual"}
    _mine(project, palace, incremental=False)
    assert manual_ids() == {"drawer_t1_decisions_manual"}
    unchanged = _mine(project, palace)
    assert unchanged["files_processed"] == 0
    assert unchanged["embedder_warmed"] is False


def test_gap6_mempalace_yaml_edits_reroute_unchanged_files_and_rerun_architecture(
    tmp_path, monkeypatch
):
    from mempalace_code import architecture
    from mempalace_code.knowledge_graph import KnowledgeGraph

    project = tmp_path / "t1"
    _t1_project(project)
    palace = tmp_path / "palace"
    kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
    arch_calls: list[dict] = []
    original = architecture.refresh_arch_facts

    def record(inventory, cfg, wing, project_path, graph):
        arch_calls.append(cfg)
        return original(inventory, cfg, wing, project_path, graph)

    monkeypatch.setattr(architecture, "refresh_arch_facts", record)
    _mine(project, palace, kg=kg)
    assert _mine(project, palace, kg=kg)["embedder_warmed"] is False  # true no-op
    calls_before = len(arch_calls)

    config = yaml.safe_load((project / "mempalace.yaml").read_text())
    config["rooms"][0]["name"] = "handbook"
    config["architecture"] = {"patterns": {"service": {"type_names": ["AuditHandler"]}}}
    (project / "mempalace.yaml").write_text(yaml.safe_dump(config))

    stats = _mine(project, palace, kg=kg)

    assert stats["files_processed"] == 1  # only docs/one.md changed room
    rooms = {Path(row["source_file"]).name: row["room"] for row in _rows(palace)}
    assert rooms["one.md"] == "handbook"
    assert "documentation" not in set(rooms.values())
    assert len(arch_calls) == calls_before + 1
    assert _mine(project, palace, kg=kg)["embedder_warmed"] is False


def test_chunker_strategy_bump_rebuilds_rows_from_older_strategies(tmp_path):
    project = tmp_path / "t1"
    _t1_project(project)
    palace = tmp_path / "palace"
    _mine(project, palace)
    store = open_store(str(palace), create=False)
    result = store.get(include=["documents", "metadatas"], limit=100)
    legacy = [{**meta, "chunker_strategy": "regex_structural_v1"} for meta in result["metadatas"]]
    store.upsert(ids=result["ids"], documents=result["documents"], metadatas=legacy)

    stats = _mine(project, palace)

    assert stats["files_processed"] == len(result["ids"])
    assert {row["chunker_strategy"] for row in _rows(palace)} <= chunkers.FILE_CHUNKER_STRATEGIES
    assert _mine(project, palace)["files_processed"] == 0


@pytest.mark.parametrize(
    "legacy_fields",
    [{"original_tokens": 120, "compression_ratio": 0.0}, {"compression_ratio": 4.2}],
)
def test_drawers_compressed_before_1_15_are_refiled_by_an_incremental_mine(tmp_path, legacy_fields):
    project = tmp_path / "t1"
    _t1_project(project)
    palace = tmp_path / "palace"
    _mine(project, palace)
    store = open_store(str(palace), create=False)
    result = store.get(include=["documents", "metadatas"], limit=1)
    drawer_id, verbatim = result["ids"][0], result["documents"][0]
    store.upsert(
        ids=[drawer_id],
        documents=["AAAK|summary"],
        metadatas=[{**result["metadatas"][0], **legacy_fields}],
    )

    stats = _mine(project, palace)

    assert stats["files_processed"] == 1
    row = next(row for row in _rows(palace) if row["id"] == drawer_id)
    assert row["text"] == verbatim
    assert row["original_tokens"] == 0
    assert row["compression_ratio"] == 0.0
    assert _mine(project, palace)["files_processed"] == 0


def test_storage_recognises_every_current_file_chunker_strategy():
    from mempalace_code import storage

    known = set(storage._FILE_MINING_CHUNKER_STRATEGIES)
    assert known >= chunkers.FILE_CHUNKER_STRATEGIES


def test_sig1_interrupt_flushes_then_propagates(tmp_path, monkeypatch, capsys):
    project = tmp_path / "t1"
    _t1_project(project)
    palace = tmp_path / "palace"
    monkeypatch.setattr(orchestrator, "get_batch_size", lambda: 1)
    original = orchestrator._collect_specs_for_file
    calls = {"n": 0}

    def interrupt_on_third(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return original(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "_collect_specs_for_file", interrupt_on_third)

    with pytest.raises(KeyboardInterrupt):
        _mine(project, palace)

    out = capsys.readouterr().out
    assert "drawers filed before interrupt" in out
    assert f"--palace {palace} mine {project}" in out
    filed = _rows(palace)
    assert filed  # the batch flushed before the interrupt stays filed
    assert len(filed) < 4
    assert not (palace / ".mempalace" / "mine_config.json").exists()


def test_sig1_cli_exits_130_on_ctrl_c(tmp_path, monkeypatch, capsys):
    from mempalace_code import cli

    def interrupted(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(orchestrator, "mine", interrupted)
    monkeypatch.setattr(sys, "argv", ["mempalace-code", "mine", str(tmp_path)])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 130
    assert "Ctrl-C" in capsys.readouterr().err


def test_gap1_source_replacement_keeps_manual_and_diary_drawers(tmp_path):
    """convo --full replaces a transcript's drawers without touching cited manual notes."""
    store = open_store(str(tmp_path / "palace"), create=True)
    transcript = str(tmp_path / "chat.jsonl")
    base = {"wing": "chats", "room": "general", "source_file": transcript, "chunk_index": 0}
    store.add(
        ids=["convo-old", "manual-note", "diary-note"],
        documents=["old exchange", "manual decision about the chat", "diary entry"],
        metadatas=[
            {**base, "ingest_mode": "convos", "chunker_strategy": "convo_turn_v1"},
            {**base, "chunker_strategy": "manual_v1"},
            {**base, "chunker_strategy": "diary_v1"},
        ],
    )

    store.replace_source(
        transcript,
        "chats",
        ["convo-new"],
        ["new exchange"],
        [{**base, "ingest_mode": "convos", "chunker_strategy": "convo_turn_v1"}],
    )

    assert set(store.get(where={"source_file": transcript}, limit=10)["ids"]) == {
        "convo-new",
        "manual-note",
        "diary-note",
    }


def test_mine12_upgrade_indexes_small_files_an_older_chunker_skipped(tmp_path):
    """A pre-1.15 sidecar lists small files as tiny; the upgrade mine indexes them once."""
    from mempalace_code.source_io import hash_regular_bytes

    project = tmp_path / "t1"
    _t1_project(project)
    settings = _write(project / "settings.json", POLYGLOT["config/settings.json"])
    palace = tmp_path / "palace"
    _mine(project, palace)
    store = open_store(str(palace), create=False)
    store.delete_by_source_file(str(settings), "t1")
    result = store.get(include=["documents", "metadatas"], limit=100)
    legacy = [{**meta, "chunker_strategy": "treesitter_v1"} for meta in result["metadatas"]]
    store.upsert(ids=result["ids"], documents=result["documents"], metadatas=legacy)
    sidecar = palace / ".mempalace" / "tiny_hashes.json"
    tiny = json.loads(sidecar.read_text())
    tiny["t1"][str(settings)] = hash_regular_bytes(settings, digest_size=16)
    sidecar.write_text(json.dumps(tiny))

    _mine(project, palace)

    assert str(settings) in {row["source_file"] for row in _rows(palace)}
    assert str(settings) not in json.loads(sidecar.read_text())["t1"]


def test_current_rows_without_strategy_and_unchanged_sidecar_stay_a_no_op(tmp_path):
    """Rows with a blank strategy are not churned, and unchanged sidecar hits stay skipped."""
    project = tmp_path / "t1"
    _t1_project(project)
    tiny = _write(project / "tiny.txt", "tiny\n")
    palace = tmp_path / "palace"
    _mine(project, palace)
    store = open_store(str(palace), create=False)
    store.delete_by_source_file(str(tiny), "t1")
    result = store.get(include=["documents", "metadatas"], limit=100)
    blank = [{**meta, "chunker_strategy": ""} for meta in result["metadatas"]]
    store.upsert(ids=result["ids"], documents=result["documents"], metadatas=blank)
    sidecar = palace / ".mempalace" / "tiny_hashes.json"
    from mempalace_code.source_io import hash_regular_bytes

    data = json.loads(sidecar.read_text())
    data["t1"][str(tiny)] = hash_regular_bytes(tiny, digest_size=16)
    sidecar.write_text(json.dumps(data))

    stats = _mine(project, palace)

    assert stats["drawers_filed"] == 0
    assert stats["embedder_warmed"] is False


def test_gap5_long_prose_lines_are_indexed_not_treated_as_minified():
    from mempalace_code.mining.source_text import decode_source

    paragraph = " ".join(f"word{i}" for i in range(1500)).encode()
    assert decode_source(paragraph, "notes.md").skip_reason is None
    assert decode_source(paragraph, "module.py").skip_reason is None
    assert decode_source(paragraph, "data.json").skip_reason == "minified"
    assert decode_source(b"var a=1;", "app.min.js").skip_reason == "minified"


# =============================================================================
# Review round: long-line reads, sidecar upgrade, recovery commands, symbols
# =============================================================================


def test_mine7_read_returns_a_line_longer_than_the_hard_split_whole(tmp_path):
    """A line cut into several drawers is rejoined by read, whitespace runs included."""
    long_line = " ".join(f"token{i}" for i in range(900)) + " END_OF_LONG_LINE"
    spaced = "a" * 2500 + " " * 2500 + "b" * 2500 + " END_OF_SPACED_LINE"
    project = tmp_path / "longline"
    text = f"# Notes\n\nShort intro.\n\n{long_line}\n\n{spaced}\n\nTail paragraph.\n"
    _write(project / "notes.md", text)
    _init_project(project, wing="longline")
    palace = tmp_path / "palace"
    _mine(project, palace)

    rows = [row for row in _rows(palace) if row["line_start"] == row["line_end"] == 5]
    assert len(rows) > 1  # stored as several pieces, each under the hard split
    store = open_store(str(palace), create=False)
    for number, expected in ((5, long_line), (7, spaced)):
        result = read_slice(store, "notes.md", number, number)
        assert result["lines"] == [{"line": number, "text": expected}]
    source_lines = text.split("\n")
    returned = {line["line"]: line["text"] for line in read_slice(store, "notes.md", 1, 9)["lines"]}
    assert all(returned[n] == source_lines[n - 1] for n in returned)
    assert {n for n, line in enumerate(source_lines, 1) if line.strip()} <= set(returned)


def test_mine12_sidecar_only_wing_from_an_older_release_is_rechecked(tmp_path, capsys):
    """No drawers and no routing fingerprint: files an older chunker called tiny get indexed."""
    from mempalace_code.source_io import hash_regular_bytes

    project = tmp_path / "tinyrepo"
    shellrc = _write(project / "shellrc.sh", "export KIWI_USER_NAME=kiwi\nalias ll=ls\n")
    gitconfig = _write(project / "gitconfig.ini", "[user]\nname = kiwi\n")
    _init_project(project, wing="tinyrepo")
    palace = tmp_path / "palace"
    sidecar = palace / ".mempalace" / "tiny_hashes.json"
    _write(
        sidecar,
        json.dumps(
            {
                "tinyrepo": {
                    str(path): hash_regular_bytes(path, digest_size=16)
                    for path in (shellrc, gitconfig)
                }
            }
        ),
    )
    open_store(str(palace), create=True)

    stats = _mine(project, palace)

    assert stats["files_processed"] == 2
    assert {Path(row["source_file"]).name for row in _rows(palace)} == {
        "shellrc.sh",
        "gitconfig.ini",
    }
    assert json.loads(sidecar.read_text())["tinyrepo"] == {}
    capsys.readouterr()
    again = _mine(project, palace)
    assert again["drawers_filed"] == 0
    assert "no changes detected" in capsys.readouterr().out


def test_recovery_commands_repeat_the_callers_wing_and_scan_options(tmp_path, monkeypatch, capsys):
    project = tmp_path / "bigfiles"
    _write(project / "app.py", "def load_customers():\n    return read('customers.json')\n")
    _write(project / "fixtures" / "customers.json", json.dumps(list(range(20000)), indent=2))
    _write(project / "extra" / "keep me.txt", "kept even though ignored\n")
    _write(project / ".gitignore", "extra/\n")
    _init_project(project, wing="bigfiles")
    config = yaml.safe_load((project / "mempalace.yaml").read_text())
    config["max_file_bytes"] = 50_000
    (project / "mempalace.yaml").write_text(yaml.safe_dump(config))
    palace = tmp_path / "palace"
    options = {
        "wing_override": "custom_wing",
        "agent": "ci-bot",
        "respect_gitignore": False,
        "include_ignored": ["extra/keep me.txt"],
    }

    _mine(project, palace, **options)

    out = capsys.readouterr().out
    hint = next(line for line in out.splitlines() if "To index one anyway" in line)
    prefix = " ".join(shlex.quote(token) for token in cli_prefix())
    expected = (
        f"{prefix} --palace {palace} mine {project} --wing custom_wing --agent ci-bot "
        "--no-gitignore --include-ignored 'extra/keep me.txt' "
        "--include-ignored fixtures/customers.json"
    )
    assert expected in hint

    monkeypatch.setattr(orchestrator, "get_batch_size", lambda: 1)
    original = orchestrator._collect_specs_for_file

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(orchestrator, "_collect_specs_for_file", interrupt)
    _write(project / "app.py", "def load_customers():\n    return []\n")
    with pytest.raises(KeyboardInterrupt):
        _mine(project, palace, **options)
    monkeypatch.setattr(orchestrator, "_collect_specs_for_file", original)
    out = capsys.readouterr().out
    rerun = next(line for line in out.splitlines() if "rerun to finish" in line)
    assert rerun.endswith(
        f"{prefix} --palace {palace} mine {project} --wing custom_wing --agent ci-bot "
        "--no-gitignore --include-ignored 'extra/keep me.txt'"
    )


def test_mine15_file_header_declarations_do_not_hide_the_definitions_after_them():
    fsharp = (
        "module Billing.Invoices\n\ntype Invoice = { Id: int; Total: decimal }\n\n"
        "let total (invoice: Invoice) = invoice.Total\nlet zero = 0m\n"
    )
    assert extract_symbol(fsharp, "fsharp") == ("Invoice", "record")
    assert extract_symbol("module Billing.Invoices\n", "fsharp") == ("Billing", "module")
    assert extract_symbol("module Tools\n\nlet helper x = x + 1\n", "fsharp") == (
        "Tools",
        "module",
    )
    assert extract_symbol("module Utils =\n    let helper x = x + 1\n", "fsharp") == (
        "Utils",
        "module",
    )
    rust = "mod parser;\nmod lexer;\n\npub fn run() -> i32 {\n    0\n}\n"
    assert extract_symbol(rust, "rust") == ("run", "function")
    assert extract_symbol("mod parser;\n", "rust") == ("parser", "mod")
    assert extract_symbol("pub mod tests {\n    fn t() {}\n}\n", "rust") == ("tests", "mod")
    lua = "local M = {}\n\nfunction M.render(x)\n  return x\nend\n\nreturn M\n"
    assert extract_symbol(lua, "lua") == ("M.render", "method")
    assert extract_symbol("local M = {}\nM.x = 1\nreturn M\n", "lua") == ("M", "module")


def test_mine15_top_level_code_after_a_definition_is_not_named_after_it(tmp_path):
    """Tree-sitter: a large constant after the last function keeps no borrowed symbol."""
    if chunkers.get_parser("python") is None:
        pytest.skip("tree-sitter python grammar not installed")
    table = "TOOL_SPECS = {\n" + "".join(
        f'    "tool_{i}": {{"description": "Describe tool number {i} in words."}},\n'
        for i in range(120)
    )
    source = (
        "def tool_read(path):\n    return open(path).read()\n\n\n"
        + table
        + "}\n\n\nif __name__ == '__main__':\n    print(tool_read('x'))\n"
    )
    module = _write(tmp_path / "tools.py", source)
    specs = orchestrator._collect_specs_for_file(
        module, tmp_path, None, "w", [{"name": "general"}], "t", mined_files=set()
    )
    named = [s for s in specs if s["metadata"]["symbol_name"] == "tool_read"]
    assert len(named) == 1
    assert named[0]["content"].startswith("def tool_read")
    assert "TOOL_SPECS" not in named[0]["content"]
    assert len(specs) > 2
    _assert_verbatim_coverage(module, specs)


def test_gap5_size_cap_reads_at_most_one_byte_past_the_cap(tmp_path, monkeypatch):
    from mempalace_code.source_io import read_regular_bytes

    big = _write(tmp_path / "dump.sql", "INSERT INTO t VALUES (1);\n" * 4000)
    requested: list = []

    def spy(path, max_bytes=None):
        requested.append(max_bytes)
        return read_regular_bytes(path, max_bytes=max_bytes)

    monkeypatch.setattr(orchestrator, "read_regular_bytes", spy)
    skipped = orchestrator._read_source(big, max_file_bytes=10_000, force_include=False)
    forced = orchestrator._read_source(big, max_file_bytes=10_000, force_include=True)

    assert skipped.skip_reason == "too_large"
    assert forced.skip_reason is None
    assert forced.text == big.read_text()
    assert requested == [10_001, None]


def test_gap5_file_hash_streams_instead_of_loading_the_file(tmp_path):
    import hashlib
    import tracemalloc

    from mempalace_code.source_io import hash_regular_bytes

    payload = os.urandom(1024 * 1024) * 12
    big = _write(tmp_path / "huge.bin", payload)
    tracemalloc.start()
    try:
        digest = hash_regular_bytes(big, digest_size=16)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert digest == hashlib.blake2b(payload, digest_size=16).hexdigest()
    assert peak < 4 * 1024 * 1024


def test_utf16_and_utf32_files_with_a_bom_are_decoded_not_called_binary(tmp_path):
    from mempalace_code.mining.source_text import decode_source

    query = "SELECT name FROM customers WHERE id = 1;\r\nSELECT 2;\r\n"
    for encoding in ("utf-16", "utf-32"):
        decoded = decode_source(query.encode(encoding), "q.sql")
        assert decoded.skip_reason is None
        assert decoded.text == query
        assert decoded.encoding == encoding
    assert decode_source(b"\xff\xfe\x00\xd8\x01\x02", "blob.cs").skip_reason == "binary"

    project = tmp_path / "wide"
    _write(project / "q.sql", query.encode("utf-16"))
    _init_project(project, wing="wide")
    palace = tmp_path / "palace"
    _mine(project, palace)
    store = open_store(str(palace), create=False)
    result = read_slice(store, "q.sql", 1, 2)
    assert [line["text"] for line in result["lines"]] == [
        "SELECT name FROM customers WHERE id = 1;\r",
        "SELECT 2;\r",
    ]
