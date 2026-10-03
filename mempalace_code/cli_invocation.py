"""cli_invocation.py — Printable commands that re-run this same mempalace-code install.

Recovery and next-step hints are copied into shells by people and agents. A bare
``mempalace-code`` resolves through PATH and can run a different installation than
the one that printed the hint, so every printed command starts from the running
installation instead:

1. the ``mempalace-code`` console script this process was started as;
2. for a sibling console script (``mempalace-code-mcp``, ``mempalace-code-alias``),
   the ``mempalace-code`` script next to it;
3. otherwise the running interpreter with the CLI module this process was started
   with (``-m mempalace_code.cli``), or ``-m mempalace_code``.
"""

from __future__ import annotations

import os
import re
import shlex
import sys

CLI_SCRIPT_NAME = "mempalace-code"
_CLI_MODULES = ("mempalace_code", "mempalace_code.__main__", "mempalace_code.cli")
# ``<dir>``-style placeholders are printed bare so they read as "fill this in".
_PLACEHOLDER = re.compile(r"<[a-z][a-z0-9-]*>")


def _is_executable_file(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def cli_prefix() -> list[str]:
    """Return the argv prefix that runs the mempalace-code CLI of this installation."""
    argv0 = sys.argv[0] if sys.argv else ""
    name = os.path.basename(argv0)
    if name.startswith(CLI_SCRIPT_NAME):
        script = os.path.join(
            os.path.dirname(os.path.abspath(os.path.expanduser(argv0))), CLI_SCRIPT_NAME
        )
        if _is_executable_file(script):
            return [script]
    if sys.executable:
        return [sys.executable, "-m", _started_cli_module()]
    return [CLI_SCRIPT_NAME]


def _started_cli_module() -> str:
    """Return the CLI module named by ``python -m`` for this process, else the package."""
    interpreter_args = list(getattr(sys, "orig_argv", []))[1:]
    # Only interpreter options precede ``-m``; stop at the first script/program argument.
    for index, token in enumerate(interpreter_args[:-1]):
        if token == "-m":
            module = interpreter_args[index + 1]
            return module if module in _CLI_MODULES else _CLI_MODULES[0]
        if not token.startswith("-"):
            break
    return _CLI_MODULES[0]


def cli_command(*args: str, palace: str | None = None) -> str:
    """Return a shell-quoted CLI command for this installation.

    ``palace`` is inserted as a root ``--palace`` option so the printed command
    targets the same palace as the command that printed it. Every other token is
    shell-quoted except ``<name>`` placeholders the reader must replace.
    """
    tokens = cli_prefix()
    if palace:
        tokens += ["--palace", palace]
    tokens += list(args)
    return " ".join(
        token if _PLACEHOLDER.fullmatch(token) else shlex.quote(token) for token in tokens
    )


def degraded_palace_next_step(palace: str | None, retry: str) -> str:
    """Return the next step after a palace read failed: health, then a rollback dry run."""
    return (
        f"run {cli_command('health', palace=palace)}; if degraded, run "
        f"{cli_command('repair', '--rollback', '--dry-run', palace=palace)} "
        f"before retrying {retry}."
    )


def no_palace_next_step(palace: str | None) -> str:
    """Return the one next step for a palace with no drawers, pinned to that palace.

    ``status``, ``search``, ``health``, ``backup``, and the MCP tools all print this, so
    following any of them mines into the palace the user selected.
    """
    mine = cli_command("mine", "<dir>", palace=palace)
    if palace and os.path.isdir(os.path.join(palace, "lance")):
        # A first mine that failed (for example without the embedding model) leaves
        # lance/ holding only LanceDB bookkeeping.
        return (
            f"an earlier mine filed no drawers here; run {cli_command('fetch-model')} if the "
            f"embedding model is missing, then {mine}"
        )
    return f"run {cli_command('init', '<dir>', palace=palace)}, then {mine}"
