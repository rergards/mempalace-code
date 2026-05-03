"""disk_budget.py — Disk-budget helpers for watcher and backup guards.

Provides byte parsing, palace/backups footprint measurement, free-space
checks, backup projection, DiskBudgetStatus, and DiskBudgetError.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Conservative default: require at least 1 GiB free before write-producing operations.
DEFAULT_DISK_MIN_FREE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB


class DiskBudgetError(Exception):
    """Raised when a write-producing operation would violate the disk-budget floor."""


@dataclass
class DiskBudgetStatus:
    """Result of a disk-budget check."""

    free_bytes: int
    min_free_bytes: int
    palace_bytes: int
    backups_bytes: int
    allowed: bool

    @property
    def total_footprint_bytes(self) -> int:
        return self.palace_bytes + self.backups_bytes


def parse_bytes(value) -> int:
    """Parse an integer byte count from int, str, or str with optional suffix.

    Accepts: integers, digit strings, and human suffixes (KB, MB, GB, TB,
    KiB, MiB, GiB, TiB — case-insensitive). Negative values raise ValueError.
    Booleans are rejected even though ``bool`` is a subclass of ``int`` in Python:
    silently coercing ``true``/``false`` from a config file to 1/0 would disable
    the disk-budget guard.
    """
    # bool is a subclass of int — reject before the int check or `True`/`False`
    # in config silently become 1 / 0 byte thresholds.
    if isinstance(value, bool):
        raise ValueError(f"Cannot parse bytes from bool: {value!r}")

    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"Byte count must be non-negative, got {value}")
        return value

    if not isinstance(value, str):
        raise ValueError(f"Cannot parse bytes from {type(value).__name__}: {value!r}")

    s = value.strip()
    if not s:
        raise ValueError("Empty byte string")

    # Ordered longest-first so "GiB" matches before "B"
    suffixes = [
        ("tib", 1024**4),
        ("gib", 1024**3),
        ("mib", 1024**2),
        ("kib", 1024),
        ("tb", 1000**4),
        ("gb", 1000**3),
        ("mb", 1000**2),
        ("kb", 1000),
        ("b", 1),
    ]
    lower = s.lower()
    for suffix, multiplier in suffixes:
        if lower.endswith(suffix):
            numeric = lower[: -len(suffix)].strip()
            try:
                n = float(numeric)
            except ValueError:
                raise ValueError(f"Cannot parse numeric part of {s!r}")
            result = int(n * multiplier)
            if result < 0:
                raise ValueError(f"Byte count must be non-negative, got {result}")
            return result

    # Plain integer string
    try:
        result = int(s)
    except ValueError:
        raise ValueError(f"Cannot parse bytes from {s!r}")
    if result < 0:
        raise ValueError(f"Byte count must be non-negative, got {result}")
    return result


def _dir_size(path: str) -> int:
    """Return total byte count of all files under path. Returns 0 if missing or on permission error."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                try:
                    total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
            elif entry.is_dir(follow_symlinks=False):
                total += _dir_size(entry.path)
    except OSError:
        pass
    return total


def palace_footprint(palace_path: str) -> tuple:
    """Return (palace_bytes, backups_bytes) for the palace and its sibling backups/ dir.

    Missing directories count as 0. Permission errors return 0 for that component.
    """
    palace_bytes = _dir_size(palace_path)
    backups_dir = os.path.join(os.path.dirname(os.path.abspath(palace_path)), "backups")
    backups_bytes = _dir_size(backups_dir)
    return palace_bytes, backups_bytes


def free_bytes(path: str) -> int:
    """Return free bytes on the filesystem containing path."""
    # Walk up to find an existing ancestor path for shutil.disk_usage
    p = Path(path)
    while not p.exists():
        if p.parent == p:
            break
        p = p.parent
    return shutil.disk_usage(str(p)).free


def check_watch_budget(
    palace_path: str,
    min_free_bytes_threshold: int,
) -> "DiskBudgetStatus":
    """Check whether the watcher is allowed to run under current disk conditions.

    Returns DiskBudgetStatus. allowed=True when free_bytes >= min_free_bytes_threshold.
    """
    palace_b, backups_b = palace_footprint(palace_path)
    free = free_bytes(palace_path)
    allowed = free >= min_free_bytes_threshold
    return DiskBudgetStatus(
        free_bytes=free,
        min_free_bytes=min_free_bytes_threshold,
        palace_bytes=palace_b,
        backups_bytes=backups_b,
        allowed=allowed,
    )


def check_backup_budget(
    palace_path: str,
    out_path: str,
    min_free_bytes_threshold: int,
    kg_path: Optional[str] = None,
) -> "DiskBudgetStatus":
    """Check whether creating a backup archive is safe given disk budget.

    Uses a conservative uncompressed estimate: palace directory size + KG size.
    The free-space check is on the filesystem containing out_path (destination).

    Returns DiskBudgetStatus. allowed=True when projected remaining free space
    after the archive would still be >= min_free_bytes_threshold.
    """
    palace_b, backups_b = palace_footprint(palace_path)

    kg_size = 0
    if kg_path and os.path.isfile(kg_path):
        try:
            kg_size = os.stat(kg_path).st_size
        except OSError:
            pass

    # Conservative: use uncompressed input size as archive size estimate
    projected_archive_size = palace_b + kg_size

    free = free_bytes(out_path)
    projected_free = free - projected_archive_size
    allowed = projected_free >= min_free_bytes_threshold

    return DiskBudgetStatus(
        free_bytes=free,
        min_free_bytes=min_free_bytes_threshold,
        palace_bytes=palace_b,
        backups_bytes=backups_b,
        allowed=allowed,
    )


def format_bytes(n: int) -> str:
    """Format bytes as a human-readable string."""
    for unit, threshold in [("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)]:
        if n >= threshold:
            return f"{n / threshold:.1f} {unit}"
    return f"{n} B"
