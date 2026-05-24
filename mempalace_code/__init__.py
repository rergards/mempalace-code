"""MemPalace — Give your AI a memory. No API key required."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .version import __version__

if TYPE_CHECKING:
    from .cli import main

__all__ = ["main", "__version__"]


def __getattr__(name: str):
    if name == "main":
        from .cli import main as _main  # noqa: PLC0415

        return _main
    raise AttributeError(f"module 'mempalace_code' has no attribute {name!r}")
