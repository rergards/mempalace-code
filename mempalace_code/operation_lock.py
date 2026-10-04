"""Per-install and per-palace operation leases.

The per-install lease (``~/.mempalace/operation.lock``) keeps watchers, MCP
servers, and mines on the shared side while updates and maintenance take it
exclusively.  The per-palace write lease serializes every writer of one palace
(project and conversation mines, watcher cycles, optimize and cleanup) so two
processes never interleave their check-then-write steps on the same table.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, ParamSpec, TypedDict, TypeVar

try:  # pragma: no cover - Windows is outside the first supported scheduler slice.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]  # reason: Windows has no fcntl; None is the intended sentinel


LockMode = Literal["shared", "exclusive"]
OwnerCallback = Callable[[dict[str, object] | None], None]

# Environment variable through which the wing-migration runner hands its exclusive
# install lease to the one CLI mine it runs inside that fence (see
# :func:`_inherits_install_lease`).
INHERITED_LEASE_ENV = "MEMPALACE_INHERITED_OPERATION_LEASE"
INHERITABLE_LEASE_OPERATION = "fixture-wing-migration"
_LEASE_TOKEN_LENGTH = 32

# A second writer waits this long for the palace write lease before giving up.
DEFAULT_PALACE_WRITE_WAIT_SECONDS = 30 * 60.0
_LOCK_POLL_SECONDS = 0.2

_P = ParamSpec("_P")
_R = TypeVar("_R")

# Advisory locks held by this process, keyed by absolute path and acquiring thread.
# flock() conflicts between descriptors of one process. Only the acquiring thread
# may reuse its lease; another thread must obtain its own shared installation lease.
_PROCESS_HOLDS: dict[tuple[str, threading.Thread], int] = {}
_PROCESS_HOLDS_GUARD = threading.Lock()


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


class PalaceBusyError(OperationLockedError):
    """Raised when another writer keeps a palace's write lease past the wait budget."""

    def __init__(
        self, palace_path: str, owner: dict[str, object] | None = None, waited: float = 0.0
    ) -> None:
        self.palace_path = palace_path
        self.waited = waited
        self.owner = owner or {}
        detail = _owner_text(self.owner)
        waited_text = f" after waiting {waited:.0f}s" if waited >= 1 else ""
        OperationLockError.__init__(
            self,
            f"Another MemPalace writer is still updating palace {palace_path}"
            f"{f' ({detail})' if detail else ''}; gave up{waited_text}. "
            "Wait for it to finish (or stop it), then retry.",
        )


def _owner_text(owner: dict[str, object] | None) -> str:
    return ", ".join(
        f"{key}={value}" for key, value in (owner or {}).items() if key in {"operation", "pid"}
    )


