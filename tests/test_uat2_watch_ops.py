"""UAT round-2 regressions for the watcher and operations group (watch-ops).

Each test reproduces one tester scenario at the smallest scope that proves it.
"""

import shlex
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import mempalace_code.watcher as watcher
from mempalace_code.cli import main
from mempalace_code.mining.orchestrator import mine
from mempalace_code.operation_lock import OperationLock
from mempalace_code.watcher import watch_all, watch_and_mine


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


def _lock(tmp_path: Path) -> OperationLock:
    return OperationLock(tmp_path / "install" / "operation.lock")


def _watch_yielding(batches):
    def fake_watch(*_paths, **_kwargs):
        yield from batches

    return fake_watch


def _module(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"def {name}():\n"
        f'    """Return the widget value computed by {name} for the dashboard."""\n'
        "    return 42\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# watch-1: directory renames and moves start an on-save cycle
# ---------------------------------------------------------------------------


class TestDirectoryEvents:
    def test_renamed_directory_is_relevant_on_both_sides(self, tmp_path):
        project = _project(tmp_path / "app", "app")
        _module(project / "handlers" / "m1.py", "m1")

        assert watcher._is_relevant_change(str(project / "handlers"), project)
        # The old name no longer exists: a moved-away directory must still start the sweep.
        assert watcher._is_relevant_change(str(project / "src"), project)

    def test_moved_away_dotted_directory_is_relevant_when_indexed(self, tmp_path):
        project = _project(tmp_path / "app", "app")
        indexed = {str(project / name / "m1.py") for name in ("lib.v2", "v1.2", "config.d")}

        def indexed_under(path):
            return any(source.startswith(path + "/") for source in indexed)

        # lib.v2, v1.2 and config.d look like files with unreadable suffixes, but the
        # palace holds sources under them, so they were directories that moved away.
        for name in ("lib.v2", "v1.2", "config.d"):
            assert watcher._is_relevant_change(
                str(project / name), project, indexed_under=indexed_under
            ), name
        # A deleted non-source file with nothing indexed under it stays irrelevant.
        for name in ("gone.pyc", ".m1.py.swp", "com.example"):
            assert not watcher._is_relevant_change(
                str(project / name), project, indexed_under=indexed_under
            ), name

    def test_indexed_prefixes_read_the_palace_once_and_fail_open(self, tmp_path):
        store = MagicMock()
        store.collection.count_by.return_value = {"/p/lib.v2/m1.py": 1, "/p/lib.v20.py": 1}
        lookup = watcher._IndexedSourcePrefixes(store)

        assert lookup("/p/lib.v2")
        assert not lookup("/p/lib.v")
        assert not lookup("/p/gone.pyc")
        assert store.collection.count_by.call_count == 1

        broken = MagicMock()
        broken.collection.count_by.side_effect = RuntimeError("palace unreadable")
        assert watcher._IndexedSourcePrefixes(broken)("/p/anything.bin")

    def test_on_save_dotted_directory_move_out_sweeps_its_drawers(self, tmp_path, capsys):
        project = _project(tmp_path / "app", "app").resolve()
        _module(project / "lib.v2" / "m1.py", "m1")
        palace = str(tmp_path / "palace")
        mine(str(project), palace, incremental=True)

        (tmp_path / "other").mkdir()

        def fake_watch(*_paths, **_kwargs):
            # The move happens after the watcher's startup mine, as with a live watcher.
            (project / "lib.v2").rename(tmp_path / "other" / "lib.v2")
            yield {(3, str(project / "lib.v2"))}

        with (
            patch("watchfiles.watch", side_effect=fake_watch),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(str(project), palace, on_commit=False, operation_lock=_lock(tmp_path))

        assert "deleted source(s) swept: lib.v2/m1.py" in capsys.readouterr().out
        sources = watcher.get_collection(palace).count_by("source_file")
        assert not any("lib.v2" in source for source in sources)

    def test_moved_in_directory_without_sources_is_ignored(self, tmp_path):
        project = _project(tmp_path / "app", "app")
        (project / "empty").mkdir()
        (project / "logs").mkdir()
        (project / "logs" / "run.bin").write_bytes(b"\0")

        assert not watcher._is_relevant_change(str(project / "empty"), project)
        assert not watcher._is_relevant_change(str(project / "logs"), project)

    def test_skipped_and_ignored_directories_stay_irrelevant(self, tmp_path):
        project = _project(tmp_path / "app", "app")
        _module(project / "node_modules" / "pkg" / "x.py", "x")
        _module(project / "build" / "gen.py", "gen")
        (project / ".gitignore").write_text("build/\ngone/\n", encoding="utf-8")

        assert not watcher._is_relevant_change(str(project / "node_modules"), project)
        assert not watcher._is_relevant_change(str(project / "build"), project)
        assert not watcher._is_relevant_change(str(project / "gone"), project)
        assert not watcher._is_relevant_change(str(project / "node_modules" / "old"), project)
        assert not watcher._is_relevant_change(str(project), project)

    def test_on_save_directory_rename_runs_a_cycle(self, tmp_path, capsys):
        project = _project(tmp_path / "app", "app")
        _module(project / "handlers" / "m1.py", "m1")
        stats = {
            "files_processed": 1,
            "drawers_filed": 1,
            "stale_sources_removed": [str(project / "src" / "m1.py")],
        }
        batch = {(1, str(project / "handlers")), (3, str(project / "src"))}

        with (
            patch("mempalace_code.watcher.mine", return_value=stats) as mine_mock,
            patch("watchfiles.watch", side_effect=_watch_yielding([batch])),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(
                str(project),
                str(tmp_path / "palace"),
                on_commit=False,
                operation_lock=_lock(tmp_path),
            )

        out = capsys.readouterr().out
        # The initial mine plus one cycle for the rename.
        assert mine_mock.call_count == 2
        assert "[app: 2 change(s)] 1 file(s), 1 drawer(s) (0s); " in out
        assert "deleted source(s) swept: src/m1.py" in out


# ---------------------------------------------------------------------------
# r1-watch-3: every mode reports what the stale sweep removed
# ---------------------------------------------------------------------------


class TestSweptReport:
    def test_mine_returns_the_swept_sources(self, tmp_path):
        project = _project(tmp_path / "app", "app")
        _module(project / "src" / "zebra.py", "zebra")
        palace = str(tmp_path / "palace")

        mine(str(project), palace, incremental=True)
        (project / "src" / "zebra.py").unlink()
        stats = mine(str(project), palace, incremental=True)

        assert stats["stale_sources_removed"] == [str((project / "src" / "zebra.py").resolve())]

    def test_commit_mode_cycle_names_swept_sources(self, tmp_path, capsys):
        project = _project(tmp_path / "p", "p", git=True)
        head_ref = project / ".git" / "refs" / "heads" / "main"
        stats = {
            "files_processed": 0,
            "drawers_filed": 0,
            "stale_sources_removed": [str(project / "src" / "zebra.py")],
        }

        with (
            patch("mempalace_code.watcher.mine", return_value=stats),
            patch("watchfiles.watch", side_effect=_watch_yielding([{(2, str(head_ref))}])),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            watch_all(str(project), str(tmp_path / "palace"), operation_lock=_lock(tmp_path))

        out = capsys.readouterr().out
        assert (
            "[git update in p] 0 file(s), 0 drawer(s) (0s); deleted source(s) swept: src/zebra.py"
        ) in out


# ---------------------------------------------------------------------------
# doc-2: a clean stop writes a WATCH_RUN terminal line
# ---------------------------------------------------------------------------


class TestCleanStopMarker:
    @pytest.mark.parametrize("entrypoint", ["watch_and_mine", "watch_all"])
    def test_signal_stop_emits_stopped_state(self, tmp_path, capsys, entrypoint):
        project = _project(tmp_path / "proj", "proj")
        with (
            patch("mempalace_code.watcher._make_run_id", return_value="STOP"),
            patch("mempalace_code.watcher.mine", return_value={}),
            patch("watchfiles.watch", side_effect=_watch_yielding([])),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph"),
        ):
            if entrypoint == "watch_and_mine":
                watch_and_mine(
                    str(project), str(tmp_path / "palace"), operation_lock=_lock(tmp_path)
                )
            else:
                watch_all(
                    str(project),
                    str(tmp_path / "palace"),
                    on_commit=False,
                    operation_lock=_lock(tmp_path),
                )

        out = capsys.readouterr().out
        assert "WATCH_RUN run_id=STOP state=stopped reason=signal" in out
        assert out.index("state=stopped reason=signal") < out.index("Watch stopped after")


# ---------------------------------------------------------------------------
# watch-4: a stop during a captured mine is acknowledged at once
# ---------------------------------------------------------------------------


class TestStopAcknowledgement:
    @pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
    def test_stop_during_initial_mine_is_acknowledged_before_the_flush(
        self, tmp_path, capfd, signum
    ):
        project = _project(tmp_path / "proj", "proj")
        seen = {}

        def fake_mine(**_kwargs):
            handler = signal.getsignal(signum)
            assert callable(handler)
            try:
                handler(signum, None)
            except KeyboardInterrupt:
                # What the operator sees while the orchestrator flushes its batch.
                seen["during_flush"] = capfd.readouterr().out
                raise
            raise AssertionError("the stop must interrupt the startup mine")

        with (
            patch("mempalace_code.watcher._make_run_id", return_value="ACK"),
            patch("mempalace_code.watcher.mine", side_effect=fake_mine),
            patch("watchfiles.watch", side_effect=AssertionError("no watch loop")),
        ):
            watch_and_mine(str(project), str(tmp_path / "palace"), operation_lock=_lock(tmp_path))

        assert (
            "Stop requested; finishing the current batch before exiting..."
            in (seen["during_flush"])
        )
        out = capfd.readouterr().out
        assert "WATCH_RUN run_id=ACK state=interrupted stage=startup" in out
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler

    def test_ignored_sigint_stays_ignored(self):
        original = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            signals = watcher._WatcherShutdownSignals()
            signals.install()
            assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
            signals.restore()
        finally:
            signal.signal(signal.SIGINT, original)


# ---------------------------------------------------------------------------
# watch-5: an all-uninitialized parent names each child's init command
# ---------------------------------------------------------------------------


class TestUninitializedParent:
    def test_error_names_each_uninitialized_child(self, tmp_path):
        parent = tmp_path / "uninit"
        child = parent / "y"
        child.mkdir(parents=True)
        (child / "pyproject.toml").write_text("[project]\nname='y'\n", encoding="utf-8")
        (child / ".git").mkdir()

        with pytest.raises(watcher.WatchRootError) as exc_info:
            watcher.plan_watch_root(str(parent), on_commit=False)

        message = str(exc_info.value)
        assert f"mempalace-code init {child.resolve()}" in message
        assert "<dir>" not in message

    def test_error_without_candidates_keeps_the_generic_hint(self, tmp_path):
        parent = tmp_path / "empty"
        parent.mkdir()

        with pytest.raises(watcher.WatchRootError) as exc_info:
            watcher.plan_watch_root(str(parent), on_commit=False)

        assert "Run mempalace-code init <dir> on a project under" in str(exc_info.value)


# ---------------------------------------------------------------------------
# watch-2 / r1-sched-2: `watch status` re-renders the job it describes
# ---------------------------------------------------------------------------


def _status(argv: list, capsys) -> str:
    not_loaded = MagicMock(returncode=1, stdout="")
    with (
        patch.object(sys, "argv", ["mempalace-code", *argv]),
        patch("sys.platform", "darwin"),
        patch("mempalace_code.disk_budget.free_bytes", return_value=5 * 1024**3),
        patch("subprocess.run", return_value=not_loaded),
    ):
        main()
    return capsys.readouterr().out


class TestWatchStatusRender:
    def test_saved_job_keeps_its_palace_and_flags(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        root = _project(tmp_path / "tw", "tw")
        palace = str(tmp_path / "pal")
        plist = watcher.render_watch_schedule(
            str(root),
            "darwin",
            "/opt/mp/bin/mempalace-code",
            palace_path=palace,
            on_save=True,
            agent="bot1",
            respect_gitignore=False,
        )
        label = watcher.watch_launchd_label(root)
        agents = home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        (agents / f"{label}.plist").write_text(plist, encoding="utf-8")

        out = _status(["watch", str(root), "status"], capsys)

        assert f"Palace:   {palace}" in out
        assert "Runnable: yes" in out
        assert (
            f" --palace {shlex.quote(palace)} watch {shlex.quote(str(root.resolve()))} "
            "--on-save --agent bot1 --no-gitignore schedule > "
        ) in out
        target = shlex.quote(str(agents / f"{label}.plist"))
        assert f"&& mv {shlex.quote(str(agents / f'{label}.plist.tmp'))} {target}" in out

    def test_status_flags_are_kept_without_a_saved_job(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        root = _project(tmp_path / "tw", "tw")
        palace = str(tmp_path / "pal")

        out = _status(
            ["--palace", palace, "watch", str(root), "--on-save", "--agent", "bot1", "status"],
            capsys,
        )

        assert "--on-save --agent bot1 schedule > " in out

    def test_commit_mode_root_without_git_is_not_runnable(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        root = _project(tmp_path / "c", "c")

        out = _status(["watch", str(root), "status"], capsys)

        assert "Runnable: no" in out
        assert "--on-save schedule" in out
        assert "launchctl load" not in out

    def test_on_save_root_without_git_is_runnable(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        root = _project(tmp_path / "c", "c")

        out = _status(["watch", str(root), "--on-save", "status"], capsys)

        assert "Runnable: yes" in out
        assert "--on-save schedule > " in out


# ---------------------------------------------------------------------------
# schedule-1 / sched-3: the backup job logs, carries its settings, and warns
# ---------------------------------------------------------------------------


class TestBackupSchedule:
    def test_plist_logs_and_carries_retention_settings(self, tmp_path, monkeypatch):
        import plistlib

        from mempalace_code.backup import backup_launchd_label, render_schedule

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        palace = str(tmp_path / "pal")
        plist = render_schedule(
            "daily",
            palace,
            "darwin",
            "/opt/mp/bin/mempalace-code",
            environment={"MEMPALACE_BACKUP_RETAIN_COUNT": "3", "GITHUB_TOKEN": "x"},
        )

        parsed = plistlib.loads(plist.encode("utf-8"))
        log = str(tmp_path / "home" / "Library" / "Logs" / f"{backup_launchd_label(palace)}.log")
        assert parsed["StandardOutPath"] == log
        assert parsed["StandardErrorPath"] == log
        assert parsed["EnvironmentVariables"] == {
            "HF_HUB_OFFLINE": "1",
            "MEMPALACE_BACKUP_RETAIN_COUNT": "3",
        }

    def test_cron_line_carries_the_settings(self, tmp_path):
        from mempalace_code.backup import render_schedule

        line = render_schedule(
            "daily",
            str(tmp_path / "pal"),
            "linux",
            "/opt/mp/bin/mempalace-code",
            environment={"MEMPALACE_BACKUP_RETAIN_COUNT": "3"},
        )

        assert line.startswith("0 3 * * * HF_HUB_OFFLINE=1 MEMPALACE_BACKUP_RETAIN_COUNT=3 ")

    def test_missing_palace_is_warned(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        missing = tmp_path / "nonexistent_pal"
        argv = ["mempalace-code", "--palace", str(missing), "backup", "schedule", "--freq", "daily"]
        with patch.object(sys, "argv", argv), patch("sys.platform", "darwin"):
            main()

        err = capsys.readouterr().err
        assert f"Warning: no palace exists at {missing}" in err
        assert "Log (refusals and failures of each run):" in err


# ---------------------------------------------------------------------------
# lease-1: a refusal names the holder's palace and the installation-wide scope
# ---------------------------------------------------------------------------


class TestLeaseHolderDiagnostics:
    def test_owner_record_carries_the_palace(self, tmp_path):
        lock = _lock(tmp_path)
        with lock.acquire_shared("mcp-stdio", palace=tmp_path / "base" / "palace"):
            owner = lock.owner_details()
        assert owner is not None
        assert owner["palace"] == str(tmp_path / "base" / "palace")

    def test_palace_write_lease_records_the_palace_on_the_install_lease(
        self, tmp_path, monkeypatch
    ):
        from mempalace_code.operation_lock import palace_write_lease

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        palace = str(tmp_path / "big" / "palace")
        with palace_write_lease(palace, "mine"):
            owner = OperationLock.default().owner_details()
        assert owner is not None
        assert owner["palace"] == palace

    def test_refusal_names_a_holder_on_another_palace(self, tmp_path, monkeypatch, capsys):
        from mempalace_code.cli_commands.common import acquire_operation_lease

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        other = str(tmp_path / "base" / "palace")
        target = str(tmp_path / "rs" / "other")
        with OperationLock.default().acquire_shared("mcp-stdio", palace=other):
            with pytest.raises(SystemExit):
                acquire_operation_lease("exclusive", "repair", target, ["repair"])

        err = capsys.readouterr().err
        assert "(operation=mcp-stdio pid=" in err
        assert (
            f"on palace {other}; the operation lease covers the whole MemPalace installation, "
            f"not only {target}"
        ) in err

    def test_refusal_for_a_holder_on_the_same_palace_stays_short(
        self, tmp_path, monkeypatch, capsys
    ):
        from mempalace_code.cli_commands.common import acquire_operation_lease

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        target = str(tmp_path / "pal")
        with OperationLock.default().acquire_shared("watcher", palace=target):
            with pytest.raises(SystemExit):
                acquire_operation_lease("exclusive", "cleanup", target, ["cleanup"])

        err = capsys.readouterr().err
        assert "covers the whole" not in err
        assert "(operation=watcher pid=" in err


# ---------------------------------------------------------------------------
# gap-10: mine-all with no initialized project fails loudly; --force is noted
# ---------------------------------------------------------------------------


class TestMineAllNothingInitialized:
    def test_all_uninitialized_exits_1_with_the_init_command(self, tmp_path, capsys):
        parent = tmp_path / "par"
        for name in ("alpha", "beta"):
            (parent / name / ".git").mkdir(parents=True)
            (parent / name / "main.py").write_text("x = 1\n", encoding="utf-8")
        argv = ["mempalace-code", "--palace", str(tmp_path / "pal2"), "mine-all", str(parent)]
        with patch.object(sys, "argv", [*argv, "--force"]), pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "--force is deprecated and has no effect" in captured.err
        assert "Summary: found 2, mined 0, skipped 2, errors 0" in captured.out
        assert "nothing mined: no project under" in captured.err
        from mempalace_code.cli_invocation import cli_command

        assert cli_command("init", str(parent.resolve() / "alpha")) in captured.err
        assert cli_command("init", str(parent.resolve() / "alpha")) in captured.out
        # The rerun names the user's --palace, not the default palace.
        rerun = cli_command("mine-all", str(parent.resolve()), palace=str(tmp_path / "pal2"))
        assert f"then run {rerun}" in captured.err

    def test_one_initialized_project_still_succeeds(self, tmp_path, capsys):
        parent = tmp_path / "par"
        _project(parent / "alpha", "alpha")
        (parent / "beta" / ".git").mkdir(parents=True)
        (parent / "beta" / "main.py").write_text("x = 1\n", encoding="utf-8")
        argv = ["mempalace-code", "--palace", str(tmp_path / "pal2"), "mine-all", str(parent)]
        with patch.object(sys, "argv", argv):
            main()

        captured = capsys.readouterr()
        assert "mined 1, skipped 1" in captured.out
        assert "nothing mined" not in captured.err


# ---------------------------------------------------------------------------
# ops-8: every Next: hint uses one launcher form
# ---------------------------------------------------------------------------


def test_live_watch_init_hint_uses_the_running_installation(tmp_path, capsys):
    from mempalace_code.cli_invocation import cli_command

    parent = tmp_path / "parent with spaces"
    child = parent / "child with spaces"
    (child / ".git").mkdir(parents=True)
    (child / "app.py").write_text("x = 1\n", encoding="utf-8")

    with patch.object(sys, "argv", ["/missing/mempalace-code"]):
        with pytest.raises(SystemExit) as stopped:
            watch_all(str(parent), str(tmp_path / "palace"), on_commit=False)
        assert stopped.value.code == 1
        assert cli_command("init", str(child.resolve())) in capsys.readouterr().err


def test_maintenance_and_degraded_hints_use_the_installation_launcher(tmp_path):
    from mempalace_code.cli_commands.common import palace_command
    from mempalace_code.cli_invocation import cli_command
    from mempalace_code.storage import PalaceReadError

    palace = str(tmp_path / "pal")
    assert palace_command(palace, "health") == cli_command("health", palace=palace)
    message = str(PalaceReadError(palace, RuntimeError("fragment missing")))
    assert cli_command("health", palace=palace) in message


# ---------------------------------------------------------------------------
# preflight-3 / docs-2: parent-directory mirrors and palace copies
# ---------------------------------------------------------------------------


class TestMirrorPreflightStateFamilies:
    def test_home_mirror_is_checked_for_state_families(self):
        from mempalace_code.mirror_preflight import classify_mirror_command

        result = classify_mirror_command(
            "rsync -a --delete --exclude='/.mempalace/palace/' ~/ user@host:backup/"
        )

        assert result.dangerous
        assert result.pattern_id == "delete-mode-state-mirror-missing-excludes"
        assert result.missing_excludes == [
            "kg",
            "config",
            "backups",
            "repair-backups",
            "quarantines",
        ]

    def test_home_mirror_excluding_the_state_dir_is_ok(self):
        from mempalace_code.mirror_preflight import classify_mirror_command

        assert classify_mirror_command(
            "rsync -a --delete --exclude=/.mempalace/ ~/ user@host:backup/"
        ).ok

    def test_repair_backups_and_quarantines_need_their_own_excludes(self):
        from mempalace_code.mirror_preflight import classify_mirror_command

        base = (
            "rsync -a --delete --exclude=palace/ --exclude=knowledge_graph.sqlite3 "
            "--exclude=knowledge_graph.sqlite3.adopted --exclude=config.json --exclude=backups/"
        )
        blocked = classify_mirror_command(f"{base} ~/.mempalace/ user@host:.mempalace/")
        assert blocked.dangerous
        assert blocked.missing_excludes == ["repair-backups", "quarantines"]

        star = base.replace("--exclude=palace/", "--exclude='palace*/'")
        assert classify_mirror_command(f"{star} ~/.mempalace/ user@host:.mempalace/").ok

    def test_relative_state_path_after_cd_is_blocked_as_documented(self):
        from mempalace_code.mirror_preflight import classify_mirror_command

        result = classify_mirror_command(
            "cd ~ && rsync -a --delete .mempalace/ user@host:.mempalace/"
        )
        assert result.pattern_id == "delete-mode-state-mirror-missing-excludes"
        guide = (Path(__file__).resolve().parent.parent / "docs" / "BACKUP_RESTORE.md").read_text(
            encoding="utf-8"
        )
        assert "a relative path that names `.mempalace` is still checked" in guide


def test_watch_messages_show_the_wing_normalized_as_mine_stores_it(tmp_path):
    from mempalace_code.watcher import _wing_label

    project = tmp_path / "proj"
    project.mkdir()
    assert _wing_label(project, "Other Wing") == "other_wing"
    (project / "mempalace.yaml").write_text("wing: proj\nrooms:\n  - name: general\n")
    assert _wing_label(project, "Other Wing") == "other_wing"
    assert _wing_label(project) == "proj"
