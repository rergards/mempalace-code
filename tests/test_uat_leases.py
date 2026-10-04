"""UAT regressions for palace write leases, handle freshness, and clean process exit.

Covers concurrent mines duplicating drawers (mcp-3, convos-8, hooks-4), long-lived
MCP/watcher handles broken or outdated by another process's mine (agent-1, mcp-2,
conc-1, perf-1), and the ONNX Runtime telemetry thread that aborted finished
processes at exit (native-1, mine-3).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from mempalace_code import operation_lock
from mempalace_code.operation_lock import (
    OperationLock,
    OperationLockedError,
    PalaceBusyError,
    holds_palace_write_lease,
    palace_lock_path,
    palace_write_lease,
)
from mempalace_code.storage import open_store

REPO_ROOT = Path(__file__).resolve().parents[1]

# A child process that runs the real CLI with the deterministic test embedder, so
# several real processes can race on one palace without a downloaded model.
_CLI_RUNNER = textwrap.dedent(
    """
    import hashlib, math, os, re, sys, time

    from mempalace_code import operation_lock
    from mempalace_code.storage import LanceStore


    class _Embedder:
        def ndims(self):
            return 384

        def compute_source_embeddings(self, texts):
            out = []
            for text in texts:
                vec = [0.0] * 384
                for token in re.findall(r"[A-Za-z0-9_]+", text.lower()):
                    digest = hashlib.blake2b(token.encode(), digest_size=4).digest()
                    vec[int.from_bytes(digest[:2], "little") % 384] += 1.0
                norm = math.sqrt(sum(v * v for v in vec)) or 1.0
                out.append([v / norm for v in vec])
            return out


    LanceStore._get_embedder = lambda self: _Embedder()
    if os.environ.get("TEST_LEASE_WAIT"):
        operation_lock.DEFAULT_PALACE_WRITE_WAIT_SECONDS = float(os.environ["TEST_LEASE_WAIT"])
    start = os.environ.get("TEST_START_FILE")
    while start and not os.path.exists(start):
        time.sleep(0.01)

    from mempalace_code.cli import _one_shot_main

    sys.argv = ["mempalace-code", *sys.argv[1:]]
    _one_shot_main()
    """
)

_LEASE_HOLDER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from mempalace_code.operation_lock import palace_write_lease

    with palace_write_lease(sys.argv[1], "test-holder"):
        Path(sys.argv[2]).write_text("held")
        while not Path(sys.argv[3]).exists():
            time.sleep(0.02)
    """
)


def _child_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), env.get("PYTHONPATH")]))
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["MEMPALACE_VERSION_CHECK"] = "0"
    env.pop("MEMPALACE_PALACE_PATH", None)
    return env


def _wait_for(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, f"timed out waiting for {path}"
        time.sleep(0.02)


class _ExternalHolder:
    """Hold one palace's write lease from another process until released."""

    def __init__(self, tmp_path: Path, palace: str) -> None:
        self._ready = tmp_path / "holder.ready"
        self._release = tmp_path / "holder.release"
        script = tmp_path / "holder.py"
        script.write_text(_LEASE_HOLDER, encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, str(script), palace, str(self._ready), str(self._release)],
            env=_child_env(Path(os.environ["HOME"])),
        )
        _wait_for(self._ready)

    def release(self) -> None:
        self._release.write_text("go")
        assert self.process.wait(timeout=30) == 0


def _write_convos(convo_dir: Path, files: int = 3, exchanges: int = 5) -> None:
    convo_dir.mkdir(parents=True, exist_ok=True)
    for f in range(files):
        lines = []
        for e in range(exchanges):
            lines.append(f"> Question {f}-{e}: who owns the schema registry for team {f}?")
            lines.append(f"The platform group {f} owns registry shard {e} and reviews changes.")
            lines.append("")
        (convo_dir / f"session-{f}.txt").write_text("\n".join(lines), encoding="utf-8")


