"""Installed CLI adapter for the receipt-bound wing migration operator."""

from __future__ import annotations


def cmd_wing_migration(args) -> None:
    """Dispatch the nested operator CLI and preserve its exit status."""
    from ..wing_migration import main

    exit_code = main(args.wing_migration_args)
    if exit_code:
        raise SystemExit(exit_code)
