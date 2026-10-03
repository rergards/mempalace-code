#!/usr/bin/env python3
"""
room_detector_local.py — Local setup, no API required.

Two ways to define rooms without calling any AI:
  1. Auto-detect from folder structure (zero config)
  2. Define manually in mempalace.yaml

No internet. No API key. Your files stay on your machine.
"""

import os
import shlex
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


def _general_room() -> dict:
    return {"name": "general", "description": "Files that don't fit other rooms", "keywords": []}


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
        rooms.append(_general_room())
    return rooms


def _is_room_candidate_dir(path: Path, project_path: Path) -> bool:
    """True for a directory ``mine`` will traverse: a real directory, not a skipped one.

    Symlinked directories are excluded because the scanner never follows them, and
    skipped, scan-filtered, or ``.gitignore``d directories because mine never reads
    them, so a room named after one could never receive a drawer.
    """
    from .mining.scanner import is_traversed_dir

    try:
        return path.is_dir() and not path.is_symlink() and is_traversed_dir(path, project_path)
    except OSError:
        return False


def _sorted_children(path: Path) -> list[Path]:
    try:
        return sorted(path.iterdir(), key=lambda child: child.name)
    except OSError:
        return []


def _collect_folder_rooms(project_path: Path, covered=None) -> dict[str, list[str]]:
    """Map room name -> source directory names from the top two folder levels.

    *covered* optionally names directories already owned by another room source
    (.NET project folders); they and their subtrees are skipped.
    """
    found: dict[str, list[str]] = {}

    def is_covered(path: Path) -> bool:
        return covered is not None and covered(path)

    def add(room_name: str, original: str) -> None:
        sources = found.setdefault(room_name, [])
        if original not in sources:
            sources.append(original)

    top_dirs = [
        item
        for item in _sorted_children(project_path)
        if _is_room_candidate_dir(item, project_path) and not is_covered(item)
    ]

    # Top-level directories first (most reliable signal)
    for item in top_dirs:
        name_lower = item.name.lower().replace("-", "_")
        if name_lower in FOLDER_ROOM_MAP:
            add(FOLDER_ROOM_MAP[name_lower], item.name)
        # Also check if folder name IS a good room name directly
        elif len(item.name) > 2 and item.name[0].isalpha():
            add(item.name.lower().replace("-", "_").replace(" ", "_"), item.name)

    # Walk one level deeper for nested patterns
    for item in top_dirs:
        for subitem in _sorted_children(item):
            if not _is_room_candidate_dir(subitem, project_path) or is_covered(subitem):
                continue
            name_lower = subitem.name.lower().replace("-", "_")
            if name_lower in FOLDER_ROOM_MAP and FOLDER_ROOM_MAP[name_lower] not in found:
                add(FOLDER_ROOM_MAP[name_lower], subitem.name)

    return found


