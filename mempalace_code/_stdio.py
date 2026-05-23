"""
mempalace_code._stdio — Windows-only UTF-8 stdio reconfiguration helper.

On win32: reconfigures stdin/stdout/stderr to UTF-8 with explicit per-stream
error policies so CLI and MCP output is not corrupted by a legacy code page.
On all other platforms: no-op.
"""

from __future__ import annotations

import sys


def configure_windows_stdio(
    *,
    stdin=None,
    stdout=None,
    stderr=None,
) -> list[str]:
    """Reconfigure stdio streams for UTF-8 on Windows.

    Returns a list of stream names that could not be reconfigured (e.g. because
    the stream is a non-text pipe that does not support reconfigure()).  An empty
    list means all streams were reconfigured (or we are not on Windows).

    Parameters allow callers to inject fake streams for testing; real callers
    pass no arguments so sys.stdin/stdout/stderr are used.
    """
    failures: list[str] = []

    if sys.platform == "win32":  # pragma: win32
        _stdin = stdin if stdin is not None else sys.stdin
        _stdout = stdout if stdout is not None else sys.stdout
        _stderr = stderr if stderr is not None else sys.stderr

        for name, stream, encoding, errors in (
            ("stdin", _stdin, "utf-8", "surrogateescape"),
            ("stdout", _stdout, "utf-8", "replace"),
            ("stderr", _stderr, "utf-8", "replace"),
        ):
            try:
                stream.reconfigure(encoding=encoding, errors=errors)  # type: ignore[union-attr]  # reason: stream is sys.stdin/stdout/stderr or an injected TextIOWrapper; reconfigure() is available on all real text streams
            except Exception:
                failures.append(name)

    return failures
