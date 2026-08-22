#!/usr/bin/env python3
"""
room_detector_local.py — Local setup, no API required.

Two ways to define rooms without calling any AI:
  1. Auto-detect from folder structure (zero config)
  2. Define manually in mempalace.yaml

No internet. No API key. Your files stay on your machine.
"""

import os
import stat
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import yaml

from .source_io import RegularSourceError, is_regular_source_path

# Common room patterns — detected from folder names and filenames
# Format: {folder_keyword: room_name}
FOLDER_ROOM_MAP = {
    "frontend": "frontend",
    "front-end": "frontend",
    "front_end": "frontend",
    "client": "frontend",
    "ui": "frontend",
    "views": "frontend",
    "components": "frontend",
    "pages": "frontend",
    "backend": "backend",
    "back-end": "backend",
    "back_end": "backend",
    "server": "backend",
    "api": "backend",
    "routes": "backend",
    "services": "backend",
    "controllers": "backend",
    "models": "backend",
    "database": "backend",
    "db": "backend",
    "docs": "documentation",
    "doc": "documentation",
    "documentation": "documentation",
    "wiki": "documentation",
    "readme": "documentation",
    "notes": "documentation",
    "design": "design",
    "designs": "design",
    "mockups": "design",
    "wireframes": "design",
    "assets": "design",
    "storyboard": "design",
    "costs": "costs",
    "cost": "costs",
    "budget": "costs",
    "finance": "costs",
    "financial": "costs",
    "pricing": "costs",
    "invoices": "costs",
    "accounting": "costs",
    "meetings": "meetings",
    "meeting": "meetings",
    "calls": "meetings",
    "meeting_notes": "meetings",
    "standup": "meetings",
    "minutes": "meetings",
    "team": "team",
    "staff": "team",
    "hr": "team",
    "hiring": "team",
    "employees": "team",
    "people": "team",
    "research": "research",
    "references": "research",
    "reading": "research",
    "papers": "research",
    "planning": "planning",
    "roadmap": "planning",
    "strategy": "planning",
    "specs": "planning",
    "requirements": "planning",
    "tests": "testing",
    "test": "testing",
    "testing": "testing",
    "qa": "testing",
    "scripts": "scripts",
    "tools": "scripts",
    "utils": "scripts",
    "config": "configuration",
    "configs": "configuration",
    "settings": "configuration",
    "infrastructure": "configuration",
    "infra": "configuration",
    "deploy": "configuration",
}


def _rooms_from_csproj(proj_files: list) -> list:
    """Build a room list from a set of .csproj/.fsproj/.vbproj files.

    De-duplicates by normalized name, returns room dicts with a "general" fallback.
    """
    from .mining.projects import _normalize_room_name

    seen: dict = {}
    for pf in proj_files:
        name = _normalize_room_name(pf.stem)
        if name not in seen:
            seen[name] = pf.stem

    rooms = []
    for room_name, original in seen.items():
        rooms.append(
            {
                "name": room_name,
                "description": f"Files from {original}/",
                "keywords": [room_name],
            }
        )

    if not any(r["name"] == "general" for r in rooms):
        rooms.append(
            {
                "name": "general",
                "description": "Files that don't fit other rooms",
                "keywords": [],
            }
        )
    return rooms


