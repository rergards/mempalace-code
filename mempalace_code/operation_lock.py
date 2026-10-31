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
import stat
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
_PROCESS_HOLDS: dict[tuple[str, threading.Thread], dict[int, LockMode]] = {}
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
            self.lock._note_process_hold(self.fd, None, self.owner_thread)

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
            return bool(_PROCESS_HOLDS.get(key))

    def _hold_key(self) -> str:
        return os.path.abspath(self.path)

    def _note_process_hold(
        self, fd: int, mode: LockMode | None, owner_thread: threading.Thread | None = None
    ) -> None:
        key = (self._hold_key(), owner_thread or threading.current_thread())
        with _PROCESS_HOLDS_GUARD:
            holds = _PROCESS_HOLDS.setdefault(key, {})
            if mode is not None:
                holds[fd] = mode
            else:
                holds.pop(fd, None)
            if not holds:
                _PROCESS_HOLDS.pop(key, None)

    def held_linked_in_thread(self, *, exclusive: bool = False) -> bool:
        """Whether a recorded live lease still names the same single-link regular inode.

        A replacement pathname does not inherit the flock of an unlinked open file.
        Keep descriptors with the existing process registry so nested operations can
        reject that state without acquiring a competing descriptor or trusting metadata.
        """
        key = (self._hold_key(), threading.current_thread())
        with _PROCESS_HOLDS_GUARD:
            try:
                named = os.lstat(self.path)
                if (
                    not stat.S_ISREG(named.st_mode)
                    or named.st_nlink != 1
                    or named.st_uid != os.getuid()
                ):
                    return False
                for fd, mode in _PROCESS_HOLDS.get(key, {}).items():
                    if exclusive and mode != "exclusive":
                        continue
                    held = os.fstat(fd)
                    if held.st_nlink == 1 and (held.st_dev, held.st_ino) == (
                        named.st_dev,
                        named.st_ino,
                    ):
                        return True
            except OSError:
                return False
        return False

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
        self._note_process_hold(fd, mode)
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


@contextmanager
def palace_snapshot_fence(palace_path: str | os.PathLike[str], *, maintenance: bool = False):
    """Fence version pruning with an existing directory descriptor, without state writes.

    Ordinary writes use their existing separate lease. Restore/repair retain their
    install/write gates. The palace directory stays stable during version pruning.
    Unsupported platforms keep reads available and refuse pruning.
    """
    if fcntl is None:
        raise OperationLockUnavailable("snapshot fencing requires POSIX advisory locking")
    path = os.path.realpath(os.path.expanduser(os.fspath(palace_path)))
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        mode = fcntl.LOCK_EX | fcntl.LOCK_NB if maintenance else fcntl.LOCK_SH
        try:
            fcntl.flock(fd, mode)
        except BlockingIOError as exc:
            raise OperationLockedError({"operation": "active snapshot read"}) from exc
        yield
    finally:
        os.close(fd)


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


def palace_writer_lock_path(palace_path: str | os.PathLike[str]) -> Path:
    """Return the permanent sibling anchor shared by writers across HOME directories.

    Keep the legacy HOME lease for older clients using that same HOME. Older
    clients using a different HOME do not participate in this additional fence.
    Never unlink the anchor: replacing it would split coordination across inodes.
    The sibling location stays outside palace archives and survives root creation.
    """
    palace = Path(os.path.realpath(os.path.expanduser(os.fspath(palace_path))))
    return palace.with_name(f".{palace.name}.mempalace-writer.lock")


@dataclass
class _PalaceWriterFence:
    path: Path
    fd: int

    def validate(self) -> None:
        """Refuse a replaced, linked, non-regular, or foreign-owned anchor."""
        try:
            named = os.lstat(self.path)
            held = os.fstat(self.fd)
            if (
                stat.S_ISREG(named.st_mode)
                and stat.S_ISREG(held.st_mode)
                and named.st_nlink == held.st_nlink == 1
                and named.st_uid == held.st_uid == os.getuid()
                and (named.st_dev, named.st_ino) == (held.st_dev, held.st_ino)
            ):
                return
        except OSError:
            pass
        raise OperationLockedError({"operation": "unsafe or replaced palace writer lock"})


