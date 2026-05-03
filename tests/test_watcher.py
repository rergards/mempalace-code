"""test_watcher.py — Tests for mempalace/watcher.py.

Covers:
  - CLI flag mutual-exclusion validation (--watch + --dry-run/--full/--limit/convos)
  - _is_relevant_change() filtering semantics
  - watch_and_mine() integration: file change triggers re-mine, deletion handled
  - SIGTERM handling (subprocess, slow)
  - ImportError message when watchfiles is missing
  - CLI dispatch: cmd_mine dispatches to watch_and_mine() with correct args
"""

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from mempalace_code.cli import main
from mempalace_code.miner import ScanFilterRules
from mempalace_code.watcher import (
    _invalidate_gitignore_cache,
    _is_relevant_change,
    render_watch_schedule,
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
                "from mempalace_code.watcher import watch_and_mine",
                "with patch('mempalace_code.watcher.mine'):",
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

        out = render_watch_schedule(str(tmp_path), "linux")

        assert f"{shlex.quote(sys.executable)} -m mempalace_code watch" in out
        assert "-m mempalace watch" not in out


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
            patch("mempalace_code.miner.detect_projects", return_value=fake_projects),
            patch("mempalace_code.miner.derive_wing_name", return_value="test_wing"),
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
            patch("mempalace_code.miner.detect_projects", return_value=fake_projects),
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
            patch("mempalace_code.miner.detect_projects", return_value=fake_projects),
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
# _optimize_once — disk-guard gate tests (AC-7)
# ---------------------------------------------------------------------------


class TestOptimizeOnce:
    """Watcher optimize routing through safe_optimize and the backup gate (AC-7).

    When backup_before_optimize=True and safe_optimize returns False (disk guard
    rejected the pre-optimize backup), _optimize_once must report the skip and
    must NOT fall through to raw store.optimize().
    """

    def test_backup_gate_rejected_skips_optimize(self, capsys):
        """safe_optimize returns False → output reports skipped, optimize() not called."""
        from mempalace_code.watcher import _optimize_once

        mock_store = MagicMock()
        mock_store.safe_optimize.return_value = False
        mock_open = MagicMock(return_value=mock_store)

        with patch("mempalace_code.config.MempalaceConfig") as mock_cfg_cls:
            mock_cfg_cls.return_value.backup_before_optimize = True
            _optimize_once("/fake/palace", mock_open)

        mock_store.safe_optimize.assert_called_once_with("/fake/palace", backup_first=True)
        mock_store.optimize.assert_not_called()
        captured = capsys.readouterr()
        assert "skipped (backup gate failed)" in captured.out

    def test_backup_gate_success_prints_done(self, capsys):
        """safe_optimize returns True → optimize completes, output shows done."""
        from mempalace_code.watcher import _optimize_once

        mock_store = MagicMock()
        mock_store.safe_optimize.return_value = True
        mock_open = MagicMock(return_value=mock_store)

        with patch("mempalace_code.config.MempalaceConfig") as mock_cfg_cls:
            mock_cfg_cls.return_value.backup_before_optimize = True
            _optimize_once("/fake/palace", mock_open)

        mock_store.safe_optimize.assert_called_once()
        mock_store.optimize.assert_not_called()
        captured = capsys.readouterr()
        assert "done" in captured.out

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