def _write_project(project: Path, files: int = 4, marker: str = "v1") -> None:
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "mempalace.yaml").write_text(
        f"wing: {project.name}\nrooms:\n  - name: general\n    description: All files\n",
        encoding="utf-8",
    )
    for index in range(files):
        (project / "src" / f"mod{index}.py").write_text(
            f'"""Module {index} for {project.name} ({marker})."""\n\n\n'
            f"def handler_{index}(request):\n"
            f'    """Handle request number {index} in {project.name}."""\n'
            f"    return {{'module': {index}, 'marker': '{marker}', 'size': len(request)}}\n",
            encoding="utf-8",
        )


def _rows(palace: str) -> list[dict]:
    store = open_store(palace, create=False)
    return [row for batch in store.iter_all() for row in batch]  # type: ignore[attr-defined]  # reason: iter_all is defined on LanceStore, the only runtime store


# ── Lease API ─────────────────────────────────────────────────────────────────


def test_palace_lock_path_is_one_file_for_every_spelling_of_a_palace(tmp_path, monkeypatch):
    palace = tmp_path / "palace"
    palace.mkdir()
    link = tmp_path / "link"
    link.symlink_to(palace)
    monkeypatch.chdir(tmp_path)

    paths = {palace_lock_path(p) for p in (palace, str(link), "palace", f"{palace}/")}

    assert len(paths) == 1
    assert next(iter(paths)).parent == Path.home() / ".mempalace" / "locks"


def test_second_process_is_refused_while_a_writer_holds_the_palace(tmp_path):
    palace = str(tmp_path / "palace")
    holder = _ExternalHolder(tmp_path, palace)
    try:
        with pytest.raises(PalaceBusyError) as exc_info:
            with palace_write_lease(palace, "mine", wait=0.3, on_wait=lambda owner: None):
                pass
        assert exc_info.value.owner["operation"] == "test-holder"
        assert exc_info.value.owner["pid"] == holder.process.pid
        assert palace in str(exc_info.value)
    finally:
        holder.release()

    with palace_write_lease(palace, "mine", wait=0):
        pass


def test_waiting_writer_reports_the_owner_once_then_proceeds(tmp_path):
    palace = str(tmp_path / "palace")
    holder = _ExternalHolder(tmp_path, palace)
    notices: list[dict | None] = []
    releaser = threading.Timer(0.6, holder.release)
    releaser.start()
    try:
        started = time.monotonic()
        with palace_write_lease(palace, "mine", wait=20, on_wait=notices.append):
            waited = time.monotonic() - started
    finally:
        releaser.join()

    assert waited >= 0.5
    assert len(notices) == 1
    assert notices[0] is not None
    assert notices[0]["operation"] == "test-holder"


def test_nested_leases_in_one_thread_do_not_self_deadlock(tmp_path):
    palace = str(tmp_path / "palace")
    with palace_write_lease(palace, "mine", wait=0):
        with palace_write_lease(palace, "optimize", wait=0):
            with palace_write_lease(palace, "cleanup", wait=0):
                assert OperationLock.for_palace(palace).held_in_process()
    assert not OperationLock.for_palace(palace).held_in_process()
    assert not OperationLock.default().held_in_process()


def test_threads_of_one_process_take_turns(tmp_path):
    palace = str(tmp_path / "palace")
    inside = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def first():
        with palace_write_lease(palace, "first", wait=5):
            order.append("first-in")
            inside.set()
            release.wait(5)
            order.append("first-out")

    worker = threading.Thread(target=first)
    worker.start()
    assert inside.wait(5)
    with pytest.raises(PalaceBusyError):
        with palace_write_lease(palace, "second", wait=0.2):
            pass
    release.set()
    with palace_write_lease(palace, "second", wait=5):
        order.append("second-in")
    worker.join(5)
    assert order == ["first-in", "first-out", "second-in"]


def test_palace_writer_holds_the_shared_install_lease(tmp_path):
    palace = str(tmp_path / "palace")
    with palace_write_lease(palace, "mine", wait=0):
        with pytest.raises(OperationLockedError) as exc_info:
            OperationLock.default().acquire_exclusive("update")
        assert exc_info.value.owner["operation"] == "mine"
    with OperationLock.default().acquire_exclusive("update"):
        pass


