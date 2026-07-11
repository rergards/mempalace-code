"""Per-install shared/exclusive coordination for watchers and updates."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

try:  # pragma: no cover - Windows is outside the first supported scheduler slice.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


LockMode = Literal["shared", "exclusive"]


class OperationLockError(RuntimeError):
    """Base class for operation lock failures."""


class OperationLockUnavailable(OperationLockError):
    """Raised when advisory file locking is unavailable on this platform."""


class OperationLockedError(OperationLockError):
    """Raised when a compatible operation lease cannot be acquired."""

    def __init__(self, owner: dict[str, object] | None = None) -> None:
        self.owner = owner or {}
        detail = ", ".join(
            f"{key}={value}"
            for key, value in self.owner.items()
            if key in {"mode", "pid", "operation"}
        )
        super().__init__(
            f"MemPalace operation is already running{f' ({detail})' if detail else ''}"
        )


@dataclass
class OperationLease:
    """A held shared or exclusive operation lease."""

    lock: OperationLock
    fd: int
    token: str
    mode: LockMode
    released: bool = False

    def release(self) -> None:
        """Release the advisory lock and remove this owner record exactly once."""
        if self.released:
            return
        try:
            self.lock._remove_owner(self.token)
        finally:
            if fcntl is not None:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.released = True

    def __enter__(self) -> OperationLease:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


class OperationLock:
    """Atomic lock plus inspectable owner records for one MemPalace installation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.owners_path = self.path.with_name(f"{self.path.name}.owners.json")
        self.metadata_lock_path = self.path.with_name(f"{self.path.name}.metadata.lock")

    @classmethod
    def default(cls) -> OperationLock:
        """Return the user-install lock without creating state during read-only commands."""
        return cls(Path.home() / ".mempalace" / "operation.lock")

    def acquire_shared(self, operation: str = "watcher") -> OperationLease:
        """Acquire a shared lease; refuse while an update owns the installation."""
        return self._acquire("shared", operation)

    def acquire_exclusive(self, operation: str = "update") -> OperationLease:
        """Acquire an exclusive lease; refuse while any watcher owns the installation."""
        return self._acquire("exclusive", operation)

    def owner_details(self) -> dict[str, object] | None:
        """Return one current owner record for actionable contention diagnostics."""
        owners = self._read_owners()
        if not owners:
            return None
        return next(iter(owners.values()))

    def _acquire(self, mode: LockMode, operation: str) -> OperationLease:
        if fcntl is None:  # pragma: no cover - platform guard
            raise OperationLockUnavailable("operation locking requires a POSIX filesystem")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        flock_mode = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
        try:
            fcntl.flock(fd, flock_mode | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise OperationLockedError(self.owner_details()) from exc

        token = uuid.uuid4().hex
        try:
            self._add_owner(
                token,
                {
                    "pid": os.getpid(),
                    "operation": operation,
                    "mode": mode,
                    "acquired_at": int(time.time()),
                },
            )
        except Exception:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            raise
        return OperationLease(lock=self, fd=fd, token=token, mode=mode)

    def _metadata_fd(self) -> int:
        if fcntl is None:  # pragma: no cover - platform guard
            raise OperationLockUnavailable("operation locking requires a POSIX filesystem")
        self.metadata_lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.metadata_lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _read_owners(self) -> dict[str, dict[str, object]]:
        try:
            raw = json.loads(self.owners_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}

    def _write_owners(self, owners: dict[str, dict[str, object]]) -> None:
        temp_path = self.owners_path.with_name(f".{self.owners_path.name}.{os.getpid()}.tmp")
        temp_path.write_text(json.dumps(owners, sort_keys=True), encoding="utf-8")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, self.owners_path)

    def _add_owner(self, token: str, owner: dict[str, object]) -> None:
        fd = self._metadata_fd()
        try:
            owners = self._read_owners()
            owners[token] = owner
            self._write_owners(owners)
        finally:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _remove_owner(self, token: str) -> None:
        try:
            fd = self._metadata_fd()
        except OSError:
            return
        try:
            owners = self._read_owners()
            if token not in owners:
                return
            owners.pop(token)
            self._write_owners(owners)
        finally:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