def detect_rooms_from_folders(project_dir: str) -> list:
    """
    Walk the project folder structure.
    Find top-level subdirectories that match known room patterns.
    Returns list of room dicts.
    """
    project_path = Path(project_dir).expanduser().resolve()
    found_rooms = {}

    SKIP_DIRS = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".next",
        "coverage",
    }

    # Check top-level directories first (most reliable signal)
    for item in project_path.iterdir():
        if item.is_dir() and item.name not in SKIP_DIRS:
            name_lower = item.name.lower().replace("-", "_")
            if name_lower in FOLDER_ROOM_MAP:
                room_name = FOLDER_ROOM_MAP[name_lower]
                if room_name not in found_rooms:
                    found_rooms[room_name] = item.name
            # Also check if folder name IS a good room name directly
            elif len(item.name) > 2 and item.name[0].isalpha():
                clean = item.name.lower().replace("-", "_").replace(" ", "_")
                if clean not in found_rooms:
                    found_rooms[clean] = item.name

    # Walk one level deeper for nested patterns
    for item in project_path.iterdir():
        if item.is_dir() and item.name not in SKIP_DIRS:
            for subitem in item.iterdir():
                if subitem.is_dir() and subitem.name not in SKIP_DIRS:
                    name_lower = subitem.name.lower().replace("-", "_")
                    if name_lower in FOLDER_ROOM_MAP:
                        room_name = FOLDER_ROOM_MAP[name_lower]
                        if room_name not in found_rooms:
                            found_rooms[room_name] = subitem.name

    # Build room list
    rooms = []
    for room_name, original in found_rooms.items():
        rooms.append(
            {
                "name": room_name,
                "description": f"Files from {original}/",
                "keywords": [room_name, original.lower()],
            }
        )

    # Always add "general" as fallback
    if not any(r["name"] == "general" for r in rooms):
        rooms.append(
            {
                "name": "general",
                "description": "Files that don't fit other rooms",
                "keywords": [],
            }
        )

    return rooms


def detect_rooms_from_files(project_dir: str) -> list:
    """
    Fallback: if folder structure gives no signal,
    detect rooms from recurring filename patterns.
    """
    project_path = Path(project_dir).expanduser().resolve()
    keyword_counts = defaultdict(int)

    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

    for root, dirs, filenames in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in filenames:
            if not is_regular_source_path(Path(root) / filename):
                continue
            name_lower = filename.lower().replace("-", "_").replace(" ", "_")
            for keyword, room in FOLDER_ROOM_MAP.items():
                if keyword in name_lower:
                    keyword_counts[room] += 1

    # Return rooms that appear more than twice
    rooms = []
    for room, count in sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True):
        if count >= 2:
            rooms.append(
                {
                    "name": room,
                    "description": f"Files related to {room}",
                    "keywords": [room],
                }
            )
        if len(rooms) >= 6:
            break

    if not rooms:
        rooms = [{"name": "general", "description": "All project files", "keywords": []}]

    return rooms


def print_proposed_structure(project_name: str, rooms: list, total_files: int, source: str):
    print(f"\n{'=' * 55}")
    print("  MemPalace Init — Local setup")
    print(f"{'=' * 55}")
    print(f"\n  WING: {project_name}")
    print(f"  ({total_files} files found, rooms detected from {source})\n")
    for room in rooms:
        print(f"    ROOM: {room['name']}")
        print(f"          {room['description']}")
    print(f"\n{'─' * 55}")


def get_user_approval(rooms: list) -> list:
    """Same approval flow as AI version."""
    print("  Review the proposed rooms above.")
    print("  Options:")
    print("    [enter]  Accept all rooms")
    print("    [edit]   Remove or rename rooms")
    print("    [add]    Add a room manually")
    print()

    while True:
        choice = input("  Your choice [enter/edit/add]: ").strip().lower()
        if choice in ("", "y", "yes", "edit", "add"):
            break
        print("  Not recognized. Press enter to accept, or type edit/add.")

    if choice in ("", "y", "yes"):
        return rooms

    if choice == "edit":
        print("\n  Current rooms:")
        for i, room in enumerate(rooms):
            print(f"    {i + 1}. {room['name']} — {room['description']}")
        remove = input("\n  Room numbers to REMOVE (comma-separated, or enter to skip): ").strip()
        if remove:
            to_remove = {int(x.strip()) - 1 for x in remove.split(",") if x.strip().isdigit()}
            rooms = [r for i, r in enumerate(rooms) if i not in to_remove]

    if choice == "add" or input("\n  Add any missing rooms? [y/N]: ").strip().lower() == "y":
        while True:
            new_name = (
                input("  New room name (or enter to stop): ").strip().lower().replace(" ", "_")
            )
            if not new_name:
                break
            new_desc = input(f"  Description for '{new_name}': ").strip()
            rooms.append({"name": new_name, "description": new_desc, "keywords": [new_name]})
            print(f"  Added: {new_name}")

    return rooms


