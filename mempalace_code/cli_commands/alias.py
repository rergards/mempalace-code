"""Alias command handlers: install-alias and mempalace-code-alias entry point."""

import argparse
import os
import shutil
import sys
from pathlib import Path

CANONICAL_CLI_COMMAND = "mempalace-code"
LEGACY_CLI_ALIAS = "mempalace"


def _same_command_path(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except OSError:
        return left.resolve(strict=False) == right.resolve(strict=False)


def _resolve_canonical_cli() -> Path:
    found = shutil.which(CANONICAL_CLI_COMMAND)
    if found:
        return Path(found).expanduser()

    argv0 = Path(sys.argv[0]).expanduser()
    if argv0.name == CANONICAL_CLI_COMMAND and argv0.exists():
        return argv0.resolve()

    raise RuntimeError(
        f"cannot find `{CANONICAL_CLI_COMMAND}` on PATH; install mempalace-code first"
    )


def install_legacy_alias(target_dir: str | os.PathLike[str] | None = None) -> Path:
    """Create an optional ``mempalace`` alias when that command name is unused."""
    canonical_path = _resolve_canonical_cli()
    alias_dir = Path(target_dir).expanduser() if target_dir else canonical_path.parent
    alias_path = alias_dir / LEGACY_CLI_ALIAS

    existing_on_path = shutil.which(LEGACY_CLI_ALIAS)
    if existing_on_path:
        existing_path = Path(existing_on_path).expanduser()
        if _same_command_path(existing_path, canonical_path):
            return existing_path
        raise RuntimeError(f"`{LEGACY_CLI_ALIAS}` is already in use at {existing_path}")

    if alias_path.exists() or alias_path.is_symlink():
        if _same_command_path(alias_path, canonical_path):
            return alias_path
        raise RuntimeError(f"{alias_path} already exists; not overwriting")

    alias_path.parent.mkdir(parents=True, exist_ok=True)
    if alias_path.parent == canonical_path.parent:
        alias_path.symlink_to(canonical_path.name)
    else:
        alias_path.symlink_to(canonical_path)
    return alias_path


def cmd_install_alias(args) -> None:
    try:
        alias_path = install_legacy_alias(target_dir=args.target_dir)
    except RuntimeError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  Alias ready: {alias_path} -> {CANONICAL_CLI_COMMAND}")


def main_alias() -> None:
    parser = argparse.ArgumentParser(
        description=f"Create an optional `{LEGACY_CLI_ALIAS}` alias for `{CANONICAL_CLI_COMMAND}`."
    )
    parser.add_argument(
        "--target-dir",
        default=None,
        help="Directory where the alias should be created (default: next to mempalace-code)",
    )
    args = parser.parse_args()
    cmd_install_alias(args)
