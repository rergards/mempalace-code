#!/usr/bin/env python3
"""Delete all drawers in a wing. Usage: python scripts/nuke_wing.py <wing_name>"""

import sys
from pathlib import Path
from mempalace.storage import open_store

PALACE = str(Path.home() / ".mempalace" / "palace")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <wing_name>")
        sys.exit(1)
    wing = sys.argv[1]
    print(f"Nuking wing '{wing}' from {PALACE}")
    store = open_store(PALACE, create=False)
    count = store.delete_wing(wing)
    print(f"Done — {count} drawers removed from wing '{wing}'")
