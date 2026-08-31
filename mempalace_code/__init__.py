"""MemPalace — Give your AI a memory. No API key required."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .version import __version__

if TYPE_CHECKING:
    from .cli import _one_shot_main as main

__all__ = ["main", "__version__"]


def __getattr__(name: str):
    if name == "main":
        from .cli import _one_shot_main  # noqa: PLC0415

        return _one_shot_main
    raise AttributeError(f"module 'mempalace_code' has no attribute {name!r}")
