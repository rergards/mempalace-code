import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import torch
import yaml

from mempalace.miner import _detect_batch_size, add_drawers_batch, mine, process_file, scan_project
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
