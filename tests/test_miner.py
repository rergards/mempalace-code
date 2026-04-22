import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import torch
import yaml

from mempalace.miner import (
    _build_csproj_room_map,
    _detect_batch_size,
    _detect_sln_wing,
    add_drawers_batch,
    detect_projects,
    detect_room,
    derive_wing_name,
    mine,
    process_file,
    scan_project,
)
from mempalace.storage import open_store


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scanned_files(project_root: Path, **kwargs):
    files = scan_project(str(project_root), **kwargs)
    return sorted(path.relative_to(project_root).as_posix() for path in files)


def test_project_mining():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        os.makedirs(project_root / "backend")

        write_file(
            project_root / "backend" / "app.py", "def main():\n    print('hello world')\n" * 20
        )
        with open(project_root / "mempalace.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_project",
                    "rooms": [
                        {"name": "backend", "description": "Backend code"},
                        {"name": "general", "description": "General"},
                    ],
                },
                f,
            )

        palace_path = project_root / "palace"
        mine(str(project_root), str(palace_path))

        store = open_store(str(palace_path), create=False)
        assert store.count() > 0
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_respects_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "ignored.py\ngenerated/\n")
        write_file(project_root / "src" / "app.py", "print('hello')\n" * 20)
        write_file(project_root / "ignored.py", "print('ignore me')\n" * 20)
        write_file(project_root / "generated" / "artifact.py", "print('artifact')\n" * 20)

        assert scanned_files(project_root) == ["src/app.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_respects_nested_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "*.log\n")
        write_file(project_root / "subrepo" / ".gitignore", "tasks/\n")
        write_file(project_root / "subrepo" / "src" / "main.py", "print('main')\n" * 20)
        write_file(project_root / "subrepo" / "tasks" / "task.py", "print('task')\n" * 20)
        write_file(project_root / "subrepo" / "debug.log", "debug\n" * 20)

        assert scanned_files(project_root) == ["subrepo/src/main.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_allows_nested_gitignore_override():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "*.csv\n")
        write_file(project_root / "subrepo" / ".gitignore", "!keep.csv\n")
        write_file(project_root / "drop.csv", "a,b,c\n" * 20)
        write_file(project_root / "subrepo" / "keep.csv", "a,b,c\n" * 20)

        assert scanned_files(project_root) == ["subrepo/keep.csv"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_allows_gitignore_negation_when_parent_dir_is_visible():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/*\n!generated/keep.py\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root) == ["generated/keep.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_does_not_reinclude_file_from_ignored_directory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/\n!generated/keep.py\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root) == []
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_disable_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "data/\n")
        write_file(project_root / "data" / "stuff.csv", "a,b,c\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["data/stuff.csv"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_ignored_directory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "docs/\n")
        write_file(project_root / "docs" / "guide.md", "# Guide\n" * 20)

        assert scanned_files(project_root, include_ignored=["docs"]) == ["docs/guide.md"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_specific_ignored_file():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root, include_ignored=["generated/keep.py"]) == [
            "generated/keep.py"
        ]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_exact_file_without_known_extension():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "README\n")
        write_file(project_root / "README", "hello\n" * 20)

        assert scanned_files(project_root, include_ignored=["README"]) == ["README"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_include_override_beats_skip_dirs():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".pytest_cache" / "cache.py", "print('cache')\n" * 20)

        assert scanned_files(
            project_root,
            respect_gitignore=False,
            include_ignored=[".pytest_cache"],
        ) == [".pytest_cache/cache.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_skip_dirs_still_apply_without_override():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".pytest_cache" / "cache.py", "print('cache')\n" * 20)
        write_file(project_root / "main.py", "print('main')\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["main.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_skips_app_level_workspace_json():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / "workspace.json", '{"generated": true}\n' * 20)
        write_file(project_root / "main.py", "print('main')\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["main.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_skips_app_level_kotlin_lsp_dir():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".kotlin-lsp" / "workspace.json", '{"generated": true}\n' * 20)
        write_file(project_root / "src" / "main.kt", "fun main() = Unit\n" * 40)

        assert scanned_files(project_root, respect_gitignore=False) == ["src/main.kt"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_include_override_beats_app_level_excludes():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / "workspace.json", '{"generated": true}\n' * 20)

        assert scanned_files(
            project_root,
            respect_gitignore=False,
            include_ignored=["workspace.json"],
        ) == ["workspace.json"]
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# Integration tests — smart chunking through process_file() and mine()
# =============================================================================

MULTI_FUNC_PY = """\
def alpha():
    \"\"\"First function.\"\"\"
    return 1


def beta():
    \"\"\"Second function.\"\"\"
    return 2


def gamma():
    \"\"\"Third function.\"\"\"
    return 3
"""

TS_WITH_IMPORTS_AND_EXPORTS = """\
import fs from 'fs';
import path from 'path';

export function readFile(p: string): string {
    return fs.readFileSync(p, 'utf8');
}

export const joinPaths = (...parts: string[]) => path.join(...parts);
"""


def _make_palace_config(project_root: Path):
    with open(project_root / "mempalace.yaml", "w") as f:
        yaml.dump(
            {
                "wing": "test_wing",
                "rooms": [
                    {"name": "backend", "description": "Backend code"},
                    {"name": "general", "description": "General"},
                ],
            },
            f,
        )


def test_process_file_python_chunk_index_ordering():
    """process_file() on a multi-function Python file produces sequential chunk_index values."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        drawers = process_file(
            filepath=py_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )

        assert drawers >= 1

        result = palace.get(
            where={"source_file": str(py_file)},
            include=["metadatas"],
            limit=100,
        )
        metas = result["metadatas"]
        chunk_indices = sorted(m["chunk_index"] for m in metas)
        # chunk_index values must be sequential starting at 0
        assert chunk_indices == list(range(len(chunk_indices)))
    finally:
        shutil.rmtree(tmpdir)


def test_process_file_python_preserves_function_boundaries():
    """process_file() stores Python function bodies intact — no function split across chunks."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        process_file(
            filepath=py_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )

        result = palace.get(
            where={"source_file": str(py_file)},
            include=["documents", "metadatas"],
            limit=100,
        )
        docs = result["documents"]
        all_text = "\n".join(docs)

        # All three functions must be present in stored drawers
        assert "def alpha" in all_text
        assert "def beta" in all_text
        assert "def gamma" in all_text

        # No stored drawer should contain parts of two different top-level functions
        # unless they were small enough to be merged (combined size < TARGET_MAX)
        from mempalace.miner import TARGET_MAX

        for doc in docs:
            has_alpha = "def alpha" in doc
            has_beta = "def beta" in doc
            has_gamma = "def gamma" in doc
            if sum([has_alpha, has_beta, has_gamma]) > 1:
                # Only allowed if the merged chunk respects TARGET_MAX
                assert len(doc) <= TARGET_MAX
    finally:
        shutil.rmtree(tmpdir)


def test_mine_end_to_end_chunk_metadata():
    """mine() stores drawers with correct source_file and sequential chunk_index for Python."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "src" / "logic.py"
        write_file(py_file, MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)

        store = open_store(palace_path, create=False)
        result = store.get(
            where={"source_file": str(py_file)},
            include=["metadatas"],
            limit=100,
        )
        metas = result["metadatas"]

        assert len(metas) >= 1
        # chunk_index values must be a prefix of 0,1,2,...
        chunk_indices = sorted(m["chunk_index"] for m in metas)
        assert chunk_indices == list(range(len(chunk_indices)))
        # source_file must be consistent
        for m in metas:
            assert m["source_file"] == str(py_file)
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# Language metadata tests
# =============================================================================


def test_process_file_stores_language_metadata():
    """process_file() stores the detected language on every drawer."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        process_file(
            filepath=py_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )

        result = palace.get(
            where={"source_file": str(py_file)},
            include=["metadatas"],
            limit=100,
        )
        metas = result["metadatas"]
        assert len(metas) >= 1
        for m in metas:
            assert m["language"] == "python"
    finally:
        shutil.rmtree(tmpdir)


def test_mine_end_to_end_language_metadata():
    """mine() roundtrip: Python file drawers have language='python' in metadata."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "src" / "logic.py"
        write_file(py_file, MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)

        store = open_store(palace_path, create=False)
        result = store.get(
            where={"source_file": str(py_file)},
            include=["metadatas"],
            limit=100,
        )
        metas = result["metadatas"]
        assert len(metas) >= 1
        for m in metas:
            assert m["language"] == "python"
    finally:
        shutil.rmtree(tmpdir)


def test_language_filter_query():
    """Drawers can be retrieved with a where={"language": "python"} filter."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        process_file(
            filepath=py_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )

        # Filter by language should return the mined drawers
        result = palace.get(
            where={"language": "python"},
            include=["metadatas"],
            limit=100,
        )
        assert len(result["ids"]) >= 1
        for m in result["metadatas"]:
            assert m["language"] == "python"
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# Symbol metadata tests
# =============================================================================

# Functions padded to exceed TARGET_MAX/2 (>1250 chars each) so combined they exceed
# TARGET_MAX (2500 chars) and are NOT merged by adaptive_merge_split.
_PADDING = "    # " + "x" * 60 + "\n"

PY_FUNC_AND_CLASS = (
    "def foo():\n"
    '    """A foo function — padded to prevent merging."""\n'
    + _PADDING
    * 22
    + "    return 42\n\n\n"
    "class Bar:\n"
    '    """A Bar class — padded to prevent merging."""\n' + _PADDING * 22 + "\n"
)


def test_process_file_stores_symbol_metadata():
    """process_file() stores symbol_name and symbol_type on every drawer."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, PY_FUNC_AND_CLASS)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        process_file(
            filepath=py_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )

        result = palace.get(
            where={"source_file": str(py_file)},
            include=["metadatas"],
            limit=100,
        )
        metas = result["metadatas"]
        assert len(metas) >= 1
        # Every drawer must have symbol_name and symbol_type keys
        for m in metas:
            assert "symbol_name" in m
            assert "symbol_type" in m
    finally:
        shutil.rmtree(tmpdir)


def test_process_file_python_symbol_roundtrip():
    """Mine a Python file with def foo() and class Bar; verify symbol metadata on retrieved drawers."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, PY_FUNC_AND_CLASS)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        process_file(
            filepath=py_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )

        result = palace.get(
            where={"source_file": str(py_file)},
            include=["documents", "metadatas"],
            limit=100,
        )
        docs = result["documents"]
        metas = result["metadatas"]

        # Build a mapping from chunk content → metadata
        by_doc = {doc: meta for doc, meta in zip(docs, metas)}

        # Find which drawer contains "def foo" and which contains "class Bar"
        foo_meta = next((m for doc, m in by_doc.items() if "def foo" in doc), None)
        bar_meta = next((m for doc, m in by_doc.items() if "class Bar" in doc), None)

        assert foo_meta is not None, "No drawer found containing 'def foo'"
        assert bar_meta is not None, "No drawer found containing 'class Bar'"

        assert foo_meta["symbol_name"] == "foo"
        assert foo_meta["symbol_type"] == "function"

        assert bar_meta["symbol_name"] == "Bar"
        assert bar_meta["symbol_type"] == "class"
    finally:
        shutil.rmtree(tmpdir)


def test_symbol_name_filter_query():
    """Drawers can be retrieved with a where={"symbol_name": "foo"} filter."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, PY_FUNC_AND_CLASS)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        process_file(
            filepath=py_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )

        result = palace.get(
            where={"symbol_name": "foo"},
            include=["documents", "metadatas"],
            limit=10,
        )
        assert len(result["ids"]) >= 1
        for doc in result["documents"]:
            assert "def foo" in doc
    finally:
        shutil.rmtree(tmpdir)


def test_mine_batch_embedding_parity():
    """mine() batch path produces correct drawer count and full metadata for multi-file projects."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        # Three files — ensures specs accumulate across file boundaries before flushing
        for idx in range(3):
            write_file(project_root / f"module{idx}.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)

        store = open_store(palace_path, create=False)
        assert store.count() > 0

        result = store.get(include=["metadatas"], limit=1000)
        for m in result["metadatas"]:
            assert "wing" in m
            assert "room" in m
            assert "source_file" in m
            assert "chunk_index" in m
            assert "language" in m
            assert "symbol_name" in m
            assert "symbol_type" in m
            assert m["language"] == "python"
    finally:
        shutil.rmtree(tmpdir)


def test_mine_no_duplicate_drawers_on_remine():
    """Re-running mine() on an already-mined project does not create duplicate drawers (AC-5)."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "code.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)
        count_first = open_store(palace_path, create=False).count()

        mine(str(project_root), palace_path)
        count_second = open_store(palace_path, create=False).count()

        assert count_second == count_first
    finally:
        shutil.rmtree(tmpdir)


def test_symbol_type_filter_query():
    """Drawers can be retrieved with a where={"symbol_type": "class"} filter."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, PY_FUNC_AND_CLASS)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        process_file(
            filepath=py_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )

        result = palace.get(
            where={"symbol_type": "class"},
            include=["documents", "metadatas"],
            limit=10,
        )
        assert len(result["ids"]) >= 1
        for doc in result["documents"]:
            assert "class Bar" in doc
    finally:
        shutil.rmtree(tmpdir)


def test_status_multi_wing(capsys):
    """status() shows all wings in a multi-wing palace (regression for limit=10000 bug)."""
    from mempalace.miner import status

    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = os.path.join(tmpdir, "palace")
        store = open_store(palace_path, create=True)
        for wing in ("alpha_wing", "beta_wing", "gamma_wing"):
            store.add(
                ids=[f"{wing}_d1", f"{wing}_d2"],
                documents=[f"{wing} document one", f"{wing} document two"],
                metadatas=[
                    {"wing": wing, "room": "general"},
                    {"wing": wing, "room": "notes"},
                ],
            )

        status(palace_path)
        captured = capsys.readouterr().out

        assert "alpha_wing" in captured
        assert "beta_wing" in captured
        assert "gamma_wing" in captured
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# _detect_batch_size() tests — monkeypatch device/memory detection
# =============================================================================


def test_detect_batch_size_mps():
    with patch.object(torch.backends.mps, "is_available", return_value=True):
        assert _detect_batch_size() == 256


def test_detect_batch_size_cuda():
    with patch.object(torch.backends.mps, "is_available", return_value=False):
        with patch.object(torch.cuda, "is_available", return_value=True):
            assert _detect_batch_size() == 256


def test_detect_batch_size_cpu_high_ram():
    """CPU with >4 GB RAM → batch size 128."""
    # 8 GB = 2097152 pages * 4096 bytes/page
    with patch.object(torch.backends.mps, "is_available", return_value=False):
        with patch.object(torch.cuda, "is_available", return_value=False):
            sysconf_vals = {"SC_PHYS_PAGES": 2097152, "SC_PAGE_SIZE": 4096}
            with patch("os.sysconf", side_effect=lambda name: sysconf_vals[name]):
                assert _detect_batch_size() == 128


def test_detect_batch_size_cpu_low_ram():
    """CPU with <=4 GB RAM → batch size 64."""
    # 2 GB = 524288 pages * 4096 bytes/page
    with patch.object(torch.backends.mps, "is_available", return_value=False):
        with patch.object(torch.cuda, "is_available", return_value=False):
            sysconf_vals = {"SC_PHYS_PAGES": 524288, "SC_PAGE_SIZE": 4096}
            with patch("os.sysconf", side_effect=lambda name: sysconf_vals[name]):
                assert _detect_batch_size() == 64


# =============================================================================
# mine() integration tests for bulk prefetch, warmup, and optimize
# =============================================================================


def test_mine_calls_warmup_once():
    """mine() calls collection.warmup() exactly once before batch processing."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "code.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)
        palace_path = str(project_root / "palace")

        with patch("mempalace.miner.get_collection") as mock_get_collection:
            mock_store = _make_mock_store()
            mock_get_collection.return_value = mock_store
            mine(str(project_root), palace_path)

        mock_store.warmup.assert_called_once()
    finally:
        shutil.rmtree(tmpdir)


def test_mine_calls_optimize_once():
    """mine() calls collection.optimize() exactly once after all batches flush."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "code.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)
        palace_path = str(project_root / "palace")

        with patch("mempalace.miner.get_collection") as mock_get_collection:
            mock_store = _make_mock_store()
            mock_get_collection.return_value = mock_store
            mine(str(project_root), palace_path)

        # Either safe_optimize (LanceDB) or optimize (legacy) should be called
        assert mock_store.safe_optimize.called or mock_store.optimize.called
    finally:
        shutil.rmtree(tmpdir)


def test_mine_get_source_file_hashes_called_once():
    """mine() calls get_source_file_hashes() once at startup (not per file)."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        # Three files — ensures the bulk prefetch is used across multiple files
        for i in range(3):
            write_file(project_root / f"module{i}.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)
        palace_path = str(project_root / "palace")

        with patch("mempalace.miner.get_collection") as mock_get_collection:
            mock_store = _make_mock_store()
            mock_get_collection.return_value = mock_store
            mine(str(project_root), palace_path)

        mock_store.get_source_file_hashes.assert_called_once()
    finally:
        shutil.rmtree(tmpdir)


def test_mine_bulk_prefetch_skips_already_mined_files():
    """Re-running mine() via the bulk prefetch path produces zero new drawers."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "code.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)
        palace_path = str(project_root / "palace")

        mine(str(project_root), palace_path)
        count_first = open_store(palace_path, create=False).count()

        mine(str(project_root), palace_path)
        count_second = open_store(palace_path, create=False).count()

        assert count_second == count_first
    finally:
        shutil.rmtree(tmpdir)


def _make_mock_store():
    """Build a MagicMock that behaves like a DrawerStore for mine() tests."""
    from unittest.mock import MagicMock

    mock_store = MagicMock()
    mock_store.get_source_files.return_value = set()
    mock_store.get_source_file_hashes.return_value = {}
    mock_store.add.return_value = None
    return mock_store


# =============================================================================
# Incremental mining tests (AC-1 through AC-4)
# =============================================================================


def test_incremental_skips_unchanged():
    """AC-1: Second incremental mine touches 0 files; drawer count is unchanged."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "code.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)
        count_first = open_store(palace_path, create=False).count()
        assert count_first > 0

        mine(str(project_root), palace_path)
        count_second = open_store(palace_path, create=False).count()

        assert count_second == count_first
    finally:
        shutil.rmtree(tmpdir)


def test_incremental_detects_content_change():
    """AC-2: Modified file is re-chunked; old drawers are replaced with updated source_hash."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)

        store = open_store(palace_path, create=False)
        result_before = store.get(
            where={"source_file": str(py_file)}, include=["metadatas"], limit=100
        )
        old_hash = result_before["metadatas"][0]["source_hash"]
        assert old_hash != ""

        # Modify the file
        write_file(py_file, MULTI_FUNC_PY + "\ndef delta():\n    return 99\n" * 10)

        mine(str(project_root), palace_path)

        store2 = open_store(palace_path, create=False)
        result_after = store2.get(
            where={"source_file": str(py_file)}, include=["metadatas"], limit=100
        )
        new_hash = result_after["metadatas"][0]["source_hash"]

        # Old drawers gone, replaced by new ones
        assert new_hash != old_hash
        assert len(result_after["ids"]) > 0
        # Total drawer count should reflect only the new drawers for this file
        # (not stale + new combined)
        total = store2.count()
        assert total == len(result_after["ids"])
    finally:
        shutil.rmtree(tmpdir)


def test_incremental_detects_deletion():
    """AC-3: Deleted file's drawers are swept; other drawers are untouched."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        keeper_file = project_root / "keeper.py"
        write_file(py_file, MULTI_FUNC_PY)
        write_file(keeper_file, MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)

        store = open_store(palace_path, create=False)
        keeper_drawers_before = len(
            store.get(where={"source_file": str(keeper_file)}, include=["metadatas"], limit=100)[
                "ids"
            ]
        )
        assert keeper_drawers_before > 0

        # Delete one file
        py_file.unlink()

        mine(str(project_root), palace_path)

        store2 = open_store(palace_path, create=False)
        # Deleted file's drawers must be gone
        gone = store2.get(where={"source_file": str(py_file)}, include=["metadatas"], limit=100)
        assert len(gone["ids"]) == 0

        # Keeper file's drawers must remain
        keeper_drawers_after = len(
            store2.get(where={"source_file": str(keeper_file)}, include=["metadatas"], limit=100)[
                "ids"
            ]
        )
        assert keeper_drawers_after == keeper_drawers_before
    finally:
        shutil.rmtree(tmpdir)


def test_incremental_full_flag_forces_rebuild():
    """AC-4: incremental=False re-chunks every file even if content is unchanged."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "code.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)
        count_first = open_store(palace_path, create=False).count()

        # Full rebuild: same file, no changes
        mine(str(project_root), palace_path, incremental=False)
        count_second = open_store(palace_path, create=False).count()

        # Drawer count must stay the same (delete-then-re-add → same content)
        assert count_second == count_first
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# Provenance tests (AC-6, AC-7)
# =============================================================================


def test_provenance_fields_set_on_mine():
    """AC-6: mine() stores extractor_version and chunker_strategy on every drawer."""
    import sys

    from mempalace.version import __version__

    # When tree-sitter-python is installed (Python 3.10+), Python files use the AST path.
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_python  # noqa: F401

        ast_active = sys.version_info >= (3, 10)
    except ImportError:
        ast_active = False
    expected_strategy = "treesitter_v1" if ast_active else "regex_structural_v1"

    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "code.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)

        store = open_store(palace_path, create=False)
        result = store.get(include=["metadatas"], limit=100)
        assert len(result["metadatas"]) > 0
        for m in result["metadatas"]:
            assert m["extractor_version"] == __version__
            assert m["chunker_strategy"] == expected_strategy
    finally:
        shutil.rmtree(tmpdir)


def test_provenance_fields_set_on_convo_mine():
    """AC-7: mine_convos() stores extractor_version and chunker_strategy on every drawer."""
    import os
    from mempalace.convo_miner import mine_convos
    from mempalace.version import __version__

    tmpdir = tempfile.mkdtemp()
    try:
        convo_dir = tmpdir
        with open(os.path.join(convo_dir, "chat.txt"), "w") as f:
            f.write(
                "> What is memory?\nMemory is persistence.\n\n"
                "> Why does it matter?\nIt enables continuity.\n\n"
                "> How do we build it?\nWith structured storage.\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        mine_convos(convo_dir, palace_path, wing="test_convos")

        store = open_store(palace_path, create=False)
        result = store.get(include=["metadatas"], limit=100)
        assert len(result["metadatas"]) > 0
        for m in result["metadatas"]:
            assert m["extractor_version"] == __version__
            assert m["chunker_strategy"] == "convo_turn_v1"
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# add_drawers_batch idempotency (MINE-BATCH-EMBED-DEDUP-UPSERT)
# =============================================================================


def test_add_drawers_batch_is_idempotent():
    """add_drawers_batch() called twice with the same specs must not increase store count."""
    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = os.path.join(tmpdir, "palace")
        store = open_store(palace_path, create=True)

        specs = [
            {
                "id": "drawer_test_general_abc123",
                "content": "Some drawer content",
                "metadata": {
                    "wing": "test",
                    "room": "general",
                    "source_file": "/fake/file.py",
                    "added_by": "test",
                    "filed_at": "2026-01-01T00:00:00",
                },
            }
        ]

        add_drawers_batch(store, specs)
        count_after_first = store.count()

        add_drawers_batch(store, specs)
        count_after_second = store.count()

        assert count_after_second == count_after_first, (
            f"Expected count to stay at {count_after_first} after second upsert, "
            f"got {count_after_second} (duplicate appended)"
        )
    finally:
        shutil.rmtree(tmpdir)


def test_add_drawers_batch_updates_content():
    """add_drawers_batch() re-upserted with changed content must overwrite the stored text."""
    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = os.path.join(tmpdir, "palace")
        store = open_store(palace_path, create=True)

        drawer_id = "drawer_test_general_abc123"
        metadata = {
            "wing": "test",
            "room": "general",
            "source_file": "/fake/file.py",
            "added_by": "test",
            "filed_at": "2026-01-01T00:00:00",
        }

        add_drawers_batch(
            store, [{"id": drawer_id, "content": "content version 1", "metadata": metadata}]
        )
        add_drawers_batch(
            store, [{"id": drawer_id, "content": "content version 2", "metadata": metadata}]
        )

        result = store.get(ids=[drawer_id], include=["documents"])
        assert result.get("documents"), f"store.get returned no documents for id {drawer_id!r}"
        assert result["documents"][0] == "content version 2", (
            f"Expected 'content version 2' after re-upsert, got {result['documents'][0]!r}"
        )
    finally:
        shutil.rmtree(tmpdir)


def _skip_if_no_ts_ast():
    """Skip test if tree-sitter TypeScript grammar is not active."""
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_typescript  # noqa: F401
    except ImportError:
        pytest.skip("tree-sitter-typescript not installed")


MULTI_FUNC_TS = """\
import { EventEmitter } from 'events';

export function processEvent(event: string): void {
    const emitter = new EventEmitter();
    emitter.emit(event);
    console.log("processed", event);
}

export class EventProcessor {
    private emitter: EventEmitter;
    constructor() { this.emitter = new EventEmitter(); }
    process(event: string): void {
        this.emitter.emit(event);
    }
}

export interface ProcessorOptions {
    timeout: number;
    retries: number;
}
"""


def test_mine_typescript_chunker_strategy():
    """AC-1: process_file() on a .ts file stores chunker_strategy='treesitter_v1'.

    Skipped when tree-sitter-typescript is not installed.
    """
    _skip_if_no_ts_ast()

    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        ts_file = project_root / "events.ts"
        write_file(ts_file, MULTI_FUNC_TS)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        drawers = process_file(
            filepath=ts_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )
        assert drawers >= 1

        result = palace.get(
            where={"source_file": str(ts_file)},
            include=["metadatas"],
            limit=100,
        )
        for meta in result["metadatas"]:
            assert meta.get("chunker_strategy") == "treesitter_v1", (
                f"Expected treesitter_v1, got {meta.get('chunker_strategy')!r}"
            )
    finally:
        shutil.rmtree(tmpdir)


def test_process_file_python_treesitter_chunker_strategy():
    """AC-4: process_file() stores chunker_strategy='treesitter_v1' when AST path is active.

    Skipped when tree-sitter-python is not installed or Python < 3.10.
    """
    import sys

    if sys.version_info < (3, 10):
        pytest.skip("tree-sitter-python requires Python 3.10+")
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_python  # noqa: F401
    except ImportError:
        pytest.skip("tree-sitter-python not installed")

    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        drawers = process_file(
            filepath=py_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )
        assert drawers >= 1

        result = palace.get(
            where={"source_file": str(py_file)},
            include=["metadatas"],
            limit=100,
        )
        for meta in result["metadatas"]:
            assert meta.get("chunker_strategy") == "treesitter_v1", (
                f"Expected treesitter_v1, got {meta.get('chunker_strategy')!r}"
            )
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# DevOps / infrastructure file support (MINE-DEVOPS-INFRA)
# =============================================================================


def test_mine_optimize_disabled_via_env(monkeypatch):
    """AC-4: mine() with MEMPALACE_OPTIMIZE_AFTER_MINE=0 skips safe_optimize and optimize."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "code.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)
        palace_path = str(project_root / "palace")

        monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")

        with patch("mempalace.miner.get_collection") as mock_get_collection:
            mock_store = _make_mock_store()
            mock_get_collection.return_value = mock_store
            mine(str(project_root), palace_path)

        mock_store.safe_optimize.assert_not_called()
        mock_store.optimize.assert_not_called()
    finally:
        shutil.rmtree(tmpdir)


def test_process_file_dry_run_matches_chunk_count():
    """process_file(dry_run=True) returns the same chunk count as dry_run=False."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        py_file = project_root / "code.py"
        write_file(py_file, MULTI_FUNC_PY)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        count_real = process_file(
            filepath=py_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=False,
        )

        count_dry = process_file(
            filepath=py_file,
            project_path=project_root,
            collection=None,
            wing="test_wing",
            rooms=[{"name": "backend"}, {"name": "general"}],
            agent="test",
            dry_run=True,
        )

        assert count_dry == count_real
    finally:
        shutil.rmtree(tmpdir)


def test_mine_backup_before_optimize_env(monkeypatch):
    """AC-5: mine() with MEMPALACE_BACKUP_BEFORE_OPTIMIZE=1 calls safe_optimize(backup_first=True)."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "code.py", MULTI_FUNC_PY)
        _make_palace_config(project_root)
        palace_path = str(project_root / "palace")

        monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")
        monkeypatch.setenv("MEMPALACE_BACKUP_BEFORE_OPTIMIZE", "1")

        with patch("mempalace.miner.get_collection") as mock_get_collection:
            mock_store = _make_mock_store()
            mock_get_collection.return_value = mock_store
            mine(str(project_root), palace_path)

        mock_store.safe_optimize.assert_called_once()
        call_kwargs = mock_store.safe_optimize.call_args
        # backup_first must be True — check positional or keyword arg
        args, kwargs = call_kwargs
        backup_first_val = kwargs.get("backup_first", args[1] if len(args) > 1 else None)
        assert backup_first_val is True, f"Expected backup_first=True, got {backup_first_val!r}"
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_includes_terraform_files():
    """AC-1: .tf, .tfvars, and .hcl files are returned by scan_project."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "main.tf", 'resource "aws_instance" "web" {}\n')
        write_file(project_root / "terraform.tfvars", 'region = "us-east-1"\n')
        write_file(project_root / "config.hcl", 'variable "env" {}\n')

        files = scanned_files(project_root)
        assert "main.tf" in files
        assert "terraform.tfvars" in files
        assert "config.hcl" in files
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_includes_dockerfile():
    """AC-2: extensionless Dockerfile is returned by scan_project."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "Dockerfile", "FROM ubuntu:22.04\nRUN apt-get update\n")

        files = scanned_files(project_root)
        assert "Dockerfile" in files
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_includes_makefile():
    """AC-3: extensionless Makefile and GNUmakefile are returned by scan_project."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "Makefile", "build:\n\tgo build ./...\n")
        write_file(project_root / "GNUmakefile", "all:\n\techo done\n")

        files = scanned_files(project_root)
        assert "Makefile" in files
        assert "GNUmakefile" in files
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_skips_terraform_dir():
    """AC-6: .terraform/ directory is entirely skipped by scan_project."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "main.tf", 'resource "aws_instance" "web" {}\n')
        write_file(
            project_root / ".terraform" / "providers" / "registry.terraform.io" / "lock.hcl",
            "# provider lock file\n",
        )

        files = scanned_files(project_root)
        assert "main.tf" in files
        # Nothing inside .terraform/ should appear
        terraform_files = [f for f in files if f.startswith(".terraform/")]
        assert terraform_files == [], f"Expected no .terraform/ files, got: {terraform_files}"
    finally:
        shutil.rmtree(tmpdir)


def test_process_file_csharp_roundtrip():
    """process_file() on a .cs file stores language='csharp' and correct symbol metadata."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        cs_file = project_root / "UserService.cs"
        cs_content = (
            "using System;\n\n"
            "namespace MyApp {\n\n"
            "    /// <summary>Manages user operations.</summary>\n"
            "    public class UserService {\n"
            "        private readonly ILogger _logger;\n\n"
            "        public UserService(ILogger logger) {\n"
            "            _logger = logger;\n"
            "        }\n\n"
            "        public void Process(string input) {\n"
            "            _logger.Log(input);\n"
            "            Console.WriteLine(input);\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        write_file(cs_file, cs_content)
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        count = process_file(
            filepath=cs_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[
                {"name": "backend", "description": "Backend code"},
                {"name": "general", "description": "General"},
            ],
            agent="test",
            dry_run=False,
        )
        assert count > 0, "Expected at least one drawer from .cs file"

        result = palace.get(where={"source_file": str(cs_file)}, include=["metadatas"])
        metadatas = result.get("metadatas", [])
        assert len(metadatas) > 0

        # Every drawer must have language='csharp'
        for meta in metadatas:
            assert meta["language"] == "csharp", (
                f"Expected language='csharp', got {meta['language']!r}"
            )

        # At least one drawer must have symbol_type='class' and symbol_name='UserService'
        class_drawers = [
            m
            for m in metadatas
            if m.get("symbol_type") == "class" and m.get("symbol_name") == "UserService"
        ]
        assert class_drawers, (
            f"Expected a drawer with symbol_type='class' and symbol_name='UserService'. "
            f"Got symbol types: {[m.get('symbol_type') for m in metadatas]}"
        )
    finally:
        shutil.rmtree(tmpdir)


def test_mine_default_calls_safe_optimize_backup_first():
    """AC-9: mine() with default MempalaceConfig() calls safe_optimize(backup_first=True)."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "hello.py", "# placeholder\ndef foo():\n    pass\n")
        _make_palace_config(project_root)

        palace_path = os.path.join(tmpdir, "palace")

        with patch("mempalace.miner.get_collection") as mock_get_collection:
            from unittest.mock import MagicMock

            mock_store = MagicMock()
            mock_store.add.return_value = None
            # Return True from safe_optimize so miner doesn't fall back
            mock_store.safe_optimize.return_value = True
            mock_get_collection.return_value = mock_store
            # No env overrides — default config has backup_before_optimize=True
            mine(str(project_root), palace_path)

        mock_store.safe_optimize.assert_called_once()
        call_args, call_kwargs = mock_store.safe_optimize.call_args
        backup_first_val = call_kwargs.get(
            "backup_first", call_args[1] if len(call_args) > 1 else None
        )
        assert backup_first_val is True, f"Expected backup_first=True, got {backup_first_val!r}"
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# .NET language — process_file() roundtrip
# =============================================================================


def test_process_file_fsharp_roundtrip():
    """process_file() on a .fs file stores a drawer with language='fsharp'."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        fs_code = (
            "module Geometry\n\n"
            "let area radius =\n"
            "    System.Math.PI * radius * radius\n"
            "// padding to exceed MIN_CHUNK threshold for adaptive merge split\n"
        )
        write_file(project_root / "geometry.fs", fs_code)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)

        store = open_store(palace_path, create=False)
        result = store.get(include=["metadatas"], limit=100)
        languages = {m.get("language") for m in result.get("metadatas", []) if m.get("language")}
        assert "fsharp" in languages, f"Expected 'fsharp' in languages, got {languages!r}"
    finally:
        shutil.rmtree(tmpdir)


def test_process_file_vbnet_roundtrip():
    """process_file() on a .vb file stores a drawer with language='vbnet'."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        vb_code = (
            "Public Class Calculator\n"
            "    ' Provides basic arithmetic operations for integer values.\n"
            "    Public Function Add(a As Integer, b As Integer) As Integer\n"
            "        ' Returns the sum of two integer arguments passed to the method.\n"
            "        Return a + b\n"
            "    End Function\n"
            "End Class\n"
        )
        write_file(project_root / "calculator.vb", vb_code)
        _make_palace_config(project_root)

        palace_path = str(project_root / "palace")
        mine(str(project_root), palace_path)

        store = open_store(palace_path, create=False)
        result = store.get(include=["metadatas"], limit=100)
        languages = {m.get("language") for m in result.get("metadatas", []) if m.get("language")}
        assert "vbnet" in languages, f"Expected 'vbnet' in languages, got {languages!r}"
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# SKIP_DIRS — .vs / bin / obj are skipped
# =============================================================================


def test_skip_dirs_dotnet():
    """scan_project() skips .vs/, bin/, and obj/ directories for .NET projects."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        # .csproj at root triggers _is_dotnet_project() so bin/ is skipped
        write_file(project_root / "MyApp.csproj", '<Project Sdk="Microsoft.NET.Sdk"/>\n' * 5)
        write_file(project_root / "src" / "App.cs", "public class App {}\n" * 20)
        write_file(project_root / ".vs" / "settings.json", '{"version": 1}\n' * 20)
        write_file(project_root / "bin" / "Debug" / "App.dll", "binary\n" * 20)
        write_file(project_root / "obj" / "App.csproj.nuget.g.targets", "<Target/>\n" * 20)

        result = scanned_files(project_root, respect_gitignore=False)
        # Only the source file should be found; none of the skip-dir files
        assert "src/App.cs" in result
        assert not any(p.startswith(".vs/") for p in result), ".vs/ should be skipped"
        assert not any(p.startswith("bin/") for p in result), "bin/ should be skipped for .NET"
        assert not any(p.startswith("obj/") for p in result), "obj/ should be skipped"
    finally:
        shutil.rmtree(tmpdir)


def test_bin_dir_not_skipped_non_dotnet():
    """scan_project() does NOT skip bin/ for non-.NET projects (AC-1)."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        # A shell script in bin/ — common in Ruby/Go/Python projects
        write_file(project_root / "bin" / "run.sh", "#!/bin/bash\necho hello\n" * 20)
        # obj/ must still be globally skipped even without .NET markers
        write_file(project_root / "obj" / "cache.py", "x = 1\n" * 20)

        result = scanned_files(project_root, respect_gitignore=False)
        assert "bin/run.sh" in result, "bin/run.sh should be included for non-.NET projects"
        assert not any(p.startswith("obj/") for p in result), (
            "obj/ should still be globally skipped"
        )
    finally:
        shutil.rmtree(tmpdir)


def test_bin_dir_skipped_when_sln_at_root():
    """scan_project() skips bin/ when a .sln file is present at root (AC-3)."""
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / "Solution.sln", "\nMicrosoft Visual Studio Solution File\n" * 5)
        write_file(project_root / "src" / "App.cs", "public class App {}\n" * 20)
        # Use a readable extension (.sh) so the assertion is meaningful:
        # if bin/ were traversed, runner.sh would appear in results.
        write_file(project_root / "bin" / "Release" / "runner.sh", "#!/bin/bash\n" * 20)

        result = scanned_files(project_root, respect_gitignore=False)
        assert "src/App.cs" in result
        assert not any(p.startswith("bin/") for p in result), (
            "bin/ should be skipped when .sln present"
        )
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# XAML language — process_file() roundtrip
# =============================================================================

_XAML_ROUNDTRIP = """\
<Window x:Class="MyApp.MainWindow"
        xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        xmlns:d="http://schemas.microsoft.com/expression/blend/2008"
        xmlns:local="clr-namespace:MyApp.ViewModels"
        d:DataContext="{d:DesignInstance Type=local:MainViewModel}">
    <Grid>
        <TextBox x:Name="txtUsername" Style="{StaticResource InputStyle}" />
        <Button Content="Save" Command="{Binding SaveCommand}"
                Background="{DynamicResource ThemeBrush}" />
    </Grid>
</Window>
"""


def test_process_file_xaml_roundtrip():
    """process_file() on a .xaml file stores drawers with language='xaml' and
    symbol_name='MainWindow' (from x:Class), and mine() emits KG triples for
    the code-behind link when an adjacent .xaml.cs file exists.
    """
    import yaml
    from mempalace.knowledge_graph import KnowledgeGraph

    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        xaml_file = project_root / "MainWindow.xaml"
        write_file(xaml_file, _XAML_ROUNDTRIP)
        # Create adjacent code-behind so has_code_behind triple is emitted
        write_file(project_root / "MainWindow.xaml.cs", "// partial class code-behind\n")
        _make_palace_config(project_root)

        palace_path = project_root / "palace"
        palace = open_store(str(palace_path), create=True)

        count = process_file(
            filepath=xaml_file,
            project_path=project_root,
            collection=palace,
            wing="test_wing",
            rooms=[{"name": "general", "description": "General"}],
            agent="test",
            dry_run=False,
        )
        assert count > 0, "Expected at least one drawer from .xaml file"

        result = palace.get(where={"source_file": str(xaml_file)}, include=["metadatas"])
        metadatas = result.get("metadatas", [])
        assert len(metadatas) > 0

        # All drawers must have language='xaml'
        for meta in metadatas:
            assert meta["language"] == "xaml", f"Expected language='xaml', got {meta['language']!r}"

        # The first chunk (root element) must have symbol_name='MainWindow', symbol_type='view'
        view_drawers = [m for m in metadatas if m.get("symbol_name") == "MainWindow"]
        assert view_drawers, (
            f"Expected a drawer with symbol_name='MainWindow'. "
            f"Got symbol names: {[m.get('symbol_name') for m in metadatas]}"
        )
        assert view_drawers[0]["symbol_type"] == "view"

        # mine() with KG should emit has_code_behind triple
        kg = KnowledgeGraph(db_path=str(project_root / "kg.sqlite3"))
        (project_root / "mempalace.yaml").write_text(
            yaml.dump(
                {"wing": "test_xaml_kg", "rooms": [{"name": "general", "description": "All"}]}
            ),
            encoding="utf-8",
        )
        mine(str(project_root), str(project_root / "palace2"), kg=kg, incremental=False)

        triples = kg.query_entity("MainWindow")
        code_behind = {t["object"] for t in triples if t["predicate"] == "has_code_behind"}
        assert "MainWindow.xaml.cs" in code_behind, (
            f"Expected has_code_behind triple, got code_behind={code_behind!r}"
        )
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# detect_projects() tests
# =============================================================================


class TestDetectProjects:
    def test_detect_finds_git_dirs(self, tmp_path):
        proj = tmp_path / "myapp"
        proj.mkdir()
        (proj / ".git").mkdir()

        results = detect_projects(str(tmp_path))
        paths = [r["path"] for r in results]
        assert str(proj) in paths

    def test_detect_finds_pyproject(self, tmp_path):
        proj = tmp_path / "pyapp"
        proj.mkdir()
        (proj / "pyproject.toml").write_text("[tool.poetry]\nname='x'\n")

        results = detect_projects(str(tmp_path))
        paths = [r["path"] for r in results]
        assert str(proj) in paths

    def test_detect_finds_package_json(self, tmp_path):
        proj = tmp_path / "jsapp"
        proj.mkdir()
        (proj / "package.json").write_text("{}")

        results = detect_projects(str(tmp_path))
        paths = [r["path"] for r in results]
        assert str(proj) in paths

    def test_detect_skips_non_project_dirs(self, tmp_path):
        empty = tmp_path / "empty_dir"
        empty.mkdir()

        results = detect_projects(str(tmp_path))
        paths = [r["path"] for r in results]
        assert str(empty) not in paths

    def test_detect_no_recurse(self, tmp_path):
        # Nested project should NOT be found (only immediate children)
        outer = tmp_path / "outer"
        outer.mkdir()
        (outer / "pyproject.toml").write_text("")
        nested = outer / "nested"
        nested.mkdir()
        (nested / "pyproject.toml").write_text("")

        results = detect_projects(str(tmp_path))
        paths = [r["path"] for r in results]
        assert str(outer) in paths
        assert str(nested) not in paths

    def test_detect_reports_initialized_flag(self, tmp_path):
        init_proj = tmp_path / "initialized"
        init_proj.mkdir()
        (init_proj / ".git").mkdir()
        (init_proj / "mempalace.yaml").write_text("wing: test\n")

        uninit_proj = tmp_path / "uninit"
        uninit_proj.mkdir()
        (uninit_proj / ".git").mkdir()

        results = detect_projects(str(tmp_path))
        result_map = {r["path"]: r for r in results}

        assert result_map[str(init_proj)]["initialized"] is True
        assert result_map[str(uninit_proj)]["initialized"] is False

    def test_detect_skips_hidden_dirs(self, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "pyproject.toml").write_text("")

        results = detect_projects(str(tmp_path))
        paths = [r["path"] for r in results]
        assert str(hidden) not in paths

    def test_detect_multiple_markers(self, tmp_path):
        proj = tmp_path / "combo"
        proj.mkdir()
        (proj / ".git").mkdir()
        (proj / "pyproject.toml").write_text("")

        results = detect_projects(str(tmp_path))
        result_map = {r["path"]: r for r in results}
        assert ".git" in result_map[str(proj)]["markers"]
        assert "pyproject.toml" in result_map[str(proj)]["markers"]

    def test_detect_empty_parent_dir(self, tmp_path):
        results = detect_projects(str(tmp_path))
        assert results == []


# =============================================================================
# derive_wing_name() tests
# =============================================================================


class TestDeriveWingName:
    def test_wing_from_git_remote_https(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "https://github.com/user/my-repo.git\n"
            result = derive_wing_name(str(tmp_path))
        assert result == "my_repo"

    def test_wing_from_git_remote_ssh(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "git@github.com:user/cool-project.git\n"
            result = derive_wing_name(str(tmp_path))
        assert result == "cool_project"

    def test_wing_fallback_folder_name(self, tmp_path):
        proj = tmp_path / "my-project"
        proj.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            result = derive_wing_name(str(proj))
        assert result == "my_project"

    def test_wing_name_normalization(self, tmp_path):
        proj = tmp_path / "My App 2.0"
        proj.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            result = derive_wing_name(str(proj))
        # spaces become underscores, non-alnum stripped
        assert result == "my_app_20"

    def test_wing_name_no_git_suffix(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "https://github.com/org/repo\n"
            result = derive_wing_name(str(tmp_path))
        assert result == "repo"

    def test_wing_name_git_exception_falls_back(self, tmp_path):
        proj = tmp_path / "fallback-proj"
        proj.mkdir()
        with patch("subprocess.run", side_effect=OSError("no git")):
            result = derive_wing_name(str(proj))
        assert result == "fallback_proj"


# =============================================================================
# REPO-STRUCTURE-DEFAULTS — .NET auto-organisation helpers
# =============================================================================

_SLN_CONTENT_ONE_PROJECT = """\
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "MyApp", "MyApp\\MyApp.csproj", "{AAA}"
EndProject
"""

_SLN_CONTENT_THREE_PROJECTS = """\
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Web", "Web\\Web.csproj", "{BBB}"
EndProject
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Core", "Core\\Core.csproj", "{CCC}"
EndProject
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Tests", "Tests\\Tests.csproj", "{DDD}"
EndProject
"""


class TestDetectSlnWing:
    def test_single_sln(self, tmp_path):
        (tmp_path / "MySolution.sln").write_text(_SLN_CONTENT_ONE_PROJECT)
        assert _detect_sln_wing(tmp_path) == "mysolution"

    def test_no_sln(self, tmp_path):
        assert _detect_sln_wing(tmp_path) is None

    def test_multiple_sln_picks_most_projects(self, tmp_path):
        (tmp_path / "Small.sln").write_text(_SLN_CONTENT_ONE_PROJECT)
        (tmp_path / "Large.sln").write_text(_SLN_CONTENT_THREE_PROJECTS)
        assert _detect_sln_wing(tmp_path) == "large"

    def test_multiple_sln_tie_break_alphabetical(self, tmp_path):
        """When both have the same number of projects, pick alphabetically first."""
        (tmp_path / "Bravo.sln").write_text(_SLN_CONTENT_ONE_PROJECT)
        (tmp_path / "Alpha.sln").write_text(_SLN_CONTENT_ONE_PROJECT)
        assert _detect_sln_wing(tmp_path) == "alpha"

    def test_normalizes_name(self, tmp_path):
        (tmp_path / "My-Solution.sln").write_text(_SLN_CONTENT_ONE_PROJECT)
        assert _detect_sln_wing(tmp_path) == "my_solution"

    def test_ignores_nested_sln(self, tmp_path):
        """Only root-level .sln files are picked up."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "Nested.sln").write_text(_SLN_CONTENT_ONE_PROJECT)
        assert _detect_sln_wing(tmp_path) is None


class TestBuildCsprojRoomMap:
    def test_single_csproj(self, tmp_path):
        proj_dir = tmp_path / "MyApp"
        proj_dir.mkdir()
        (proj_dir / "MyApp.csproj").write_text("<Project/>")
        room_map = _build_csproj_room_map(tmp_path)
        assert room_map[proj_dir.resolve()] == "myapp"

    def test_multiple_projects(self, tmp_path):
        for name in ("App", "Core", "Tests"):
            d = tmp_path / name
            d.mkdir()
            (d / f"{name}.csproj").write_text("<Project/>")
        room_map = _build_csproj_room_map(tmp_path)
        assert room_map[(tmp_path / "App").resolve()] == "app"
        assert room_map[(tmp_path / "Core").resolve()] == "core"
        assert room_map[(tmp_path / "Tests").resolve()] == "tests"

    def test_fsproj_and_vbproj(self, tmp_path):
        (tmp_path / "FSharpLib").mkdir()
        (tmp_path / "FSharpLib" / "FSharpLib.fsproj").write_text("<Project/>")
        (tmp_path / "VbApp").mkdir()
        (tmp_path / "VbApp" / "VbApp.vbproj").write_text("<Project/>")
        room_map = _build_csproj_room_map(tmp_path)
        assert room_map[(tmp_path / "FSharpLib").resolve()] == "fsharplib"
        assert room_map[(tmp_path / "VbApp").resolve()] == "vbapp"

    def test_empty_when_no_projects(self, tmp_path):
        assert _build_csproj_room_map(tmp_path) == {}

    def test_normalizes_dotted_names(self, tmp_path):
        d = tmp_path / "MyApp.Infrastructure"
        d.mkdir()
        (d / "MyApp.Infrastructure.csproj").write_text("<Project/>")
        room_map = _build_csproj_room_map(tmp_path)
        assert room_map[d.resolve()] == "myapp_infrastructure"


class TestDetectRoomCsprojMap:
    def test_csproj_priority_over_folder_keyword(self, tmp_path):
        """File under a .csproj project folder → map takes precedence."""
        proj_dir = tmp_path / "backend"
        (proj_dir / "src").mkdir(parents=True)
        (proj_dir / "MyService.csproj").write_text("<Project/>")
        cs_file = proj_dir / "src" / "Foo.cs"
        cs_file.write_text("class Foo {}")
        room_map = {proj_dir.resolve(): "myservice"}
        rooms = [{"name": "backend", "description": "backend room", "keywords": ["backend"]}]
        result = detect_room(cs_file, "class Foo {}", rooms, tmp_path, csproj_room_map=room_map)
        assert result == "myservice"

    def test_csproj_no_match_falls_through(self, tmp_path):
        """File outside any project folder → falls through to existing logic."""
        cs_file = tmp_path / "standalone" / "Foo.cs"
        cs_file.parent.mkdir()
        cs_file.write_text("class Foo {}")
        room_map = {}
        rooms = [
            {"name": "general", "description": "General", "keywords": []},
        ]
        result = detect_room(cs_file, "class Foo {}", rooms, tmp_path, csproj_room_map=room_map)
        assert result == "general"

    def test_csproj_deeply_nested_file(self, tmp_path):
        """Deeply nested file resolves to its ancestor project folder."""
        proj_dir = tmp_path / "MyProject"
        nested = proj_dir / "Controllers" / "HomeController.cs"
        nested.parent.mkdir(parents=True)
        nested.write_text("class HomeController {}")
        room_map = {proj_dir.resolve(): "myproject"}
        rooms = [{"name": "general", "description": "General", "keywords": []}]
        result = detect_room(
            nested, "class HomeController {}", rooms, tmp_path, csproj_room_map=room_map
        )
        assert result == "myproject"

    def test_no_csproj_map_unchanged(self, tmp_path):
        """When csproj_room_map is None, existing detect_room logic is used."""
        f = tmp_path / "backend" / "app.py"
        f.parent.mkdir()
        f.write_text("def main(): pass")
        rooms = [
            {"name": "backend", "description": "Backend code", "keywords": ["backend"]},
            {"name": "general", "description": "General", "keywords": []},
        ]
        result = detect_room(f, "def main(): pass", rooms, tmp_path)
        assert result == "backend"


class TestMineWithDotnetStructure:
    def _make_dotnet_repo(self, project_root: Path, sln_name: str = "MySolution"):
        """Create a minimal .NET repo structure for testing."""
        # Solution file
        sln_content = (
            'Project("{FAE04EC0}") = "AppCore", "AppCore\\AppCore.csproj", "{AAA}"\n'
            "EndProject\n"
            'Project("{FAE04EC0}") = "AppWeb", "AppWeb\\AppWeb.csproj", "{BBB}"\n'
            "EndProject\n"
        )
        (project_root / f"{sln_name}.sln").write_text(sln_content)

        # Two project dirs with .csproj files
        for proj in ("AppCore", "AppWeb"):
            proj_dir = project_root / proj
            proj_dir.mkdir(parents=True, exist_ok=True)
            (proj_dir / f"{proj}.csproj").write_text("<Project/>")
            # Add a real .cs file large enough to mine
            cs_code = (
                "using System;\n\nnamespace App {\n    " + "public class Stub {}\n    " * 30 + "}"
            )
            (proj_dir / "Stub.cs").write_text(cs_code)

        # Config with dotnet_structure enabled
        config = {
            "wing": "placeholder",
            "dotnet_structure": True,
            "rooms": [
                {"name": "appcore", "description": "AppCore project", "keywords": ["appcore"]},
                {"name": "appweb", "description": "AppWeb project", "keywords": ["appweb"]},
                {"name": "general", "description": "General", "keywords": []},
            ],
        }
        with open(project_root / "mempalace.yaml", "w") as f:
            yaml.dump(config, f)

    def test_mine_dotnet_structure_wing(self, tmp_path):
        """Wing is derived from the .sln filename when dotnet_structure is true."""
        project_root = tmp_path / "dotnet_repo"
        project_root.mkdir()
        self._make_dotnet_repo(project_root, sln_name="MySolution")
        palace_path = tmp_path / "palace"

        mine(str(project_root), str(palace_path))

        store = open_store(str(palace_path), create=False)
        wing_room_counts = store.count_by_pair("wing", "room")
        assert "mysolution" in wing_room_counts

    def test_mine_dotnet_structure_rooms(self, tmp_path):
        """Rooms are derived from .csproj files when dotnet_structure is true."""
        project_root = tmp_path / "dotnet_repo"
        project_root.mkdir()
        self._make_dotnet_repo(project_root, sln_name="MySolution")
        palace_path = tmp_path / "palace"

        mine(str(project_root), str(palace_path))

        store = open_store(str(palace_path), create=False)
        wing_room_counts = store.count_by_pair("wing", "room")
        all_rooms: set = set()
        for rooms_dict in wing_room_counts.values():
            all_rooms.update(rooms_dict.keys())
        assert "appcore" in all_rooms or "appweb" in all_rooms

    def test_mine_dotnet_structure_wing_override(self, tmp_path):
        """--wing override wins over .sln-derived wing."""
        project_root = tmp_path / "dotnet_repo"
        project_root.mkdir()
        self._make_dotnet_repo(project_root, sln_name="MySolution")
        palace_path = tmp_path / "palace"

        mine(str(project_root), str(palace_path), wing_override="my_custom_wing")

        store = open_store(str(palace_path), create=False)
        wing_room_counts = store.count_by_pair("wing", "room")
        assert "my_custom_wing" in wing_room_counts
        assert "mysolution" not in wing_room_counts

    def test_mine_dotnet_structure_off(self, tmp_path):
        """Without dotnet_structure, wing stays as config value."""
        project_root = tmp_path / "normal_repo"
        project_root.mkdir()

        (project_root / "app.py").write_text("def main(): pass\n" * 30)
        config = {
            "wing": "my_static_wing",
            "rooms": [{"name": "general", "description": "General", "keywords": []}],
        }
        with open(project_root / "mempalace.yaml", "w") as f:
            yaml.dump(config, f)

        palace_path = tmp_path / "palace"
        mine(str(project_root), str(palace_path))

        store = open_store(str(palace_path), create=False)
        wing_room_counts = store.count_by_pair("wing", "room")
        assert "my_static_wing" in wing_room_counts
