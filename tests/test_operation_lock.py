"""Deterministic coordination tests for watcher/update operation leases."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from mempalace_code import operation_lock
from mempalace_code.operation_lock import OperationLock, OperationLockedError


def test_exclusive_lock_reports_shared_watcher_owner_and_releases(tmp_path):
    lock = OperationLock(tmp_path / "operation.lock")

    with lock.acquire_shared("watcher"):
        with pytest.raises(OperationLockedError) as exc_info:
            lock.acquire_exclusive("update")
        assert exc_info.value.owner["operation"] == "watcher"
        assert exc_info.value.owner["mode"] == "shared"

    with lock.acquire_exclusive("update") as lease:
        assert lease.mode == "exclusive"
        assert lock.owner_details()["operation"] == "update"  # type: ignore[index]  # reason: owner_details() returns dict when lock is held

    assert lock.owner_details() is None


def test_multiple_watchers_share_lease_but_block_update(tmp_path):
    lock = OperationLock(tmp_path / "operation.lock")

    with lock.acquire_shared("watcher-one"), lock.acquire_shared("watcher-two"):
        with pytest.raises(OperationLockedError):
            lock.acquire_exclusive("update")

    with lock.acquire_exclusive("update"):
        pass


def test_dead_owner_metadata_is_pruned_before_the_next_lease(tmp_path):
    lock = OperationLock(tmp_path / "operation.lock")
    lock.owners_path.write_text(
        '{"stale": {"mode": "exclusive", "operation": "update", "pid": 999999999}}',
        encoding="utf-8",
    )

    assert lock.exclusive_owner_details() is None
    assert lock.owner_details() is None

    with lock.acquire_exclusive("update") as lease:
        assert lease.mode == "exclusive"


def test_other_thread_cannot_bypass_install_maintenance(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(operation_lock.INHERITED_LEASE_ENV, raising=False)
    install = OperationLock.default()
    started = threading.Event()
    finished = threading.Event()
    outcomes = []

    def contender():
        started.set()
        try:
            for action in (
                lambda: install.acquire_shared("direct-control", wait=0),
                lambda: operation_lock.palace_write_lease(tmp_path / "palace", "mine", wait=0),
            ):
                try:
                    with action():
                        outcomes.append("entered")
                except OperationLockedError as exc:
                    outcomes.append(exc.owner.get("operation"))
        finally:
            finished.set()

    with install.acquire_exclusive("maintenance"):
        worker = threading.Thread(target=contender)
        worker.start()
        assert started.wait(5)
        assert finished.wait(5)
        worker.join(5)
        assert not worker.is_alive()
        assert outcomes == ["maintenance", "maintenance"]

    # Refusal must release the per-palace RLock and leave no acquired leases.
    with operation_lock.palace_write_lease(tmp_path / "palace", "retry", wait=0):
        pass
    assert install.owner_details() is None
    assert OperationLock.for_palace(tmp_path / "palace").owner_details() is None


def test_other_thread_writer_keeps_its_own_shared_install_lease(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(operation_lock.INHERITED_LEASE_ENV, raising=False)
    install = OperationLock.default()
    entered = threading.Event()
    release = threading.Event()
    errors = []

    def writer():
        try:
            with operation_lock.palace_write_lease(tmp_path / "palace", "mine", wait=0):
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("writer release was not signalled")
        except Exception as exc:
            errors.append(exc)
            entered.set()

    initial = install.acquire_shared("watcher")
    worker = threading.Thread(target=writer)
    try:
        worker.start()
        assert entered.wait(5)
        assert not errors
        initial.release()
        with pytest.raises(OperationLockedError) as exc_info:
            with install.acquire_exclusive("maintenance", wait=0):
                pass
        assert exc_info.value.owner["operation"] == "mine"
    finally:
        initial.release()
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert not errors
    with install.acquire_exclusive("maintenance", wait=0):
        pass


def test_release_from_another_thread_clears_acquiring_thread_hold(tmp_path):
    install = OperationLock(tmp_path / "operation.lock")
    lease = install.acquire_exclusive("maintenance")
    assert install.held_in_thread()
    errors = []

    def release():
        try:
            assert install.held_in_process()
            assert not install.held_in_thread()
            lease.release()
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=release)
    try:
        worker.start()
        worker.join(5)
        assert not worker.is_alive()
        assert not errors
        assert not install.held_in_process()
        assert not install.held_in_thread()
    finally:
        lease.release()
    with install.acquire_shared("retry", wait=0):
        assert install.held_in_thread()


def test_palace_body_error_releases_leases_for_another_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(operation_lock.INHERITED_LEASE_ENV, raising=False)
    palace = tmp_path / "palace"
    with pytest.raises(ValueError, match="writer failed"):
        with operation_lock.palace_write_lease(palace, "mine", wait=0):
            raise ValueError("writer failed")
    outcomes = []

    def retry():
        try:
            with operation_lock.palace_write_lease(palace, "retry", wait=0):
                outcomes.append("entered")
        except Exception as exc:
            outcomes.append(exc)

    worker = threading.Thread(target=retry)
    worker.start()
    worker.join(5)
    assert not worker.is_alive()
    assert outcomes == ["entered"]
    assert not OperationLock.default().held_in_process()
    assert not OperationLock.for_palace(palace).held_in_process()


def _cross_home_probe(palace, home, *, wait: float = 0.0):
    """Run the public writer lease in a fresh process with separate install state."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = """
