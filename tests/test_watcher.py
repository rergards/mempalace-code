"""test_watcher.py — Tests for mempalace/watcher.py.

Covers:
  - CLI flag mutual-exclusion validation (--watch + --dry-run/--full/--limit/convos)
  - _is_relevant_change() filtering semantics
  - watch_and_mine() integration: file change triggers re-mine, deletion handled
  - SIGTERM/SIGHUP handler installation, delivery, and restoration
  - ImportError message when watchfiles is missing
  - CLI dispatch: cmd_mine dispatches to watch_and_mine() with correct args
"""

import json
import os
import plistlib
import shlex
import signal
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml

import mempalace_code.watcher as watcher_module

if TYPE_CHECKING:
    from collections.abc import Callable

from mempalace_code.cli import main
from mempalace_code.cli_commands.watch import cmd_watch_schedule
from mempalace_code.miner import ScanFilterRules
from mempalace_code.operation_lock import OperationLock
from mempalace_code.watcher import (
    _invalidate_gitignore_cache,
    _is_relevant_change,
    _WatcherShutdownSignals,
    render_watch_schedule,
    watch_all,
    watch_and_mine,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(root: Path, *, content: str = "def foo():\n    return 1\n" * 30) -> None:
    """Write a minimal mempalace project with one Python file."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text(content, encoding="utf-8")
    yaml.dump(
        {"wing": "test_watch", "rooms": [{"name": "general", "description": "General"}]},
        (root / "mempalace.yaml").open("w"),
    )


def _fake_watch_factory(change_batches):
    """Return a watchfiles.watch replacement that yields each batch then stops."""

    def _fake_watch(*args, stop_event=None, **kwargs):
        for batch in change_batches:
            yield batch

    return _fake_watch


# ---------------------------------------------------------------------------
# CLI flag mutual-exclusion tests
# ---------------------------------------------------------------------------


class TestWatchFlagValidation:
    def _run(self, tmp_path, *extra_args):
        """Run `mempalace-code mine <dir> --watch <extra_args>` and return exit code."""
        project = tmp_path / "proj"
        _make_project(project)
        argv = [
            "mempalace",
            "--palace",
            str(tmp_path / "palace"),
            "mine",
            str(project),
            "--watch",
        ] + list(extra_args)
        with patch.object(sys, "argv", argv):
            try:
                main()
                return 0
            except SystemExit as exc:
                return exc.code

    def test_watch_rejects_dry_run(self, tmp_path, capsys):
        assert self._run(tmp_path, "--dry-run") == 2
        err = capsys.readouterr().err
        assert "Next:" in err
        assert "without --watch" in err

    def test_watch_rejects_full(self, tmp_path, capsys):
        assert self._run(tmp_path, "--full") == 2
        err = capsys.readouterr().err
        assert "Next:" in err
        assert "--full once without --watch" in err

    def test_watch_rejects_limit(self, tmp_path, capsys):
        assert self._run(tmp_path, "--limit", "5") == 2
        err = capsys.readouterr().err
        assert "Next:" in err
        assert "remove --limit" in err

    def test_watch_rejects_convos(self, tmp_path, capsys):
        assert self._run(tmp_path, "--mode", "convos") == 2
        err = capsys.readouterr().err
        assert "Next:" in err
        assert "without --watch" in err


# ---------------------------------------------------------------------------
# _is_relevant_change() filtering tests
# ---------------------------------------------------------------------------


class TestIsRelevantChange:
    @pytest.fixture()
    def proj(self, tmp_path):
        """Project root Path; files need not exist for filter tests."""
        p = tmp_path / "myproject"
        p.mkdir()
        return p

    # --- Files that SHOULD be accepted ---

    def test_accepts_py_file(self, proj):
        assert _is_relevant_change(str(proj / "module.py"), proj)

    def test_accepts_js_file(self, proj):
        assert _is_relevant_change(str(proj / "index.js"), proj)

    def test_accepts_rs_file(self, proj):
        assert _is_relevant_change(str(proj / "main.rs"), proj)

    def test_accepts_md_file(self, proj):
        assert _is_relevant_change(str(proj / "README.md"), proj)

    def test_accepts_ts_file(self, proj):
        assert _is_relevant_change(str(proj / "src" / "types.ts"), proj)

    # --- KNOWN_FILENAMES (no extension) ---

    def test_is_relevant_change_known_filenames(self, proj):
        """Files in KNOWN_FILENAMES are accepted even without a recognised extension."""
        from mempalace_code.miner import KNOWN_FILENAMES

        for name in ("Dockerfile", "Makefile", "Justfile"):
            if name in KNOWN_FILENAMES:
                assert _is_relevant_change(str(proj / name), proj), f"{name} should be accepted"

    def test_watcher_miner_filter_imports_remain_available(self):
        from mempalace_code import watcher

        assert ".py" in watcher.READABLE_EXTENSIONS
        assert ".yaml" in watcher.READABLE_EXTENSIONS
        assert "Dockerfile" in watcher.KNOWN_FILENAMES
        assert "Makefile" in watcher.KNOWN_FILENAMES

    # --- Files that SHOULD be rejected ---

    def test_rejects_pyc_file(self, proj):
        assert not _is_relevant_change(str(proj / "module.pyc"), proj)

    def test_rejects_git_config(self, proj):
        assert not _is_relevant_change(str(proj / ".git" / "config"), proj)

    def test_rejects_node_modules(self, proj):
        assert not _is_relevant_change(str(proj / "node_modules" / "lodash" / "index.js"), proj)

    def test_rejects_pycache(self, proj):
        assert not _is_relevant_change(str(proj / "__pycache__" / "module.cpython-311.pyc"), proj)

    def test_rejects_package_lock_json(self, proj):
        """package-lock.json is in SKIP_FILENAMES."""
        assert not _is_relevant_change(str(proj / "package-lock.json"), proj)

    def test_rejects_ds_store(self, proj):
        assert not _is_relevant_change(str(proj / ".DS_Store"), proj)

    def test_rejects_egg_info_dir(self, proj):
        assert not _is_relevant_change(str(proj / "mypkg.egg-info" / "PKG-INFO"), proj)

    # --- include_ignored overrides ---

    def test_is_relevant_change_include_ignored(self, proj):
        """Explicitly included paths bypass SKIP_FILENAMES."""
        assert _is_relevant_change(
            str(proj / "package-lock.json"),
            proj,
            include_ignored=["package-lock.json"],
        )

    def test_include_ignored_bypasses_skip_dir(self, proj):
        """A file inside node_modules is accepted when explicitly force-included."""
        assert _is_relevant_change(
            str(proj / "node_modules" / "special.js"),
            proj,
            include_ignored=["node_modules/special.js"],
        )

    # --- Delete events ---

    def test_is_relevant_change_deleted_path(self, proj):
        """Delete event for a .py file returns True even though the file does not exist."""
        deleted = proj / "gone.py"
        assert not deleted.exists()
        assert _is_relevant_change(str(deleted), proj)

    def test_deleted_pyc_is_irrelevant(self, proj):
        """Delete event for a .pyc file is still filtered out."""
        assert not _is_relevant_change(str(proj / "gone.pyc"), proj)

    # --- Outside-project path ---

    def test_rejects_path_outside_project(self, proj, tmp_path):
        outside = tmp_path / "other" / "file.py"
        assert not _is_relevant_change(str(outside), proj)

    # --- gitignore filtering ---

    def test_gitignore_rejects_ignored_file(self, proj):
        """A file matched by .gitignore is rejected when respect_gitignore=True."""
        (proj / ".gitignore").write_text("secrets.txt\n", encoding="utf-8")
        assert not _is_relevant_change(str(proj / "secrets.txt"), proj, respect_gitignore=True)

    def test_gitignore_disabled(self, proj):
        """With respect_gitignore=False, gitignored files are accepted."""
        (proj / ".gitignore").write_text("secrets.txt\n", encoding="utf-8")
        assert _is_relevant_change(str(proj / "secrets.txt"), proj, respect_gitignore=False)

    # --- App-level scan excludes ---

    def test_app_scan_excludes_match_scan_project(self, proj):
        """AC-4: _is_relevant_change() rejects dirs, files, and globs that scan_project() excludes."""
        rules = ScanFilterRules(
            skip_dirs=frozenset([".kotlin-lsp"]),
            skip_files=frozenset(["workspace.json"]),
            skip_globs=["generated/**/*.js"],
        )

        # File inside excluded directory
        assert not _is_relevant_change(
            str(proj / ".kotlin-lsp" / "index.py"), proj, scan_rules=rules
        )
        # Excluded filename
        assert not _is_relevant_change(str(proj / "workspace.json"), proj, scan_rules=rules)
        # File matching glob pattern
        assert not _is_relevant_change(
            str(proj / "generated" / "bundle.js"), proj, scan_rules=rules
        )
        # Normal source file — still accepted
        assert _is_relevant_change(str(proj / "main.py"), proj, scan_rules=rules)

    def test_include_ignored_bypasses_app_scan_exclude(self, proj):
        """AC-6b: include_ignored paths bypass both app-level dir and file excludes."""
        rules = ScanFilterRules(
            skip_dirs=frozenset([".kotlin-lsp"]),
            skip_files=frozenset(["workspace.json"]),
            skip_globs=[],
        )

        # workspace.json bypassed by explicit include
        assert _is_relevant_change(
            str(proj / "workspace.json"),
            proj,
            include_ignored=["workspace.json"],
            scan_rules=rules,
        )
        # File inside excluded dir bypassed by explicit include of that file
        assert _is_relevant_change(
            str(proj / ".kotlin-lsp" / "special.py"),
            proj,
            include_ignored=[".kotlin-lsp/special.py"],
            scan_rules=rules,
        )

    # --- MINE-SCAN-GLOB-DIR-PRUNE: subtree skip-glob pruning ---

    def test_subtree_skip_glob_rejects_descendant_change(self, proj):
        """AC-2: _is_relevant_change() returns False for paths under a subtree skip glob."""
        rules = ScanFilterRules(
            skip_dirs=frozenset(),
            skip_files=frozenset(),
            skip_globs=["build/**"],
        )
        assert not _is_relevant_change(str(proj / "build" / "output.py"), proj, scan_rules=rules)
        assert not _is_relevant_change(
            str(proj / "build" / "sub" / "deep.py"), proj, scan_rules=rules
        )

    def test_subtree_skip_glob_multi_segment_prefix(self, proj):
        """Subtree glob with a multi-segment prefix (src/generated/**) prunes the right dir."""
        rules = ScanFilterRules(
            skip_dirs=frozenset(),
            skip_files=frozenset(),
            skip_globs=["src/generated/**"],
        )
        assert not _is_relevant_change(
            str(proj / "src" / "generated" / "api.py"), proj, scan_rules=rules
        )
        # Sibling directory is not affected
        assert _is_relevant_change(str(proj / "src" / "app.py"), proj, scan_rules=rules)

    def test_non_coverage_globs_remain_file_level_only(self, proj):
        """AC-3: file-specific globs don't prune the directory."""
        rules = ScanFilterRules(
            skip_dirs=frozenset(),
            skip_files=frozenset(),
            skip_globs=["generated/**/*.js"],
        )
        assert not _is_relevant_change(
            str(proj / "generated" / "bundle.js"), proj, scan_rules=rules
        )
        assert _is_relevant_change(str(proj / "generated" / "data.py"), proj, scan_rules=rules)

    def test_include_override_beats_subtree_skip_glob(self, proj):
        """AC-4: include_ignored path inside a subtree-pruned dir is accepted."""
        rules = ScanFilterRules(
            skip_dirs=frozenset(),
            skip_files=frozenset(),
            skip_globs=["build/**"],
        )
        assert _is_relevant_change(
            str(proj / "build" / "special.py"),
            proj,
            include_ignored=["build/special.py"],
            scan_rules=rules,
        )


# ---------------------------------------------------------------------------
# _invalidate_gitignore_cache() unit tests
# ---------------------------------------------------------------------------


class TestInvalidateGitignoreCache:
    def test_gitignore_event_evicts_cache_entry(self, tmp_path):
        """.gitignore modified event removes the directory's cache entry."""
        from watchfiles import Change

        gitignore_path = tmp_path / ".gitignore"
        cache = {tmp_path: "stale_matcher"}
        changes = {(Change.modified, str(gitignore_path))}
        _invalidate_gitignore_cache(changes, cache)
        assert tmp_path not in cache

    def test_gitignore_added_evicts_cache_entry(self, tmp_path):
        """.gitignore created event removes the directory's cache entry (previously None)."""
        from watchfiles import Change

        gitignore_path = tmp_path / ".gitignore"
        cache = {tmp_path: None}
        changes = {(Change.added, str(gitignore_path))}
        _invalidate_gitignore_cache(changes, cache)
        assert tmp_path not in cache

    def test_gitignore_deleted_evicts_cache_entry(self, tmp_path):
        """.gitignore deleted event removes the directory's cache entry."""
        from watchfiles import Change

        gitignore_path = tmp_path / ".gitignore"
        cache = {tmp_path: "stale_matcher"}
        changes = {(Change.deleted, str(gitignore_path))}
        _invalidate_gitignore_cache(changes, cache)
        assert tmp_path not in cache

    def test_non_gitignore_event_leaves_cache_unchanged(self, tmp_path):
        """Non-.gitignore file event does not modify the cache."""
        from watchfiles import Change

        py_file = tmp_path / "app.py"
        cache = {tmp_path: "matcher"}
        changes = {(Change.modified, str(py_file))}
        _invalidate_gitignore_cache(changes, cache)
        assert cache == {tmp_path: "matcher"}

    def test_missing_cache_key_is_noop(self, tmp_path):
        """pop on an absent key is a no-op (no KeyError)."""
        from watchfiles import Change

        gitignore_path = tmp_path / ".gitignore"
        cache: dict = {}
        changes = {(Change.modified, str(gitignore_path))}
        _invalidate_gitignore_cache(changes, cache)
        assert cache == {}


# ---------------------------------------------------------------------------
# watch_and_mine() integration — mocked watchfiles and mine()
# ---------------------------------------------------------------------------


class TestWatchAndMine:
    """Integration tests that mock watchfiles.watch and mine() for speed and determinism."""

    def test_watch_detects_file_change(self, tmp_path):
        """Changed .py file triggers a re-mine cycle."""
        from watchfiles import Change

        project = tmp_path / "proj"
        project.mkdir()
        py_file = project / "code.py"

        changes = [{(Change.modified, str(py_file))}]
        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory(changes)),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        # Initial mine + 1 re-mine cycle
        assert len(mine_calls) == 2
        assert mine_calls[0]["incremental"] is True
        assert mine_calls[1]["incremental"] is True

    def test_watch_skips_irrelevant_changes(self, tmp_path):
        """Changes to .pyc files do not trigger a re-mine cycle."""
        from watchfiles import Change

        project = tmp_path / "proj"
        project.mkdir()
        pyc_file = project / "code.pyc"

        changes = [{(Change.modified, str(pyc_file))}]
        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory(changes)),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        # Only the initial mine; no re-mine for .pyc
        assert len(mine_calls) == 1

    def test_watch_detects_file_deletion(self, tmp_path):
        """Delete event for a .py file triggers a re-mine (stale-sweep handled by mine)."""
        from watchfiles import Change

        project = tmp_path / "proj"
        project.mkdir()
        py_file = project / "old.py"
        # File does not exist on disk (simulates delete event)
        changes = [{(Change.deleted, str(py_file))}]
        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory(changes)),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        # Initial mine + 1 re-mine triggered by delete event
        assert len(mine_calls) == 2

    def test_watch_passes_kg_to_mine(self, tmp_path):
        """watch_and_mine() passes the kg instance through to every mine() call."""
        from watchfiles import Change

        project = tmp_path / "proj"
        project.mkdir()
        py_file = project / "code.py"

        changes = [{(Change.modified, str(py_file))}]
        mine_calls = []
        fake_kg = MagicMock()

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory(changes)),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"), kg=fake_kg)

        assert all(c["kg"] is fake_kg for c in mine_calls)

    def test_watch_keyboard_interrupt_exits_cleanly(self, tmp_path):
        """KeyboardInterrupt (Ctrl-C) exits without raising."""
        project = tmp_path / "proj"
        project.mkdir()

        def fake_watch(*args, **kwargs):
            raise KeyboardInterrupt

        with (
            patch("mempalace_code.watcher.mine"),
            patch("watchfiles.watch", side_effect=fake_watch),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

    def test_watch_nonexistent_dir_exits_1(self, tmp_path, capsys):
        """watch_and_mine() exits with code 1 if project_dir doesn't exist."""
        with pytest.raises(SystemExit) as exc_info:
            watch_and_mine(str(tmp_path / "nonexistent"), str(tmp_path / "palace"))
        assert exc_info.value.code == 1

    def test_watch_passes_respect_gitignore_and_include_ignored(self, tmp_path):
        """watch_and_mine() forwards respect_gitignore and include_ignored to mine()."""
        project = tmp_path / "proj"
        project.mkdir()
        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
        ):
            watch_and_mine(
                str(project),
                str(tmp_path / "palace"),
                respect_gitignore=False,
                include_ignored=["vendor/special.py"],
            )

        assert mine_calls[0]["respect_gitignore"] is False
        assert mine_calls[0]["include_ignored"] == ["vendor/special.py"]

    def test_watch_reload_scan_rules_after_config_edit(self, tmp_path, monkeypatch):
        """Config edit adding workspace.json to scan_skip_files filters the next batch."""
        from watchfiles import Change

        project = tmp_path / "proj"
        project.mkdir()

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        mempalace_dir = fake_home / ".mempalace"
        mempalace_dir.mkdir()
        config_file = mempalace_dir / "config.json"
        config_file.write_text(json.dumps({"scan_skip_files": []}), encoding="utf-8")
        past = time.time() - 2
        os.utime(config_file, (past, past))

        monkeypatch.setenv("HOME", str(fake_home))

        def fake_watch(*args, stop_event=None, **kwargs):
            config_file.write_text(
                json.dumps({"scan_skip_files": ["workspace.json"]}), encoding="utf-8"
            )
            yield {(Change.modified, str(project / "workspace.json"))}

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=fake_watch),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        # Only the initial mine — workspace.json was filtered by the refreshed rules
        assert len(mine_calls) == 1


