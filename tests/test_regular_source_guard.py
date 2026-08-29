from __future__ import annotations

import collections
import contextlib
import errno
import hashlib
import io
import multiprocessing as mp
import os
import queue
import socket
import sys
import tempfile
import textwrap
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mempalace_code import source_io
from mempalace_code.convo_miner import scan_convos
from mempalace_code.entity_detector import scan_for_detection
from mempalace_code.mining.kg_extract import (
    extract_type_relationships,
    parse_dotnet_project_file,
    parse_sln_file,
    parse_xaml_file,
)
from mempalace_code.mining.orchestrator import (
    _collect_specs_for_file,
    _file_hash,
    _warn_source_read_error,
)
from mempalace_code.mining.projects import (
    InvalidProjectConfigError,
    _build_csproj_room_map,
    _detect_sln_wing,
    detect_projects,
    load_config,
)
from mempalace_code.mining.scanner import scan_project
from mempalace_code.normalize import normalize
from mempalace_code.source_io import (
    RegularSourceError,
    hash_regular_bytes,
    read_regular_bytes,
    read_regular_text,
    source_path_kind,
    stat_regular_source,
)
from mempalace_code.split_mega_files import discover_text_sources, split_file

if TYPE_CHECKING:
    from multiprocessing.context import ForkContext, SpawnContext
    from pathlib import Path
    from typing import TypeAlias

    if sys.platform == "win32":
        MPContext: TypeAlias = SpawnContext
    else:
        MPContext: TypeAlias = ForkContext | SpawnContext


def _require_fifo() -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo is not available on this platform")


def _make_fifo(path: Path) -> Path:
    _require_fifo()
    os.mkfifo(path)
    return path


def _make_unix_socket(path: Path) -> socket.socket:
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("Unix sockets are not available on this platform")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(path))
        return sock
    except OSError as exc:
        # Python raises OSError(errno=None, "AF_UNIX path too long") before the
        # syscall; the kernel may raise ENAMETOOLONG instead — handle both.
        path_too_long = exc.errno == errno.ENAMETOOLONG or (
            exc.errno is None and "too long" in str(exc).lower()
        )
        if not path_too_long:
            sock.close()
            pytest.skip(f"cannot create Unix socket fixture: {exc}")

    # Path too long for AF_UNIX — bind through a short temporary symlink alias
    # that points to path.parent.  The socket node lands at path after the kernel
    # resolves the symlink; removing the alias leaves the node in place.
    alias_dir: str | None = None
    alias: str | None = None
    try:
        alias_dir = tempfile.mkdtemp()
        alias = os.path.join(alias_dir, "d")
        try:
            os.symlink(str(path.parent), alias)
        except (NotImplementedError, OSError) as sym_exc:
            sock.close()
            pytest.skip(f"symlink creation unavailable for Unix socket alias: {sym_exc}")
        try:
            sock.bind(os.path.join(alias, path.name))
        except OSError as bind_exc:
            sock.close()
            pytest.skip(f"cannot bind Unix socket via alias: {bind_exc}")
    finally:
        if alias is not None:
            try:
                os.unlink(alias)
            except OSError:
                pass
        if alias_dir is not None:
            try:
                os.rmdir(alias_dir)
            except OSError:
                pass
    return sock


def _write_regular_project(project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "mempalace.yaml").write_text(
        "wing: guard\nrooms:\n  - name: general\n    description: All\n",
        encoding="utf-8",
    )
    (project / "app.py").write_text(
        textwrap.dedent(
            """\
            class GuardedApp(BaseApp):
                def run(self):
                    return "regular source"

            def enough_content_for_chunking():
                return "regular project mining source with enough content"
            """
        ),
        encoding="utf-8",
    )


def _make_session_text() -> str:
    return "\n".join(
        [
            "> First user question about regular source ingestion",
            "Assistant answer with enough content to chunk the transcript.",
            "",
            "> Second user question about a filesystem guard",
            "Assistant answer mentions architecture and testing for room scoring.",
            "",
            "> Third user question about reliability",
            "Assistant answer keeps this regular transcript above minimum size.",
            "",
        ]
    )