def test_process_holding_the_install_lease_can_still_write(tmp_path):
    """Maintenance that took the install lease exclusively must not trip over itself."""
    palace = str(tmp_path / "palace")
    with OperationLock.default().acquire_exclusive("repair"):
        with palace_write_lease(palace, "cleanup", wait=0):
            pass


_INHERITED_LEASE_CHILD = textwrap.dedent(
    """
    import sys
    from mempalace_code.operation_lock import OperationLockedError, palace_write_lease

    try:
        with palace_write_lease(sys.argv[1], "mine", wait=0):
            print("wrote")
    except OperationLockedError as exc:
        print("refused", exc.owner.get("operation"))
    """
)


def _child_write_attempt(tmp_path: Path, token: str | None) -> str:
    script = tmp_path / "inherited_child.py"
    script.write_text(_INHERITED_LEASE_CHILD, encoding="utf-8")
    env = _child_env(Path(os.environ["HOME"]))
    env.pop(operation_lock.INHERITED_LEASE_ENV, None)
    if token is not None:
        env[operation_lock.INHERITED_LEASE_ENV] = token
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "palace")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return result.stdout.strip()


def test_wing_migration_child_inherits_only_the_live_fence_lease(tmp_path):
    """Only the wing-migration runner's current exclusive lease lets its child mine write."""
    install = OperationLock.default()
    with install.acquire_exclusive(operation_lock.INHERITABLE_LEASE_OPERATION) as fence:
        assert _child_write_attempt(tmp_path, None) == "refused fixture-wing-migration"
        assert _child_write_attempt(tmp_path, fence.token) == "wrote"
        for bogus in ("not-a-token", fence.token.upper(), "0" * 32, f"{fence.token} "):
            assert _child_write_attempt(tmp_path, bogus) == "refused fixture-wing-migration"
    # A released (stale) fence token no longer bypasses anything.
    with install.acquire_exclusive("update"):
        assert _child_write_attempt(tmp_path, fence.token) == "refused update"
    # Another exclusive owner's token is not inheritable.
    with install.acquire_exclusive("update") as update:
        assert _child_write_attempt(tmp_path, update.token) == "refused update"


def test_platform_without_advisory_locks_still_mines(tmp_path, monkeypatch):
    """Without fcntl the lease serializes threads only instead of refusing to write."""
    monkeypatch.setattr(operation_lock, "fcntl", None)
    palace = str(tmp_path / "palace")
    with palace_write_lease(palace, "mine", wait=0):
        assert not palace_lock_path(palace).exists()


def test_decorated_writer_skips_the_lease_for_dry_runs(tmp_path):
    palace = str(tmp_path / "palace")
    seen: list[bool] = []

    @holds_palace_write_lease("mine")
    def writer(project_dir, palace_path, dry_run=False):
        seen.append(OperationLock.for_palace(palace_path).held_in_process())

    writer("proj", palace)
    writer("proj", palace, dry_run=True)
    writer("proj", palace_path=palace)

    assert seen == [True, False, True]


# ── Concurrent mines (mcp-3, convos-8, hooks-4) ──────────────────────────────