class TestWatcherOperationLease:
    def test_watcher_refuses_while_update_owns_exclusive_lease(self, tmp_path, capsys):
        project = tmp_path / "proj"
        project.mkdir()
        lock = OperationLock(tmp_path / "operation.lock")

        with lock.acquire_exclusive("update"):
            with pytest.raises(SystemExit) as exc_info:
                watch_and_mine(str(project), str(tmp_path / "palace"), operation_lock=lock)

        assert exc_info.value.code == 3
        assert "Watcher refused" in capsys.readouterr().err

    def test_watcher_releases_shared_lease_after_shutdown(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        lock = OperationLock(tmp_path / "operation.lock")

        with (
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"), operation_lock=lock)

        with lock.acquire_exclusive("update"):
            pass


# ---------------------------------------------------------------------------
# Graceful watcher shutdown signals
# ---------------------------------------------------------------------------


class TestWatcherShutdownSignals:
    @pytest.mark.parametrize("entrypoint", ["watch_and_mine", "watch_all"])
    def test_immediate_sigint_after_watch_ready_is_clean(self, tmp_path, capsys, entrypoint):
        project = tmp_path / "project"
        _make_project(project)
        supported_signals = [signal.SIGTERM]
        if hasattr(signal, "SIGHUP"):
            supported_signals.append(signal.SIGHUP)

        original_handlers = {
            shutdown_signal: signal.SIG_DFL for shutdown_signal in supported_signals
        }
        current_handlers = dict(original_handlers)
        signal_calls = []
        emitted_states = []
        original_emit_run_state = watcher_module._emit_run_state
        watch_mock = MagicMock(side_effect=AssertionError("watch loop must not start"))

        def fake_getsignal(shutdown_signal):
            return current_handlers[shutdown_signal]

        def fake_signal(shutdown_signal, handler):
            signal_calls.append((shutdown_signal, handler))
            current_handlers[shutdown_signal] = handler

        def interrupt_after_ready(run_id, state, extra=""):
            original_emit_run_state(run_id, state, extra)
            emitted_states.append(state)
            if state == "watch-ready":
                raise KeyboardInterrupt

        with (
            patch("mempalace_code.watcher.signal.getsignal", side_effect=fake_getsignal),
            patch("mempalace_code.watcher.signal.signal", side_effect=fake_signal),
            patch("mempalace_code.watcher._emit_run_state", side_effect=interrupt_after_ready),
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("mempalace_code.watcher.get_collection"),
            patch("watchfiles.watch", new=watch_mock),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
        ):
            if entrypoint == "watch_and_mine":
                watch_and_mine(str(project), str(tmp_path / "palace"))
            else:
                watch_all(str(project), str(tmp_path / "palace"), on_commit=False)

        assert emitted_states[-1] == "watch-ready"
        watch_mock.assert_not_called()
        assert [call[0] for call in signal_calls[: len(supported_signals)]] == supported_signals
        assert [call[0] for call in signal_calls[-len(supported_signals) :]] == list(
            reversed(supported_signals)
        )
        assert current_handlers == original_handlers

        captured = capsys.readouterr()
        combined_output = captured.out + captured.err
        assert "Watch stopped after" in captured.out
        expected_summary = (
            "0 re-mine cycle(s), 0 file event(s)."
            if entrypoint == "watch_and_mine"
            else "0 re-mine cycle(s), 0 event(s) across 1 project(s)."
        )
        assert expected_summary in captured.out
        assert "Traceback" not in combined_output

    @pytest.mark.parametrize("entrypoint", ["watch_and_mine", "watch_all"])
    def test_entrypoints_register_deliver_and_restore_supported_signals(self, tmp_path, entrypoint):
        project = tmp_path / "project"
        _make_project(project)
        supported_signals = [signal.SIGTERM]
        if hasattr(signal, "SIGHUP"):
            supported_signals.append(signal.SIGHUP)

        def original_sigterm_handler(_signum: int, _frame: FrameType | None) -> None:
            pass

        original_handlers: dict[int, Callable[[int, FrameType | None], object] | int | None] = {
            shutdown_signal: (
                original_sigterm_handler if shutdown_signal == signal.SIGTERM else signal.SIG_DFL
            )
            for shutdown_signal in supported_signals
        }
        current_handlers = dict(original_handlers)
        signal_calls = []

        def fake_getsignal(shutdown_signal):
            return current_handlers[shutdown_signal]

        def fake_signal(shutdown_signal, handler):
            signal_calls.append((shutdown_signal, handler))
            current_handlers[shutdown_signal] = handler

        def fake_watch(*args, stop_event=None, **kwargs):
            assert stop_event is not None
            assert stop_event.is_set() is False
            for shutdown_signal in supported_signals:
                handler = current_handlers[shutdown_signal]
                assert callable(handler)
                handler(shutdown_signal, None)
                handler(shutdown_signal, None)
            assert stop_event.is_set() is True
            return iter([])

        with (
            patch("mempalace_code.watcher.signal.getsignal", side_effect=fake_getsignal),
            patch("mempalace_code.watcher.signal.signal", side_effect=fake_signal),
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("mempalace_code.watcher.get_collection"),
            patch("watchfiles.watch", side_effect=fake_watch),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
        ):
            if entrypoint == "watch_and_mine":
                watch_and_mine(str(project), str(tmp_path / "palace"))
            else:
                watch_all(str(project), str(tmp_path / "palace"), on_commit=False)

        assert [call[0] for call in signal_calls[: len(supported_signals)]] == supported_signals
        assert [call[0] for call in signal_calls[-len(supported_signals) :]] == list(
            reversed(supported_signals)
        )
        assert current_handlers == original_handlers
        assert all(shutdown_signal != signal.SIGINT for shutdown_signal, _ in signal_calls)

    def test_watch_iteration_error_restores_every_handler(self, tmp_path):
        project = tmp_path / "project"
        _make_project(project)
        supported_signals = [signal.SIGTERM]
        if hasattr(signal, "SIGHUP"):
            supported_signals.append(signal.SIGHUP)
        original_handlers: dict[int, Callable[[int, FrameType | None], object] | int | None] = {
            shutdown_signal: signal.SIG_DFL for shutdown_signal in supported_signals
        }
        current_handlers = dict(original_handlers)

        def fake_signal(shutdown_signal, handler):
            current_handlers[shutdown_signal] = handler

        with (
            patch(
                "mempalace_code.watcher.signal.getsignal",
                side_effect=lambda shutdown_signal: current_handlers[shutdown_signal],
            ),
            patch("mempalace_code.watcher.signal.signal", side_effect=fake_signal),
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("mempalace_code.watcher.get_collection"),
            patch("watchfiles.watch", side_effect=RuntimeError("watch iteration failed")),
            pytest.raises(RuntimeError, match="watch iteration failed"),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        assert current_handlers == original_handlers

    def test_partial_registration_failure_restores_replaced_handler(self):
        if not hasattr(signal, "SIGHUP"):
            pytest.skip("SIGHUP is unavailable on this platform")

        original_sigterm = signal.SIG_DFL
        current_sigterm = original_sigterm

        def fake_getsignal(shutdown_signal):
            return original_sigterm if shutdown_signal == signal.SIGTERM else signal.SIG_IGN

        def fake_signal(shutdown_signal, handler):
            nonlocal current_sigterm
            if shutdown_signal == signal.SIGHUP:
                raise OSError("SIGHUP registration failed")
            current_sigterm = handler

        shutdown_signals = _WatcherShutdownSignals()
        with (
            patch("mempalace_code.watcher.signal.getsignal", side_effect=fake_getsignal),
            patch("mempalace_code.watcher.signal.signal", side_effect=fake_signal),
            pytest.raises(OSError, match="SIGHUP registration failed"),
        ):
            shutdown_signals.install()

        assert current_sigterm is original_sigterm

    def test_runtime_without_sighup_registers_only_sigterm(self):
        original_sigterm = signal.SIG_DFL
        signal_calls = []

        with (
            patch.object(signal, "SIGHUP", None),
            patch("mempalace_code.watcher.signal.getsignal", return_value=original_sigterm),
            patch(
                "mempalace_code.watcher.signal.signal",
                side_effect=lambda shutdown_signal, handler: signal_calls.append(
                    (shutdown_signal, handler)
                ),
            ),
        ):
            shutdown_signals = _WatcherShutdownSignals()
            shutdown_signals.install()
            shutdown_signals.restore()
            shutdown_signals.restore()

        assert [shutdown_signal for shutdown_signal, _ in signal_calls] == [
            signal.SIGTERM,
            signal.SIGTERM,
        ]
        assert signal_calls[-1][1] is original_sigterm


# ---------------------------------------------------------------------------
# ImportError message when watchfiles is missing
# ---------------------------------------------------------------------------


class TestImportError:
    def test_import_error_message(self, tmp_path, capsys):
        """Clear error message is printed when watchfiles is not installed."""
        project = tmp_path / "proj"
        project.mkdir()

        with patch.dict(sys.modules, {"watchfiles": None}), pytest.raises(SystemExit) as exc_info:
            watch_and_mine(str(project), str(tmp_path / "palace"))

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "watchfiles" in captured.err
        assert "mempalace-code[watch]" in captured.err


# ---------------------------------------------------------------------------
# CLI dispatch test
# ---------------------------------------------------------------------------


class TestCliWatchDispatch:
    def test_cli_watch_dispatches_to_watcher_module(self, tmp_path):
        """cmd_mine imports and calls watch_and_mine() from mempalace_code.watcher."""
        project = tmp_path / "proj"
        _make_project(project)
        palace = tmp_path / "palace"

        watch_calls = []

        def fake_watch(**kw):
            watch_calls.append(kw)

        # Patch watch_and_mine at the module level before cmd_mine imports it
        with patch("mempalace_code.watcher.watch_and_mine", side_effect=fake_watch):
            argv = [
                "mempalace",
                "--palace",
                str(palace),
                "mine",
                str(project),
                "--watch",
            ]
            with patch.object(sys, "argv", argv):
                main()

        assert len(watch_calls) == 1
        assert watch_calls[0]["project_dir"] == str(project)
        assert watch_calls[0]["palace_path"] == str(palace)
        assert watch_calls[0]["respect_gitignore"] is True


# ---------------------------------------------------------------------------
# Watch scheduler rendering
# ---------------------------------------------------------------------------


class TestRenderWatchSchedule:
    def test_default_bin_falls_back_to_mempalace_code_module(self, tmp_path, monkeypatch):
        """Generated daemon snippets should run the renamed package module."""
        monkeypatch.setattr("shutil.which", lambda _name: None)
        # Write an init marker so the root guard allows rendering.
        (tmp_path / "mempalace.yaml").write_text("wing: test\n")

        out = render_watch_schedule(str(tmp_path), "linux")

        assert f"{shlex.quote(sys.executable)} -m mempalace_code watch" in out
        assert "-m mempalace watch" not in out

    def test_darwin_plist_bounds_respawn_with_throttle_interval(self, tmp_path):
        """Darwin plist contains ThrottleInterval so crash-looping jobs can't respawn unbounded."""
        (tmp_path / "mempalace.yaml").write_text("wing: test\n")
        plist = render_watch_schedule(str(tmp_path), "darwin")
        assert "<key>ThrottleInterval</key>" in plist
        assert "<integer>60</integer>" in plist

    def test_invoked_launcher_precedes_conflicting_path(self, tmp_path, monkeypatch):
        (tmp_path / "mempalace.yaml").write_text("wing: test\n")
        invoked_dir = tmp_path / "invoked bin"
        ambient_dir = tmp_path / "ambient-bin"
        invoked_dir.mkdir()
        ambient_dir.mkdir()
        invoked = invoked_dir / "mempalace-code"
        ambient = ambient_dir / "mempalace-code"
        for executable in (invoked, ambient):
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
        monkeypatch.setenv("PATH", str(ambient_dir))
        monkeypatch.setattr(sys, "argv", [str(invoked), "watch", "schedule"])

        out = render_watch_schedule(str(tmp_path), "linux")

        assert shlex.quote(str(invoked)) in out
        assert str(ambient) not in out

    @pytest.mark.parametrize("platform", ["linux", "darwin"])
    def test_rendered_command_executes_launcher_and_preserves_arguments(self, tmp_path, platform):
        watch_root = tmp_path / "watch root ; path"
        watch_root.mkdir()
        (watch_root / "mempalace.yaml").write_text("wing: test\n", encoding="utf-8")
        launcher = tmp_path / "launcher ; path" / "mempalace-code"
        record = tmp_path / "recorded argv"
        launcher.parent.mkdir()
        launcher.write_text(
            f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {shlex.quote(str(record))}\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)

        snippet = render_watch_schedule(str(watch_root), platform, mempalace_bin=str(launcher))
        if platform == "linux":
            command = snippet.removeprefix("@reboot ").rstrip()
            subprocess.run(["/bin/sh", "-c", command], check=True)
        else:
            arguments = plistlib.loads(snippet.encode())["ProgramArguments"]
            subprocess.run(arguments, check=True)

        assert record.read_text(encoding="utf-8").splitlines() == [
            "watch",
            str(watch_root.resolve()),
        ]

    def test_command_handler_reuses_selected_launcher_in_deterministic_guidance(
        self, tmp_path, monkeypatch, capsys
    ):
        watch_root = tmp_path / "watch root ; quoted"
        watch_root.mkdir()
        (watch_root / "mempalace.yaml").write_text("wing: test\n")
        invoked = tmp_path / "invoked bin" / "mempalace-code"
        ambient = tmp_path / "ambient-bin" / "mempalace-code"
        home = tmp_path / "home with spaces"
        for directory in (invoked.parent, ambient.parent, home):
            directory.mkdir()
        for executable in (invoked, ambient):
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
        args = Namespace(dir=str(watch_root), install=False)
        monkeypatch.setenv("PATH", str(ambient.parent))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(sys, "argv", [str(invoked), "watch", "schedule"])
        before = tuple(sorted(tmp_path.rglob("*")))

        cmd_watch_schedule(args)
        first = capsys.readouterr()
        cmd_watch_schedule(args)
        second = capsys.readouterr()

        assert first == second
        assert shlex.quote(str(invoked)) in first.out
        assert shlex.quote(str(invoked)) in first.err
        assert str(ambient) not in first.out + first.err
        assert shlex.quote(str(watch_root.resolve())) in first.out + first.err
        assert (
            shlex.quote(str(home / "Library/LaunchAgents/com.mempalace.watch.plist")) in first.err
        )
        assert tuple(sorted(tmp_path.rglob("*"))) == before

    def test_install_refusal_names_selected_launcher_and_explicit_targets(
        self, tmp_path, monkeypatch, capsys
    ):
        invoked = tmp_path / "bin with spaces" / "mempalace-code"
        invoked.parent.mkdir()
        invoked.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        invoked.chmod(0o755)
        watch_root = tmp_path / "watch root with spaces"
        monkeypatch.setattr(sys, "argv", [str(invoked), "watch", "schedule"])

        with pytest.raises(SystemExit) as exc_info:
            cmd_watch_schedule(Namespace(dir=str(watch_root), install=True))

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert shlex.quote(str(invoked)) in captured.err
        assert shlex.quote(str(watch_root.resolve())) in captured.err
        assert "com.mempalace.watch.plist" in captured.err


# ---------------------------------------------------------------------------
# render_watch_schedule root guard tests (AC-2, AC-3, AC-4)
# ---------------------------------------------------------------------------


class TestRenderWatchScheduleRootGuard:
    def test_uninitialized_parent_root_refused(self, tmp_path):
        """render_watch_schedule raises ValueError for a parent with no initialized children,
        naming the root path and the supported root shapes per AC-2."""
        with patch("mempalace_code.mining.projects.detect_projects", return_value=[]):
            with pytest.raises(ValueError, match="Supported watch roots") as exc_info:
                render_watch_schedule(str(tmp_path), "linux")
        msg = str(exc_info.value)
        assert str(tmp_path) in msg, "error must name the refused root path"
        assert "Supported watch roots" in msg, "error must list supported root shapes"

    def test_initialized_root_renders_snippet(self, tmp_path):
        """Initialized project root renders a schedule snippet."""
        (tmp_path / "mempalace.yaml").write_text("wing: test\n")
        snippet = render_watch_schedule(str(tmp_path), "linux")
        assert "@reboot" in snippet

    def test_parent_with_initialized_children_renders_snippet(self, tmp_path):
        """Parent dir with at least one initialized child renders a schedule snippet."""
        child = tmp_path / "myproject"
        child.mkdir()
        (child / "mempalace.yaml").write_text("wing: child_wing\n")

        fake_projects = [{"path": str(child), "initialized": True}]

        with patch("mempalace_code.mining.projects.detect_projects", return_value=fake_projects):
            snippet = render_watch_schedule(str(tmp_path), "linux")
        assert "@reboot" in snippet

    def test_uninitialized_project_root_names_init_command(self, tmp_path):
        """Project root with project markers but no init file gets exact init command in error."""
        # Has a project marker (.git) but no mempalace.yaml
        (tmp_path / ".git").mkdir()

        with pytest.raises(ValueError, match="mempalace-code init"):
            render_watch_schedule(str(tmp_path), "linux")


class TestWatchRootProjectMarkerClassification:
    @pytest.mark.parametrize("marker", ["pyproject.toml", "Guard.sln"])
    def test_regular_project_file_marker_keeps_actionable_schedule_error(self, tmp_path, marker):
        (tmp_path / marker).write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match=f"mempalace-code init {tmp_path}"):
            render_watch_schedule(str(tmp_path), "linux")

    @pytest.mark.parametrize("git_shape", ["directory", "file"])
    def test_supported_git_shape_keeps_actionable_watch_error(self, tmp_path, capsys, git_shape):
        git_marker = tmp_path / ".git"
        if git_shape == "directory":
            git_marker.mkdir()
        else:
            git_marker.write_text("gitdir: ../git-data\n", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            watch_all(str(tmp_path), str(tmp_path / "palace"))

        assert exc_info.value.code == 1
        assert f"mempalace-code init {tmp_path}" in capsys.readouterr().err

    def test_irregular_project_marker_fails_closed_as_parent(self, tmp_path, capsys):
        target = tmp_path / "git-data"
        target.mkdir()
        try:
            (tmp_path / ".git").symlink_to(target, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        with pytest.raises(SystemExit) as exc_info:
            watch_all(str(tmp_path), str(tmp_path / "palace"))

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "No initialized projects found" in combined
        assert "is a project directory" not in combined

    def test_irregular_init_marker_does_not_hide_initialized_child(self, tmp_path):
        target = tmp_path / "config-target.yaml"
        target.write_text("wing: wrong-root\n", encoding="utf-8")
        try:
            (tmp_path / "mempalace.yaml").symlink_to(target)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        child = tmp_path / "child"
        child.mkdir()
        (child / "pyproject.toml").write_text("", encoding="utf-8")
        (child / "mempalace.yaml").write_text("wing: child-wing\n", encoding="utf-8")
        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)
            return {}

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", return_value=iter([])),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
        ):
            watch_all(str(tmp_path), str(tmp_path / "palace"), on_commit=False)

        assert [call["project_dir"] for call in mine_calls] == [str(child)]
        assert mine_calls[0]["wing_override"] == "child_wing"
        assert render_watch_schedule(str(tmp_path), "linux").startswith("@reboot ")


# ---------------------------------------------------------------------------
# watch_all() on-save high-churn pruning and warning (AC-5)
# ---------------------------------------------------------------------------


class TestWatchAllHighChurnPrune:
    def test_on_save_prunes_skip_dirs_and_warns(self, tmp_path, capsys):
        """watch_all on-save passes extended ignore filter and warns about churn dirs found."""
        from mempalace_code.mining.scanner import SKIP_DIRS

        project = tmp_path / "proj"
        project.mkdir()
        (project / "mempalace.yaml").write_text("wing: test_wing\n")
        # Create a couple of high-churn dirs so the warning fires
        (project / "node_modules").mkdir()
        (project / ".venv").mkdir()

        watch_filter_seen = []

        def fake_watch(*args, watch_filter=None, stop_event=None, **kwargs):
            watch_filter_seen.append(watch_filter)
            return iter([])

        with (
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("watchfiles.watch", side_effect=fake_watch),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
        ):
            watch_all(str(project), str(tmp_path / "palace"), on_commit=False)

        # Filter must have been passed and must include all SKIP_DIRS entries
        assert len(watch_filter_seen) == 1
        filt = watch_filter_seen[0]
        assert filt is not None
        # _ignore_dirs is the compiled set BaseFilter builds from ignore_dirs
        assert all(d in filt._ignore_dirs for d in SKIP_DIRS)

        # Pre-start warning must name the churn dirs actually found
        captured = capsys.readouterr()
        assert "node_modules" in captured.out
        assert ".venv" in captured.out
        assert "high-churn" in captured.out


# ---------------------------------------------------------------------------
# watch_all() — on_commit=False live-reload test (AC-2)
# ---------------------------------------------------------------------------


class TestWatchAll:
    def test_watch_all_on_save_reload_scan_rules_after_config_edit(self, tmp_path, monkeypatch):
        """watch_all on_commit=False reloads scan rules mid-watch; skipped file is not re-mined."""
        from watchfiles import Change

        from mempalace_code.watcher import watch_all

        project = tmp_path / "proj"
        project.mkdir()

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        mempalace_dir = fake_home / ".mempalace"
        mempalace_dir.mkdir()
        config_file = mempalace_dir / "config.json"
        config_file.write_text(json.dumps({"scan_skip_files": []}), encoding="utf-8")
        past = time.time() - 2
        os.utime(config_file, (past, past))

        monkeypatch.setenv("HOME", str(fake_home))

        def fake_watch(*args, stop_event=None, **kwargs):
            config_file.write_text(
                json.dumps({"scan_skip_files": ["workspace.json"]}), encoding="utf-8"
            )
            yield {(Change.modified, str(project / "workspace.json"))}

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        fake_projects = [{"path": str(project), "initialized": True}]

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=fake_watch),
            patch("mempalace_code.mining.projects.detect_projects", return_value=fake_projects),
            patch("mempalace_code.mining.projects.derive_wing_name", return_value="test_wing"),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
        ):
            watch_all(str(tmp_path), str(tmp_path / "palace"), on_commit=False)

        # Only the initial mine — workspace.json was filtered by the refreshed rules
        assert len(mine_calls) == 1

    def test_watch_all_duplicate_wings_exit_before_initial_mine(self, tmp_path, capsys):
        """AC-6: two initialized projects resolving to the same wing → exit 1 before mine/watch."""
        from mempalace_code.watcher import watch_all

        proj_a = tmp_path / "proj_a"
        proj_a.mkdir()
        (proj_a / "mempalace.yaml").write_text("wing: same_wing\n")

        proj_b = tmp_path / "proj_b"
        proj_b.mkdir()
        (proj_b / "mempalace.yaml").write_text("wing: same_wing\n")

        fake_projects = [
            {"path": str(proj_a), "initialized": True},
            {"path": str(proj_b), "initialized": True},
        ]

        mine_calls = []

        with (
            patch("mempalace_code.watcher.mine", side_effect=mine_calls.append),
            patch("mempalace_code.mining.projects.detect_projects", return_value=fake_projects),
        ):
            with pytest.raises(SystemExit) as exc_info:
                watch_all(str(tmp_path), str(tmp_path / "palace"))

        assert exc_info.value.code == 1
        assert len(mine_calls) == 0

        err = capsys.readouterr().err
        assert "same_wing" in err
        assert "proj_a" in err
        assert "proj_b" in err

    def test_watch_all_uses_configured_wings(self, tmp_path, monkeypatch):
        """watch_all reads wing from mempalace.yaml and passes it to mine()."""
        from mempalace_code.watcher import watch_all

        project = tmp_path / "my_proj"
        project.mkdir()
        (project / "mempalace.yaml").write_text("wing: configured_wing\n")

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".mempalace").mkdir()
        config_file = fake_home / ".mempalace" / "config.json"
        config_file.write_text(json.dumps({}), encoding="utf-8")
        past = time.time() - 2
        os.utime(config_file, (past, past))
        monkeypatch.setenv("HOME", str(fake_home))

        def fake_watch(*args, stop_event=None, **kwargs):
            return iter([])

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        fake_projects = [{"path": str(project), "initialized": True}]

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=fake_watch),
            patch("mempalace_code.mining.projects.detect_projects", return_value=fake_projects),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
        ):
            watch_all(str(tmp_path), str(tmp_path / "palace"), on_commit=False)

        assert any(c["wing_override"] == "configured_wing" for c in mine_calls)


