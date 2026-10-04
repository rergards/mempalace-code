"""Shared helpers used by multiple CLI command modules."""

import contextlib
import json
import os
import shlex
import sys
from typing import NoReturn


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


def palace_command(palace_path: str, *parts: str) -> str:
    """Return a copy-pasteable ``mempalace-code`` command pinned to *palace_path*.

    Recovery hints always name the palace explicitly, so following one can never
    act on the default palace instead of the one the user selected. The command
    starts from this installation's launcher (see :mod:`mempalace_code.cli_invocation`),
    like every other recovery hint.
    """
    from ..cli_invocation import cli_command

    return cli_command(*parts, palace=os.path.abspath(palace_path))


def exit_writer_busy(exc: Exception) -> NoReturn:
    """Report a refused palace write lease with the exact command to rerun."""
    print(f"  Error: {exc}", file=sys.stderr)
    print(f"  Next: {shlex.join(['mempalace-code', *sys.argv[1:]])}", file=sys.stderr)
    sys.exit(os.EX_TEMPFAIL if hasattr(os, "EX_TEMPFAIL") else 75)


def palace_holds_state(palace_path: str) -> bool:
    """True when *palace_path* holds a drawer table or a knowledge graph.

    A project directory, an empty directory, or one whose first mine failed holds
    neither, and read commands report it as "No palace found".
    """
    from ..knowledge_graph import palace_kg_path
    from ..storage import _LANCE_TABLE

    table_dir = os.path.join(palace_path, "lance", f"{_LANCE_TABLE}.lance")
    return os.path.isdir(table_dir) or os.path.isfile(palace_kg_path(palace_path))


def no_palace_next_step(palace_path: str) -> str:
    """Next step for a path without a drawer table; see ``cli_invocation.no_palace_next_step``."""
    from ..cli_invocation import no_palace_next_step as shared_next_step

    return shared_next_step(os.path.abspath(palace_path))


def fail(
    message: str,
    *,
    next_step: str | None = None,
    json_output: bool = False,
    code: str = "error",
    exit_code: int = 1,
    **extra,
) -> NoReturn:
    """Report one failure and exit: a JSON object on stdout with --json, else stderr text."""
    sys.stdout.flush()  # keep stdout progress ahead of the error when both are piped
    if json_output:
        payload = {"ok": False, "error": message, "error_code": code, **extra}
        if next_step:
            payload["next"] = next_step
        print(json.dumps(payload, indent=2))
    else:
        print(f"  Error: {message}", file=sys.stderr)
        if next_step:
            print(f"  Next: {next_step}", file=sys.stderr)
    sys.exit(exit_code)


def lease_holder_text(owner: dict, target_palace: str) -> str:
    """Describe a lease holder, naming its palace when it works on a different one.

    The operation lease covers the whole installation, so a holder on an unrelated
    palace still blocks maintenance of *target_palace*; say so instead of implying a
    conflict on the target.
    """
    ids = " ".join(f"{key}={owner[key]}" for key in ("operation", "pid") if key in owner)
    text = f" ({ids})" if ids else ""
    holder_palace = owner.get("palace")
    target = os.path.abspath(os.path.expanduser(target_palace))
    if holder_palace and holder_palace != target:
        text += (
            f" on palace {holder_palace}; the operation lease covers the whole MemPalace "
            f"installation, not only {target}"
        )
    elif not holder_palace:
        text += "; the operation lease covers the whole MemPalace installation, every palace"
    return text


def acquire_operation_lease(
    mode: str,
    operation: str,
    palace_path: str,
    retry_parts: list[str],
    *,
    json_output: bool = False,
):
    """Take the installation's operation lease for a maintenance command, or exit 1.

    ``exclusive`` refuses while any other MemPalace process that takes the lease (an
    MCP server, watcher, update, or maintenance command) holds it; ``shared`` refuses
    only while an exclusive owner runs.
    Returns a context manager that releases the lease.
    """
    from ..operation_lock import (
        OperationLock,
        OperationLockedError,
        OperationLockUnavailable,
        owner_palace_kwargs,
    )

    lock = OperationLock.default()
    owner = owner_palace_kwargs(lock, palace_path)
    try:
        if mode == "exclusive":
            return lock.acquire_exclusive(operation, **owner)
        return lock.acquire_shared(operation, **owner)
    except OperationLockUnavailable:
        print(
            "  Warning: operation locking is unavailable on this platform; make sure no "
            "other MemPalace process is running.",
            file=sys.stderr,
        )
        return contextlib.nullcontext()
    except OperationLockedError as exc:
        fail(
            f"{operation} refused: another MemPalace process holds the operation lease"
            f"{lease_holder_text(exc.owner, palace_path)}. "
            "Stop MemPalace MCP servers (quit the AI client that runs mempalace-code-mcp), "
            "watchers, and miners first.",
            next_step=f"after they stop, run: {palace_command(palace_path, *retry_parts)}",
            json_output=json_output,
            code="operation_locked",
            owner=exc.owner,
        )
