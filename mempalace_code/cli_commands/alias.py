"""Alias command handlers: install-alias and mempalace-code-alias entry point."""

import argparse
import os
import shlex
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


def resolve_invoked_canonical_cli() -> Path | None:
    """Return the invocation-preserving canonical CLI path when it can be proven."""
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


def recovery_cli_command() -> str:
    """Name the launcher to print in a recovery command.

    That is the invoked ``mempalace-code``, or the bare name when PATH already finds that
    same launcher, so a copied command never runs a different installation. The value is
    not shell-quoted.
    """
    try:
        invoked = resolve_invoked_canonical_cli()
    except RuntimeError:
        invoked = None
    if invoked is None:
        return CANONICAL_CLI_COMMAND
    found = shutil.which(CANONICAL_CLI_COMMAND)
    try:
        if found and invoked.samefile(found):
            return CANONICAL_CLI_COMMAND
    except OSError:
        pass
    return str(invoked)


def _resolve_canonical_cli() -> Path:
    invoked = resolve_invoked_canonical_cli()
    if invoked is not None:
        return invoked

    found = shutil.which(CANONICAL_CLI_COMMAND)
    if found:
        return Path(found).expanduser()

    raise RuntimeError(
        f"cannot find `{CANONICAL_CLI_COMMAND}` on PATH; install mempalace-code first"
    )


def install_legacy_alias(target_dir: str | os.PathLike[str] | None = None) -> Path:
    """Create an optional ``mempalace`` alias when that command name is unused.

    An explicit *target_dir* must already exist: a mistyped directory is refused rather
    than created.
    """
    canonical_path = _resolve_canonical_cli()
    alias_dir = Path(target_dir).expanduser() if target_dir is not None else canonical_path.parent
    if target_dir is not None and not alias_dir.is_dir():
        raise RuntimeError(
            f"target directory does not exist: {alias_dir}. Create it first with "
            f"`mkdir -p {shlex.quote(str(alias_dir))}`, or pass an existing directory on PATH."
        )
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

    if alias_path.parent == canonical_path.parent:
        alias_path.symlink_to(canonical_path.name)
    else:
        alias_path.symlink_to(canonical_path)
    return alias_path


def _alias_target(alias_path: Path) -> str:
    """Return what the alias actually points at, as the filesystem records it."""
    try:
        return os.readlink(alias_path)
    except OSError:
        return str(alias_path.resolve(strict=False))


def _on_path(directory: Path) -> bool:
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry and _same_command_path(Path(entry).expanduser(), directory):
            return True
    return False


def cmd_install_alias(args) -> None:
    try:
        alias_path = install_legacy_alias(target_dir=args.target_dir)
    except (OSError, RuntimeError) as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  Alias ready: {alias_path} -> {_alias_target(alias_path)}")
    if not _on_path(alias_path.parent):
        print(
            f"  Note: {alias_path.parent} is not on PATH; add it to PATH to run "
            f"`{LEGACY_CLI_ALIAS}` by name."
        )


def main_alias() -> None:
    """Entry point of the ``mempalace-code-alias`` console script.

    It is a standalone form of ``mempalace-code install-alias``. Run bare, it only prints
    this help, so discovering the command never creates files.
    """
    parser = argparse.ArgumentParser(
        prog=ALIAS_INSTALLER_COMMAND,
        description=(
            f"Create an optional `{LEGACY_CLI_ALIAS}` alias for `{CANONICAL_CLI_COMMAND}`; "
            f"the same as `{CANONICAL_CLI_COMMAND} install-alias`. Pass --yes to create it "
            "next to mempalace-code, or --target-dir to choose an existing directory."
        ),
    )
    parser.add_argument(
        "--target-dir",
        default=None,
        help="Existing directory where the alias should be created (default: next to "
        "mempalace-code)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Create the alias next to mempalace-code",
    )
    args = parser.parse_args()
    if args.target_dir is None and not args.yes:
        parser.print_help()
        raise SystemExit(2)
    cmd_install_alias(args)