# ---------------------------------------------------------------------------
# _ScanRulesSnapshot unit tests (AC-3, AC-4, AC-5)
# ---------------------------------------------------------------------------


class TestWatchScanRuleReload:
    def test_malformed_config_keeps_last_good_rules(self, tmp_path, monkeypatch):
        """Malformed config.json does not raise; previous ScanFilterRules decide relevance."""
        from watchfiles import Change

        project = tmp_path / "proj"
        project.mkdir()

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        mempalace_dir = fake_home / ".mempalace"
        mempalace_dir.mkdir()
        config_file = mempalace_dir / "config.json"
        config_file.write_text(
            json.dumps({"scan_skip_files": ["workspace.json"]}), encoding="utf-8"
        )
        past = time.time() - 2
        os.utime(config_file, (past, past))

        monkeypatch.setenv("HOME", str(fake_home))

        def fake_watch(*args, stop_event=None, **kwargs):
            config_file.write_text("{bad json", encoding="utf-8")
            yield {(Change.modified, str(project / "workspace.json"))}

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=fake_watch),
        ):
            # Must not raise despite malformed config
            watch_and_mine(str(project), str(tmp_path / "palace"))

        # Previous rules (skip workspace.json) still apply — no re-mine triggered
        assert len(mine_calls) == 1

    def test_config_created_after_watch_start_reloads_rules(self, tmp_path, monkeypatch):
        """Config created mid-watch causes rules to reload on the next batch."""
        from watchfiles import Change

        project = tmp_path / "proj"
        project.mkdir()

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".mempalace").mkdir()
        config_file = fake_home / ".mempalace" / "config.json"
        # No config initially — defaults apply (workspace.json not in skip_files)

        monkeypatch.setenv("HOME", str(fake_home))

        def fake_watch(*args, stop_event=None, **kwargs):
            config_file.write_text(
                json.dumps({"scan_skip_files": ["workspace.json"]}), encoding="utf-8"
            )
            yield {(Change.modified, str(project / "workspace.json"))}

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=fake_watch),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        # Config created mid-watch loaded new rules; workspace.json filtered — no re-mine
        assert len(mine_calls) == 1

    def test_reload_check_runs_once_per_batch(self, tmp_path, monkeypatch):
        """A batch with multiple changed files triggers exactly one config freshness check."""
        from watchfiles import Change

        import mempalace_code.watcher as watcher_module

        project = tmp_path / "proj"
        project.mkdir()

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".mempalace").mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        batch = {
            (Change.modified, str(project / "a.py")),
            (Change.modified, str(project / "b.py")),
            (Change.modified, str(project / "c.py")),
        }

        refresh_calls = []
        original_refresh = watcher_module._ScanRulesSnapshot.refresh

        def tracking_refresh(self):
            refresh_calls.append(True)
            return original_refresh(self)

        with (
            patch.object(watcher_module._ScanRulesSnapshot, "refresh", tracking_refresh),
            patch("mempalace_code.watcher.mine", return_value=None),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([batch])),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        # One batch → exactly one refresh call
        assert len(refresh_calls) == 1

    def test_snapshot_recovers_after_malformed_then_fixed_config(self, tmp_path, monkeypatch):
        """Bad config sets _bad_mtime; subsequent good write with new mtime reloads rules."""
        import mempalace_code.watcher as watcher_module

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        mempalace_dir = fake_home / ".mempalace"
        mempalace_dir.mkdir()
        config_file = mempalace_dir / "config.json"
        config_file.write_text(json.dumps({"scan_skip_files": []}), encoding="utf-8")
        os.utime(config_file, (time.time() - 10, time.time() - 10))

        monkeypatch.setenv("HOME", str(fake_home))

        initial_rules = ScanFilterRules(
            skip_dirs=frozenset(),
            skip_files=frozenset(),
            skip_globs=[],
        )
        snapshot = watcher_module._ScanRulesSnapshot(initial_rules)

        # Step 1: write malformed JSON with a newer mtime — refresh keeps last-good rules.
        config_file.write_text("{not valid json", encoding="utf-8")
        os.utime(config_file, (time.time() - 5, time.time() - 5))
        rules_after_bad = snapshot.refresh()
        assert rules_after_bad is initial_rules
        assert snapshot._bad_mtime is not watcher_module._UNSET

        # Step 2: write good JSON with a newer mtime — refresh reloads and clears bad_mtime.
        config_file.write_text(
            json.dumps({"scan_skip_files": ["workspace.json"]}), encoding="utf-8"
        )
        os.utime(config_file, (time.time(), time.time()))
        rules_after_fix = snapshot.refresh()
        assert rules_after_fix is not initial_rules
        assert "workspace.json" in rules_after_fix.skip_files
        assert snapshot._bad_mtime is watcher_module._UNSET