def _rooms_from_folder_sources(found: dict[str, list[str]]) -> list:
    """Room dicts for collected folder sources, with unique keywords per room."""
    rooms = []
    for room_name, originals in found.items():
        rooms.append(
            {
                "name": room_name,
                "description": "Files from " + ", ".join(f"{o}/" for o in originals),
                "keywords": list(dict.fromkeys([room_name, *(o.lower() for o in originals)])),
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
    rooms = _rooms_from_folder_sources(_collect_folder_rooms(project_path))

    # Always add "general" as fallback
    if not any(r["name"] == "general" for r in rooms):
        rooms.append(_general_room())

    return rooms


def _merge_dotnet_and_folder_rooms(project_path: Path, csproj_files: list) -> tuple[list, bool]:
    """Return .csproj rooms plus folder rooms for directories outside every .NET project.

    A mixed repository keeps folder-based rooms (backend/, frontend/, docs/, ...) for
    code that no .csproj covers instead of sending all of it to "general". The bool is
    True when any folder room was added.

    A directory is covered when it is a project directory, contains one, or sits inside
    one: ``mine`` routes every file under a project directory to that project's room,
    so a folder room there could never be filled (a root-level .csproj covers the tree).
    """
    project_dirs = {pf.parent.resolve() for pf in csproj_files}

    def covered(path: Path) -> bool:
        resolved = path.resolve()
        return any(
            d == resolved or resolved in d.parents or d in resolved.parents for d in project_dirs
        )

    rooms = [room for room in _rooms_from_csproj(csproj_files) if room["name"] != "general"]
    by_name = {room["name"]: room for room in rooms}
    added = False
    for folder_room in _rooms_from_folder_sources(_collect_folder_rooms(project_path, covered)):
        existing = by_name.get(folder_room["name"])
        if existing is not None:
            existing["keywords"] = list(
                dict.fromkeys([*existing["keywords"], *folder_room["keywords"]])
            )
            continue
        rooms.append(folder_room)
        by_name[folder_room["name"]] = folder_room
        added = True
    rooms.append(_general_room())
    return rooms, added


def detect_rooms_from_files(project_dir: str) -> list:
    """
    Fallback: if folder structure gives no signal,
    detect rooms from recurring filename patterns.
    """
    project_path = Path(project_dir).expanduser().resolve()
    keyword_counts = defaultdict(int)

    from .mining.scanner import should_skip_dir

    for root, dirs, filenames in os.walk(project_path):
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]
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


def snapshot_regular_destinations(
    destinations: list[Path],
) -> dict[Path, tuple[bytes | None, int | None]]:
    """Capture regular destination bytes and modes before a multi-file write."""
    from .source_io import read_regular_bytes

    snapshots: dict[Path, tuple[bytes | None, int | None]] = {}
    for destination in destinations:
        mode = validate_regular_destination(destination)
        snapshots[destination] = (
            None if mode is None else read_regular_bytes(destination),
            mode,
        )
    return snapshots


def restore_regular_destinations(
    snapshots: dict[Path, tuple[bytes | None, int | None]],
) -> None:
    """Restore a failed multi-file write to its captured regular-file state."""
    from .source_io import read_regular_bytes

    for destination, (content, mode) in reversed(list(snapshots.items())):
        if content is None:
            try:
                current_mode = os.lstat(destination).st_mode
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(current_mode):
                raise RegularSourceError(destination, "changed during rollback")
            destination.unlink()
            continue
        current_mode = validate_regular_destination(destination)
        if (
            current_mode is not None
            and current_mode == mode
            and read_regular_bytes(destination) == content
        ):
            continue
        write_regular_destination(destination, content.decode("utf-8"))
        if mode is not None:
            os.chmod(destination, mode)


PROJECT_CONFIG_NAMES = ("mempalace.yaml", "mempal.yaml")
# Keys init regenerates on --force; every other key in an existing config is kept.
_REGENERATED_CONFIG_KEYS = frozenset({"wing", "rooms", "dotnet_structure"})


def existing_project_config(project_dir: str | Path) -> Path | None:
    """Return the project's existing mempalace.yaml (or legacy mempal.yaml), if any."""
    project_path = Path(project_dir).expanduser().resolve()
    for name in PROJECT_CONFIG_NAMES:
        candidate = project_path / name
        if os.path.lexists(candidate):
            return candidate
    return None


def _read_existing_config(config_path: Path) -> tuple[dict, str | None]:
    """Return ``(mapping, error)`` for an existing project config; error is None when valid."""
    from .mining.projects import InvalidProjectConfigError, _load_yaml_mapping

    try:
        return _load_yaml_mapping(config_path), None
    except InvalidProjectConfigError as exc:
        return {}, exc.detail
    except OSError as exc:
        return {}, exc.strerror or str(exc)


def _configured_wing(config: dict) -> str | None:
    """The existing config's usable wing text, read the way mining reads it."""
    from .mining.projects import _config_scalar_text

    wing = _config_scalar_text(config.get("wing"))
    return wing if wing and wing.strip() else None


def report_kept_config(config_path: Path) -> None:
    """Explain that init left an existing project config untouched, and how to regenerate."""
    project_path = config_path.parent
    existing, error = _read_existing_config(config_path)
    print(f"\n  {config_path.name} already exists: {config_path}")
    if error is not None:
        print(f"  Warning: it cannot be parsed ({error}); mining will refuse it until it is fixed.")
    else:
        wing = _configured_wing(existing)
        rooms = existing.get("rooms")
        room_count = len(rooms) if isinstance(rooms, list) else 0
        wing_text = f"wing: {wing}" if wing else "no wing set"
        print(f"  Kept unchanged ({wing_text}, {room_count} room(s)).")
    if config_path.name == "mempalace.yaml":
        detail = "the old file is backed up first"
    else:
        detail = f"writes a new mempalace.yaml and leaves {config_path.name} in place"
    print(f"  To regenerate its rooms (keeps the wing and other settings; {detail}), run:")
    print(f"    mempalace-code init {shlex.quote(str(project_path))} --force")


def backup_project_config(config_path: Path) -> Path:
    """Copy an existing regular config to a new ``<name>.bak`` (or ``.bak.N``) file."""
    from .source_io import read_regular_bytes

    mode = validate_regular_destination(config_path)
    content = read_regular_bytes(config_path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    for index in range(1000):
        suffix = ".bak" if index == 0 else f".bak.{index}"
        candidate = config_path.with_name(config_path.name + suffix)
        try:
            fd = os.open(candidate, flags, mode if mode is not None else 0o644)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return candidate
    raise RegularSourceError(config_path, "no free backup file name")


def save_config(
    project_dir: str,
    project_name: str,
    rooms: list,
    dotnet_structure: bool = False,
    preserved: dict | None = None,
) -> Path:
    """Write mempalace.yaml; an existing file is backed up first.

    *preserved* carries keys from a previous config (``architecture``, ``scan_skip_*``,
    ...) that are written back unchanged after the regenerated wing and rooms.
    """
    config: dict = {
        "wing": project_name,
        "rooms": [
            {
                "name": r["name"],
                "description": r["description"],
                "keywords": list(dict.fromkeys(r.get("keywords", [r["name"]]))),
            }
            for r in rooms
        ],
    }
    if dotnet_structure:
        config["dotnet_structure"] = True
    for key, value in (preserved or {}).items():
        if key not in _REGENERATED_CONFIG_KEYS:
            config[key] = value
    config_path = Path(project_dir).expanduser().resolve() / "mempalace.yaml"
    backup_path = backup_project_config(config_path) if os.path.lexists(config_path) else None
    write_regular_destination(
        config_path, yaml.dump(config, default_flow_style=False, sort_keys=False)
    )

    print(f"\n  Config saved: {config_path}")
    if backup_path is not None:
        print(f"  Previous config backed up to: {backup_path}")
    return config_path


def _init_wing_name(project_path: Path, dotnet_structure: bool) -> str:
    """The wing ``mine`` will store for a fresh config: .sln name, git origin, or folder."""
    from .mining.projects import _detect_sln_wing, derive_wing_name

    if dotnet_structure:
        sln_wing = _detect_sln_wing(project_path)
        if sln_wing:
            return sln_wing
    return derive_wing_name(str(project_path))


def detect_rooms_local(
    project_dir: str, yes: bool = False, interactive: bool = False, force: bool = False
) -> str:
    """Main entry point for local setup.

    Returns ``"kept"`` when an existing mempalace.yaml (or legacy mempal.yaml) was left
    untouched, ``"regenerated"`` when *force* replaced the rooms of an existing config,
    or ``"written"`` after saving a first config. Rerunning init never replaces an
    existing config unless *force* is True; then the rooms are regenerated while the
    existing wing and every other key are kept, and the old file is backed up.
    *yes* suppresses the *interactive* room review.
    """
    project_path = Path(project_dir).expanduser().resolve()

    if not project_path.is_dir():
        problem = "not a directory" if project_path.exists() else "directory not found"
        print(f"  Error: {problem}: {project_dir}", file=sys.stderr)
        sys.exit(1)

    existing_path = existing_project_config(project_path)
    if existing_path is not None and not force:
        report_kept_config(existing_path)
        return "kept"

    preserved: dict = {}
    if existing_path is not None:
        preserved, error = _read_existing_config(existing_path)
        if error is not None:
            kept_as = "backed up" if existing_path.name == "mempalace.yaml" else "left in place"
            print(
                f"  Warning: existing {existing_path} cannot be parsed ({error}); "
                f"regenerating it from scratch (the original is {kept_as}).",
                file=sys.stderr,
            )

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
        rooms, folder_rooms_added = _merge_dotnet_and_folder_rooms(project_path, csproj_files)
        source = (
            ".csproj projects and folder structure" if folder_rooms_added else ".csproj projects"
        )
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

    project_name = _configured_wing(preserved) or _init_wing_name(project_path, dotnet_structure)

    print_proposed_structure(project_name, rooms, len(files), source)
    if interactive and not yes:
        approved_rooms = get_user_approval(rooms)
    else:
        approved_rooms = rooms
    save_config(
        project_dir,
        project_name,
        approved_rooms,
        dotnet_structure=dotnet_structure,
        preserved=preserved,
    )
    if existing_path is None:
        return "written"
    if existing_path.name != "mempalace.yaml":
        print(
            f"  Legacy {existing_path.name} was left in place; mempalace.yaml now takes precedence."
        )
    return "regenerated"
