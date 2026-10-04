"""Deterministic coordination tests for watcher/update operation leases."""

from __future__ import annotations

import threading

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