# ---------------------------------------------------------------------------
# _optimize_once — safe optimize outcome tests
# ---------------------------------------------------------------------------


class TestOptimizeOnce:
    """Watcher optimize routing through optimize_store."""

    def test_safety_check_failure_reports_truthful_outcome(self, capsys):
        """optimize_store() returning ok=False → output reports skipped."""
        from mempalace_code.storage import OptimizeResult
        from mempalace_code.watcher import _optimize_once

        mock_open = MagicMock()
        with patch(
            "mempalace_code.watcher.optimize_store",
            return_value=OptimizeResult(ok=False, supported=True),
        ):
            with patch("mempalace_code.config.MempalaceConfig") as mock_cfg_cls:
                mock_cfg_cls.return_value.backup_before_optimize = True
                outcome = _optimize_once("/fake/palace", mock_open)

        captured = capsys.readouterr()
        assert outcome == "skipped:safety-check"
        assert "skipped (safety check failed; see preceding error)" in captured.out
        assert "backup gate" not in captured.out.lower()

    def test_safe_optimize_success_prints_done(self, capsys):
        """optimize_store() returning ok=True → output shows done."""
        from mempalace_code.storage import OptimizeResult
        from mempalace_code.watcher import _optimize_once

        mock_open = MagicMock()
        with patch(
            "mempalace_code.watcher.optimize_store",
            return_value=OptimizeResult(ok=True, supported=True),
        ):
            with patch("mempalace_code.config.MempalaceConfig") as mock_cfg_cls:
                mock_cfg_cls.return_value.backup_before_optimize = True
                outcome = _optimize_once("/fake/palace", mock_open)

        captured = capsys.readouterr()
        assert outcome == "completed"
        assert "done" in captured.out

    def test_optimize_exception_reports_error_outcome(self, capsys):
        """Raised optimize errors retain their precise text and error outcome."""
        from mempalace_code.watcher import _optimize_once

        with (
            patch(
                "mempalace_code.watcher.optimize_store",
                side_effect=RuntimeError("concurrent optimize conflict"),
            ),
            patch("mempalace_code.config.MempalaceConfig") as mock_cfg_cls,
        ):
            mock_cfg_cls.return_value.backup_before_optimize = True
            outcome = _optimize_once("/fake/palace", MagicMock())

        captured = capsys.readouterr()
        assert outcome == "skipped:error"
        assert "skipped (concurrent optimize conflict)" in captured.out

    def test_store_without_safe_optimize_uses_raw_optimize(self, capsys):
        """Stores without safe_optimize fall back to raw optimize()."""
        from mempalace_code.watcher import _optimize_once

        class _StoreNoSafe:
            def optimize(self):
                pass

        mock_store = MagicMock(spec=_StoreNoSafe)
        mock_open = MagicMock(return_value=mock_store)

        _optimize_once("/fake/palace", mock_open)

        mock_store.optimize.assert_called_once()
        captured = capsys.readouterr()
        assert "done" in captured.out