def validate_regular_destination(destination: Path) -> int | None:
    """Return an existing regular file's mode, or None when it is absent."""
    try:
        destination_stat = os.lstat(destination)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RegularSourceError(destination, exc.strerror or str(exc)) from exc
    if stat.S_ISREG(destination_stat.st_mode):
        return stat.S_IMODE(destination_stat.st_mode)
    raise RegularSourceError(destination)


def validate_init_destinations(project_dir: str | Path, write_entities: bool) -> dict[str, Path]:
    """Validate every enabled init output before scanning the project."""
    project_path = Path(project_dir).expanduser().resolve()
    validate_regular_destination(project_path / "mempalace.yaml")
    destinations = {}
    if write_entities:
        entities_path = project_path / "entities.json"
        validate_regular_destination(entities_path)
        destinations["entities.json"] = entities_path
    return destinations


def write_regular_destination(destination: Path, content: str) -> None:
    """Atomically write text without following an irregular destination."""
    temp_path: Path | None = None
    try:
        existing_mode = validate_regular_destination(destination)
        if existing_mode is None:
            umask = os.umask(0)
            try:
                existing_mode = 0o666 & ~umask
            finally:
                os.umask(umask)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            delete=False,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        ) as handle:
            temp_path = Path(handle.name)
            os.fchmod(handle.fileno(), existing_mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
        temp_path = None
    except RegularSourceError:
        raise
    except OSError as exc:
        raise RegularSourceError(destination, exc.strerror or str(exc)) from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def save_config(project_dir: str, project_name: str, rooms: list, dotnet_structure: bool = False):
    config = {
        "wing": project_name,
        "rooms": [
            {
                "name": r["name"],
                "description": r["description"],
                "keywords": r.get("keywords", [r["name"]]),
            }
            for r in rooms
        ],
    }
    if dotnet_structure:
        config["dotnet_structure"] = True
    config_path = Path(project_dir).expanduser().resolve() / "mempalace.yaml"
    write_regular_destination(
        config_path, yaml.dump(config, default_flow_style=False, sort_keys=False)
    )

    print(f"\n  Config saved: {config_path}")
    print("\n  Next step:")
    print(f"    mempalace-code mine {project_dir}")
    print(f"\n{'=' * 55}\n")


def detect_rooms_local(project_dir: str, yes: bool = False, interactive: bool = False):
    """Main entry point for local setup.

    The yes parameter is accepted for backward compatibility; it maps to interactive=False.
    """
    project_path = Path(project_dir).expanduser().resolve()
    project_name = project_path.name.lower().replace(" ", "_").replace("-", "_")

    if not project_path.exists():
        print(f"  Error: directory not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    # Count files
    from .mining.scanner import scan_project

    files = scan_project(project_dir)

    dotnet_structure = False

    # .NET repo: detect from .csproj/.fsproj/.vbproj files first
    csproj_files = (
        [path for path in project_path.glob("**/*.csproj") if is_regular_source_path(path)]
        + [path for path in project_path.glob("**/*.fsproj") if is_regular_source_path(path)]
        + [path for path in project_path.glob("**/*.vbproj") if is_regular_source_path(path)]
    )
    if csproj_files:
        rooms = _rooms_from_csproj(csproj_files)
        source = ".csproj projects"
        dotnet_structure = True
    else:
        # Try folder structure first
        rooms = detect_rooms_from_folders(project_dir)
        source = "folder structure"

        # If only "general" found, try filename patterns
        if len(rooms) <= 1:
            rooms = detect_rooms_from_files(project_dir)
            source = "filename patterns"

        # If still nothing, just use general
        if not rooms:
            rooms = [{"name": "general", "description": "All project files", "keywords": []}]
            source = "fallback (flat project)"

    print_proposed_structure(project_name, rooms, len(files), source)
    if interactive:
        approved_rooms = get_user_approval(rooms)
    else:
        approved_rooms = rooms
    save_config(project_dir, project_name, approved_rooms, dotnet_structure=dotnet_structure)