@dataclass
class OperationLease:
    """A held shared or exclusive operation lease."""

    lock: OperationLock
    fd: int
    token: str
    mode: LockMode
    released: bool = False
    owner_thread: threading.Thread = field(default_factory=threading.current_thread)

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
            self.lock._note_process_hold(-1, self.owner_thread)

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

    @classmethod
    def for_palace(cls, palace_path: str | os.PathLike[str]) -> OperationLock:
        """Return the write lock that serializes writers of one palace directory."""
        return cls(palace_lock_path(palace_path))

    def acquire_shared(
        self,
        operation: str = "watcher",
        *,
        wait: float | None = 0.0,
        on_wait: OwnerCallback | None = None,
        palace: str | os.PathLike[str] | None = None,
    ) -> OperationLease:
        """Acquire a shared lease; refuse while an update owns the installation.

        *wait* is how many seconds to keep retrying a contended lock (``None``
        waits indefinitely); *on_wait* is called once with the current owner
        record when the first attempt is refused. *palace* is recorded in the
        owner record so a refused operation can name the palace the holder uses.
        """
        return self._acquire("shared", operation, wait=wait, on_wait=on_wait, palace=palace)

    def acquire_exclusive(
        self,
        operation: str = "update",
        *,
        wait: float | None = 0.0,
        on_wait: OwnerCallback | None = None,
        palace: str | os.PathLike[str] | None = None,
    ) -> OperationLease:
        """Acquire an exclusive lease; refuse while any watcher owns the installation.

        *wait*, *on_wait*, and *palace* behave as for :meth:`acquire_shared`.
        """
        return self._acquire("exclusive", operation, wait=wait, on_wait=on_wait, palace=palace)

    def held_in_process(self) -> bool:
        """Return True while this process holds any lease on this lock file."""
        path = self._hold_key()
        with _PROCESS_HOLDS_GUARD:
            return any(key[0] == path for key in _PROCESS_HOLDS)

    def held_in_thread(self) -> bool:
        """Return True while the current thread holds a lease on this lock file."""
        key = (self._hold_key(), threading.current_thread())
        with _PROCESS_HOLDS_GUARD:
            return _PROCESS_HOLDS.get(key, 0) > 0

    def _hold_key(self) -> str:
        return os.path.abspath(self.path)

    def _note_process_hold(self, delta: int, owner_thread: threading.Thread | None = None) -> None:
        key = (self._hold_key(), owner_thread or threading.current_thread())
        with _PROCESS_HOLDS_GUARD:
            count = _PROCESS_HOLDS.get(key, 0) + delta
            if count > 0:
                _PROCESS_HOLDS[key] = count
            else:
                _PROCESS_HOLDS.pop(key, None)

    def owner_details(self) -> dict[str, object] | None:
        """Return one current owner record for actionable contention diagnostics."""
        owners = self._active_owners()
        if not owners:
            return None
        return next(iter(owners.values()))

    def exclusive_owner_details(self) -> dict[str, object] | None:
        """Return a live exclusive owner without treating stale metadata as a lock."""
        return next(
            (owner for owner in self._active_owners().values() if owner.get("mode") == "exclusive"),
            None,
        )

    def _acquire(
        self,
        mode: LockMode,
        operation: str,
        *,
        wait: float | None = 0.0,
        on_wait: OwnerCallback | None = None,
        palace: str | os.PathLike[str] | None = None,
    ) -> OperationLease:
        if fcntl is None:  # pragma: no cover - platform guard
            raise OperationLockUnavailable("operation locking requires a POSIX filesystem")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        flock_mode = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
        deadline = None if wait is None else time.monotonic() + max(wait, 0.0)
        notified = False
        while True:
            try:
                fcntl.flock(fd, flock_mode | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    os.close(fd)
                    raise OperationLockedError(self.owner_details()) from exc
                if on_wait is not None and not notified:
                    notified = True
                    try:
                        on_wait(self.owner_details())
                    except Exception:
                        os.close(fd)
                        raise
                pause = (
                    _LOCK_POLL_SECONDS if remaining is None else min(_LOCK_POLL_SECONDS, remaining)
                )
                time.sleep(max(pause, 0.0))

        token = uuid.uuid4().hex
        owner: dict[str, object] = {
            "pid": os.getpid(),
            "operation": operation,
            "mode": mode,
            "acquired_at": int(time.time()),
        }
        if palace is not None:
            owner["palace"] = os.path.abspath(os.path.expanduser(os.fspath(palace)))
        try:
            self._add_owner(token, owner)
        except Exception:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            raise
        self._note_process_hold(1)
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

    def _active_owners(self) -> dict[str, dict[str, object]]:
        """Read owner diagnostics and prune records whose owning process has exited."""
        fd = self._metadata_fd()
        try:
            owners = self._read_owners()
            active = {
                token: owner for token, owner in owners.items() if self._owner_is_alive(owner)
            }
            if active != owners:
                self._write_owners(active)
            return active
        finally:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _owner_is_alive(owner: dict[str, object]) -> bool:
        pid = owner.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _write_owners(self, owners: dict[str, dict[str, object]]) -> None:
        temp_path = self.owners_path.with_name(f".{self.owners_path.name}.{os.getpid()}.tmp")
        temp_path.write_text(json.dumps(owners, sort_keys=True), encoding="utf-8")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, self.owners_path)

    def _add_owner(self, token: str, owner: dict[str, object]) -> None:
        fd = self._metadata_fd()
        try:
            owners = {
                existing_token: existing_owner
                for existing_token, existing_owner in self._read_owners().items()
                if self._owner_is_alive(existing_owner)
            }
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


class OwnerPalaceKwargs(TypedDict, total=False):
    """Optional ``palace`` keyword for :meth:`OperationLock.acquire_shared` and friends."""

    palace: str | os.PathLike[str]


def owner_palace_kwargs(lock: object, palace: str | os.PathLike[str] | None) -> OwnerPalaceKwargs:
    """Return ``{"palace": ...}`` for an :class:`OperationLock`, else no extra arguments.

    Injected lock objects that predate the ``palace`` owner field keep working.
    """
    if palace is None or not isinstance(lock, OperationLock):
        return OwnerPalaceKwargs()
    return OwnerPalaceKwargs(palace=palace)


def palace_lock_path(palace_path: str | os.PathLike[str]) -> Path:
    """Return the per-install write-lock file for one palace directory.

    The lock lives beside the install lease instead of inside the palace, so it
    survives restore/repair replacing the palace directory and never lands in a
    backup archive.  Every spelling of one palace (``~``, symlinks, relative
    paths) maps to the same lock.
    """
    resolved = os.path.realpath(os.path.expanduser(os.fspath(palace_path)))
    digest = hashlib.sha256(resolved.encode("utf-8", "surrogatepass")).hexdigest()[:24]
    return Path.home() / ".mempalace" / "locks" / f"palace-{digest}.lock"