def test_concurrent_convo_mines_never_overlap_in_one_process(tmp_path, monkeypatch):
    """Two mines of one palace used to pass the already-mined check together."""
    from mempalace_code import convo_miner

    convos = tmp_path / "convos"
    _write_convos(convos)
    palace = str(tmp_path / "palace")
    barrier = threading.Barrier(2, timeout=2)
    overlaps: list[bool] = []
    original = convo_miner._load_convo_state

    def racing_check(store, wing):
        try:
            barrier.wait()
            overlaps.append(True)
        except threading.BrokenBarrierError:
            overlaps.append(False)
        return original(store, wing)

    monkeypatch.setattr(convo_miner, "_load_convo_state", racing_check)
    errors: list[BaseException] = []

    def run():
        try:
            convo_miner.mine_convos(str(convos), palace, wing="c1", spellcheck=False)
        except BaseException as exc:  # noqa: BLE001  # reason: surface thread failures in the test
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    assert not errors
    assert not any(overlaps), "two mines of one palace were inside the write path together"
    rows = _rows(palace)
    ids = [row["id"] for row in rows]
    assert ids
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("mode", ["convos", "projects"])
def test_parallel_cli_mines_file_each_drawer_once(tmp_path, mode):
    """Three real `mine` processes started together leave no duplicate drawers."""
    home = Path(os.environ["HOME"])
    palace = str(tmp_path / "palace")
    runner = tmp_path / "runner.py"
    runner.write_text(_CLI_RUNNER, encoding="utf-8")
    start = tmp_path / "go"
    if mode == "convos":
        source = tmp_path / "convos"
        _write_convos(source, files=4, exchanges=6)
        extra = ["--mode", "convos", "--wing", "c1", "--no-spellcheck"]
    else:
        source = tmp_path / "proj"
        _write_project(source, files=6)
        extra = []
    env = _child_env(home)
    env["TEST_START_FILE"] = str(start)
    procs = [
        subprocess.Popen(
            [sys.executable, str(runner), "--palace", palace, "mine", str(source), *extra],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for _ in range(3)
    ]
    time.sleep(1.0)  # let all three import and park on the start file
    start.write_text("go")
    outputs = [proc.communicate(timeout=180)[0] for proc in procs]

    assert [proc.returncode for proc in procs] == [0, 0, 0], "\n".join(outputs)
    rows = _rows(palace)
    ids = [row["id"] for row in rows]
    assert ids
    assert len(ids) == len(set(ids)), f"{len(ids) - len(set(ids))} duplicate drawer ids"
    pairs = [(row["source_file"], row["chunk_index"]) for row in rows]
    assert len(pairs) == len(set(pairs))


def test_cli_mine_reports_busy_palace_with_exact_rerun_command(tmp_path):
    palace = str(tmp_path / "palace")
    convos = tmp_path / "convos"
    _write_convos(convos, files=1)
    runner = tmp_path / "runner.py"
    runner.write_text(_CLI_RUNNER, encoding="utf-8")
    env = _child_env(Path(os.environ["HOME"]))
    env["TEST_LEASE_WAIT"] = "0.5"
    holder = _ExternalHolder(tmp_path, palace)
    try:
        result = subprocess.run(
            [sys.executable, str(runner), "--palace", palace, "mine", str(convos)]
            + ["--mode", "convos", "--no-spellcheck"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        holder.release()

    assert result.returncode == 75, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert "Another MemPalace writer is still updating palace" in result.stderr
    assert "operation=test-holder" in result.stderr
    expected_next = f"Next: mempalace-code --palace {palace} mine {convos} --mode convos"
    assert expected_next in result.stderr


def test_mcp_mine_returns_busy_error_instead_of_blocking(
    tmp_path, monkeypatch, config, palace_path
):
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.tools.write import tool_mine

    project = tmp_path / "proj"
    _write_project(project)
    palace = palace_path
    monkeypatch.setattr(runtime, "_config", config)
    monkeypatch.setattr(runtime, "_store", None)
    monkeypatch.setattr(runtime, "MCP_MINE_LEASE_WAIT_SECONDS", 0.5)
    holder = _ExternalHolder(tmp_path, palace)
    try:
        started = time.monotonic()
        result = tool_mine(str(project))
        elapsed = time.monotonic() - started
    finally:
        holder.release()

    assert result["success"] is False
    assert "Another MemPalace writer is still updating palace" in result["error"]
    assert elapsed < 30


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("mempalace_add_drawer", {"wing": "w", "room": "r", "content": "lease probe 7"}),
        ("mempalace_diary_write", {"agent_name": "probe", "entry": "lease probe"}),
        ("mempalace_delete_drawer", {"drawer_id": "drawer_missing"}),
        ("mempalace_delete_wing", {"wing": "w"}),
    ],
)
def test_mcp_drawer_writes_return_busy_tool_error_while_palace_is_held(
    tmp_path, monkeypatch, config, palace_path, tool, arguments
):
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.dispatch import handle_request

    monkeypatch.setattr(runtime, "_config", config)
    monkeypatch.setattr(runtime, "_store", None)
    monkeypatch.setattr(runtime, "MCP_WRITE_LEASE_WAIT_SECONDS", 0.3)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    holder = _ExternalHolder(tmp_path, palace_path)
    try:
        started = time.monotonic()
        response = handle_request(request)
        elapsed = time.monotonic() - started
    finally:
        holder.release()

    result = response["result"]
    assert result["isError"] is True
    assert "Another MemPalace writer is still updating palace" in result["content"][0]["text"]
    assert elapsed < 10


# ── Handle freshness and reader-safe cleanup (agent-1, mcp-2, conc-1, perf-1) ─


def _external_mine(tmp_path: Path, palace: str, project: Path) -> str:
    runner = tmp_path / "runner.py"
    runner.write_text(_CLI_RUNNER, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(runner), "--palace", palace, "mine", str(project)],
        env=_child_env(Path(os.environ["HOME"])),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Optimizing storage... done" in result.stdout, result.stdout
    return result.stdout


def _add_note(palace: str, drawer_id: str, text: str, wing: str = "notes") -> None:
    open_store(palace, create=True).add(
        ids=[drawer_id],
        documents=[text],
        metadatas=[{"wing": wing, "room": "decisions", "source_file": "", "chunk_index": 0}],
    )


def test_long_lived_mcp_server_survives_and_sees_an_external_mine(
    tmp_path, monkeypatch, config, palace_path
):
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.tools.diary import tool_diary_read, tool_diary_write
    from mempalace_code.mcp.tools.read import tool_status
    from mempalace_code.mcp.tools.search import tool_check_duplicate

    palace = palace_path
    decision = "Decision D2: we keep the palace write lease per palace, not per install."
    _add_note(palace, "drawer_notes_decisions_d2", decision)
    monkeypatch.setattr(runtime, "_config", config)
    monkeypatch.setattr(runtime, "_store", None)

    assert tool_status()["total_drawers"] == 1
    assert tool_check_duplicate(decision)["is_duplicate"] is True
    assert tool_diary_write("uat-agent", "Watched the lease rollout closely.").get("success")
    assert len(tool_diary_read("uat-agent")["entries"]) == 1

    project = tmp_path / "proj"
    _write_project(project)
    _external_mine(tmp_path, palace, project)
    _write_project(project, marker="v2")
    _external_mine(tmp_path, palace, project)

    status = tool_status()
    assert "error" not in status, status
    wings = status["wings"]
    assert isinstance(wings, dict)
    assert wings.get("proj", 0) > 0, "server did not see the other process's mine"
    assert tool_check_duplicate(decision)["is_duplicate"] is True
    assert len(tool_diary_read("uat-agent")["entries"]) == 1


def test_post_optimize_cleanup_keeps_files_a_pinned_reader_still_uses(tmp_path):
    """A reader pinned on the previous version keeps working after another mine."""
    import lancedb

    palace = str(tmp_path / "palace")
    _add_note(palace, "drawer_pinned", "A note that existed before the external mine ran.")
    pinned = lancedb.connect(os.path.join(palace, "lance")).open_table("mempalace_drawers")
    assert pinned.to_arrow().num_rows == 1

    project = tmp_path / "proj"
    _write_project(project)
    _external_mine(tmp_path, palace, project)

    # Default consistency: this handle still reads the version it opened.
    assert pinned.to_arrow().num_rows == 1
    assert len(pinned.search().limit(10).to_list()) == 1


def test_watcher_style_store_stays_incremental_after_an_external_mine(tmp_path):
    """A long-lived store must not lose its hash inventory and re-embed everything."""
    from mempalace_code.mining.orchestrator import get_collection, mine

    palace = str(tmp_path / "palace")
    project = tmp_path / "proj"
    other = tmp_path / "other"
    _write_project(project, files=6)
    _write_project(other, files=2)
    watcher_store = get_collection(palace)
    first = mine(str(project), palace, collection=watcher_store, skip_optimize=True)
    assert first["files_processed"] == 6

    _external_mine(tmp_path, palace, other)
    changed = project / "src" / "mod0.py"
    changed.write_text(
        changed.read_text(encoding="utf-8") + "\n# changed after the external mine\n"
    )

    again = mine(str(project), palace, collection=watcher_store, skip_optimize=True)
    assert again["files_processed"] == 1, again


def _short_reader_grace(monkeypatch) -> None:
    from datetime import timedelta

    from mempalace_code import storage

    monkeypatch.setattr(storage, "READER_VERSION_GRACE", timedelta(seconds=1))
    monkeypatch.setattr(storage, "_PRUNE_CUTOFF_MARGIN", timedelta(milliseconds=100))


def _versions(palace: str) -> list[dict]:
    return open_store(palace, create=False)._table.list_versions()  # type: ignore[attr-defined]  # reason: LanceStore is the only runtime store and exposes its table


def _fragments(versions: list[dict]) -> int:
    return int(versions[-1]["metadata"]["total_fragments"])


def _record_optimize_and_backup(monkeypatch) -> list[str]:
    """Log every Lance Table.optimize() call and every palace backup, in order."""
    from lancedb.table import LanceTable

    from mempalace_code import backup

    events: list[str] = []
    optimize = LanceTable.optimize
    create_backup = backup.create_backup

    def recording_optimize(self, *args, **kwargs):
        events.append("optimize")
        return optimize(self, *args, **kwargs)

    def recording_backup(*args, **kwargs):
        events.append("backup")
        return create_backup(*args, **kwargs)

    monkeypatch.setattr(LanceTable, "optimize", recording_optimize)
    monkeypatch.setattr(backup, "create_backup", recording_backup)
    return events


def test_prune_before_writing_only_prunes_an_already_compact_table(tmp_path, monkeypatch):
    """The pre-write step prunes settled versions but never compacts new drawers."""
    from mempalace_code.mining.orchestrator import mine
    from mempalace_code.storage import prune_settled_versions

    _short_reader_grace(monkeypatch)
    palace = str(tmp_path / "palace")
    project = tmp_path / "proj"
    _write_project(project)
    mine(str(project), palace)
    time.sleep(1.5)
    latest = _versions(palace)[-1]["version"]

    prune_settled_versions(palace)
    assert [v["version"] for v in _versions(palace)] == [latest]

    _add_note(palace, "drawer_between_mines", "A decision filed between two mines by an agent.")
    time.sleep(1.5)
    before = _versions(palace)
    prune_settled_versions(palace)
    after = _versions(palace)
    assert [v["version"] for v in after] == [v["version"] for v in before]
    assert _fragments(after) == _fragments(before) == 2


def test_mine_never_compacts_before_its_pre_optimize_backup(tmp_path, monkeypatch):
    """Drawers written since the last optimize are compacted only after the backup."""
    from mempalace_code.mining.orchestrator import mine

    _short_reader_grace(monkeypatch)
    palace = str(tmp_path / "palace")
    project = tmp_path / "proj"
    _write_project(project)
    mine(str(project), palace)
    _add_note(palace, "drawer_manual_1", "Decision: the registry keeps one owner per shard.")
    _add_note(palace, "drawer_manual_2", "Decision: every schema change needs a reviewer.")
    time.sleep(1.5)
    changed = project / "src" / "mod1.py"
    changed.write_text(changed.read_text(encoding="utf-8") + "\n# second mine\n")

    events = _record_optimize_and_backup(monkeypatch)
    mine(str(project), palace)

    assert events[:1] == ["backup"], events


def test_mine_with_optimize_disabled_never_compacts_or_prunes(tmp_path, monkeypatch):
    """With optimize_after_mine off, a mine keeps every version and fragment."""
    from mempalace_code.mining.orchestrator import mine

    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    _short_reader_grace(monkeypatch)
    palace = str(tmp_path / "palace")
    project = tmp_path / "proj"
    _write_project(project)
    for round_index in range(1, 3):
        mine(str(project), palace)
        changed = project / "src" / f"mod{round_index}.py"
        changed.write_text(changed.read_text(encoding="utf-8") + f"\n# round {round_index}\n")
    time.sleep(1.5)
    before = _versions(palace)

    events = _record_optimize_and_backup(monkeypatch)
    mine(str(project), palace)
    after = _versions(palace)

    assert events == []
    assert {v["version"] for v in before} <= {v["version"] for v in after}
    assert _fragments(after) >= _fragments(before)


def test_backup_of_the_next_mine_does_not_carry_the_previous_generation(tmp_path, monkeypatch):
    from datetime import timedelta

    from mempalace_code import storage
    from mempalace_code.mining.orchestrator import mine

    monkeypatch.setattr(storage, "READER_VERSION_GRACE", timedelta(seconds=1))
    monkeypatch.setattr(storage, "_PRUNE_CUTOFF_MARGIN", timedelta(milliseconds=100))
    palace = str(tmp_path / "palace")
    project = tmp_path / "proj"
    _write_project(project, files=12)
    backups = tmp_path / "backups" / "palace"  # backup.managed_backups_dir(palace)
    sizes = []
    for round_index in range(3):
        if round_index:
            time.sleep(1.5)
            changed = project / "src" / f"mod{round_index}.py"
            changed.write_text(changed.read_text(encoding="utf-8") + f"\n# round {round_index}\n")
        mine(str(project), palace)
        archives = sorted(backups.glob("pre_optimize_*.tar.gz"), key=lambda p: p.stat().st_mtime)
        sizes.append(archives[-1].stat().st_size)

    assert sizes[2] < sizes[0] * 1.5, sizes


def test_mcp_server_reopens_a_palace_replaced_by_another_process(monkeypatch, config, palace_path):
    import shutil

    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.tools.read import tool_status

    palace = palace_path
    _add_note(palace, "drawer_before", "Before the palace was rebuilt by another process.")
    monkeypatch.setattr(runtime, "_config", config)
    monkeypatch.setattr(runtime, "_store", None)
    assert tool_status()["total_drawers"] == 1

    shutil.rmtree(os.path.join(palace, "lance"))
    for index in range(3):
        _add_note(palace, f"drawer_after_{index}", f"Rebuilt palace drawer number {index} here.")

    status = tool_status()
    assert "error" not in status, status
    assert status["total_drawers"] == 3


# ── Clean exit (native-1, mine-3) ────────────────────────────────────────────


def test_importing_mempalace_disables_onnxruntime_telemetry(tmp_path):
    """ORT's telemetry worker thread raced static destructors and aborted at exit."""
    pytest.importorskip("onnxruntime")
    env = _child_env(tmp_path)
    env.pop("ORT_DISABLE_TELEMETRY", None)
    probe = (
        "import os, mempalace_code, onnxruntime\nprint(os.environ.get('ORT_DISABLE_TELEMETRY'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=120
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"
    # On macOS ORT's telemetry creates a usage database under HOME at import time.
    assert not (tmp_path / "Library" / "Application Support" / "Microsoft").exists()


def test_explicit_onnxruntime_telemetry_setting_wins(tmp_path):
    env = _child_env(tmp_path)
    env["ORT_DISABLE_TELEMETRY"] = "0"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, mempalace_code; print(os.environ['ORT_DISABLE_TELEMETRY'])",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.stdout.strip() == "0"


def test_default_wait_budget_is_long_enough_for_a_large_mine():
    assert operation_lock.DEFAULT_PALACE_WRITE_WAIT_SECONDS >= 15 * 60


# ── Release gate awareness of palace lease files ─────────────────────────────


def _release_gate():
    import importlib.util

    path = REPO_ROOT / "scripts" / "release_readiness_gate.py"
    spec = importlib.util.spec_from_file_location("_uat_leases_release_gate", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_gate_ignores_released_palace_lease_files_only(tmp_path):
    gate = _release_gate()
    home = tmp_path / "home"
    palace = tmp_path / "palace"
    (home / "keep.txt").parent.mkdir(parents=True)
    (home / "keep.txt").write_text("stable", encoding="utf-8")
    before = gate._semantic_tree_snapshot(tmp_path)

    with palace_write_lease(palace, "mine", wait=0):
        assert not gate._palace_leases_released(Path(os.environ["HOME"]))
    lease_root = Path(os.environ["HOME"]) / ".mempalace" / "locks"
    (home / ".mempalace").mkdir()
    for entry in lease_root.iterdir():
        (home / ".mempalace" / "locks").mkdir(exist_ok=True)
        (home / ".mempalace" / "locks" / entry.name).write_bytes(entry.read_bytes())

    after = gate._semantic_tree_snapshot(tmp_path)
    assert after != before
    filtered = gate._without_palace_lease_rows(tmp_path, home, after)
    assert [row for row in filtered if row[0] != "home/.mempalace"] == list(before)
    assert gate._palace_leases_released(home)

    (home / "keep.txt").write_text("changed", encoding="utf-8")
    assert gate._without_palace_lease_rows(
        tmp_path, home, gate._semantic_tree_snapshot(tmp_path)
    ) != gate._without_palace_lease_rows(tmp_path, home, after)


# ── Backup and restore hold the palace write lease ──────────────────────────


def _backup_palace(tmp_path: Path) -> str:
    palace = str(tmp_path / "palace")
    open_store(palace, create=True).add(
        ["d1", "d2"], ["first note", "second note"], [{"wing": "w", "room": "r"}] * 2
    )
    return palace


def _run_cli(monkeypatch, capsys, *argv: str) -> tuple[int, str, str]:
    from mempalace_code.cli import main

    monkeypatch.setenv("MEMPALACE_VERSION_CHECK", "0")
    monkeypatch.setattr(sys, "argv", ["mempalace-code", *argv])
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_backup_nests_inside_a_writer_lease_of_the_same_thread(tmp_path):
    from mempalace_code.backup import create_backup

    palace = _backup_palace(tmp_path)
    store = open_store(palace, create=False)
    with palace_write_lease(palace, "mine", wait=0):
        meta, archive = create_backup(palace, out_path=str(tmp_path / "nested.tar.gz"))
        assert store.safe_optimize(palace, backup_first=True) is True
    assert meta["drawer_count"] == 2
    assert os.path.isfile(archive)


def test_cli_backup_and_restore_refuse_a_busy_palace_with_the_rerun_command(
    tmp_path, monkeypatch, capsys
):
    from mempalace_code.backup import create_backup

    palace = _backup_palace(tmp_path)
    _, archive = create_backup(palace, out_path=str(tmp_path / "before.tar.gz"))
    target = str(tmp_path / "restored")
    out = str(tmp_path / "busy.tar.gz")
    monkeypatch.setattr(operation_lock, "DEFAULT_PALACE_WRITE_WAIT_SECONDS", 0.3)
    holder = _ExternalHolder(tmp_path, palace)
    try:
        code, stdout, err = _run_cli(
            monkeypatch, capsys, "--palace", palace, "backup", "create", "--out", out
        )
        assert code == 75, stdout + err
        assert "Another MemPalace writer is still updating palace" in err
        assert "operation=test-holder" in err
        assert f"Next: mempalace-code --palace {palace} backup create --out {out}" in err
        assert not os.path.exists(out)
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        holder.release()

    second = tmp_path / "second-holder"
    second.mkdir()
    holder = _ExternalHolder(second, target)
    try:
        code, stdout, err = _run_cli(monkeypatch, capsys, "--palace", target, "restore", archive)
        assert code == 75, stdout + err
        assert "Another MemPalace writer is still updating palace" in err
        assert not os.path.exists(target)
    finally:
        holder.release()

    code, stdout, err = _run_cli(monkeypatch, capsys, "--palace", palace, "backup", "create")
    assert code == 0, err
    assert "Backed up 2 drawers" in stdout