import json, sys, time
from mempalace_code.operation_lock import OperationLockedError, palace_write_lease
notices = []
started = time.monotonic()
try:
    with palace_write_lease(sys.argv[1], "cross-home-probe", wait=float(sys.argv[2]),
                            on_wait=notices.append):
        entered = True
except OperationLockedError:
    entered = False
print(json.dumps({"entered": entered, "notices": len(notices),
                  "elapsed": time.monotonic() - started}))
"""
    env = dict(os.environ, HOME=str(home))
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-c", script, str(palace), str(wait)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("exists", [False, True])
@pytest.mark.parametrize("alias", [False, True])
def test_sibling_anchor_excludes_cross_home_writers_and_survives_release(
    tmp_path, monkeypatch, exists, alias
):
    monkeypatch.setenv("HOME", str(tmp_path / "home-one"))
    palace = tmp_path / "palace"
    if exists:
        palace.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(palace, target_is_directory=True)
    contender = link if alias else palace
    anchor = operation_lock.palace_writer_lock_path(palace)
    assert anchor == operation_lock.palace_writer_lock_path(link)
    assert anchor.parent == palace.parent
    with operation_lock.palace_write_lease(palace, "first", wait=0):
        with operation_lock.palace_write_lease(link, "nested", wait=0):
            assert _cross_home_probe(contender, tmp_path / "home-two")["entered"] is False
        assert palace.exists() is exists
        identity = anchor.stat().st_ino
        assert anchor.read_bytes() == b""
    assert anchor.stat().st_ino == identity
    assert _cross_home_probe(contender, tmp_path / "home-two")["entered"] is True
    assert anchor.stat().st_ino == identity
    assert palace.exists() is exists


def test_cross_home_wait_uses_one_deadline_and_one_notice(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home-one"))
    palace = tmp_path / "palace"
    with operation_lock.palace_write_lease(palace, "first", wait=0):
        outcome = _cross_home_probe(palace, tmp_path / "home-two", wait=0.25)
    assert outcome["entered"] is False
    assert outcome["notices"] == 1
    assert 0.20 <= outcome["elapsed"] < 2
    assert _cross_home_probe(palace, tmp_path / "home-two")["entered"] is True


@pytest.mark.parametrize("shape", ["symlink", "hardlink", "fifo", "directory"])
@pytest.mark.parametrize("prepare_parent", [False, True])
def test_unsafe_anchor_refuses_without_writing_target(tmp_path, monkeypatch, shape, prepare_parent):
    import os
    import time

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "palace"
    anchor = operation_lock.palace_writer_lock_path(palace)
    victim = tmp_path / "valuable"
    victim.write_bytes(b"preserve this content")
    if shape == "symlink":
        anchor.symlink_to(victim)
    elif shape == "hardlink":
        os.link(victim, anchor)
    elif shape == "fifo":
        os.mkfifo(anchor)
    else:
        anchor.mkdir()
    started = time.monotonic()
    with pytest.raises(operation_lock.PalaceBusyError, match="unsafe"):
        with operation_lock.palace_write_lease(
            palace, "refused", wait=0, prepare_parent=prepare_parent
        ):
            pytest.fail("unsafe anchor accepted")
    assert time.monotonic() - started < 1
    assert victim.read_bytes() == b"preserve this content"
    assert not palace.exists()
    assert not OperationLock.default().held_in_process()
    assert not OperationLock.for_palace(palace).held_in_process()


def test_read_only_regular_anchor_is_not_truncated_or_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home-one"))
    palace = tmp_path / "palace"
    anchor = operation_lock.palace_writer_lock_path(palace)
    anchor.write_bytes(b"existing anchor content")
    anchor.chmod(0o400)
    before = anchor.stat()
    with operation_lock.palace_write_lease(palace, "first", wait=0):
        assert _cross_home_probe(palace, tmp_path / "home-two")["entered"] is False
    after = anchor.stat()
    assert (after.st_dev, after.st_ino, after.st_mode, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_mtime_ns,
    )
    assert anchor.read_bytes() == b"existing anchor content"


def test_missing_anchor_parent_refuses_without_creating_palace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "missing-parent" / "palace"
    with pytest.raises(operation_lock.PalaceBusyError, match="unavailable"):
        with operation_lock.palace_write_lease(palace, "refused", wait=0):
            pytest.fail("missing anchor parent accepted")
    assert not palace.parent.exists()
    assert not OperationLock.default().held_in_process()
    assert not OperationLock.for_palace(palace).held_in_process()


def test_preparation_retains_lock_order_until_canonical_acquisition(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "missing" / "nested" / "palace"
    attempts = []
    ready = threading.Event()

    def ordinary_writer():
        ready.set()
        try:
            with operation_lock.palace_write_lease(palace, "other thread", wait=0.1):
                attempts.append("entered")
        except operation_lock.PalaceBusyError:
            attempts.append("busy")

    with operation_lock._palace_write_preparation(palace, "restore", wait=1) as anchor:
        assert not palace.parent.exists()
        assert OperationLock.default().held_in_thread()
        assert OperationLock.for_palace(palace).held_linked_in_thread(exclusive=True)
        writer = threading.Thread(target=ordinary_writer)
        writer.start()
        assert ready.wait(1)
        writer.join(2)
        assert not writer.is_alive()
        assert attempts == ["busy"]
        with operation_lock.palace_write_lease(
            palace, "restore", wait=0, prepare_parent=True, _expected_anchor=anchor
        ):
            assert palace.parent.is_dir()
            assert not palace.exists()
    assert not OperationLock.default().held_in_process()
    assert not OperationLock.for_palace(palace).held_in_process()


@pytest.mark.parametrize("context", ["writer", "preparation"])
def test_writer_body_lock_error_propagates_unchanged_and_releases_leases(
    tmp_path, monkeypatch, context
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "palace"
    original = OperationLockedError({"operation": "synthetic body sentinel"})
    lease = (
        operation_lock.palace_write_lease
        if context == "writer"
        else operation_lock._palace_write_preparation
    )

    with pytest.raises(OperationLockedError) as caught:
        with lease(palace, "body error", wait=0):
            raise original

    assert caught.value is original
    assert type(caught.value) is OperationLockedError
    assert not OperationLock.default().held_in_process()
    assert not OperationLock.for_palace(palace).held_in_process()
    with operation_lock.palace_write_lease(palace, "after body error", wait=0):
        pass


@pytest.mark.parametrize("drift", ["replace", "unlink", "hardlink"])
def test_preparation_refuses_stale_legacy_hold(tmp_path, monkeypatch, drift):
    import os

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "missing" / "palace"
    lock = OperationLock.for_palace(palace)
    with operation_lock._palace_write_preparation(palace, "restore", wait=0) as anchor:
        if drift == "replace":
            lock.path.rename(tmp_path / "parked")
            lock.path.write_bytes(b"replacement")
        elif drift == "unlink":
            lock.path.unlink()
        else:
            os.link(lock.path, tmp_path / "other-name")
        with pytest.raises(OperationLockedError, match="unsafe or replaced legacy"):
            with operation_lock.palace_write_lease(
                palace, "restore", wait=0, prepare_parent=True, _expected_anchor=anchor
            ):
                pytest.fail("stale legacy hold accepted")
        assert not palace.parent.exists()


def test_initializer_prepares_only_parent_under_install_and_palace_leases(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "missing-parent" / "nested" / "palace"
    original_mkdir = Path.mkdir

    def checked_mkdir(path, *args, **kwargs):
        if path == palace.parent:
            assert OperationLock.default().held_in_thread()
            assert OperationLock.for_palace(palace).held_in_thread()
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", checked_mkdir)
    with operation_lock.palace_write_lease(palace, "initializer", prepare_parent=True, wait=0):
        assert palace.parent.is_dir()
        assert not palace.exists()
        assert operation_lock.palace_writer_lock_path(palace).is_file()
    assert not OperationLock.default().held_in_process()
    assert not OperationLock.for_palace(palace).held_in_process()


def test_initializer_refuses_canonical_destination_drift(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "missing-parent" / "palace"
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    original_mkdir = Path.mkdir

    def redirected_mkdir(path, *args, **kwargs):
        result = original_mkdir(path, *args, **kwargs)
        if path == palace.parent:
            path.rmdir()
            path.symlink_to(redirected, target_is_directory=True)
        return result

    monkeypatch.setattr(Path, "mkdir", redirected_mkdir)
    with pytest.raises(operation_lock.PalaceBusyError, match="destination changed"):
        with operation_lock.palace_write_lease(palace, "initializer", prepare_parent=True, wait=0):
            pytest.fail("changed initializer destination accepted")
    assert list(redirected.iterdir()) == []
    assert not OperationLock.default().held_in_process()
    assert not OperationLock.for_palace(palace).held_in_process()


def test_initializer_does_not_prepare_parent_when_install_lease_refuses(
    tmp_path, exclusive_install_lease_elsewhere
):
    palace = tmp_path / "missing-parent" / "palace"
    with exclusive_install_lease_elsewhere():
        with pytest.raises(OperationLockedError):
            with operation_lock.palace_write_lease(
                palace, "initializer", prepare_parent=True, wait=0
            ):
                pytest.fail("exclusive installation lease bypassed")
    assert not palace.parent.exists()
    assert not OperationLock.default().held_in_process()
    assert not OperationLock.for_palace(palace).held_in_process()


@pytest.mark.parametrize("drift", ["replace", "hardlink", "unlink"])
def test_nested_writer_refuses_anchor_inode_drift(tmp_path, monkeypatch, drift):
    import os

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "palace"
    anchor = operation_lock.palace_writer_lock_path(palace)
    with operation_lock.palace_write_lease(palace, "outer", wait=0):
        if drift == "replace":
            anchor.rename(tmp_path / "parked-anchor")
            anchor.write_bytes(b"replacement")
        elif drift == "hardlink":
            os.link(anchor, tmp_path / "other-name")
        else:
            anchor.unlink()
        with pytest.raises(OperationLockedError, match="unsafe or replaced"):
            with operation_lock.palace_write_lease(palace, "nested", wait=0):
                pytest.fail("anchor drift accepted")
    assert not palace.exists()
    assert not OperationLock.default().held_in_process()
    assert not OperationLock.for_palace(palace).held_in_process()


def test_sibling_anchor_refuses_pathname_swap_during_open(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "palace"
    anchor = operation_lock.palace_writer_lock_path(palace)
    real_open = os.open
    swapped = []

    def swap(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if path == anchor and not swapped:
            swapped.append(fd)
            anchor.rename(tmp_path / "parked-anchor")
            anchor.write_bytes(b"replacement")
        return fd

    monkeypatch.setattr(operation_lock.os, "open", swap)
    with pytest.raises(operation_lock.PalaceBusyError, match="unsafe or replaced"):
        with operation_lock.palace_write_lease(palace, "refused", wait=0):
            pytest.fail("pathname swap accepted")
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(swapped[0])
    assert anchor.read_bytes() == b"replacement"
    assert not palace.exists()
    assert not OperationLock.default().held_in_process()


def test_writer_error_releases_sibling_fence_for_other_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home-one"))
    palace = tmp_path / "palace"
    with pytest.raises(ValueError, match="writer failed"):
        with operation_lock.palace_write_lease(palace, "outer", wait=0):
            raise ValueError("writer failed")
    assert _cross_home_probe(palace, tmp_path / "home-two")["entered"] is True
    assert not operation_lock._PALACE_WRITER_FENCES


def test_sibling_lock_keeps_different_palaces_parallel_and_threads_exclusive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    one = tmp_path / "one"
    two = tmp_path / "two"
    outcomes = []

    def contender():
        for palace in (one, two):
            try:
                with operation_lock.palace_write_lease(palace, "thread", wait=0):
                    outcomes.append("entered")
            except OperationLockedError:
                outcomes.append("refused")

    with operation_lock.palace_write_lease(one, "outer", wait=0):
        worker = threading.Thread(target=contender)
        worker.start()
        worker.join(5)
        assert not worker.is_alive()
    assert outcomes == ["refused", "entered"]


def test_anchor_symlink_swap_before_open_is_not_followed(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "palace"
    anchor = operation_lock.palace_writer_lock_path(palace)
    anchor.touch()
    victim = tmp_path / "valuable"
    victim.write_bytes(b"preserve")
    real_open = os.open

    def swap(path, *args, **kwargs):
        if path == anchor:
            anchor.unlink()
            anchor.symlink_to(victim)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(operation_lock.os, "open", swap)
    with pytest.raises(operation_lock.PalaceBusyError, match="unavailable"):
        with operation_lock.palace_write_lease(palace, "refused", wait=0):
            pytest.fail("symlink swap accepted")
    assert victim.read_bytes() == b"preserve"
    assert not palace.exists()
    assert not OperationLock.for_palace(palace).held_in_process()


def test_anchor_wait_callback_error_releases_all_acquired_leases(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    palace = tmp_path / "palace"
    anchor = operation_lock.palace_writer_lock_path(palace)
    anchor.touch()
    fd = os.open(anchor, os.O_RDONLY)

    def interrupted(owner):
        raise ValueError("wait callback failed")

    try:
        operation_lock.fcntl.flock(fd, operation_lock.fcntl.LOCK_EX)
        with pytest.raises(ValueError, match="wait callback failed"):
            with operation_lock.palace_write_lease(palace, "refused", wait=1, on_wait=interrupted):
                pytest.fail("contended anchor entered")
        assert not OperationLock.default().held_in_process()
        assert not OperationLock.for_palace(palace).held_in_process()
        assert not operation_lock._PALACE_WRITER_FENCES
    finally:
        os.close(fd)
    with operation_lock.palace_write_lease(palace, "retry", wait=0):
        pass
