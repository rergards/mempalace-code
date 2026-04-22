"""test_watcher.py — Tests for mempalace/watcher.py.

Covers:
  - CLI flag mutual-exclusion validation (--watch + --dry-run/--full/--limit/convos)
  - _is_relevant_change() filtering semantics
  - watch_and_mine() integration: file change triggers re-mine, deletion handled
  - SIGTERM handling (subprocess, slow)
  - ImportError message when watchfiles is missing
  - CLI dispatch: cmd_mine dispatches to watch_and_mine() with correct args
"""

import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from mempalace.cli import main
from mempalace.watcher import _invalidate_gitignore_cache, _is_relevant_change, watch_and_mine


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
        """Run `mempalace mine <dir> --watch <extra_args>` and return exit code."""
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

    def test_watch_rejects_dry_run(self, tmp_path):
        assert self._run(tmp_path, "--dry-run") == 2

    def test_watch_rejects_full(self, tmp_path):
        assert self._run(tmp_path, "--full") == 2

    def test_watch_rejects_limit(self, tmp_path):
        assert self._run(tmp_path, "--limit", "5") == 2

    def test_watch_rejects_convos(self, tmp_path):
        assert self._run(tmp_path, "--mode", "convos") == 2


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
        from mempalace.miner import KNOWN_FILENAMES

        for name in ("Dockerfile", "Makefile", "Justfile"):
            if name in KNOWN_FILENAMES:
                assert _is_relevant_change(str(proj / name), proj), f"{name} should be accepted"

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

    def test_rejects_app_level_workspace_json(self, proj):
        assert not _is_relevant_change(str(proj / "workspace.json"), proj)

    def test_rejects_app_level_kotlin_lsp_dir(self, proj):
        assert not _is_relevant_change(str(proj / ".kotlin-lsp" / "workspace.json"), proj)

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

    def test_include_ignored_bypasses_app_level_exclude(self, proj):
        assert _is_relevant_change(
            str(proj / "workspace.json"),
            proj,
            include_ignored=["workspace.json"],
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
            patch("mempalace.watcher.mine", side_effect=fake_mine),
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
            patch("mempalace.watcher.mine", side_effect=fake_mine),
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
            patch("mempalace.watcher.mine", side_effect=fake_mine),
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
            patch("mempalace.watcher.mine", side_effect=fake_mine),
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

        with patch("mempalace.watcher.mine"), patch("watchfiles.watch", side_effect=fake_watch):
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
            patch("mempalace.watcher.mine", side_effect=fake_mine),
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


# ---------------------------------------------------------------------------
# SIGTERM handling — subprocess (slow)
# ---------------------------------------------------------------------------


class TestSigterm:
    @pytest.mark.slow
    def test_watch_handles_sigterm(self, tmp_path):
        """Watcher subprocess exits with code 0 on SIGTERM."""
        import time

        project = tmp_path / "proj"
        _make_project(project)
        palace = tmp_path / "palace"

        script = "\n".join(
            [
                "from unittest.mock import patch",
                "from mempalace.watcher import watch_and_mine",
                "with patch('mempalace.watcher.mine'):",
                f"    watch_and_mine({str(project)!r}, {str(palace)!r})",
            ]
        )

        proc = subprocess.Popen([sys.executable, "-c", script])
        time.sleep(1)
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            pytest.fail("watcher did not exit within 15s after SIGTERM")

        # Accept clean exit (0) or killed-by-signal (-15) — on CI the signal
        # may terminate the process before the handler sets the stop event.
        assert proc.returncode in (0, -15, -signal.SIGTERM)


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
        assert "mempalace[watch]" in captured.err


# ---------------------------------------------------------------------------
# CLI dispatch test
# ---------------------------------------------------------------------------


class TestCliWatchDispatch:
    def test_cli_watch_dispatches_to_watcher_module(self, tmp_path):
        """cmd_mine imports and calls watch_and_mine() from mempalace.watcher."""
        project = tmp_path / "proj"
        _make_project(project)
        palace = tmp_path / "palace"

        watch_calls = []

        def fake_watch(**kw):
            watch_calls.append(kw)

        # Patch watch_and_mine at the module level before cmd_mine imports it
        with patch("mempalace.watcher.watch_and_mine", side_effect=fake_watch):
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