def _try_symlink(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        return False
    return True


def _mp_context() -> MPContext:
    methods = mp.get_all_start_methods()
    if sys.platform != "win32" and "fork" in methods:
        return mp.get_context("fork")
    return mp.get_context("spawn")


def _run_child(worker, *args, timeout: float = 2.0) -> dict:
    ctx = _mp_context()
    result_queue = ctx.Queue()
    proc = ctx.Process(target=worker, args=(*args, result_queue))
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(2)
        pytest.fail(f"{worker.__name__} exceeded {timeout}s hard timeout")
    assert proc.exitcode == 0, f"{worker.__name__} exited {proc.exitcode}"
    try:
        return result_queue.get_nowait()
    except queue.Empty:
        pytest.fail(f"{worker.__name__} returned no result")


def _direct_reader_worker(paths: dict[str, str], out_dir: str, result_queue) -> None:
    from pathlib import Path

    from mempalace_code.entity_detector import detect_entities
    from mempalace_code.mining.kg_extract import (
        extract_type_relationships,
        parse_dotnet_project_file,
        parse_sln_file,
        parse_xaml_file,
    )
    from mempalace_code.mining.orchestrator import _file_hash
    from mempalace_code.mining.projects import load_config
    from mempalace_code.normalize import normalize
    from mempalace_code.split_mega_files import split_file

    results = {}

    def record(label: str, fn) -> None:
        try:
            results[label] = {"status": "ok", "value": fn()}
        except Exception as exc:
            results[label] = {
                "status": "error",
                "type": type(exc).__name__,
                "message": str(exc),
            }

    record("hash", lambda: _file_hash(Path(paths["hash"])))
    record("normalize", lambda: normalize(paths["convo"], spellcheck=False))
    record("load_config", lambda: load_config(paths["config_dir"]))
    record("parse_sln", lambda: parse_sln_file(Path(paths["sln"])))
    record("parse_project", lambda: parse_dotnet_project_file(Path(paths["project"])))
    record("parse_xaml", lambda: parse_xaml_file(Path(paths["xaml"])))
    record("extract_types", lambda: extract_type_relationships(Path(paths["py"])))
    record("detect_entities", lambda: detect_entities([Path(paths["entity"])]))
    record("split_file", lambda: [str(p) for p in split_file(paths["split"], out_dir)])
    result_queue.put(results)


def _read_path_worker(path: str, result_queue) -> None:
    from mempalace_code.source_io import read_regular_text

    try:
        result_queue.put({"status": "ok", "value": read_regular_text(path)})
    except Exception as exc:
        result_queue.put({"status": "error", "type": type(exc).__name__, "message": str(exc)})


def _detect_projects_worker(parent: str, result_queue) -> None:
    from mempalace_code.mining.projects import detect_projects

    result_queue.put(detect_projects(parent))


def _project_marker_classification_worker(parent: str, root_names: list[str], result_queue) -> None:
    from pathlib import Path

    from mempalace_code.mining.projects import classify_project_root, detect_projects
    from mempalace_code.watcher import render_watch_schedule

    parent_path = Path(parent)
    result_queue.put(
        {
            "classifications": {
                name: classify_project_root(parent_path / name) for name in root_names
            },
            "projects": detect_projects(parent),
            "schedule": render_watch_schedule(
                parent, "linux", mempalace_bin="/usr/bin/mempalace-code"
            ),
        }
    )


def _init_destination_worker(project_dir: str, result_queue) -> None:
    from mempalace_code.cli_commands.ingest import cmd_init

    stderr = io.StringIO()
    args = SimpleNamespace(
        dir=project_dir,
        detect_entities=True,
        yes=False,
        interactive=False,
        skip_model_download=True,
    )
    with (
        patch(
            "mempalace_code.entity_detector.scan_for_detection",
            side_effect=AssertionError("entity scan must not run"),
        ) as entity_scan,
        patch(
            "mempalace_code.room_detector_local.detect_rooms_local",
            side_effect=AssertionError("room discovery must not run"),
        ) as room_scan,
        contextlib.redirect_stderr(stderr),
    ):
        try:
            cmd_init(args)
        except SystemExit as exc:
            result_queue.put(
                {
                    "exit_code": exc.code,
                    "stderr": stderr.getvalue(),
                    "entity_scan_called": entity_scan.called,
                    "room_scan_called": room_scan.called,
                }
            )
            return
        except Exception as exc:
            result_queue.put({"exception": type(exc).__name__, "message": str(exc)})
            return
    result_queue.put({"exit_code": 0, "stderr": stderr.getvalue()})


def _assert_init_destination_rejected(project: Path, destination: Path) -> None:
    result = _run_child(_init_destination_worker, str(project))
    assert "exception" not in result, result
    assert result["exit_code"] != 0, result
    assert result["entity_scan_called"] is False
    assert result["room_scan_called"] is False
    assert str(destination) in result["stderr"]
    assert f"mempalace-code init {project}" in result["stderr"]


@pytest.mark.parametrize("target_exists", [True, False])
def test_init_rejects_config_symlink_before_work(tmp_path, target_exists):
    target = tmp_path / "outside.yaml"
    target_bytes = b"wing: outside\nrooms: []\n"
    if target_exists:
        target.write_bytes(target_bytes)

    symlink_project = tmp_path / "symlink-project"
    symlink_project.mkdir()
    symlink_config = symlink_project / "mempalace.yaml"
    if not _try_symlink(symlink_config, target):
        pytest.skip("symlink creation is not available for this user/platform")
    _assert_init_destination_rejected(symlink_project, symlink_config)
    assert symlink_config.is_symlink()
    if target_exists:
        assert target.read_bytes() == target_bytes
    else:
        assert not target.exists()


def test_init_rejects_entities_symlink_before_work(tmp_path):
    project = tmp_path / "symlink-project"
    project.mkdir()
    target = tmp_path / "outside.json"
    target_bytes = b'{"people": ["outside"]}'
    target.write_bytes(target_bytes)
    destination = project / "entities.json"
    if not _try_symlink(destination, target):
        pytest.skip("symlink creation is not available for this user/platform")
    _assert_init_destination_rejected(project, destination)
    assert destination.is_symlink()
    assert target.read_bytes() == target_bytes


def test_init_rejects_entities_socket_and_directory_before_work(tmp_path):
    socket_project = tmp_path / "socket-project"
    socket_project.mkdir()
    socket_destination = socket_project / "entities.json"
    sock = _make_unix_socket(socket_destination)
    try:
        _assert_init_destination_rejected(socket_project, socket_destination)
        assert socket_destination.exists()
    finally:
        sock.close()

    directory_project = tmp_path / "directory-project"
    directory_project.mkdir()
    destination = directory_project / "entities.json"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    _assert_init_destination_rejected(directory_project, destination)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_init_rejects_entities_fifo_without_blocking(tmp_path):
    _require_fifo()
    project = tmp_path / "fifo-project"
    project.mkdir()
    destination = _make_fifo(project / "entities.json")

    _assert_init_destination_rejected(project, destination)

    assert destination.exists()


def test_atomic_destination_write_replaces_post_validation_symlink_without_following(tmp_path):
    from mempalace_code.room_detector_local import (
        validate_init_destinations,
        write_regular_destination,
    )

    project = tmp_path / "project"
    project.mkdir()
    destination = project / "mempalace.yaml"
    destination.write_text("wing: old\n", encoding="utf-8")
    outside = tmp_path / "outside.yaml"
    outside.write_text("wing: outside\n", encoding="utf-8")
    validate_init_destinations(project, write_entities=False)
    real_replace = os.replace

    def plant_symlink_then_replace(source, target):
        assert target == destination
        target.unlink()
        target.symlink_to(outside)
        real_replace(source, target)

    with patch(
        "mempalace_code.room_detector_local.os.replace", side_effect=plant_symlink_then_replace
    ):
        write_regular_destination(destination, "wing: replacement\n")

    assert not destination.is_symlink()
    assert destination.read_text(encoding="utf-8") == "wing: replacement\n"
    assert outside.read_text(encoding="utf-8") == "wing: outside\n"


def test_atomic_destination_write_cleans_temp_on_keyboard_interrupt(tmp_path):
    from mempalace_code.room_detector_local import write_regular_destination

    destination = tmp_path / "mempalace.yaml"
    destination.write_text("wing: old\n", encoding="utf-8")

    with patch("mempalace_code.room_detector_local.os.replace", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            write_regular_destination(destination, "wing: replacement\n")

    assert destination.read_text(encoding="utf-8") == "wing: old\n"
    assert list(tmp_path.glob(".mempalace.yaml.*")) == []


def test_atomic_destination_write_respects_restrictive_umask_for_absent_file(tmp_path):
    from mempalace_code.room_detector_local import write_regular_destination

    destination = tmp_path / "entities.json"

    prior_umask = os.umask(0o077)
    try:
        write_regular_destination(destination, "{}")
    finally:
        os.umask(prior_umask)

    assert destination.stat().st_mode & 0o777 == 0o600


def _make_direct_fifo_fixture(tmp_path: Path) -> dict[str, str]:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    paths = {
        "hash": tmp_path / "hash.py",
        "convo": tmp_path / "chat.jsonl",
        "sln": tmp_path / "Guard.sln",
        "project": tmp_path / "Guard.csproj",
        "xaml": tmp_path / "Guard.xaml",
        "py": tmp_path / "type_source.py",
        "entity": tmp_path / "notes.md",
        "split": tmp_path / "mega.txt",
        "config": config_dir / "mempalace.yaml",
    }
    for path in paths.values():
        _make_fifo(path)
    return {**{key: str(path) for key, path in paths.items()}, "config_dir": str(config_dir)}


def test_scan_discovery_rejects_non_regular_sources(tmp_path, capsys):
    _require_fifo()
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('regular')\n", encoding="utf-8")
    fifo_py = _make_fifo(project / "blocked.py")
    sock = _make_unix_socket(project / "blocked_socket.py")

    convo_dir = tmp_path / "convos"
    convo_dir.mkdir()
    (convo_dir / "chat.md").write_text(_make_session_text(), encoding="utf-8")
    fifo_md = _make_fifo(convo_dir / "blocked.md")

    entity_dir = tmp_path / "entities"
    entity_dir.mkdir()
    (entity_dir / "README.md").write_text("Alice Alice Alice wrote notes.\n", encoding="utf-8")
    fifo_entity = _make_fifo(entity_dir / "blocked.md")

    split_dir = tmp_path / "splits"
    split_dir.mkdir()
    (split_dir / "mega.txt").write_text(_make_session_text(), encoding="utf-8")
    fifo_txt = _make_fifo(split_dir / "blocked.txt")

    try:
        project_files = scan_project(str(project))
        convo_files = scan_convos(str(convo_dir))
        entity_files = scan_for_detection(str(entity_dir), max_files=10)
        split_files = discover_text_sources(split_dir)
    finally:
        sock.close()

    assert [path.name for path in project_files] == ["app.py"]
    assert [path.name for path in convo_files] == ["chat.md"]
    assert [path.name for path in entity_files] == ["README.md"]
    assert [path.name for path in split_files] == ["mega.txt"]

    skipped = capsys.readouterr().err
    for path in (fifo_py, project / "blocked_socket.py", fifo_md, fifo_entity, fifo_txt):
        assert str(path) in skipped
    assert skipped.count("not a regular file") >= 5


def test_detect_projects_rejects_non_regular_git_marker_without_blocking(tmp_path):
    _require_fifo()
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    _make_fifo(unsafe / ".git")
    valid = tmp_path / "valid"
    valid.mkdir()
    (valid / "pyproject.toml").write_text("[project]\nname = 'valid'\n", encoding="utf-8")

    results = _run_child(_detect_projects_worker, str(tmp_path))

    assert results == [{"path": str(valid), "markers": ["pyproject.toml"], "initialized": False}]


def test_project_marker_classification_rejects_non_regular_nodes_without_blocking(tmp_path):
    _require_fifo()
    unsafe_markers = {
        "fifo_git": ".git",
        "socket_literal": "pyproject.toml",
        "symlink_git": ".git",
        "symlink_literal": "package.json",
        "symlink_glob": "Guard.sln",
        "symlink_init": "mempalace.yaml",
        "directory_literal": "Cargo.toml",
    }
    roots = {name: tmp_path / name for name in unsafe_markers}
    for root in roots.values():
        root.mkdir()

    _make_fifo(roots["fifo_git"] / ".git")
    sock = _make_unix_socket(roots["socket_literal"] / "pyproject.toml")
    (roots["symlink_git"] / "git-data").mkdir()
    regular_target = tmp_path / "regular-target"
    regular_target.write_text("regular\n", encoding="utf-8")
    assert _try_symlink(roots["symlink_git"] / ".git", roots["symlink_git"] / "git-data")
    assert _try_symlink(roots["symlink_literal"] / "package.json", regular_target)
    assert _try_symlink(roots["symlink_glob"] / "Guard.sln", regular_target)
    assert _try_symlink(roots["symlink_init"] / "mempalace.yaml", regular_target)
    (roots["directory_literal"] / "Cargo.toml").mkdir()

    valid = tmp_path / "valid"
    valid.mkdir()
    (valid / "pyproject.toml").write_text("[project]\nname = 'valid'\n", encoding="utf-8")
    (valid / "mempalace.yaml").write_text("wing: valid\n", encoding="utf-8")

    try:
        result = _run_child(
            _project_marker_classification_worker,
            str(tmp_path),
            list(unsafe_markers),
        )
    finally:
        sock.close()

    assert result["classifications"] == {name: ("parent", []) for name in unsafe_markers}
    assert result["projects"] == [
        {"path": str(valid), "markers": ["pyproject.toml"], "initialized": True}
    ]
    assert result["schedule"].startswith("@reboot /usr/bin/mempalace-code watch ")


def test_direct_readers_non_regular_hard_timeout(tmp_path):
    _require_fifo()
    paths = _make_direct_fifo_fixture(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    no_writer = _run_child(_direct_reader_worker, paths, str(output_dir))

    held_fds = []
    try:
        for key in ("hash", "convo", "sln", "project", "xaml", "py", "entity", "split", "config"):
            held_fds.append(os.open(paths[key], os.O_RDWR | getattr(os, "O_NONBLOCK", 0)))
        live_writer = _run_child(_direct_reader_worker, paths, str(output_dir))
    finally:
        for fd in held_fds:
            os.close(fd)

    for results in (no_writer, live_writer):
        for label in ("hash", "normalize", "split_file"):
            assert results[label]["status"] == "error", results[label]
            assert "not a regular file" in results[label]["message"]

        assert results["load_config"]["status"] == "error", results["load_config"]
        assert results["load_config"]["type"] == "InvalidProjectConfigError"
        assert "not a regular file" in results["load_config"]["message"]

        for label in ("parse_sln", "parse_project", "parse_xaml", "extract_types"):
            assert results[label] == {"status": "ok", "value": []}

        assert results["detect_entities"] == {
            "status": "ok",
            "value": {"people": [], "projects": [], "uncertain": []},
        }


def test_eagain_retry_revalidates_regular_source(tmp_path, monkeypatch):
    path = tmp_path / "regular.txt"
    path.write_text("regular eagain retry content", encoding="utf-8")

    original_open = source_io.os.open
    original_close = source_io.os.close
    original_read = source_io.os.read
    opens: list[int] = []
    closes: list[int] = []
    calls = {"count": 0}

    def tracking_open(p, flags, mode=0o777):
        fd = original_open(p, flags, mode)
        opens.append(fd)
        return fd

    def tracking_close(fd: int) -> None:
        closes.append(fd)
        original_close(fd)

    def flaky_read(fd: int, size: int) -> bytes:
        calls["count"] += 1
        if calls["count"] == 1:
            raise BlockingIOError(errno.EAGAIN, "try again")
        return original_read(fd, size)

    monkeypatch.setattr(source_io.os, "open", tracking_open)
    monkeypatch.setattr(source_io.os, "close", tracking_close)
    monkeypatch.setattr(source_io.os, "read", flaky_read)

    assert read_regular_text(path) == "regular eagain retry content"
    assert calls["count"] >= 2
    # Exactly one path open and one descriptor close across the EAGAIN retry
    assert len(opens) == 1
    assert len(closes) == 1
    assert opens == closes

    calls["count"] = 0
    opens.clear()
    closes.clear()
    with pytest.raises(RegularSourceError, match="not a regular file"):
        read_regular_bytes(tmp_path)
    assert calls["count"] == 0


def _eagain_fifo_replace_worker(path: str, result_queue) -> None:
    """Child: replace path with a FIFO at EAGAIN; fix must use original fd."""
    import errno as _errno
    import os as _os

    import mempalace_code.source_io as _source_io

    original_open = _source_io.os.open
    original_read = _source_io.os.read
    open_count = [0]
    read_call = [0]

    def tracking_open(p, flags, mode=0o777):
        open_count[0] += 1
        return original_open(p, flags, mode)

    def patched_read(fd, size):
        read_call[0] += 1
        if read_call[0] == 1:
            # Replace the path-side entry with a FIFO while the original fd stays open
            _os.unlink(path)
            _os.mkfifo(path)
            raise BlockingIOError(_errno.EAGAIN, "try again")
        return original_read(fd, size)

    _source_io.os.open = tracking_open
    _source_io.os.read = patched_read
    try:
        text = _source_io.read_regular_text(path)
        result_queue.put({"status": "ok", "value": text, "open_count": open_count[0]})
    except Exception as exc:
        result_queue.put({"status": "error", "type": type(exc).__name__, "message": str(exc)})
    finally:
        _source_io.os.open = original_open
        _source_io.os.read = original_read
        try:
            if _os.path.exists(path):
                _os.unlink(path)
        except OSError:
            pass


def test_eagain_after_partial_read(tmp_path, monkeypatch):
    """EAGAIN after a partial read: seek to zero and retry returns the complete content."""
    content = b"partial-read-before-eagain-" * 4
    path = tmp_path / "partial.txt"
    path.write_bytes(content)

    original_read = source_io.os.read
    calls = [0]

    def patched_read(fd: int, size: int) -> bytes:
        calls[0] += 1
        if calls[0] == 1:
            return original_read(fd, 10)
        if calls[0] == 2:
            raise BlockingIOError(errno.EAGAIN, "try again after partial")
        return original_read(fd, size)

    monkeypatch.setattr(source_io.os, "read", patched_read)
    result = read_regular_bytes(path)
    assert result == content
    assert calls[0] >= 3


def test_eagain_fifo_path_replace_uses_original_fd(tmp_path):
    """After EAGAIN, a path replaced by a FIFO does not affect the retry: original fd is used."""
    _require_fifo()
    content = "eagain fifo replace content"
    path = tmp_path / "regular.txt"
    path.write_text(content, encoding="utf-8")

    result = _run_child(_eagain_fifo_replace_worker, str(path), timeout=5.0)
    assert result["status"] == "ok", result
    assert result["value"] == content
    # Single path open: the FIFO replacement is invisible to the retry
    assert result["open_count"] == 1


def test_descriptor_closes_on_all_regular_source_paths(tmp_path, monkeypatch):
    regular = tmp_path / "regular.txt"
    regular.write_text("abcdef", encoding="utf-8")
    invalid_utf8 = tmp_path / "invalid.txt"
    invalid_utf8.write_bytes(b"\xff")

    original_open = source_io.os.open
    original_close = source_io.os.close
    original_read = source_io.os.read
    opened: list[int] = []
    closed: list[int] = []
    read_calls = {"count": 0}

    def tracking_open(path, flags, mode=0o777):
        fd = original_open(path, flags, mode)
        opened.append(fd)
        return fd

    def tracking_close(fd: int) -> None:
        closed.append(fd)
        original_close(fd)

    def flaky_read(fd: int, size: int) -> bytes:
        read_calls["count"] += 1
        if read_calls["count"] == 1:
            raise BlockingIOError(errno.EAGAIN, "try again")
        return original_read(fd, size)

    monkeypatch.setattr(source_io.os, "open", tracking_open)
    monkeypatch.setattr(source_io.os, "close", tracking_close)

    assert read_regular_bytes(regular) == b"abcdef"
    assert read_regular_bytes(regular, max_bytes=3) == b"abc"
    with pytest.raises(RegularSourceError, match="not a regular file"):
        read_regular_bytes(tmp_path)
    with pytest.raises(UnicodeDecodeError):
        read_regular_text(invalid_utf8, errors="strict")

    monkeypatch.setattr(source_io.os, "read", flaky_read)
    assert read_regular_bytes(regular) == b"abcdef"

    assert collections.Counter(opened) == collections.Counter(closed)


def test_diagnostic_or_required_input_error(tmp_path, capsys):
    _require_fifo()
    project = tmp_path / "project"
    project.mkdir()
    fifo_source = _make_fifo(project / "blocked.py")
    diagnostics = []

    assert scan_project(str(project), symlink_diagnostics=diagnostics) == []
    assert diagnostics == [{"path": str(fifo_source), "reason": "fifo"}]

    convo_dir = tmp_path / "convos"
    convo_dir.mkdir()
    fifo_convo = _make_fifo(convo_dir / "blocked.txt")
    assert scan_convos(str(convo_dir)) == []
    stderr = capsys.readouterr().err
    assert str(fifo_convo) in stderr
    assert "not a regular file" in stderr

    with pytest.raises(OSError, match="not a regular file"):
        normalize(str(fifo_convo), spellcheck=False)
    with pytest.raises(OSError, match="not a regular file"):
        split_file(fifo_convo, tmp_path / "out")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _make_fifo(config_dir / "mempalace.yaml")
    with pytest.raises(InvalidProjectConfigError, match="not a regular file"):
        load_config(str(config_dir))


def test_source_read_warning_classifies_regular_source_by_type(tmp_path, capsys):
    source = tmp_path / "rejected.py"

    _warn_source_read_error(source, RegularSourceError(source, "not a regular file"))

    assert capsys.readouterr().err == f"{source}: not a regular file\n"


def test_source_read_warning_does_not_classify_oserror_by_message(tmp_path, capsys):
    source = tmp_path / "unreadable.py"
    error = OSError("backend said not a regular file while reading")

    _warn_source_read_error(source, error)

    assert capsys.readouterr().err == f"{source}: {error}\n"


def test_symlink_regular_contract(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target.py"
    target.write_text("print('valid symlink target')\n", encoding="utf-8")
    link = project / "linked.py"
    if not _try_symlink(link, target):
        pytest.skip("symlink creation is not available for this user/platform")

    diagnostics = []
    files = scan_project(str(project), symlink_diagnostics=diagnostics)

    assert files == []
    assert diagnostics == [{"path": str(link), "reason": "symlink"}]
    assert source_path_kind(link) == "symlink"
    with pytest.raises(RegularSourceError, match=r"not a regular file \(symlink\)"):
        read_regular_text(link)


def test_symlink_rejection_contract(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    broken = project / "broken.py"
    if not _try_symlink(broken, project / "missing.py"):
        pytest.skip("symlink creation is not available for this user/platform")

    diagnostics = []
    files = scan_project(str(project), symlink_diagnostics=diagnostics)
    assert files == []
    assert diagnostics == [{"path": str(broken), "reason": "symlink"}]

    if hasattr(os, "mkfifo"):
        fifo = _make_fifo(project / "pipe")
        link = project / "fifo_link.py"
        assert _try_symlink(link, fifo)
        diagnostics = []
        files = scan_project(str(project), symlink_diagnostics=diagnostics)
        assert files == []
        assert {"path": str(link), "reason": "symlink"} in diagnostics


def test_regular_bytes_decoding_size_metadata(tmp_path):
    raw_path = tmp_path / "raw.txt"
    raw_bytes = b"alpha\xffbeta\n"
    raw_path.write_bytes(raw_bytes)

    assert read_regular_bytes(raw_path) == raw_bytes
    assert "\ufffd" in read_regular_text(raw_path, errors="replace")
    assert stat_regular_source(raw_path).st_size == len(raw_bytes)
    assert hash_regular_bytes(raw_path) == hashlib.blake2b(raw_bytes, digest_size=16).hexdigest()

    project = tmp_path / "project"
    _write_regular_project(project)
    source = project / "app.py"
    source_hash = _file_hash(source)
    specs = _collect_specs_for_file(
        source,
        project,
        collection=None,
        wing="guard",
        rooms=[{"name": "general", "description": "All"}],
        agent="test",
        mined_files=set(),
        source_hash=source_hash,
    )

    assert specs
    assert specs[0]["metadata"]["source_file"] == str(source)
    assert specs[0]["metadata"]["source_hash"] == source_hash
    assert specs[0]["metadata"]["line_start"] >= 1

    sln = tmp_path / "Guard.sln"
    sln.write_text(
        'Project("{GUID}") = "App", "App\\App.csproj", "{APP}"\nEndProject\n',
        encoding="utf-8",
    )
    assert parse_sln_file(sln) == [("Guard", "contains_project", "App")]

    csproj = tmp_path / "App.csproj"
    csproj.write_text(
        "<Project><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>",
        encoding="utf-8",
    )
    assert ("App", "targets_framework", "net8.0") in parse_dotnet_project_file(csproj)

    xaml = tmp_path / "View.xaml"
    xaml.write_text(
        '<Window x:Class="Demo.View" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" />'
    )
    assert parse_xaml_file(xaml) == []

    py = tmp_path / "types.py"
    py.write_text("class Child(Base):\n    pass\nimport os\n", encoding="utf-8")
    assert ("Child", "inherits", "Base") in extract_type_relationships(py)

    mega = tmp_path / "mega.txt"
    mega.write_text(
        "Claude Code v1\n"
        + "\n".join(["> prompt"] + ["answer"] * 12)
        + "\nClaude Code v1\n"
        + "\n".join(["> prompt two"] + ["answer"] * 12),
        encoding="utf-8",
    )
    output = tmp_path / "out"
    output.mkdir()
    assert len(split_file(mega, output)) == 2


def test_posix_non_regular_subprocess_matrix(tmp_path):
    _require_fifo()
    regular = tmp_path / "regular.txt"
    regular.write_text("regular control", encoding="utf-8")
    fifo_no_writer = _make_fifo(tmp_path / "blocked_no_writer.txt")
    fifo_live_writer = _make_fifo(tmp_path / "blocked_live_writer.txt")
    sock = _make_unix_socket(tmp_path / "blocked_socket.txt")
    directory = tmp_path / "blocked_directory.txt"
    directory.mkdir()
    symlink = tmp_path / "blocked_symlink.txt"
    assert _try_symlink(symlink, regular)

    scanned = tmp_path / "scanned.py"
    scanned.write_text("print('initial regular')\n", encoding="utf-8")
    assert scan_project(str(tmp_path), symlink_diagnostics=[])  # regular control appears
    scanned.unlink()
    replacement_fifo = _make_fifo(scanned)

    held_fd = os.open(fifo_live_writer, os.O_RDWR | getattr(os, "O_NONBLOCK", 0))
    try:
        cases = {
            "fifo_no_writer": fifo_no_writer,
            "fifo_live_writer": fifo_live_writer,
            "unix_socket": tmp_path / "blocked_socket.txt",
            "directory": directory,
            "symlink": symlink,
            "replacement_race": replacement_fifo,
            "regular_control": regular,
        }
        results = {
            name: _run_child(_read_path_worker, str(path), timeout=2.0)
            for name, path in cases.items()
        }
    finally:
        os.close(held_fd)
        sock.close()

    for name in (
        "fifo_no_writer",
        "fifo_live_writer",
        "unix_socket",
        "directory",
        "symlink",
        "replacement_race",
    ):
        assert results[name]["status"] == "error", results[name]
        assert "not a regular file" in results[name]["message"]
    assert "(fifo)" in results["fifo_no_writer"]["message"]
    assert "(socket)" in results["unix_socket"]["message"]
    assert "(directory)" in results["directory"]["message"]
    assert "(symlink)" in results["symlink"]["message"]
    assert results["regular_control"] == {"status": "ok", "value": "regular control"}


def test_windows_regular_and_symlink_compatibility(tmp_path):
    regular = tmp_path / "regular.py"
    regular.write_text("print('regular compatibility')\n", encoding="utf-8")

    assert read_regular_text(regular) == "print('regular compatibility')\n"
    assert _file_hash(regular) == hash_regular_bytes(regular)
    assert scan_project(str(tmp_path)) == [regular]

    link = tmp_path / "linked.py"
    if _try_symlink(link, regular):
        files = sorted(path.name for path in scan_project(str(tmp_path)))
        assert files == ["regular.py"]
        with pytest.raises(RegularSourceError, match="symlink"):
            read_regular_text(link)

    projects_parent = tmp_path / "projects"
    dotnet = projects_parent / "dotnet"
    dotnet.mkdir(parents=True)
    (dotnet / "App.sln").write_text(
        'Project("{GUID}") = "App", "App\\App.csproj", "{APP}"\nEndProject\n',
        encoding="utf-8",
    )
    app_dir = dotnet / "App"
    app_dir.mkdir()
    (app_dir / "App.csproj").write_text("<Project />", encoding="utf-8")
    assert _detect_sln_wing(dotnet) == "app"
    assert _build_csproj_room_map(dotnet) == {app_dir.resolve(): "app"}
    assert detect_projects(str(projects_parent))[0]["markers"] == ["App.sln"]
