"""MemPalace — Give your AI a memory. No API key required."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .version import __version__

# ONNX Runtime (the FastEmbed backend) starts a usage-telemetry subsystem when it
# is imported unless this is set first.  Its worker thread outlives interpreter
# shutdown and races C++ static destructors, aborting a finished process with
# "libc++abi: ... recursive_mutex lock failed" (exit 134).  It also writes a
# usage database under the user's home.  An explicit user setting wins.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

if TYPE_CHECKING:
    from .cli import _one_shot_main as main

__all__ = ["main", "__version__"]


def __getattr__(name: str):
    if name == "main":
        from .cli import _one_shot_main  # noqa: PLC0415

        return _one_shot_main
    raise AttributeError(f"module 'mempalace_code' has no attribute {name!r}")