def _inherits_install_lease(install: OperationLock) -> bool:
    """Return True when the parent's live wing-migration fence covers this process.

    Only a current owner record of *install* whose token equals
    :data:`INHERITED_LEASE_ENV`, held exclusively by the wing-migration runner,
    qualifies.  A missing, malformed, stale, or any other owner's token keeps the
    normal shared-lease behaviour.
    """
    token = os.environ.get(INHERITED_LEASE_ENV, "")
    if len(token) != _LEASE_TOKEN_LENGTH or any(ch not in "0123456789abcdef" for ch in token):
        return False
    owner = install._active_owners().get(token)
    return (
        owner is not None
        and owner.get("mode") == "exclusive"
        and owner.get("operation") == INHERITABLE_LEASE_OPERATION
    )


# In-process reentrancy for palace write leases: one RLock per lock file keeps
# threads of one process in line, and the depth counter lets a writer that
# already holds the lease (mine -> optimize -> cleanup) nest without asking the
# kernel for a second, self-conflicting flock.
_PALACE_THREAD_LOCKS: dict[str, threading.RLock] = {}
_PALACE_DEPTH: dict[str, int] = {}
_PALACE_REGISTRY_GUARD = threading.Lock()


def _print_wait_notice(palace_path: str) -> OwnerCallback:
    def notice(owner: dict[str, object] | None) -> None:
        detail = _owner_text(owner)
        print(
            f"  Waiting for another MemPalace writer to finish with {palace_path}"
            f"{f' ({detail})' if detail else ''}...",
            file=sys.stderr,
            flush=True,
        )

    return notice


@contextmanager
def palace_write_lease(
    palace_path: str | os.PathLike[str],
    operation: str,
    *,
    wait: float | None = None,
    on_wait: OwnerCallback | None = None,
) -> Iterator[None]:
    """Hold the exclusive write lease of one palace for the ``with`` block.

    A second writer of the same palace (another process or thread) waits up to
    *wait* seconds (default :data:`DEFAULT_PALACE_WRITE_WAIT_SECONDS`; ``None``
    selects that default) and then raises :class:`PalaceBusyError`.  *on_wait*
    is called once with the current owner record when waiting starts; by
    default a one-line notice goes to stderr.  The lease also holds the shared
    side of the per-install operation lease unless this thread already holds
    that lease, so updates and exclusive maintenance never run mid-write.  The
    one exception is a child the wing-migration runner starts inside its
    exclusive fence and names in :data:`INHERITED_LEASE_ENV`.
    Re-entering from the thread that already holds the lease is a no-op.
    """
    palace_text = os.fspath(palace_path)
    lock = OperationLock.for_palace(palace_text)
    key = lock._hold_key()
    budget = DEFAULT_PALACE_WRITE_WAIT_SECONDS if wait is None else max(wait, 0.0)
    deadline = time.monotonic() + budget
    with _PALACE_REGISTRY_GUARD:
        thread_lock = _PALACE_THREAD_LOCKS.setdefault(key, threading.RLock())
    if not thread_lock.acquire(timeout=budget):
        raise PalaceBusyError(palace_text, {"pid": os.getpid()}, budget)
    try:
        depth = _PALACE_DEPTH.get(key, 0)
        if depth:
            _PALACE_DEPTH[key] = depth + 1
            try:
                yield
            finally:
                _PALACE_DEPTH[key] = depth
            return

        leases: list[OperationLease] = []
        try:
            # Without POSIX advisory locks only this process's threads are serialized.
            if fcntl is not None:
                install = OperationLock.default()
                if not install.held_in_thread() and not _inherits_install_lease(install):
                    leases.append(install.acquire_shared(operation, palace=palace_text))
                try:
                    leases.append(
                        lock.acquire_exclusive(
                            operation,
                            wait=max(deadline - time.monotonic(), 0.0),
                            on_wait=on_wait or _print_wait_notice(palace_text),
                        )
                    )
                except OperationLockedError as exc:
                    raise PalaceBusyError(palace_text, exc.owner, budget) from exc
            _PALACE_DEPTH[key] = 1
            yield
        finally:
            _PALACE_DEPTH.pop(key, None)
            for lease in reversed(leases):
                lease.release()
    finally:
        thread_lock.release()


def holds_palace_write_lease(
    operation: str,
    *,
    on_acquire: Callable[[str], object] | None = None,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Decorate a writer whose ``palace_path`` argument names the palace it mutates.

    Calls with ``dry_run=True`` or without a palace run unlocked; every other
    call runs inside :func:`palace_write_lease`.  *on_acquire* runs with the
    palace path once the lease is held, before the writer starts.
    """

    def decorate(func: Callable[_P, _R]) -> Callable[_P, _R]:
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            arguments = signature.bind_partial(*args, **kwargs).arguments
            palace_path = arguments.get("palace_path")
            if not palace_path or arguments.get("dry_run"):
                return func(*args, **kwargs)
            with palace_write_lease(palace_path, operation):
                if on_acquire is not None:
                    on_acquire(os.fspath(palace_path))
                return func(*args, **kwargs)

        return wrapped

    return decorate
