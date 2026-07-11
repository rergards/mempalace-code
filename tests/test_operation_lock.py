"""Deterministic coordination tests for watcher/update operation leases."""

from __future__ import annotations

import pytest

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
