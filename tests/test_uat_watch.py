"""UAT regressions for the watcher and its schedules (watch-1/2/3, conc-2, sched-1/2,
gap-11, daemon-env).

Each test reproduces one tester scenario at the smallest scope that proves it:
commit-mode preflight before any backup, git worktree/reftable/checkout triggers,
loud handling of vanished projects and ``sys.exit`` inside mine(), no automatic
rollback of a shared palace on a transient storage error, and rendered daemons that
reproduce the invocation, refuse crash-loop roots, and carry their environment.
"""

import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import mempalace_code.watcher as watcher
from mempalace_code.cli import main
from mempalace_code.cli_commands.watch import cmd_watch_schedule
from mempalace_code.operation_lock import OperationLock, PalaceBusyError
from mempalace_code.updater import _LAUNCHD_WATCH_LABEL, _is_supported_watch_command
from mempalace_code.watcher import (
    WatchRootError,
    plan_watch_root,
    render_watch_schedule,
    watch_all,
    watch_and_mine,
    watch_launchd_label,
)

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git is not installed")


def _project(root: Path, wing: str, *, git: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text(
        "\n".join(
            f"def {wing}_function_{i}(value):\n"
            f'    """Function {i} of the {wing} project multiplies a value."""\n'
            f"    return value * {i}\n"
            for i in range(8)
        ),
        encoding="utf-8",
    )
    yaml.safe_dump(
        {"wing": wing, "rooms": [{"name": "general", "description": "General"}]},
        (root / "mempalace.yaml").open("w", encoding="utf-8"),
    )
    if git:
        (root / ".git" / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    return root


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [GIT or "git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _watch_yielding(batches):
    def fake_watch(*_paths, **_kwargs):
        yield from batches

    return fake_watch


def _lock(tmp_path: Path) -> OperationLock:
    return OperationLock(tmp_path / "install" / "operation.lock")


# ---------------------------------------------------------------------------
# watch-1: commit-mode preflight, worktrees, reftable
# ---------------------------------------------------------------------------


class TestCommitModePreflight:
    def test_non_git_root_fails_before_backup_and_mine_with_on_save_command(self, tmp_path, capsys):
        project = _project(tmp_path / "proj", "nogit")
        palace = tmp_path / "my palace"
        (palace / "lance").mkdir(parents=True)
        (palace / "lance" / "data.lance").write_bytes(b"x")

        with (
            patch("mempalace_code.watcher._make_run_id", return_value="W1"),
            patch("mempalace_code.watcher.create_backup") as backup,
            patch("mempalace_code.watcher.mine") as mine,
            patch("watchfiles.watch") as watch,
        ):
            with pytest.raises(SystemExit) as exc_info:
                watch_all(str(project), str(palace), operation_lock=_lock(tmp_path))

        assert exc_info.value.code == 1
        backup.assert_not_called()
        mine.assert_not_called()
        watch.assert_not_called()
        captured = capsys.readouterr()
        assert "WATCH_RUN run_id=W1 state=preflight-failed" in captured.out
        assert "Watching for changes" not in captured.out
        expected = (
            f"{shlex.quote(sys.executable)} -m mempalace_code "
            f"--palace {shlex.quote(str(palace))} watch "
            f"{shlex.quote(str(project.resolve()))} --on-save"
        )
        assert expected in captured.err

    def test_parent_names_skipped_children_and_mines_only_git_projects(self, tmp_path, capsys):
        parent = tmp_path / "parent"
        git_project = _project(parent / "withgit", "withgit", git=True)
        _project(parent / "nogit", "nogit")
        uninit = parent / "uninit"
        uninit.mkdir()
        (uninit / "pyproject.toml").write_text("[project]\nname = 'u'\n", encoding="utf-8")
        mined = []

        with (
            patch("mempalace_code.watcher.mine", side_effect=lambda **kw: mined.append(kw) or {}),
            patch("watchfiles.watch", side_effect=_watch_yielding([])),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(str(parent), str(tmp_path / "palace"), operation_lock=_lock(tmp_path))

        assert [call["project_dir"] for call in mined] == [str(git_project.resolve())]
        out = capsys.readouterr().out
        assert "Skipping nogit: not a git repository" in out
        assert "Skipping uninit: project files found but not initialized" in out
        assert (
            f"{shlex.quote(sys.executable)} -m mempalace_code "
            f"init {shlex.quote(str(uninit.resolve()))}"
        ) in out
        assert "picked up when the watcher restarts" in out

    @requires_git
    def test_linked_worktree_commit_and_checkout_trigger_remine(self, tmp_path):
        main_checkout = _project(tmp_path / "alpha", "alpha")
        _git(main_checkout, "init", "-q", "-b", "main")
        _git(main_checkout, "add", "-A")
        _git(main_checkout, "commit", "-qm", "init")
        _git(main_checkout, "branch", "feature-x")
        worktree = tmp_path / "wt" / "alpha-fx"
        _git(main_checkout, "worktree", "add", "-q", str(worktree), "feature-x")
        assert (worktree / ".git").is_file()

        plan = plan_watch_root(str(worktree), on_commit=True)
        paths = {target.path for target in plan.git_targets}
        common = (main_checkout / ".git").resolve()
        own = next(p for p in paths if p.name == "logs")
        assert common / "refs" / "heads" in paths
        assert own.parent.parent == common / "worktrees"

        batches = [
            {(2, str(common / "refs" / "heads" / "feature-x"))},  # commit
            {(2, str(own / "HEAD"))},  # checkout in the worktree
            {(2, str(own / "refs" / "remotes" / "origin" / "main"))},  # not HEAD: ignored
        ]
        mined = []
        with (
            patch("mempalace_code.watcher.mine", side_effect=lambda **kw: mined.append(kw) or {}),
            patch("watchfiles.watch", side_effect=_watch_yielding(batches)),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(str(worktree), str(tmp_path / "palace"), operation_lock=_lock(tmp_path))

        assert len(mined) == 3, "initial mine + commit cycle + checkout cycle"
        assert {call["project_dir"] for call in mined} == {str(worktree.resolve())}

    @requires_git
    def test_reftable_repository_is_watched(self, tmp_path):
        project = _project(tmp_path / "rt", "rt")
        created = subprocess.run(
            [GIT or "git", "init", "-q", "--ref-format=reftable", "-b", "main"],
            cwd=project,
            capture_output=True,
        )
        if created.returncode != 0:
            pytest.skip("this git does not support the reftable ref format")
        _git(project, "add", "-A")
        _git(project, "commit", "-qm", "init")

        plan = plan_watch_root(str(project), on_commit=True)

        assert [t.path for t in plan.git_targets] == [(project / ".git" / "reftable").resolve()]

    def test_checkout_in_normal_checkout_triggers_remine(self, tmp_path):
        """watch-3 (8): a branch checkout moves HEAD, not refs/heads, and must re-mine."""
        project = _project(tmp_path / "proj", "proj", git=True)
        logs = project / ".git" / "logs"
        logs.mkdir()
        (logs / "HEAD").write_text("", encoding="utf-8")
        mined = []

        with (
            patch("mempalace_code.watcher.mine", side_effect=lambda **kw: mined.append(kw) or {}),
            patch(
                "watchfiles.watch",
                side_effect=_watch_yielding([{(2, str((logs / "HEAD").resolve()))}]),
            ),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(str(project), str(tmp_path / "palace"), operation_lock=_lock(tmp_path))

        assert len(mined) == 2


# ---------------------------------------------------------------------------
# watch-2: vanished projects and sys.exit inside mine()
# ---------------------------------------------------------------------------


class TestVanishedProjects:
    def test_removed_init_file_drops_project_and_exits_with_markers(self, tmp_path, capsys):
        project = _project(tmp_path / "proj", "gone", git=True)

        def batches(*_paths, **_kwargs):
            (project / "mempalace.yaml").unlink()
            yield {(2, str(project / "app.py"))}

        with (
            patch("mempalace_code.watcher._make_run_id", return_value="W2"),
            patch("mempalace_code.watcher.mine", return_value={}) as mine,
            patch("watchfiles.watch", side_effect=batches),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                watch_all(
                    str(project),
                    str(tmp_path / "palace"),
                    on_commit=False,
                    operation_lock=_lock(tmp_path),
                )

        assert exc_info.value.code == 1
        assert mine.call_count == 1, "only the initial mine; the dropped project is not mined"
        captured = capsys.readouterr()
        assert "is no longer initialized (mempalace.yaml is missing)" in captured.err
        assert f"mempalace-code init {shlex.quote(str(project.resolve()))}" in captured.err
        palace = shlex.quote(str(tmp_path / "palace"))
        restart = f"mempalace-code --palace {palace} watch {shlex.quote(str(project.resolve()))}"
        assert f"then restart the watcher:  {restart} --on-save\n" in captured.err
        assert "state=project-dropped wing=gone reason=uninitialized" in captured.out
        assert "WATCH_RUN run_id=W2 state=stopped reason=no-projects" in captured.out

    def test_idle_timeout_detects_deleted_root(self, tmp_path, capsys):
        project = _project(tmp_path / "p", "gone")

        def batches(*_paths, **kwargs):
            assert kwargs["yield_on_timeout"] is True
            shutil.rmtree(project)
            yield set()  # idle timeout: no events arrive for a deleted root

        with (
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("watchfiles.watch", side_effect=batches),
        ):
            with pytest.raises(SystemExit) as exc_info:
                watch_and_mine(
                    str(project), str(tmp_path / "palace"), operation_lock=_lock(tmp_path)
                )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "was removed or moved (directory not found)" in captured.err
        # mine --watch labels markers with the configured wing, not the directory name,
        # and names the exact command that restarts it.
        assert "state=project-dropped wing=gone reason=removed" in captured.out
        palace = shlex.quote(str(tmp_path / "palace"))
        restart = f"mempalace-code --palace {palace} mine {shlex.quote(str(project.resolve()))}"
        assert f"then restart the watcher:  {restart} --watch\n" in captured.err
        assert "state=stopped reason=no-projects" in captured.out

    def test_other_projects_keep_being_watched(self, tmp_path, capsys):
        parent = tmp_path / "parent"
        keep = _project(parent / "keep", "keep")
        gone = _project(parent / "gone", "gone")
        mined = []

        def batches(*_paths, **_kwargs):
            shutil.rmtree(gone)
            yield set()
            yield {(2, str(keep / "app.py"))}

        with (
            patch("mempalace_code.watcher.mine", side_effect=lambda **kw: mined.append(kw) or {}),
            patch("watchfiles.watch", side_effect=batches),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(
                str(parent),
                str(tmp_path / "palace"),
                on_commit=False,
                operation_lock=_lock(tmp_path),
            )

        assert mined[-1]["project_dir"] == str(keep.resolve())
        out = capsys.readouterr().out
        assert "state=project-dropped wing=gone reason=removed" in out
        assert "across 1 project(s)" in out

    def test_project_vanishing_before_watch_starts_restarts_on_the_rest(self, tmp_path, capsys):
        parent = tmp_path / "parent"
        keep = _project(parent / "keep", "keep")
        gone = _project(parent / "gone", "gone")
        calls = []

        def watch(*paths, **_kwargs):
            calls.append(paths)
            if len(calls) == 1:
                shutil.rmtree(gone)
                raise FileNotFoundError(f"No path was found. about {list(paths)}")
            yield from ()

        with (
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("watchfiles.watch", side_effect=watch),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(
                str(parent),
                str(tmp_path / "palace"),
                on_commit=False,
                operation_lock=_lock(tmp_path),
            )

        assert calls[-1] == (str(keep.resolve()),)
        captured = capsys.readouterr()
        assert "Traceback" not in captured.out + captured.err
        assert "reason=removed" in captured.out

    def test_sys_exit_inside_mine_is_reported_and_watcher_keeps_running(self, tmp_path, capfd):
        project = _project(tmp_path / "proj", "proj")
        calls = []

        def fake_mine(**_kwargs):
            calls.append(1)
            if len(calls) == 2:
                os.write(1, b"ERROR: No mempalace.yaml found in /somewhere\n")
                raise SystemExit(1)
            return {"files_processed": 1, "drawers_filed": 1}

        changes = [{(2, str(project / "app.py"))}, {(2, str(project / "app.py"))}]
        with (
            patch("mempalace_code.watcher._make_run_id", return_value="W2B"),
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("mempalace_code.watcher._optimize_once", return_value="completed"),
            patch("watchfiles.watch", side_effect=_watch_yielding(changes)),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"), operation_lock=_lock(tmp_path))

        assert len(calls) == 3, "the watcher survived the failed cycle and ran the next one"
        captured = capfd.readouterr()
        assert "Error [proj]: re-mine failed: ERROR: No mempalace.yaml found" in captured.err
        assert "WATCH_RUN run_id=W2B state=cycle-failed wing=proj" in captured.out

    def test_mine_warnings_are_replayed_after_a_successful_cycle(self, tmp_path, capfd):
        project = _project(tmp_path / "proj", "proj")

        def fake_mine(**_kwargs):
            os.write(1, b"progress line that stays quiet\n")
            os.write(2, b"  Stale-file sweep failed: disk is read-only\n")
            return {}

        with (
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_watch_yielding([])),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"), operation_lock=_lock(tmp_path))

        captured = capfd.readouterr()
        assert "Stale-file sweep failed: disk is read-only" in captured.err
        assert "progress line that stays quiet" not in captured.out + captured.err


# ---------------------------------------------------------------------------
# watch-3: noise and precision
# ---------------------------------------------------------------------------


class TestWatcherPrecision:
    def test_churn_warning_ignores_git_metadata(self, tmp_path, capsys):
        parent = tmp_path / "parent"
        plain_repo = _project(parent / "plain", "plain", git=True)
        heavy_repo = _project(parent / "heavy", "heavy", git=True)
        (heavy_repo / "node_modules").mkdir()

        with (
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("watchfiles.watch", side_effect=_watch_yielding([])),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(
                str(parent),
                str(tmp_path / "palace"),
                on_commit=False,
                operation_lock=_lock(tmp_path),
            )

        out = capsys.readouterr().out
        assert f"[{plain_repo.name}] high-churn" not in out
        assert "[heavy] high-churn directories detected: node_modules." in out

    def test_deletion_only_cycle_is_reported(self, tmp_path, capsys):
        project = _project(tmp_path / "proj", "proj")
        deleted = project / "old_module.py"

        with (
            patch("mempalace_code.watcher.mine", return_value={"files_processed": 0}),
            patch(
                "watchfiles.watch",
                side_effect=_watch_yielding([{(3, str(deleted)), (2, str(deleted))}]),
            ),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(
                str(project),
                str(tmp_path / "palace"),
                on_commit=False,
                operation_lock=_lock(tmp_path),
            )

        out = capsys.readouterr().out
        assert (
            "[proj: 1 change(s)] 0 file(s), 0 drawer(s) (0s); "
            "deleted source(s) swept: old_module.py"
        ) in out

    def test_file_path_names_the_project_to_watch(self, tmp_path, capsys):
        project = _project(tmp_path / "proj", "proj", git=True)
        (project / "src").mkdir()
        source = project / "src" / "auth.py"
        source.write_text("x = 1\n", encoding="utf-8")

        with pytest.raises(SystemExit):
            watch_all(str(source), str(tmp_path / "palace"), operation_lock=_lock(tmp_path))

        err = capsys.readouterr().err
        assert f"{source.resolve()} is a file; watch takes a directory" in err
        assert f"watch {shlex.quote(str(project.resolve()))}" in err
        assert "directory not found" not in err

    def test_second_watcher_on_the_same_project_and_palace_is_refused(self, tmp_path, capsys):
        project = _project(tmp_path / "proj", "proj")
        palace = str(tmp_path / "palace")
        lock = _lock(tmp_path)
        guards = watcher._ProjectWatchGuards(lock.path.parent, palace)
        assert guards.acquire(project.resolve()) is None
        try:
            with patch("mempalace_code.watcher.mine") as mine:
                with pytest.raises(SystemExit) as exc_info:
                    watch_all(str(project), palace, on_commit=False, operation_lock=lock)
        finally:
            guards.release_all()

        assert exc_info.value.code == 1
        mine.assert_not_called()
        err = capsys.readouterr().err
        assert f"already watched into this palace (pid {os.getpid()})" in err
        assert f"Stop it first:  kill {os.getpid()}" in err

        # Released guards let the next watcher start, and leave no lock file behind.
        with (
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("watchfiles.watch", side_effect=_watch_yielding([])),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(str(project), palace, on_commit=False, operation_lock=lock)
        assert not list(lock.path.parent.glob("watch-*"))

    def test_guard_survives_a_released_file_and_skips_pathless_locks(self, tmp_path):
        palace = str(tmp_path / "palace")
        project = tmp_path / "proj"
        first = watcher._ProjectWatchGuards(tmp_path, palace)
        assert first.acquire(project) is None
        first.release_all()
        second = watcher._ProjectWatchGuards(tmp_path, palace)
        third = watcher._ProjectWatchGuards(tmp_path, palace)
        assert second.acquire(project) is None
        assert third.acquire(project) == f"pid {os.getpid()}"
        second.release_all()
        assert third.acquire(project) is None
        third.release_all()
        assert not list(tmp_path.glob("watch-*"))
        assert watcher._ProjectWatchGuards(None, palace).acquire(project) is None

    def test_guard_sweeps_the_claim_of_a_crashed_watcher(self, tmp_path):
        palace = str(tmp_path / "palace")
        project = tmp_path / "proj"
        crashed = watcher._ProjectWatchGuards(tmp_path, palace)
        assert crashed.acquire(project) is None
        assert crashed._claim is not None
        fd, claim = crashed._claim
        os.close(fd)  # the kernel drops the flock of a dead process
        crashed._claim = None

        survivor = watcher._ProjectWatchGuards(tmp_path, palace)
        assert survivor.acquire(project) is None
        assert not claim.exists()
        survivor.release_all()
        assert not list(tmp_path.glob("watch-*"))

    def test_guard_holds_one_descriptor_for_hundreds_of_projects(self, tmp_path):
        # launchd gives a LaunchAgent a soft limit of 256 descriptors; a parent watch
        # of hundreds of projects must not spend one per project.
        script = f"""
import os, resource, sys
from pathlib import Path
import mempalace_code.watcher as watcher
resource.setrlimit(resource.RLIMIT_NOFILE, (64, resource.getrlimit(resource.RLIMIT_NOFILE)[1]))
lock_dir = Path({str(tmp_path / "install")!r})
projects = [Path({str(tmp_path)!r}) / f"p{{i}}" for i in range(300)]
first = watcher._ProjectWatchGuards(lock_dir, "palace")
assert first.acquire_many(projects) == {{}}
second = watcher._ProjectWatchGuards(lock_dir, "palace")
taken = second.acquire_many(projects[:5] + [Path("/elsewhere")])
assert sorted(taken) == projects[:5], taken
assert set(taken.values()) == {{f"pid {{os.getpid()}}"}}
second.release_all()
first.release_all()
assert not list(lock_dir.glob("watch-*"))
print("ok")
"""
        env = {**os.environ, "PYTHONPATH": str(Path(watcher.__file__).parents[1])}
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=60
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ok"

    def test_guard_failure_warns_and_watches_unguarded(self, tmp_path, capsys):
        project = _project(tmp_path / "proj", "proj")
        palace = str(tmp_path / "palace")
        lock = _lock(tmp_path)
        err = OSError(24, "Too many open files")
        with (
            patch.object(watcher._ProjectWatchGuards, "_write_claim", side_effect=err),
            patch("mempalace_code.watcher.mine", return_value={}) as mine,
            patch("watchfiles.watch", side_effect=_watch_yielding([])),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(str(project), palace, on_commit=False, operation_lock=lock)

        mine.assert_called()
        assert "could not check for other watchers" in capsys.readouterr().err
        assert not list(lock.path.parent.glob("watch-*"))

    def test_status_formats_size_and_quoted_watched_root(self, tmp_path, capsys):
        root = tmp_path / "my projects"
        _project(root, "spaced")
        palace = tmp_path / "palace"
        palace.mkdir()
        label = watch_launchd_label(root)
        launchctl = MagicMock(returncode=0)
        launchctl.stdout = (
            f"gui/501/{label} = {{\n"
            "    state = running\n"
            "    stdout path = /Users/example/Library/Logs/job.log\n"
            "    arguments = {\n"
            "        /bin/sh\n"
            "        -c\n"
            f"        '/opt/mem bin/mempalace-code' watch {shlex.quote(str(root.resolve()))}"
            " --on-save\n"
            "    }\n"
            "    last exit code = 78: EX_CONFIG\n"
            "}\n"
        )
        argv = ["mempalace-code", "--palace", str(palace), "watch", str(root), "status"]
        with (
            patch.object(sys, "argv", argv),
            patch("sys.platform", "darwin"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
            patch("subprocess.run", return_value=launchctl),
        ):
            main()

        out = capsys.readouterr().out
        assert "Palace sz:" not in out
        assert re.search(r"^  Size:     \S+ \S+ \(palace\)$", out, re.MULTILINE)
        assert f"Watched root: {root.resolve()}" in out
        assert "LaunchAgent: last exit code = 78" in out
        assert f"Stop:     launchctl bootout gui/{os.getuid()}/{label}" in out
        assert "inspect /Users/example/Library/Logs/job.log" in out

    @pytest.mark.parametrize("on_save", [False, True])
    def test_status_checks_git_for_a_loaded_commit_mode_job(self, tmp_path, capsys, on_save):
        root = _project(tmp_path / "nogit", "nogit")
        label = watch_launchd_label(root)
        launchctl = MagicMock(returncode=0)
        launchctl.stdout = (
            f"gui/501/{label} = {{\n"
            "    state = running\n"
            "    arguments = {\n"
            "        /opt/mempalace-code\n"
            "        watch\n"
            f"        {root.resolve()}\n" + ("        --on-save\n" if on_save else "") + "    }\n"
            "}\n"
        )
        argv = ["mempalace-code", "watch", str(root), "status"]
        with (
            patch.object(sys, "argv", argv),
            patch("sys.platform", "darwin"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
            patch("subprocess.run", return_value=launchctl),
        ):
            main()

        out = capsys.readouterr().out
        if on_save:
            assert "Runnable: yes" in out
        else:
            assert "Runnable: no  (watch root: the loaded job runs in commit mode" in out
            assert f"watch {shlex.quote(str(root.resolve()))} --on-save schedule" in out

    def test_status_reports_missing_root_as_not_runnable(self, tmp_path, capsys):
        argv = ["mempalace-code", "watch", str(tmp_path / "nope"), "status"]
        with (
            patch.object(sys, "argv", argv),
            patch("sys.platform", "linux"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
        ):
            main()

        out = capsys.readouterr().out
        assert "Runnable: no  (watch root: directory not found" in out
        assert "Runnable: yes" not in out

    def test_status_names_the_setting_that_chose_the_disk_floor(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("MEMPALACE_WATCH_DISK_MIN_FREE_BYTES", "10TiB")
        root = _project(tmp_path / "proj", "proj", git=True)
        argv = ["mempalace-code", "watch", str(root), "status"]
        with (
            patch.object(sys, "argv", argv),
            patch("sys.platform", "linux"),
            patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
        ):
            main()

        out = capsys.readouterr().out
        assert "(from MEMPALACE_WATCH_DISK_MIN_FREE_BYTES)" in out
        assert "Next: free disk space or lower MEMPALACE_WATCH_DISK_MIN_FREE_BYTES" in out


# ---------------------------------------------------------------------------
# Per-cycle robustness and shutdown during startup
# ---------------------------------------------------------------------------


class TestCycleRobustness:
    def test_palace_busy_cycle_is_skipped_and_the_next_change_mines(self, tmp_path, capfd):
        project = _project(tmp_path / "proj", "proj")
        calls = []

        def fake_mine(**_kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise PalaceBusyError(str(tmp_path / "palace"), {"operation": "mine", "pid": 42})
            return {"files_processed": 1, "drawers_filed": 0}

        changes = [{(2, str(project / "app.py"))}, {(2, str(project / "app.py"))}]
        with (
            patch("mempalace_code.watcher._make_run_id", return_value="BUSY"),
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=_watch_yielding(changes)),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"), operation_lock=_lock(tmp_path))

        assert len(calls) == 3, "the busy cycle was skipped and the next change mined"
        captured = capfd.readouterr()
        assert (
            "Skipped [proj]: another MemPalace writer held the palace past the wait "
            "(operation=mine, pid=42); the watcher retries on the next change." in captured.out
        )
        assert "WATCH_RUN run_id=BUSY state=cycle-skipped wing=proj reason=palace-busy" in (
            captured.out
        )
        assert "re-mine failed" not in captured.err

    def test_wait_for_another_writer_is_logged_outside_the_mine_capture(self, tmp_path, capfd):
        project = _project(tmp_path / "proj", "proj")
        palace = tmp_path / "palace"
        other_writer = OperationLock.for_palace(palace).acquire_exclusive("mine")
        release = threading.Timer(0.5, other_writer.release)
        release.start()
        try:
            with (
                patch("mempalace_code.watcher.mine", return_value={}),
                patch("watchfiles.watch", side_effect=_watch_yielding([])),
            ):
                watch_and_mine(str(project), str(palace), operation_lock=_lock(tmp_path))
        finally:
            release.cancel()
            other_writer.release()

        err = capfd.readouterr().err
        assert f"Waiting for another MemPalace writer to finish with {palace}" in err
        assert "operation=mine" in err

    def test_knowledge_graph_failure_fails_only_that_cycle(self, tmp_path, capsys):
        project = _project(tmp_path / "proj", "proj")
        opened = []

        def open_kg(_palace):
            opened.append(1)
            if len(opened) == 2:
                raise sqlite3.OperationalError("database is locked")
            return MagicMock()

        mined = []
        changes = [{(2, str(project / "app.py"))}, {(2, str(project / "app.py"))}]
        with (
            patch("mempalace_code.watcher._make_run_id", return_value="KG"),
            patch("mempalace_code.knowledge_graph.open_palace_kg", side_effect=open_kg),
            patch(
                "mempalace_code.watcher.mine",
                side_effect=lambda **kw: mined.append(kw) or {"files_processed": 1},
            ),
            patch("watchfiles.watch", side_effect=_watch_yielding(changes)),
        ):
            watch_all(
                str(project),
                str(tmp_path / "palace"),
                on_commit=False,
                operation_lock=_lock(tmp_path),
            )

        assert len(mined) == 2, "the initial mine and the cycle after the failed one ran"
        captured = capsys.readouterr()
        assert "Error [proj]: re-mine failed: database is locked" in captured.err
        assert "WATCH_RUN run_id=KG state=cycle-failed wing=proj" in captured.out


class TestShutdownDuringStartup:
    @pytest.mark.parametrize("entrypoint", ["watch_and_mine", "watch_all"])
    def test_sigterm_during_initial_mine_records_state_and_releases_leases(
        self, tmp_path, capsys, entrypoint
    ):
        project = _project(tmp_path / "proj", "proj")
        lock = _lock(tmp_path)
        original = signal.getsignal(signal.SIGTERM)
        seen = {}

        def fake_mine(**_kwargs):
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler), "the shutdown handler is installed before the mine"
            seen["owners"] = json.loads(lock.owners_path.read_text(encoding="utf-8"))
            handler(signal.SIGTERM, None)
            raise AssertionError("the startup handler must interrupt the mine")

        watch = MagicMock(side_effect=AssertionError("the watch loop must not start"))
        with (
            patch("mempalace_code.watcher._make_run_id", return_value="TERM"),
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", new=watch),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            if entrypoint == "watch_and_mine":
                watch_and_mine(str(project), str(tmp_path / "palace"), operation_lock=lock)
            else:
                watch_all(
                    str(project), str(tmp_path / "palace"), on_commit=False, operation_lock=lock
                )

        watch.assert_not_called()
        assert [o["operation"] for o in seen["owners"].values()] == ["watcher"]
        assert json.loads(lock.owners_path.read_text(encoding="utf-8")) == {}
        assert signal.getsignal(signal.SIGTERM) is original
        out = capsys.readouterr().out
        assert "WATCH_RUN run_id=TERM state=interrupted stage=startup" in out
        assert "state=initial-mine-completed" not in out


# ---------------------------------------------------------------------------
# conc-2: a transient 'Not found' never rolls back the shared palace
# ---------------------------------------------------------------------------


class TestNoSharedPalaceRollback:
    def test_transient_not_found_keeps_other_projects_rows(self, tmp_path, monkeypatch, capsys):
        from mempalace_code.mining.orchestrator import mine as real_mine
        from mempalace_code.storage import open_store

        monkeypatch.setattr(watcher, "_TRANSIENT_RETRY_DELAY_SECS", 0)
        palace = str(tmp_path / "shared palace")
        project_a = _project(tmp_path / "a", "wing_a")
        project_b = _project(tmp_path / "b", "wing_b")
        real_mine(str(project_a), palace, skip_optimize=True)
        real_mine(str(project_b), palace, skip_optimize=True)

        def rows(wing: str) -> int:
            store = open_store(palace, create=False, read_only=True)
            return len(store.get(where={"wing": wing})["ids"])

        b_rows = rows("wing_b")
        assert b_rows > 0
        calls = []

        def flaky_mine(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("lance error: Not found: wing_b fragment vanished (cleanup)")
            return real_mine(**kwargs)

        with (
            patch("mempalace_code.watcher.mine", side_effect=flaky_mine),
            patch("watchfiles.watch", side_effect=_watch_yielding([])),
            patch("mempalace_code.watcher._optimize_once", return_value="completed"),
        ):
            watch_all(str(project_a), palace, on_commit=False, operation_lock=_lock(tmp_path))

        assert rows("wing_b") == b_rows, "another project's drawers survived the watcher"
        out = capsys.readouterr().out
        assert "Transient storage error" in out
        assert "rolled back" not in out
        assert len(calls) == 2

    def test_pre_watch_backup_retries_a_file_removed_by_a_concurrent_writer(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(watcher, "_TRANSIENT_RETRY_DELAY_SECS", 0)
        project = _project(tmp_path / "proj", "proj")
        palace = tmp_path / "palace"
        (palace / "lance").mkdir(parents=True)
        (palace / "lance" / "data.lance").write_bytes(b"x")
        vanished = FileNotFoundError(2, "No such file or directory", "_transactions/153.txn")

        with (
            patch(
                "mempalace_code.watcher.create_backup",
                side_effect=[vanished, ({}, "pre_watch_1.tar.gz")],
            ) as backup,
            patch("mempalace_code.watcher.mine", return_value={}) as mine,
            patch("watchfiles.watch", side_effect=_watch_yielding([])),
        ):
            watch_and_mine(str(project), str(palace), operation_lock=_lock(tmp_path))

        assert backup.call_count == 2
        mine.assert_called_once()
        out = capsys.readouterr().out
        assert "Transient backup error" in out
        assert "Pre-watch backup: pre_watch_1.tar.gz" in out

    def test_pre_watch_backup_that_keeps_failing_still_fails_closed(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(watcher, "_TRANSIENT_RETRY_DELAY_SECS", 0)
        project = _project(tmp_path / "proj", "proj")
        palace = tmp_path / "palace"
        (palace / "lance").mkdir(parents=True)
        (palace / "lance" / "data.lance").write_bytes(b"x")

        with (
            patch(
                "mempalace_code.watcher.create_backup",
                side_effect=FileNotFoundError(2, "No such file or directory", "x.txn"),
            ) as backup,
            patch("mempalace_code.watcher.mine") as mine,
        ):
            with pytest.raises(SystemExit) as exc_info:
                watch_and_mine(str(project), str(palace), operation_lock=_lock(tmp_path))

        assert exc_info.value.code == 1
        assert backup.call_count == watcher._TRANSIENT_MINE_ATTEMPTS
        mine.assert_not_called()
        captured = capsys.readouterr()
        assert "state=pre-watch-backup-failed" in captured.out
        assert "Watcher did not start." in captured.err


# ---------------------------------------------------------------------------
# sched-1 / sched-2 / gap-11 / daemon-env
# ---------------------------------------------------------------------------


def _render_cli(tmp_path, monkeypatch, argv_tail, *, palace=None):
    launcher = tmp_path / "bin dir" / "mempalace-code"
    launcher.parent.mkdir(exist_ok=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sys, "platform", "darwin")
    argv = [str(launcher)]
    if palace is not None:
        argv += ["--palace", str(palace)]
    monkeypatch.setattr(sys, "argv", argv + argv_tail)
    return launcher, home


class TestScheduleRendering:
    def test_schedule_reproduces_palace_and_watch_flags(self, tmp_path, monkeypatch, capsys):
        root = _project(tmp_path / "projects", "projects")
        palace = tmp_path / "p2 palace"
        launcher, _home = _render_cli(
            tmp_path,
            monkeypatch,
            ["watch", str(root), "--on-save", "--agent", "bot1", "--no-gitignore", "schedule"],
            palace=palace,
        )

        main()

        captured = capsys.readouterr()
        plist = plistlib.loads(captured.out.encode())
        tokens = shlex.split(plist["ProgramArguments"][2])
        assert tokens == [
            str(launcher),
            "watch",
            str(root.resolve()),
            "--palace",
            str(palace),
            "--on-save",
            "--agent",
            "bot1",
            "--no-gitignore",
        ]
        assert _is_supported_watch_command(tokens), "update discovery still attributes the job"
        rerender = (
            f"{shlex.quote(str(launcher))} --palace {shlex.quote(str(palace))} watch "
            f"{shlex.quote(str(root.resolve()))} --on-save --agent bot1 --no-gitignore schedule"
        )
        assert f"# Re-render: {rerender}" in captured.err

    def test_rendered_command_runs_with_the_requested_palace(self, tmp_path):
        root = _project(tmp_path / "proj", "proj", git=True)
        record = tmp_path / "argv"
        launcher = tmp_path / "mempalace-code"
        launcher.write_text(
            f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {shlex.quote(str(record))}\n", encoding="utf-8"
        )
        launcher.chmod(0o755)

        line = render_watch_schedule(
            str(root), "linux", mempalace_bin=str(launcher), palace_path=str(tmp_path / "pal")
        )
        subprocess.run(["/bin/sh", "-c", line.removeprefix("@reboot ")], check=True)

        assert record.read_text().splitlines() == [
            "watch",
            str(root.resolve()),
            "--palace",
            str(tmp_path / "pal"),
        ]

    @pytest.mark.parametrize(
        ("case", "expected"),
        [
            ("missing", "directory not found"),
            ("file", "is a file; watch takes a directory"),
            ("non-git", "--on-save schedule"),
            ("no-watchfiles", "'watchfiles' is not installed"),
        ],
    )
    def test_schedule_refuses_roots_that_would_crash_loop(
        self, tmp_path, monkeypatch, capsys, case, expected
    ):
        project = _project(tmp_path / "proj", "proj", git=case == "no-watchfiles")
        target = {
            "missing": tmp_path / "nope",
            "file": project / "app.py",
            "non-git": project,
            "no-watchfiles": project,
        }[case]
        _render_cli(tmp_path, monkeypatch, ["watch", str(target), "schedule"])
        real_find_spec = watcher.importlib.util.find_spec

        def find_spec(name, *args, **kwargs):
            if case == "no-watchfiles" and name == "watchfiles":
                return None
            return real_find_spec(name, *args, **kwargs)

        with patch.object(watcher.importlib.util, "find_spec", side_effect=find_spec):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == "", "no daemon snippet is printed for a refused root"
        assert expected in captured.err

    def test_each_root_gets_its_own_job_label_plist_and_log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        first = _project(tmp_path / "wpf app", "wpf", git=True)
        second = _project(tmp_path / "infra", "infra", git=True)

        plists = [
            plistlib.loads(
                render_watch_schedule(
                    str(root), "darwin", mempalace_bin="/usr/bin/mempalace-code"
                ).encode()
            )
            for root in (first, second, first)
        ]

        labels = [p["Label"] for p in plists]
        assert labels[0] != labels[1]
        assert labels[0] == labels[2], "re-rendering one root replaces only its own job"
        assert labels[0].startswith("com.mempalace.watch.wpf-app-")
        assert all(_LAUNCHD_WATCH_LABEL.fullmatch(label) for label in labels)
        logs = {p["StandardOutPath"] for p in plists}
        assert len(logs) == 2
        for p in plists:
            assert p["StandardOutPath"] == p["StandardErrorPath"]
            assert p["StandardOutPath"].startswith(str(tmp_path / "home" / "Library" / "Logs"))
            assert not p["StandardOutPath"].startswith("/tmp/")

    def test_schedule_guidance_names_the_per_root_plist(self, tmp_path, monkeypatch, capsys):
        root = _project(tmp_path / "proj", "proj", git=True)
        _launcher, home = _render_cli(tmp_path, monkeypatch, ["watch", str(root), "schedule"])

        main()

        err = capsys.readouterr().err
        label = watch_launchd_label(root)
        plist = shlex.quote(str(home / "Library" / "LaunchAgents" / f"{label}.plist"))
        assert f"> {plist}" in err
        assert f"launchctl load {plist}" in err
        assert "com.mempalace.watch.plist" not in err

    @pytest.mark.parametrize(
        ("other", "other_palace", "warned"),
        [
            ("legacy-same-root", None, True),
            ("parent-root", None, True),
            ("parent-root", "other", False),
            ("unrelated-root", None, False),
        ],
    )
    def test_schedule_warns_about_an_overlapping_saved_job(
        self, tmp_path, monkeypatch, capsys, other, other_palace, warned
    ):
        parent = tmp_path / "projects"
        root = _project(parent / "proj", "proj", git=True)
        _launcher, home = _render_cli(tmp_path, monkeypatch, ["watch", str(root), "schedule"])
        agents = home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        other_root = {
            "legacy-same-root": root,
            "parent-root": parent,
            "unrelated-root": tmp_path / "elsewhere",
        }[other]
        name = "com.mempalace.watch" if other == "legacy-same-root" else "com.mempalace.watch.x-1"
        command = f"mempalace-code watch {shlex.quote(str(other_root))}"
        if other_palace:
            command += f" --palace {shlex.quote(str(tmp_path / other_palace))}"
        saved = agents / f"{name}.plist"
        saved.write_bytes(
            plistlib.dumps({"Label": name, "ProgramArguments": ["/bin/sh", "-c", command]})
        )

        main()

        err = capsys.readouterr().err
        assert (f"Warning: {saved} already watches {other_root.resolve()}" in err) is warned
        if warned:
            assert f"launchctl unload {shlex.quote(str(saved))}" in err

    def test_plist_carries_environment_offline_default_and_exit_timeout(self, tmp_path):
        root = _project(tmp_path / "proj", "proj", git=True)
        environment = {
            "HF_HOME": str(tmp_path / "custom hf"),
            "MEMPALACE_WATCH_DISK_MIN_FREE_BYTES": "2GiB",
            "MEMPALACE_BACKUP_RETAIN_COUNT": "7",
            "HF_TOKEN": "hf_secret",
            "MEMPALACE_API_TOKEN": "secret",
            "PATH": "/usr/bin",
        }

        plist = plistlib.loads(
            render_watch_schedule(
                str(root),
                "darwin",
                mempalace_bin="/usr/bin/mempalace-code",
                environment=environment,
            ).encode()
        )

        assert plist["EnvironmentVariables"] == {
            "HF_HOME": str(tmp_path / "custom hf"),
            "HF_HUB_OFFLINE": "1",
            "MEMPALACE_BACKUP_RETAIN_COUNT": "7",
            "MEMPALACE_WATCH_DISK_MIN_FREE_BYTES": "2GiB",
        }
        assert plist["ExitTimeOut"] == 120
        assert plist["KeepAlive"] is True

    def test_explicit_offline_setting_is_kept_and_cron_line_carries_environment(self, tmp_path):
        root = _project(tmp_path / "proj", "proj", git=True)

        line = render_watch_schedule(
            str(root),
            "linux",
            mempalace_bin="/usr/bin/mempalace-code",
            environment={"HF_HUB_OFFLINE": "0", "HF_HOME": "/data/hf cache"},
        )

        assert line.startswith("@reboot HF_HOME='/data/hf cache' HF_HUB_OFFLINE=0 ")

    def test_uncached_model_is_warned_at_render_time(self, tmp_path, monkeypatch, capsys):
        root = _project(tmp_path / "proj", "proj", git=True)
        _render_cli(tmp_path, monkeypatch, ["watch", str(root), "schedule"])
        monkeypatch.setenv("HF_HOME", str(tmp_path / "empty hf"))

        main()

        err = capsys.readouterr().err
        assert f"not cached at {tmp_path / 'empty hf'}" in err
        # The recovery names the launcher that rendered the job, not whatever PATH finds.
        launcher = shlex.quote(str(tmp_path / "bin dir" / "mempalace-code"))
        assert f"{launcher} fetch-model" in err

    def test_install_refusal_uses_per_root_plist(self, tmp_path, monkeypatch, capsys):
        root = tmp_path / "some root"
        _render_cli(tmp_path, monkeypatch, [])

        with pytest.raises(SystemExit) as exc_info:
            cmd_watch_schedule(Namespace(dir=str(root), install=True, palace=None))

        assert exc_info.value.code == 2
        assert f"{watch_launchd_label(root)}.plist" in capsys.readouterr().err

    def test_plan_error_is_a_value_error_for_library_callers(self, tmp_path):
        with pytest.raises(ValueError, match="directory not found"):
            render_watch_schedule(str(tmp_path / "nope"), "linux")
        assert issubclass(WatchRootError, ValueError)