# Disk-budget gating tests (AC-1, AC-2, AC-3)
# ---------------------------------------------------------------------------


class TestWatchAndMineDiskBudget:
    """Unit tests for disk-budget gating in watch_and_mine()."""

    def test_ac1_budget_ok_mine_is_called(self, tmp_path, monkeypatch):
        """AC-1: when disk budget is OK, mine() is called and progress is printed."""
        project = tmp_path / "proj"
        project.mkdir()

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)
            return {"drawers_filed": 1, "files_processed": 2, "elapsed_secs": 0}

        # Large free space → budget check passes
        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
            patch("mempalace_code.disk_budget.free_bytes", return_value=10 * 1024**3),
            patch("mempalace_code.storage.open_store"),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        # Initial mine was called
        assert len(mine_calls) >= 1
        assert mine_calls[0].get("skip_optimize") is True

    def test_ac2_low_disk_skips_mine_and_prints_message(self, tmp_path, capsys):
        """AC-2: low-disk cycle is skipped; stdout/stderr contains disk budget info."""
        project = tmp_path / "proj"
        project.mkdir()

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)
            return {}

        from watchfiles import Change

        changes = [{(Change.modified, str(project / "app.py"))}]

        # free_bytes=0 → budget check always fails
        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory(changes)),
            patch("mempalace_code.disk_budget.free_bytes", return_value=0),
            patch("mempalace_code.watcher.time.monotonic", return_value=1.0),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        captured = capsys.readouterr()
        combined = captured.out + captured.err

        # No mine calls (initial mine skipped, re-mine cycle skipped)
        assert len(mine_calls) == 0
        # Message contains required fields (AC-2)
        assert "disk budget" in combined
        assert str(tmp_path / "palace") in combined
        assert "0 B" in combined  # free bytes reported (exact format_bytes output)
        assert "launchctl" in combined

    def test_ac3_exactly_at_threshold_allows_mine(self, tmp_path):
        """AC-3: free == threshold is allowed; free == threshold-1 is skipped."""
        project = tmp_path / "proj"
        project.mkdir()

        threshold = 512 * 1024 * 1024  # 512 MiB
        mine_calls_ok = []
        mine_calls_low = []

        def fake_mine_ok(**kwargs):
            mine_calls_ok.append(kwargs)
            return {}

        def fake_mine_low(**kwargs):
            mine_calls_low.append(kwargs)
            return {}

        # free == threshold: mine must be called
        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine_ok),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
            patch("mempalace_code.disk_budget.free_bytes", return_value=threshold),
            patch("mempalace_code.watcher._load_watch_min_free", return_value=threshold),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        assert len(mine_calls_ok) >= 1

        # free == threshold - 1: mine must NOT be called
        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine_low),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
            patch("mempalace_code.disk_budget.free_bytes", return_value=threshold - 1),
            patch("mempalace_code.watcher._load_watch_min_free", return_value=threshold),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace2"))

        assert len(mine_calls_low) == 0

    def test_initial_mine_uses_skip_optimize(self, tmp_path):
        """Initial mine in watch_and_mine() must pass skip_optimize=True."""
        project = tmp_path / "proj"
        project.mkdir()

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)
            return {}

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
            patch("mempalace_code.disk_budget.free_bytes", return_value=10 * 1024**3),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        # Initial mine call must have skip_optimize=True
        assert mine_calls[0].get("skip_optimize") is True

    def test_low_disk_message_throttled(self, tmp_path, capsys):
        """Disk-budget skip message is not repeated for every skipped cycle."""
        project = tmp_path / "proj"
        project.mkdir()

        from watchfiles import Change

        # Three change batches, all skipped due to low disk
        changes = [
            {(Change.modified, str(project / "a.py"))},
            {(Change.modified, str(project / "b.py"))},
            {(Change.modified, str(project / "c.py"))},
        ]

        with (
            patch("mempalace_code.watcher.mine"),
            patch("watchfiles.watch", side_effect=_fake_watch_factory(changes)),
            patch("mempalace_code.disk_budget.free_bytes", return_value=0),
            # Throttle interval set to a large value so only first message is printed
            patch("mempalace_code.watcher._BUDGET_LOG_INTERVAL", 9999),
            patch("mempalace_code.watcher.time.monotonic", return_value=1.0),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        captured = capsys.readouterr()
        # Message should appear exactly once (throttled)
        assert captured.out.count("disk budget") == 1


# ---------------------------------------------------------------------------
# watch status CLI tests (AC-5, AC-6)
# ---------------------------------------------------------------------------


class TestWatchStatusCli:
    def _run_status(self, tmp_path, argv_extra=None):
        palace = str(tmp_path / "palace")
        argv = ["mempalace-code", "--palace", palace, "watch", str(tmp_path), "status"]
        if argv_extra:
            argv += argv_extra
        with patch.object(sys, "argv", argv):
            main()

    def test_ac6_non_macos_exits_0_and_prints_summary(self, tmp_path, capsys):
        """AC-6: on non-macOS, exit 0 and print disk-budget summary + launchd unavailable."""
        palace = tmp_path / "palace"
        palace.mkdir()

        with (
            patch("sys.platform", "linux"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
        ):
            self._run_status(tmp_path)

        captured = capsys.readouterr()
        assert str(palace) in captured.out
        assert "Free:" in captured.out
        assert "launchd is macOS-only" in captured.out or "not available" in captured.out

    def test_ac6_macos_unloaded_launchd_reports_not_loaded(self, tmp_path, capsys):
        """AC-6: on macOS where launchctl returns non-zero, report not loaded and exit 0."""

        palace = tmp_path / "palace"
        palace.mkdir()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("sys.platform", "darwin"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
            patch("subprocess.run", return_value=mock_result),
        ):
            self._run_status(tmp_path)

        captured = capsys.readouterr()
        assert "not loaded" in captured.out or "not loaded" in captured.err
        assert str(palace) in captured.out

    def test_status_not_loaded_prints_safe_next_action(self, tmp_path, capsys):
        """watch status tells the operator how to proceed when launchd is not loaded."""
        palace = tmp_path / "palace"
        palace.mkdir()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("sys.platform", "darwin"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
            patch("subprocess.run", return_value=mock_result),
        ):
            self._run_status(tmp_path)

        out = capsys.readouterr().out
        assert "LaunchAgent: com.mempalace.watch  (not loaded)" in out
        assert "Next:" in out
        assert "already points at the intended root" in out
        assert "launchctl load" in out
        assert "mempalace-code watch" in out
        assert "schedule >" in out

    def test_status_disk_budget_prints_disk_next_action(self, tmp_path, capsys):
        """Disk-budget blocks should point at disk recovery before launchd actions."""
        palace = tmp_path / "palace"
        palace.mkdir()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("sys.platform", "darwin"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=0),
            patch("subprocess.run", return_value=mock_result),
        ):
            self._run_status(tmp_path)

        out = capsys.readouterr().out
        assert "Runnable: no" in out
        assert "Next:" in out
        assert "free disk space" in out
        assert "launchctl load" not in out

    def test_ac5_macos_loaded_prints_required_fields(self, tmp_path, capsys):
        """AC-5: on macOS with running daemon, stdout includes com.mempalace.watch and state."""

        palace = tmp_path / "palace"
        palace.mkdir()

        watched_root = str(tmp_path / "watched_dir")
        fake_launchctl_output = (
            "com.mempalace.watch = {\n"
            "    state = running\n"
            "    program = /usr/local/bin/mempalace-code\n"
            "    arguments = {\n"
            "        /bin/sh\n"
            "        -c\n"
            f"        /usr/local/bin/mempalace-code watch {watched_root}\n"
            "    }\n"
            "}\n"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_launchctl_output

        with (
            patch("sys.platform", "darwin"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
            patch("subprocess.run", return_value=mock_result),
        ):
            self._run_status(tmp_path)

        captured = capsys.readouterr()
        out = captured.out
        assert "com.mempalace.watch" in out
        assert "running" in out
        assert str(palace) in out
        assert "Free:" in out

    def test_status_reports_last_exit_code_and_runs(self, tmp_path, capsys):
        """watch status prints runs count and last exit code when launchctl exposes them."""
        palace = tmp_path / "palace"
        palace.mkdir()

        fake_launchctl_output = (
            "com.mempalace.watch = {\n"
            "    state = waiting\n"
            "    runs = 42\n"
            "    last exit code = 1\n"
            "    program = /usr/local/bin/mempalace-code\n"
            "}\n"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_launchctl_output

        with (
            patch("sys.platform", "darwin"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
            patch("subprocess.run", return_value=mock_result),
        ):
            self._run_status(tmp_path)

        captured = capsys.readouterr()
        out = captured.out
        assert "runs = 42" in out
        assert "last exit code = 1" in out
        # Existing fields still present
        assert "com.mempalace.watch" in out
        assert str(palace) in out
        assert "Next:" in out
        assert "/tmp/mempalace-watch.log" in out

    def test_status_uses_service_state_not_coalition_state(self, tmp_path, capsys):
        """watch status reports the top-level launchd state, not nested coalition state."""
        palace = tmp_path / "palace"
        palace.mkdir()

        watched_root = str(tmp_path / "watched_dir")
        fake_launchctl_output = (
            "com.mempalace.watch = {\n"
            "    active count = 0\n"
            "    state = spawn scheduled\n"
            "    arguments = {\n"
            "        /bin/sh\n"
            "        -c\n"
            f"        /usr/local/bin/mempalace-code watch {watched_root}\n"
            "    }\n"
            "    runs = 42\n"
            "    last exit code = 1\n"
            "    resource coalition = {\n"
            "        state = active\n"
            "        active count = 1\n"
            "    }\n"
            "    jetsam coalition = {\n"
            "        state = active\n"
            "        active count = 1\n"
            "    }\n"
            "}\n"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_launchctl_output

        with (
            patch("sys.platform", "darwin"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
            patch("subprocess.run", return_value=mock_result),
        ):
            self._run_status(tmp_path)

        captured = capsys.readouterr()
        out = captured.out
        assert "state = spawn scheduled" in out
        assert "state = active" not in out
        assert "runs = 42" in out
        assert "last exit code = 1" in out
        assert f"Watched root: {watched_root}" in out

    def test_status_omits_crash_loop_fields_when_absent(self, tmp_path, capsys):
        """watch status does not print runs/exit-code lines when launchctl output lacks them."""
        palace = tmp_path / "palace"
        palace.mkdir()

        fake_launchctl_output = (
            "com.mempalace.watch = {\n"
            "    state = running\n"
            "    program = /usr/local/bin/mempalace-code\n"
            "}\n"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_launchctl_output

        with (
            patch("sys.platform", "darwin"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
            patch("subprocess.run", return_value=mock_result),
        ):
            self._run_status(tmp_path)

        captured = capsys.readouterr()
        out = captured.out
        assert "runs =" not in out
        assert "last exit code =" not in out
        # Existing output still present
        assert "running" in out


# ---------------------------------------------------------------------------
# Watcher startup recovery tests (AC-1 – AC-5)
# ---------------------------------------------------------------------------


class TestWatchInitialMineRecovery:
    """Tests for watcher startup backup and missing-fragment recovery behavior."""

    def test_initial_mine_creates_pre_watch_backup_before_mining(self, tmp_path):
        """AC-1: pre_watch backup created before initial mine; mine runs after."""
        palace = tmp_path / "palace"
        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        project = tmp_path / "proj"
        project.mkdir()

        call_order = []
        backup_archive = str(tmp_path / "pre_watch_20260101_120000.tar.gz")

        def fake_create_backup(palace_path, kind=None, **kwargs):
            call_order.append("backup")
            return {}, backup_archive

        def fake_mine(**kwargs):
            call_order.append("mine")
            return {}

        with (
            patch("mempalace_code.watcher.create_backup", side_effect=fake_create_backup),
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
        ):
            watch_and_mine(str(project), str(palace))

        assert "backup" in call_order
        assert "mine" in call_order
        assert call_order.index("backup") < call_order.index("mine")

    def test_initial_backup_failure_exits_before_mine(self, tmp_path, capsys):
        """AC-2: backup failure is fail-closed — mine and watch not called."""
        palace = tmp_path / "palace"
        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        project = tmp_path / "proj"
        project.mkdir()

        mine_called = []
        watch_called = []

        with (
            patch("mempalace_code.watcher.create_backup", side_effect=Exception("disk full")),
            patch("mempalace_code.watcher.mine", side_effect=lambda **kw: mine_called.append(1)),
            patch(
                "watchfiles.watch",
                side_effect=lambda *a, **kw: watch_called.append(1) or iter([]),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                watch_and_mine(str(project), str(palace))

        assert exc_info.value.code == 1
        assert not mine_called, "_quiet_mine must not be called after backup failure"
        assert not watch_called, "watchfiles.watch must not be called after backup failure"
        out = capsys.readouterr()
        assert "Watcher did not start" in (out.out + out.err)

    def test_missing_fragment_initial_mine_rolls_back_and_retries_once(self, tmp_path, capsys):
        """AC-3: missing-fragment → DEGRADED → rollback → single retry → watch loop entered."""
        palace = tmp_path / "palace"
        palace.mkdir(parents=True)
        project = tmp_path / "proj"
        project.mkdir()

        mine_call_count = []

        def fake_mine(**kwargs):
            mine_call_count.append(1)
            if len(mine_call_count) == 1:
                raise Exception("no such file or directory: fragment.lance")
            return {}

        fake_store = MagicMock()
        fake_store.recover_to_last_working_version.return_value = {
            "recovered": True,
            "restored_to": 5,
            "rows_after": 10,
        }

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("mempalace_code.storage.open_store", return_value=fake_store),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
        ):
            watch_and_mine(str(project), str(palace))

        assert len(mine_call_count) == 2, "initial mine + one retry"
        fake_store.recover_to_last_working_version.assert_called_once_with(dry_run=False)
        out = capsys.readouterr()
        assert "DEGRADED" in (out.out + out.err)

    def test_initial_recovery_recreates_lifecycle_store_before_retry(self, tmp_path):
        """Rollback retries with a fresh collection instead of the stale failing handle."""
        from mempalace_code import watcher

        palace = tmp_path / "palace"
        stale_store = MagicMock(name="stale_store")
        fresh_store = MagicMock(name="fresh_store")
        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)
            if len(mine_calls) == 1:
                raise Exception("no such file or directory: fragment.lance")
            return {"embedder_warmed": kwargs["warmup"]}

        recovery_store = MagicMock()
        recovery_store.recover_to_last_working_version.return_value = {
            "recovered": True,
            "restored_to": 5,
            "rows_after": 10,
        }

        with (
            patch(
                "mempalace_code.watcher.get_collection",
                side_effect=[stale_store, fresh_store],
            ) as get_collection,
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("mempalace_code.storage.open_store", return_value=recovery_store),
        ):
            mining_store = watcher._WatcherMiningStore(str(palace))
            stats = watcher._run_initial_mine_with_recovery(
                {}, str(palace), None, None, mining_store
            )

        assert stats == {"embedder_warmed": True}
        assert [call["collection"] for call in mine_calls] == [stale_store, fresh_store]
        assert all(call["warmup"] for call in mine_calls)
        assert get_collection.call_count == 2
        recovery_store.recover_to_last_working_version.assert_called_once_with(dry_run=False)

    def test_watcher_lifecycle_reuses_one_collection_and_warms_once(self, tmp_path):
        """Changed cycles share the watcher collection after its first explicit warmup."""
        project = tmp_path / "proj"
        _make_project(project)
        collection = MagicMock()
        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)
            if kwargs["warmup"]:
                kwargs["collection"].warmup()
            return {
                "drawers_filed": 1,
                "files_processed": 1,
                "elapsed_secs": 0,
                "embedder_warmed": kwargs["warmup"],
            }

        changes = [{(1, str(project / "app.py"))}, {(1, str(project / "app.py"))}]
        with (
            patch(
                "mempalace_code.watcher.get_collection", return_value=collection
            ) as get_collection,
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("mempalace_code.watcher._optimize_once", return_value="completed"),
            patch("mempalace_code.watcher._load_watch_min_free", return_value=0),
            patch("watchfiles.watch", side_effect=_fake_watch_factory(changes)),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        assert len(mine_calls) == 3, "initial mine plus two changed watcher cycles"
        assert {id(call["collection"]) for call in mine_calls} == {id(collection)}
        assert [call["warmup"] for call in mine_calls] == [True, False, False]
        collection.warmup.assert_called_once()
        get_collection.assert_called_once_with(str(tmp_path / "palace"))

    def test_missing_fragment_without_candidate_exits_with_recovery_commands(
        self, tmp_path, capsys
    ):
        """AC-4: no rollback candidate → exit before watching, commands include palace/archive."""
        palace = tmp_path / "palace"
        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        project = tmp_path / "proj"
        project.mkdir()

        backup_archive = str(tmp_path / "backups" / "pre_watch_20260101_120000.tar.gz")

        def fake_create_backup(palace_path, kind=None, **kwargs):
            return {}, backup_archive

        fake_store = MagicMock()
        fake_store.recover_to_last_working_version.return_value = {
            "recovered": False,
            "candidate_version": None,
        }

        watch_called = []

        with (
            patch("mempalace_code.watcher.create_backup", side_effect=fake_create_backup),
            patch(
                "mempalace_code.watcher.mine",
                side_effect=Exception("no such file: fragment.lance"),
            ),
            patch("mempalace_code.storage.open_store", return_value=fake_store),
            patch(
                "watchfiles.watch",
                side_effect=lambda *a, **kw: watch_called.append(1) or iter([]),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                watch_and_mine(str(project), str(palace))

        assert exc_info.value.code == 1
        assert not watch_called, "watch loop must not be entered"

        out = capsys.readouterr()
        all_output = out.out + out.err
        assert str(palace) in all_output
        assert backup_archive in all_output
        assert "repair --rollback --dry-run" in all_output
        assert "restore" in all_output

    def test_first_ever_watch_without_existing_lance_data_skips_pre_watch_backup(self, tmp_path):
        """AC-5: no existing lance data → no backup required, initial mine runs normally."""
        # No lance dir at all — first-ever palace
        palace = tmp_path / "palace"
        project = tmp_path / "proj"
        project.mkdir()

        backup_called = []
        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(1)
            return {}

        with (
            patch(
                "mempalace_code.watcher.create_backup",
                side_effect=lambda *a, **kw: backup_called.append(1),
            ),
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
        ):
            watch_and_mine(str(project), str(palace))

        assert not backup_called, "no pre-watch backup for first-ever palace"
        assert mine_calls, "initial mine should still run"

    def test_non_lance_file_not_found_does_not_trigger_rollback(self, tmp_path, capsys):
        """F-1: FileNotFoundError from a source file outside palace/lance does not trigger rollback."""
        palace = tmp_path / "palace"
        palace.mkdir()
        project = tmp_path / "proj"
        project.mkdir()

        rollback_called = []
        fake_store = MagicMock()
        fake_store.recover_to_last_working_version.side_effect = lambda **kw: (
            rollback_called.append(1) or {"recovered": False}
        )

        # Simulate a Python FileNotFoundError from the miner reading a source file
        source_exc = FileNotFoundError(2, "No such file or directory", str(project / "src.py"))

        with (
            patch("mempalace_code.watcher.mine", side_effect=source_exc),
            patch("mempalace_code.storage.open_store", return_value=fake_store),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
        ):
            with pytest.raises(SystemExit) as exc_info:
                watch_and_mine(str(project), str(palace))

        assert exc_info.value.code == 1
        assert not rollback_called, "Lance rollback must NOT fire for source-file FileNotFoundError"

    def test_recovery_commands_quote_paths_with_spaces(self, tmp_path, capsys):
        """F-3: Palace or archive paths containing spaces are shell-quoted in recovery output."""
        palace = tmp_path / "my palace"
        palace.mkdir()
        project = tmp_path / "proj"
        project.mkdir()

        backup_archive = str(tmp_path / "my backups" / "pre_watch_20260101_120000.tar.gz")

        def fake_create_backup(palace_path, kind=None, **kwargs):
            return {}, backup_archive

        fake_store = MagicMock()
        fake_store.recover_to_last_working_version.return_value = {
            "recovered": False,
            "candidate_version": None,
        }

        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        with (
            patch("mempalace_code.watcher.create_backup", side_effect=fake_create_backup),
            patch(
                "mempalace_code.watcher.mine",
                side_effect=Exception("no such file: fragment.lance"),
            ),
            patch("mempalace_code.storage.open_store", return_value=fake_store),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
        ):
            with pytest.raises(SystemExit):
                watch_and_mine(str(project), str(palace))

        out = capsys.readouterr()
        all_output = out.out + out.err
        assert shlex.quote(str(palace)) in all_output
        assert "repair --rollback --dry-run" in all_output


# ---------------------------------------------------------------------------
# Non-regular source startup guard (INGEST-NONREGULAR-SOURCE-GUARD)
# ---------------------------------------------------------------------------


class TestWatcherStartupSourceGuard:
    """Tests for unconditional watcher startup source classification."""

    def test_invalid_source_symlink_is_diagnosed_before_backup_or_mine(self, tmp_path, capsys):
        """AC-1: guarded discovery diagnoses an invalid symlink before backup/mine run."""
        palace = tmp_path / "palace"
        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        project = tmp_path / "proj"
        project.mkdir()
        (project / "app.py").write_text("print('ok')\n" * 20)
        dangling = project / "broken.py"
        dangling.symlink_to(project / "does_not_exist.py")
        fifo = project / "blocked.py"
        if not hasattr(os, "mkfifo"):
            pytest.skip("os.mkfifo is unavailable")
        os.mkfifo(fifo)

        call_order = []

        def fake_create_backup(palace_path, kind=None, **kwargs):
            call_order.append("backup")
            return {}, str(tmp_path / "pre_watch.tar.gz")

        def fake_mine(**kwargs):
            call_order.append("mine")
            return {}

        with (
            patch("mempalace_code.watcher.create_backup", side_effect=fake_create_backup),
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
        ):
            watch_and_mine(str(project), str(palace))

        assert call_order == ["backup", "mine"], "backup and mine still run for a mixed project"

        out = capsys.readouterr().out
        assert "Rejected 2 non-regular source(s):" in out
        assert str(dangling) in out
        assert f"{dangling} (symlink)" in out
        assert f"{fifo} (fifo)" in out
        assert "Remove or replace each path with a regular file" in out
        diagnostic_index = out.index("Rejected 2 non-regular source(s):")
        backup_index = out.index("Pre-watch backup:")
        assert diagnostic_index < backup_index, (
            "guarded source discovery and its diagnostic must run before pre-watch backup"
        )

    def test_invalid_only_startup_enters_watch_without_pre_watch_backup_churn(
        self, tmp_path, capsys
    ):
        """AC-2: invalid-only startup stays alive without repeated pre_watch backups."""
        palace = tmp_path / "palace"
        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        project = tmp_path / "proj"
        project.mkdir()
        dangling = project / "broken.py"
        dangling.symlink_to(project / "does_not_exist.py")

        backup_calls = []
        mine_calls = []
        watch_calls = []

        with (
            patch(
                "mempalace_code.watcher.create_backup",
                side_effect=lambda *a, **kw: backup_calls.append(1),
            ),
            patch("mempalace_code.watcher.mine", side_effect=lambda **kw: mine_calls.append(1)),
            patch(
                "watchfiles.watch",
                side_effect=lambda *a, **kw: watch_calls.append(1) or iter([]),
            ),
        ):
            watch_and_mine(str(project), str(palace))
            watch_and_mine(str(project), str(palace))

        assert not backup_calls, "invalid-only startup must not create a pre_watch archive"
        assert not mine_calls, "invalid-only startup must not attempt an initial mine"
        assert len(watch_calls) == 2, "watcher must still reach the watch loop each startup"

        out = capsys.readouterr().out
        assert out.count("reason=no-valid-sources") == 2

    def test_symlink_and_regular_file_startup_runs_mine_for_regular_only(self, tmp_path):
        """A rejected symlink does not prevent a sibling regular source from mining."""
        palace = tmp_path / "palace"
        project = tmp_path / "proj"
        project.mkdir()
        target = project / "real.py"
        target.write_text("print('real')\n" * 20)
        link = project / "link.py"
        link.symlink_to(target)

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)
            return {}

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
        ):
            watch_and_mine(str(project), str(palace))

        assert len(mine_calls) == 1, "initial mine must still run for valid sources"
        assert mine_calls[0]["incremental"] is True
        assert mine_calls[0]["limit"] == 0
        assert "skip_invalid_source_symlinks" not in mine_calls[0]

    def test_watch_all_invalid_only_startup_enters_watch_without_backup_or_mine(
        self, tmp_path, capsys
    ):
        """AC-4: watch_all skips the shared backup and every mine when all projects are
        invalid-symlink-only, and still reaches the watch loop."""
        palace = tmp_path / "palace"
        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        parent = tmp_path / "parent"
        parent.mkdir()
        proj_a = parent / "proj_a"
        proj_b = parent / "proj_b"
        proj_a.mkdir()
        proj_b.mkdir()
        (proj_a / "broken.py").symlink_to(proj_a / "does_not_exist.py")
        (proj_b / "broken.py").symlink_to(proj_b / "does_not_exist.py")

        backup_calls = []
        mine_calls = []
        watch_calls = []

        fake_projects = [
            {"path": str(proj_a), "initialized": True},
            {"path": str(proj_b), "initialized": True},
        ]

        def fake_resolve_wing(project_dir):
            return f"wing_{Path(project_dir).name}"

        with (
            patch(
                "mempalace_code.watcher.create_backup",
                side_effect=lambda *a, **kw: backup_calls.append(1),
            ),
            patch("mempalace_code.watcher.mine", side_effect=lambda **kw: mine_calls.append(kw)),
            patch(
                "watchfiles.watch",
                side_effect=lambda *a, **kw: watch_calls.append(1) or iter([]),
            ),
            patch("mempalace_code.mining.projects.detect_projects", return_value=fake_projects),
            patch(
                "mempalace_code.mining.projects.resolve_wing_for_project",
                side_effect=fake_resolve_wing,
            ),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(str(parent), str(palace), on_commit=False)

        assert not backup_calls, "all-invalid startup must not create a shared pre_watch archive"
        assert not mine_calls, "all-invalid startup must not attempt any initial mine"
        assert watch_calls == [1], "watcher must still reach the watch loop"

        out = capsys.readouterr().out
        assert out.count("Rejected 1 non-regular source(s):") == 2, (
            "each invalid-only project prints its own bounded diagnostic"
        )
        assert "[wing_proj_a]" in out
        assert "[wing_proj_b]" in out
        assert "reason=no-valid-sources" in out

    def test_watch_all_mixed_startup_mines_only_valid_project(self, tmp_path, capsys):
        """AC-4: watch_all keeps the shared backup and mines only the project with valid
        sources when a sibling project's only discovered source is an invalid symlink."""
        palace = tmp_path / "palace"
        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        parent = tmp_path / "parent"
        parent.mkdir()
        proj_a = parent / "proj_a"
        proj_b = parent / "proj_b"
        proj_a.mkdir()
        proj_b.mkdir()
        (proj_a / "real.py").write_text("print('real')\n" * 20)
        (proj_b / "broken.py").symlink_to(proj_b / "does_not_exist.py")

        backup_calls = []
        mine_calls = []
        watch_calls = []
        backup_archive = str(tmp_path / "pre_watch_20260101_120000.tar.gz")

        fake_projects = [
            {"path": str(proj_a), "initialized": True},
            {"path": str(proj_b), "initialized": True},
        ]

        def fake_resolve_wing(project_dir):
            return f"wing_{Path(project_dir).name}"

        def fake_create_backup(palace_path, kind=None, **kwargs):
            backup_calls.append(1)
            return {}, backup_archive

        with (
            patch("mempalace_code.watcher.create_backup", side_effect=fake_create_backup),
            patch("mempalace_code.watcher.mine", side_effect=lambda **kw: mine_calls.append(kw)),
            patch(
                "watchfiles.watch",
                side_effect=lambda *a, **kw: watch_calls.append(1) or iter([]),
            ),
            patch("mempalace_code.mining.projects.detect_projects", return_value=fake_projects),
            patch(
                "mempalace_code.mining.projects.resolve_wing_for_project",
                side_effect=fake_resolve_wing,
            ),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(str(parent), str(palace), on_commit=False)

        assert backup_calls == [1], "mixed startup still creates the shared pre_watch backup"
        assert len(mine_calls) == 1, "only the project with a valid source is mined"
        assert mine_calls[0]["wing_override"] == "wing_proj_a"
        assert watch_calls == [1], "watcher must still reach the watch loop"

        out = capsys.readouterr().out
        assert out.count("Rejected 1 non-regular source(s):") == 1, (
            "only the invalid-only project prints a diagnostic"
        )
        assert "[wing_proj_b]" in out
        assert "[wing_proj_a]" not in out, "the valid project must not print a skip diagnostic"


# ---------------------------------------------------------------------------
# watch_all() — initialized root support (AC-1 through AC-4)
# ---------------------------------------------------------------------------


class TestWatchAllInitializedRoot:
    """Tests for watch_all() behavior when the supplied directory is itself a project."""

    def test_initialized_root_is_watched_as_single_project(self, tmp_path):
        """AC-1: watch_all with an initialized project root mines that root with its wing."""
        project = tmp_path / "my_project"
        project.mkdir()
        (project / "mempalace.yaml").write_text("wing: root_wing\n")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)
            return {}

        watch_paths_seen = []

        def fake_watch(*paths, stop_event=None, **kwargs):
            watch_paths_seen.extend(paths)
            return iter([])

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=fake_watch),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
        ):
            watch_all(str(project), str(tmp_path / "palace"), on_commit=False)

        # Initial mine must have run for the root with its configured wing
        assert len(mine_calls) >= 1
        assert mine_calls[0]["project_dir"] == str(project)
        assert mine_calls[0]["wing_override"] == "root_wing"
        # The root directory must be passed to watchfiles, not a parent or child path
        resolved = str(project.resolve())
        assert resolved in watch_paths_seen

    def test_uninitialized_project_root_prints_actionable_init_command(self, tmp_path, capsys):
        """AC-2: project root with project markers but no init file exits 1 with init command."""
        project = tmp_path / "my_project"
        project.mkdir()
        # Has a project marker but no mempalace.yaml
        (project / ".git").mkdir()

        with pytest.raises(SystemExit) as exc_info:
            watch_all(str(project), str(tmp_path / "palace"))

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert f"mempalace-code init {project}" in combined

    def test_parent_directory_still_watches_initialized_children(self, tmp_path):
        """AC-3: plain parent directory still discovers and mines initialized child projects."""
        parent = tmp_path / "workspace"
        parent.mkdir()
        child = parent / "my_project"
        child.mkdir()
        (child / "mempalace.yaml").write_text("wing: child_wing\n")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)
            return {}

        fake_projects = [{"path": str(child), "initialized": True}]

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", return_value=iter([])),
            patch("mempalace_code.mining.projects.detect_projects", return_value=fake_projects),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
        ):
            watch_all(str(parent), str(tmp_path / "palace"), on_commit=False)

        assert len(mine_calls) >= 1
        assert mine_calls[0]["project_dir"] == str(child)
        assert mine_calls[0]["wing_override"] == "child_wing"

    def test_initialized_root_takes_precedence_over_child_project_scan(self, tmp_path):
        """AC-4: when the root is initialized, detect_projects() is not called and children are not mined."""
        project = tmp_path / "my_project"
        project.mkdir()
        (project / "mempalace.yaml").write_text("wing: root_wing\n")
        # Project-looking child that should NOT be scanned
        child = project / "sub_project"
        child.mkdir()
        (child / "pyproject.toml").write_text("[project]\nname = 'sub'\n")

        mine_calls = []
        detect_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)
            return {}

        def fake_detect(parent_dir):
            detect_calls.append(parent_dir)
            return []

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", return_value=iter([])),
            patch("mempalace_code.mining.projects.detect_projects", side_effect=fake_detect),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
        ):
            watch_all(str(project), str(tmp_path / "palace"), on_commit=False)

        # detect_projects must NOT be called when root is initialized
        assert len(detect_calls) == 0
        # All mine calls must be for the root project only
        assert len(mine_calls) >= 1
        assert all(c["project_dir"] == str(project) for c in mine_calls)
        assert all(c["wing_override"] == "root_wing" for c in mine_calls)


# ---------------------------------------------------------------------------
# watch_all startup recovery tests (AC-6)
# ---------------------------------------------------------------------------


class TestWatchAllInitialMineRecovery:
    """Tests for watch_all startup guard — one pre_watch backup, fail-closed."""

    def test_watch_all_initial_batch_uses_one_pre_watch_backup_and_fails_closed(
        self, tmp_path, capsys
    ):
        """AC-6: one pre_watch archive before batch; fails closed before watch if any mine unrecovered."""
        palace = tmp_path / "palace"
        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        parent = tmp_path / "parent"
        parent.mkdir()
        proj_a = parent / "proj_a"
        proj_b = parent / "proj_b"
        proj_a.mkdir()
        proj_b.mkdir()

        backup_call_count = []
        backup_archive = str(tmp_path / "pre_watch_20260101_120000.tar.gz")

        def fake_create_backup(palace_path, kind=None, **kwargs):
            backup_call_count.append(1)
            return {}, backup_archive

        mine_call_count = []

        def fake_mine(**kwargs):
            mine_call_count.append(kwargs.get("wing_override"))
            if len(mine_call_count) == 2:
                raise Exception("no such file: fragment.lance")
            return {}

        fake_store = MagicMock()
        fake_store.recover_to_last_working_version.return_value = {
            "recovered": False,
            "candidate_version": None,
        }

        watch_called = []

        fake_projects = [
            {"path": str(proj_a), "initialized": True},
            {"path": str(proj_b), "initialized": True},
        ]

        def fake_resolve_wing(project_dir):
            return f"wing_{Path(project_dir).name}"

        with (
            patch("mempalace_code.watcher.create_backup", side_effect=fake_create_backup),
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("mempalace_code.storage.open_store", return_value=fake_store),
            patch(
                "watchfiles.watch",
                side_effect=lambda *a, **kw: watch_called.append(1) or iter([]),
            ),
            patch("mempalace_code.mining.projects.detect_projects", return_value=fake_projects),
            patch(
                "mempalace_code.mining.projects.resolve_wing_for_project",
                side_effect=fake_resolve_wing,
            ),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                watch_all(str(parent), str(palace), on_commit=False)

        assert exc_info.value.code == 1
        assert len(backup_call_count) == 1, "exactly one pre_watch backup before initial batch"
        assert not watch_called, "watch loop must not be entered on unrecovered failure"


# ---------------------------------------------------------------------------
# Watch run readiness diagnostics tests (WATCH-RUN-READINESS-DIAGNOSTICS)
# ---------------------------------------------------------------------------


class TestWatchRunReadinessDiagnostics:
    """Tests for WATCH_RUN startup state markers."""

    def test_successful_watch_startup_emits_run_marker_and_ready_states(self, tmp_path, capsys):
        """AC-1: successful single-project startup emits run id and required readiness states."""
        from mempalace_code.storage import OptimizeResult

        project = tmp_path / "proj"
        project.mkdir()

        with (
            patch("mempalace_code.watcher._make_run_id", return_value="TEST-RUN-ID"),
            patch(
                "mempalace_code.watcher.mine",
                return_value={"drawers_filed": 1, "files_processed": 2, "elapsed_secs": 0},
            ),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
            patch(
                "mempalace_code.watcher.optimize_store",
                return_value=OptimizeResult(ok=True, supported=True),
            ),
            patch("mempalace_code.storage.open_store"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=10 * 1024**3),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        output = capsys.readouterr().out
        assert "WATCH_RUN run_id=TEST-RUN-ID state=run-started" in output
        assert "WATCH_RUN run_id=TEST-RUN-ID state=initial-mine-started" in output
        assert "WATCH_RUN run_id=TEST-RUN-ID state=initial-mine-completed" in output
        assert "WATCH_RUN run_id=TEST-RUN-ID state=optimize-completed" in output
        assert "WATCH_RUN run_id=TEST-RUN-ID state=watch-ready" in output

    @pytest.mark.parametrize("entrypoint", ["watch_and_mine", "watch_all"])
    def test_safety_check_skip_keeps_watch_ready(self, entrypoint, tmp_path, capsys):
        """A false safe-optimize result is truthful and non-fatal at both entry points."""
        project = tmp_path / "proj"
        project.mkdir()
        if entrypoint == "watch_all":
            (project / "mempalace.yaml").write_text("wing: test_wing\n")

        with (
            patch("mempalace_code.watcher._make_run_id", return_value="SAFETY-CHECK-RUN"),
            patch(
                "mempalace_code.watcher.mine",
                return_value={"drawers_filed": 1, "files_processed": 1, "elapsed_secs": 0},
            ),
            patch(
                "mempalace_code.watcher._optimize_once",
                return_value="skipped:safety-check",
            ),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=10 * 1024**3),
        ):
            if entrypoint == "watch_and_mine":
                watch_and_mine(str(project), str(tmp_path / "palace"))
            else:
                watch_all(str(project), str(tmp_path / "palace"), on_commit=False)

        output = capsys.readouterr().out
        assert (
            "WATCH_RUN run_id=SAFETY-CHECK-RUN state=optimize-skipped reason=safety-check" in output
        )
        assert "reason=backup-gate" not in output
        assert "WATCH_RUN run_id=SAFETY-CHECK-RUN state=watch-ready" in output

    def test_watch_and_mine_pre_watch_backup_failure_emits_failed_state(self, tmp_path, capsys):
        """AC-2: watch_and_mine backup failure emits pre-watch-backup-failed; no watch-ready."""
        palace = tmp_path / "palace"
        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        project = tmp_path / "proj"
        project.mkdir()

        with (
            patch("mempalace_code.watcher._make_run_id", return_value="BACKUP-FAIL-RUN"),
            patch("mempalace_code.watcher.create_backup", side_effect=Exception("disk full")),
            patch("mempalace_code.watcher.mine"),
            patch("watchfiles.watch"),
        ):
            with pytest.raises(SystemExit):
                watch_and_mine(str(project), str(palace))

        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "WATCH_RUN run_id=BACKUP-FAIL-RUN state=run-started" in output
        assert "WATCH_RUN run_id=BACKUP-FAIL-RUN state=pre-watch-backup-failed" in output
        assert "state=watch-ready" not in output

    def test_latest_successful_run_is_distinguishable_from_stale_appended_failures(self, tmp_path):
        """AC-3: latest watch-ready run id is identifiable even when stale failures exist in log."""
        import re

        stale_log = (
            "WATCH_RUN run_id=OLD-RUN-1 state=run-started\n"
            "WATCH_RUN run_id=OLD-RUN-1 state=initial-mine-skipped reason=disk-budget\n"
            "WATCH_RUN run_id=OLD-RUN-2 state=run-started\n"
            "WATCH_RUN run_id=OLD-RUN-2 state=pre-watch-backup-failed\n"
            "WATCH_RUN run_id=NEW-RUN-1 state=run-started\n"
            "WATCH_RUN run_id=NEW-RUN-1 state=initial-mine-started\n"
            "WATCH_RUN run_id=NEW-RUN-1 state=initial-mine-completed\n"
            "WATCH_RUN run_id=NEW-RUN-1 state=watch-ready\n"
        )

        lines = stale_log.splitlines()

        # Locate the latest watch-ready line and extract its run_id
        latest_run_id = None
        for line in reversed(lines):
            if "state=watch-ready" in line:
                m = re.search(r"run_id=(\S+)", line)
                if m:
                    latest_run_id = m.group(1)
                break

        assert latest_run_id == "NEW-RUN-1", "latest watch-ready must belong to the newest run"

        # Using that run_id, stale disk-budget and backup-failure lines are excluded
        run_lines = [ln for ln in lines if f"run_id={latest_run_id}" in ln]
        assert not any("pre-watch-backup-failed" in ln for ln in run_lines)
        assert not any("reason=disk-budget" in ln for ln in run_lines)
        assert any("state=watch-ready" in ln for ln in run_lines)

    def test_low_disk_startup_skip_keeps_run_id_and_ready_boundary(self, tmp_path, capsys):
        """AC-4: low-disk mine skip is tied to the current run id; watch-ready still appears."""
        project = tmp_path / "proj"
        project.mkdir()

        with (
            patch("mempalace_code.watcher._make_run_id", return_value="LOW-DISK-RUN"),
            patch("mempalace_code.watcher.mine"),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
            patch("mempalace_code.watcher.time.monotonic", return_value=1.0),
            patch("mempalace_code.disk_budget.free_bytes", return_value=0),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"))

        output = capsys.readouterr().out
        assert "WATCH_RUN run_id=LOW-DISK-RUN state=run-started" in output
        assert (
            "WATCH_RUN run_id=LOW-DISK-RUN state=initial-mine-skipped reason=disk-budget" in output
        )
        assert "WATCH_RUN run_id=LOW-DISK-RUN state=watch-ready" in output

    def test_watch_all_startup_uses_same_run_state_format(self, tmp_path, capsys):
        """AC-5: watch_all emits the same run id and state format as watch_and_mine."""
        project = tmp_path / "my_project"
        project.mkdir()
        (project / "mempalace.yaml").write_text("wing: root_wing\n")

        with (
            patch("mempalace_code.watcher._make_run_id", return_value="WATCH-ALL-RUN"),
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("watchfiles.watch", side_effect=_fake_watch_factory([])),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
            patch("mempalace_code.storage.open_store"),
        ):
            watch_all(str(project), str(tmp_path / "palace"), on_commit=False)

        output = capsys.readouterr().out
        assert "WATCH_RUN run_id=WATCH-ALL-RUN state=run-started" in output
        assert "WATCH_RUN run_id=WATCH-ALL-RUN state=initial-mine-started" in output
        assert "WATCH_RUN run_id=WATCH-ALL-RUN state=initial-mine-completed" in output
        assert "WATCH_RUN run_id=WATCH-ALL-RUN state=watch-ready" in output

    def test_watch_all_pre_watch_backup_failure_emits_failed_state(self, tmp_path, capsys):
        """AC-1: watch_all backup failure emits pre-watch-backup-failed; exits 1; no watch loop."""
        palace = tmp_path / "palace"
        lance_dir = palace / "lance"
        lance_dir.mkdir(parents=True)
        (lance_dir / "data.lance").write_bytes(b"x")

        project = tmp_path / "proj"
        project.mkdir()
        (project / "mempalace.yaml").write_text("wing: test_wing\n")

        watch_entered = []

        with (
            patch("mempalace_code.watcher._make_run_id", return_value="WATCH-ALL-BACKUP-FAIL"),
            patch("mempalace_code.watcher.create_backup", side_effect=Exception("disk full")),
            patch("mempalace_code.watcher.mine") as mock_mine,
            patch(
                "watchfiles.watch",
                side_effect=lambda *a, **kw: watch_entered.append(1) or iter([]),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                watch_all(str(project), str(palace), on_commit=False)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "WATCH_RUN run_id=WATCH-ALL-BACKUP-FAIL state=run-started" in output
        assert "WATCH_RUN run_id=WATCH-ALL-BACKUP-FAIL state=pre-watch-backup-failed" in output
        assert "state=watch-ready" not in output
        mock_mine.assert_not_called()
        assert not watch_entered, "watch loop must not be entered on backup failure"
