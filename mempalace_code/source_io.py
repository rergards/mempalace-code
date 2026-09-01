"""Descriptor-validated regular-file reads for ingest sources."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from pathlib import Path
from typing import Literal, TypeAlias

_READ_CHUNK_SIZE = 1024 * 1024
_HAS_O_NONBLOCK = bool(getattr(os, "O_NONBLOCK", 0))
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
_EAGAIN_ERRNOS = {errno.EAGAIN, getattr(errno, "EWOULDBLOCK", errno.EAGAIN)}

SourceKind: TypeAlias = Literal[
    "regular file",
    "symlink",
    "directory",
    "fifo",
    "socket",
    "character device",
    "block device",
    "missing",
    "unreadable",
    "other",
]


class RegularSourceError(OSError):
    """Raised when an ingest source path does not open as a regular file."""

    def __init__(self, path: str | os.PathLike[str], reason: str = "not a regular file") -> None:
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"{self.path}: {reason}")


def source_path_kind(path: str | os.PathLike[str]) -> SourceKind:
    """Classify a source candidate without following symlinks."""
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"

    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISREG(mode):
        return "regular file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "character device"
    if stat.S_ISBLK(mode):
        return "block device"
    return "other"


def regular_source_diagnostic(path: str | os.PathLike[str], kind: SourceKind | None = None) -> str:
    """Return the bounded diagnostic text used when discovery skips a source."""
    return f"{Path(path)}: not a regular file ({kind or source_path_kind(path)})"


def is_regular_source_path(path: str | os.PathLike[str]) -> bool:
    """Discovery-only regular-source check; actual reads revalidate the descriptor."""
    return source_path_kind(path) == "regular file"


def stat_regular_source(path: str | os.PathLike[str]) -> os.stat_result:
    """Return fstat() metadata for a descriptor-validated regular source."""
    fd, st = _open_regular_descriptor(Path(path), nonblocking=_HAS_O_NONBLOCK)
    try:
        return st
    finally:
        os.close(fd)


def read_regular_bytes(path: str | os.PathLike[str], max_bytes: int | None = None) -> bytes:
    """Read bytes from a descriptor-validated regular source.

    On POSIX the descriptor is opened with O_NONBLOCK.  If os.read raises EAGAIN
    on the validated descriptor, that same descriptor is made blocking via fcntl,
    seeked back to offset zero, and retried once.  No second path open is performed.
    """
    path_obj = Path(path)
    fd, _ = _open_regular_descriptor(path_obj, nonblocking=_HAS_O_NONBLOCK)
    try:
        try:
            return _read_fd(fd, max_bytes=max_bytes)
        except OSError as exc:
            if _HAS_O_NONBLOCK and _is_eagain(exc):
                _make_fd_blocking(fd)
                os.lseek(fd, 0, os.SEEK_SET)
                return _read_fd(fd, max_bytes=max_bytes)
            raise
    finally:
        os.close(fd)


def read_regular_text(
    path: str | os.PathLike[str],
    encoding: str = "utf-8",
    errors: str = "replace",
    max_bytes: int | None = None,
) -> str:
    """Read text from a descriptor-validated regular source."""
    return read_regular_bytes(path, max_bytes=max_bytes).decode(encoding, errors=errors)


def hash_regular_bytes(
    path: str | os.PathLike[str], *, digest_size: int = 16, name: str = "blake2b"
) -> str:
    """Hash bytes from a descriptor-validated regular source."""
    if name != "blake2b":
        raise ValueError(f"unsupported hash: {name}")
    h = hashlib.blake2b(digest_size=digest_size)
    h.update(read_regular_bytes(path))
    return h.hexdigest()


def _open_regular_descriptor(path: Path, *, nonblocking: bool) -> tuple[int, os.stat_result]:
    path_st = _lstat_regular_source(path)
    flags = os.O_RDONLY | _O_BINARY
    if nonblocking and _HAS_O_NONBLOCK:
        flags |= os.O_NONBLOCK
    if _O_NOFOLLOW:
        flags |= _O_NOFOLLOW

    try:
        fd = os.open(path, flags)
    except OSError as exc:
        kind = source_path_kind(path)
        if kind != "regular file":
            raise RegularSourceError(path, f"not a regular file ({kind})") from exc
        raise

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or not _same_file(path_st, st):
            kind = source_path_kind(path)
            raise RegularSourceError(path, f"not a regular file ({kind})")
        return fd, st
    except Exception:
        os.close(fd)
        raise


def _lstat_regular_source(path: Path) -> os.stat_result:
    try:
        st = os.lstat(path)
    except OSError as exc:
        kind = source_path_kind(path)
        raise RegularSourceError(path, f"not a regular file ({kind})") from exc
    if not stat.S_ISREG(st.st_mode):
        kind = source_path_kind(path)
        raise RegularSourceError(path, f"not a regular file ({kind})")
    return st


def _same_file(before: os.stat_result, after: os.stat_result) -> bool:
    """Return whether path metadata and the opened descriptor identify one file."""
    return before.st_dev == after.st_dev and before.st_ino == after.st_ino


def _make_fd_blocking(fd: int) -> None:
    import fcntl

    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)


def _read_fd(fd: int, *, max_bytes: int | None) -> bytes:
    data = bytearray()
    remaining = max_bytes
    while True:
        chunk_size = _READ_CHUNK_SIZE if remaining is None else min(_READ_CHUNK_SIZE, remaining)
        if chunk_size <= 0:
            break
        chunk = os.read(fd, chunk_size)
        if not chunk:
            break
        data.extend(chunk)
        if remaining is not None:
            remaining -= len(chunk)
    return bytes(data)


def _is_eagain(exc: OSError) -> bool:
    return isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in _EAGAIN_ERRNOS
