#!/usr/bin/env python3
"""Delete all drawers in one wing of a palace.

Usage: python scripts/nuke_wing.py WING [--palace PATH] [--yes]

Without --yes it only reports how many drawers the wing holds. The palace defaults to
the configured one (MEMPALACE_PALACE_PATH, then ~/.mempalace/config.json palace_path).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mempalace_code.config import MempalaceConfig
from mempalace_code.storage import open_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete all drawers in one wing of a palace.")
    parser.add_argument("wing", help="wing whose drawers are deleted")
    parser.add_argument("--palace", help="palace directory (default: the configured palace)")
    parser.add_argument(
        "--yes", action="store_true", help="delete; without it, only report the drawer count"
    )
    args = parser.parse_args(argv)

    palace = str(Path(args.palace or MempalaceConfig().palace_path).expanduser())
    try:
        store = open_store(palace, create=False)
    except RuntimeError as exc:
        print(f"Cannot open palace {palace}: {exc}; nothing deleted.", file=sys.stderr)
        return 1
    count = store.count_by("wing").get(args.wing, 0)
    if count == 0:
        print(f"Wing '{args.wing}' has no drawers in {palace}; nothing deleted.", file=sys.stderr)
        return 1
    if not args.yes:
        print(
            f"Wing '{args.wing}' has {count} drawers in {palace}. Deletion is irreversible; "
            "rerun with --yes to delete them."
        )
        return 0
    deleted = store.delete_wing(args.wing)
    print(f"Deleted {deleted} drawers from wing '{args.wing}' in {palace}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