def _acquire_palace_writer_fence(
    path: Path, deadline: float, on_wait: OwnerCallback
) -> _PalaceWriterFence:
    """Lock one safe inode without writing metadata or creating the palace root."""
    if fcntl is None or not hasattr(os, "O_NOFOLLOW"):
        raise OperationLockUnavailable("palace writer locking requires POSIX O_NOFOLLOW")
    fd = -1
    try:
        try:
            named = os.lstat(path)
        except FileNotFoundError:
            pass
        else:
            if (
                not stat.S_ISREG(named.st_mode)
                or named.st_nlink != 1
                or named.st_uid != os.getuid()
            ):
                raise OperationLockedError({"operation": "unsafe palace writer lock"})
        # O_NONBLOCK also prevents an inode-swap to a FIFO from blocking open().
        # Read-only access permits a safe 0400 anchor and never truncates content.
        fd = os.open(path, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        fence = _PalaceWriterFence(path, fd)
        fence.validate()
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                remaining = deadline - time.monotonic()
                owner: dict[str, object] = {"operation": "active palace writer"}
                if remaining <= 0:
                    raise OperationLockedError(owner) from exc
                on_wait(owner)
                time.sleep(min(_LOCK_POLL_SECONDS, remaining))
        fence.validate()
        fd = -1
        return fence
    except OSError as exc:
        raise OperationLockedError(
            {"operation": f"palace writer lock unavailable: {exc.strerror}"}
        ) from exc
    finally:
        if fd >= 0:
            os.close(fd)


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
_PALACE_THREAD_LOCKS: dict[tuple[int, str], threading.RLock] = {}
_PALACE_DEPTH: dict[tuple[int, threading.Thread, str], int] = {}
_PALACE_WRITER_FENCES: dict[tuple[int, threading.Thread, str], _PalaceWriterFence] = {}
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
def _palace_write_preparation(
    palace_path: str | os.PathLike[str],
    operation: str,
    *,
    wait: float | None = None,
    on_wait: OwnerCallback | None = None,
    expected_anchor: Path | None = None,
) -> Iterator[Path]:
    """Hold the existing thread, installation and legacy fences without creating parents.

    Restore stages and validates its archive inside these fences before requesting
    the canonical writer fence. Keep the ordinary writer's acquisition order and
    reuse only a live, linked exclusive legacy lease in this thread.
    """
    palace_text = os.fspath(palace_path)
    anchor = palace_writer_lock_path(palace_text)
    if expected_anchor is not None and anchor != expected_anchor:
        raise OperationLockedError({"operation": "palace writer destination changed"})
    key = str(anchor)
    budget = DEFAULT_PALACE_WRITE_WAIT_SECONDS if wait is None else max(wait, 0.0)
    deadline = time.monotonic() + budget
    with _PALACE_REGISTRY_GUARD:
        thread_lock = _PALACE_THREAD_LOCKS.setdefault((os.getpid(), key), threading.RLock())
    if not thread_lock.acquire(timeout=budget):
        raise PalaceBusyError(palace_text, {"pid": os.getpid()}, budget)
    leases: list[OperationLease] = []
    try:
        if fcntl is not None:
            install = OperationLock.default()
            if not install.held_in_thread() and not _inherits_install_lease(install):
                leases.append(install.acquire_shared(operation, palace=palace_text))
            lock = OperationLock.for_palace(palace_text)
            try:
                # A standalone legacy lease retains its ordinary contention path.
                # Reuse is limited to a full writer or pinned restore preparation.
                nested_writer = _PALACE_DEPTH.get((os.getpid(), threading.current_thread(), key), 0)
                if lock.held_in_thread() and (expected_anchor is not None or nested_writer):
                    if not lock.held_linked_in_thread(exclusive=True):
                        missing = (
                            ": lease file is missing" if not os.path.lexists(lock.path) else ""
                        )
                        raise OperationLockedError(
                            {"operation": f"unsafe or replaced legacy palace writer lock{missing}"}
                        )
                else:
                    leases.append(
                        lock.acquire_exclusive(
                            operation,
                            wait=max(deadline - time.monotonic(), 0.0),
                            on_wait=on_wait or _print_wait_notice(palace_text),
                        )
                    )
                if palace_writer_lock_path(palace_text) != anchor:
                    raise OperationLockedError({"operation": "palace writer destination changed"})
            except OperationLockedError as exc:
                raise PalaceBusyError(palace_text, exc.owner, budget) from exc
        yield anchor
    finally:
        for lease in reversed(leases):
            lease.release()
        thread_lock.release()


@contextmanager
def palace_write_lease(
    palace_path: str | os.PathLike[str],
    operation: str,
    *,
    wait: float | None = None,
    on_wait: OwnerCallback | None = None,
    prepare_parent: bool = False,
    _expected_anchor: Path | None = None,
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
    On POSIX, the permanent sibling anchor also serializes writers with different
    HOME directories. Readers retain their separate snapshot fence and can overlap
    ordinary writes. Missing anchor parents or unsafe anchors refuse the write.
    Without fcntl, only the existing in-process thread serialization is available.
    Re-entering from the owning thread revalidates the held anchor.
    Initializers may opt into *prepare_parent* to create only the anchor's parent
    under the installation and legacy palace leases, before acquiring the anchor.
    A changed canonical destination refuses initialization.
    """
    palace_text = os.fspath(palace_path)
    budget = DEFAULT_PALACE_WRITE_WAIT_SECONDS if wait is None else max(wait, 0.0)
    deadline = time.monotonic() + budget
    notified = False
    callback = on_wait or _print_wait_notice(palace_text)

    def notify(owner: dict[str, object] | None) -> None:
        nonlocal notified
        if not notified:
            notified = True
            callback(owner)

    with _palace_write_preparation(
        palace_text, operation, wait=budget, on_wait=notify, expected_anchor=_expected_anchor
    ) as anchor:
        owner_key = (os.getpid(), threading.current_thread(), str(anchor))
        depth = _PALACE_DEPTH.get(owner_key, 0)
        if depth:
            if fcntl is not None:
                _PALACE_WRITER_FENCES[owner_key].validate()
            _PALACE_DEPTH[owner_key] = depth + 1
            try:
                yield
            finally:
                _PALACE_DEPTH[owner_key] = depth
            return

        try:
            # Without POSIX advisory locks only this process's threads are serialized.
            if fcntl is not None:
                try:
                    if prepare_parent:
                        try:
                            anchor.parent.mkdir(parents=True, exist_ok=True)
                        except OSError as exc:
                            raise OperationLockedError(
                                {"operation": f"palace writer parent unavailable: {exc.strerror}"}
                            ) from exc
                        if palace_writer_lock_path(palace_text) != anchor:
                            raise OperationLockedError(
                                {"operation": "palace writer destination changed"}
                            )
                    _PALACE_WRITER_FENCES[owner_key] = _acquire_palace_writer_fence(
                        anchor, deadline, notify
                    )
                    if prepare_parent and palace_writer_lock_path(palace_text) != anchor:
                        raise OperationLockedError(
                            {"operation": "palace writer destination changed"}
                        )
                except OperationLockedError as exc:
                    raise PalaceBusyError(palace_text, exc.owner, budget) from exc
            _PALACE_DEPTH[owner_key] = 1
            yield
        finally:
            _PALACE_DEPTH.pop(owner_key, None)
            fence = _PALACE_WRITER_FENCES.pop(owner_key, None)
            if fence is not None:
                os.close(fence.fd)


def holds_palace_write_lease(
    operation: str,
    *,
    on_acquire: Callable[[str], object] | None = None,
    prepare_parent: bool = False,
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
            with palace_write_lease(palace_path, operation, prepare_parent=prepare_parent):
                if on_acquire is not None:
                    on_acquire(os.fspath(palace_path))
                return func(*args, **kwargs)

        return wrapped

    return decorate
