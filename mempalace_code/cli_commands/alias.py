"""Alias command handlers: install-alias and mempalace-code-alias entry point."""

import argparse
import os
import shutil
import sys
from pathlib import Path

CANONICAL_CLI_COMMAND = "mempalace-code"
ALIAS_INSTALLER_COMMAND = "mempalace-code-alias"
LEGACY_CLI_ALIAS = "mempalace"


def _same_command_path(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except OSError:
        return left.resolve(strict=False) == right.resolve(strict=False)


def _resolve_invoked_canonical_cli() -> Path | None:
    argv0_text = sys.argv[0] if sys.argv else ""
    if not argv0_text:
        return None

    argv0 = Path(argv0_text).expanduser()
    if argv0.name not in (CANONICAL_CLI_COMMAND, ALIAS_INSTALLER_COMMAND):
        return None

    if not argv0.is_absolute() and not os.path.dirname(argv0_text):
        if argv0.name != ALIAS_INSTALLER_COMMAND:
            return None
        found_installer = shutil.which(ALIAS_INSTALLER_COMMAND)
        if not found_installer:
            return None
        argv0 = Path(found_installer).expanduser()

    invoked = argv0.parent.resolve() / argv0.name
    if not invoked.exists() or not os.access(invoked, os.X_OK):
        return None
    if invoked.name == CANONICAL_CLI_COMMAND:
        return invoked

    canonical_sibling = invoked.with_name(CANONICAL_CLI_COMMAND)
    if canonical_sibling.exists() and os.access(canonical_sibling, os.X_OK):
        return canonical_sibling
    raise RuntimeError(
        f"cannot find executable sibling `{CANONICAL_CLI_COMMAND}` next to "
        f"`{ALIAS_INSTALLER_COMMAND}`"
    )


def _resolve_canonical_cli() -> Path:
    invoked = _resolve_invoked_canonical_cli()
    if invoked is not None:
        return invoked

    found = shutil.which(CANONICAL_CLI_COMMAND)
    if found:
        return Path(found).expanduser()

    raise RuntimeError(
        f"cannot find `{CANONICAL_CLI_COMMAND}` on PATH; install mempalace-code first"
    )


def install_legacy_alias(target_dir: str | os.PathLike[str] | None = None) -> Path:
    """Create an optional ``mempalace`` alias when that command name is unused."""
    canonical_path = _resolve_canonical_cli()
    alias_dir = Path(target_dir).expanduser() if target_dir is not None else canonical_path.parent
    alias_path = alias_dir / LEGACY_CLI_ALIAS

    if target_dir is None:
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
    except (OSError, RuntimeError) as exc:
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
