"""Shared helpers used by multiple CLI command modules."""

import os


def resolve_palace(args, config=None):
    """Return the palace path from args.palace or config.palace_path."""
    if getattr(args, "palace", None):
        return os.path.expanduser(args.palace)
    if config is not None:
        return config.palace_path
    from ..config import MempalaceConfig

    return MempalaceConfig().palace_path


def parse_include_ignored(raw_list) -> list:
    """Flatten comma-separated include-ignored paths into a clean list."""
    result = []
    for raw in raw_list or []:
        result.extend(part.strip() for part in raw.split(",") if part.strip())
    return result


def fmt_bytes(n: int | float) -> str:
    """Human-readable byte count."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n = n / 1024
    return f"{n:.1f} TB"
