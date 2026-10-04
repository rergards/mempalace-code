"""mining.projects — Config loading, room detection, multi-project discovery, wing derivation."""

import fnmatch
import os
import re
import shlex
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from ..errors import InvalidArgumentError
from ..source_io import is_regular_source_path, read_regular_text
from ..taxonomy_filters import clean_write_name, near_duplicate_names
from .kg_extract import parse_sln_file

# Markers that indicate a directory is a software project
PROJECT_MARKERS = frozenset(
    [
        ".git",  # directory
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Gemfile",
        "composer.json",
    ]
)

# Glob-style patterns for markers (matched via fnmatch against filenames)
PROJECT_MARKER_GLOBS = ["*.sln", "*.csproj"]

# Files that indicate mempalace has been initialized for this project
INIT_MARKERS = frozenset(["mempalace.yaml", "mempal.yaml"])


def classify_project_root(root: str | os.PathLike[str]) -> tuple[str, list[str]]:
    """Return the safe root kind and project-marker evidence for *root*.

    Marker contents are never opened.  Symlinks and non-regular nodes are
    ignored; ``.git`` additionally accepts a real directory.
    """
    root_path = Path(root)
    try:
        contents = set(os.listdir(root_path))
    except OSError:
        return "parent", []

    found_markers: list[str] = []
    for marker in PROJECT_MARKERS:
        if marker not in contents:
            continue
        marker_path = root_path / marker
        if marker_path.is_symlink():
            continue
        if marker == ".git":
            if marker_path.is_dir() or is_regular_source_path(marker_path):
                found_markers.append(marker)
        elif is_regular_source_path(marker_path):
            found_markers.append(marker)

    for pattern in PROJECT_MARKER_GLOBS:
        for item in sorted(contents):
            marker_path = root_path / item
            if (
                fnmatch.fnmatch(item, pattern)
                and not marker_path.is_symlink()
                and is_regular_source_path(marker_path)
            ):
                found_markers.append(item)
                break

    initialized = any(
        marker in contents
        and not (root_path / marker).is_symlink()
        and is_regular_source_path(root_path / marker)
        for marker in INIT_MARKERS
    )
    if initialized:
        return "initialized", sorted(found_markers)
    if found_markers:
        return "project", sorted(found_markers)
    return "parent", []


class InvalidProjectConfigError(ValueError):
    """Raised when mempalace.yaml/mempal.yaml cannot be parsed or is not a mapping.

    Attributes:
        code: stable machine-testable error code ("invalid_project_config").
        config_path: path to the offending config file.
    """

    code = "invalid_project_config"

    def __init__(self, config_path, detail: str):
        self.config_path = config_path
        self.detail = detail
        super().__init__(f"cannot parse {config_path}: {detail}")


def _load_yaml_mapping(config_path: Path) -> dict:
    """Load *config_path* as YAML and validate its top-level content is a mapping.

    Returns an empty dict for an empty file. Raises InvalidProjectConfigError (a
    ValueError subclass) when the file cannot be parsed or its top-level content
    is not a mapping (e.g. a list or scalar).
    """
    import yaml

    try:
        data = yaml.safe_load(read_regular_text(config_path, encoding="utf-8"))
    except Exception as exc:
        raise InvalidProjectConfigError(config_path, str(exc)) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise InvalidProjectConfigError(
            config_path, f"top-level content must be a mapping, got {type(data).__name__}"
        )
    return data


def _config_scalar_text(value: object) -> str | None:
    """Return a YAML scalar (string or number) as text, or None for other types."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    return str(value)


def _validated_project_config(data: dict, config_path: Path, project_dir: str | Path) -> dict:
    """Check the fields mining reads and fill the documented defaults.

    A missing or empty ``wing`` defaults to the wing ``init`` would write: the root
    ``.sln`` name when ``dotnet_structure`` is set, else :func:`derive_wing_name` (git
    origin of a repository root, else the folder name); a numeric wing such as
    ``wing: 12345`` is read as text. ``rooms`` must be a list whose items are mappings with a non-empty
    ``name`` or plain room-name strings; ``keywords`` must be a list of scalars (a
    single string is accepted). Anything else raises :class:`InvalidProjectConfigError`
    naming the offending field, instead of a KeyError/TypeError deep inside mining.
    """
    config = dict(data)
    wing = config.get("wing")
    if wing is None or (isinstance(wing, str) and not wing.strip()):
        project_path = Path(project_dir).expanduser().resolve()
        sln_wing = _detect_sln_wing(project_path) if config.get("dotnet_structure") else None
        config["wing"] = sln_wing or derive_wing_name(str(project_path))
    else:
        wing_text = _config_scalar_text(wing)
        if wing_text is None:
            raise InvalidProjectConfigError(
                config_path, f"'wing' must be a text value, got {type(wing).__name__}"
            )
        config["wing"] = wing_text

    rooms = config.get("rooms")
    if rooms is None:
        return config
    if not isinstance(rooms, list):
        raise InvalidProjectConfigError(
            config_path, f"'rooms' must be a list of rooms, got {type(rooms).__name__}"
        )
    validated_rooms = []
    for index, item in enumerate(rooms):
        room = {"name": item.strip()} if isinstance(item, str) else item
        name = room.get("name") if isinstance(room, dict) else None
        if not isinstance(room, dict) or not isinstance(name, str) or not name.strip():
            raise InvalidProjectConfigError(
                config_path,
                f"rooms[{index}] must be a mapping with a non-empty 'name' (or a plain room name)",
            )
        keywords = room.get("keywords")
        if keywords is None:
            keywords = []
        elif isinstance(keywords, str):
            keywords = [keywords]
        if not isinstance(keywords, list):
            raise InvalidProjectConfigError(
                config_path, f"rooms[{index}].keywords must be a list of words"
            )
        keyword_texts = [_config_scalar_text(keyword) for keyword in keywords]
        if any(text is None for text in keyword_texts):
            raise InvalidProjectConfigError(
                config_path, f"rooms[{index}].keywords must contain only words"
            )
        validated_rooms.append({**room, "name": name, "keywords": keyword_texts})
    config["rooms"] = validated_rooms
    return config


def _nearest_initialized_ancestor(path: Path) -> Path | None:
    for candidate in path.parents:
        if any((candidate / marker).is_file() for marker in INIT_MARKERS):
            return candidate
    return None


def load_config(project_dir: str) -> dict:
    """Load mempalace.yaml from project directory (falls back to mempal.yaml).

    The result is validated by :func:`_validated_project_config`; malformed files
    raise :class:`InvalidProjectConfigError`.
    """
    project_path = Path(project_dir).expanduser().resolve()
    if not project_path.exists():
        print(f"ERROR: directory not found: {project_dir}", file=sys.stderr)
        print(
            "Next: check the path; mine takes an existing project directory "
            "(set up a new one with: mempalace-code init <dir>).",
            file=sys.stderr,
        )
        sys.exit(1)
    if not project_path.is_dir():
        print(
            f"ERROR: not a directory: {project_dir} (mine takes a project directory, not a file)",
            file=sys.stderr,
        )
        ancestor = _nearest_initialized_ancestor(project_path)
        if ancestor is not None:
            print(f"Next: mine the project that contains it: {ancestor}", file=sys.stderr)
        else:
            print(
                f"Next: run mempalace-code init {project_path.parent}, then mine that directory.",
                file=sys.stderr,
            )
        sys.exit(1)
    config_path = project_path / "mempalace.yaml"
    if not config_path.exists():
        # Fallback to legacy name
        legacy_path = Path(project_dir).expanduser().resolve() / "mempal.yaml"
        if legacy_path.exists():
            config_path = legacy_path
        else:
            print(f"ERROR: No mempalace.yaml found in {project_dir}")
            print(f"Run: mempalace-code init {project_dir}")
            sys.exit(1)
    return _validated_project_config(_load_yaml_mapping(config_path), config_path, project_dir)


_TOKEN_RE = re.compile(r"[^\W_]+")
# init describes a folder-derived room as "Files from <dir>/" (or "<a>/, <b>/").
_FOLDER_ROOM_DESCRIPTION_RE = re.compile(r"^Files from .+/$")


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase letter/digit tokens (any script) at separator boundaries."""
    return _TOKEN_RE.findall(unicodedata.normalize("NFC", text).lower())


def _is_folder_room(room: dict) -> bool:
    """True for a room that stands for directories (``init`` wrote "Files from <dir>/")."""
    description = room.get("description")
    return isinstance(description, str) and bool(
        _FOLDER_ROOM_DESCRIPTION_RE.match(description.strip())
    )


def _token_seq_in(needle: list[str], haystack: list[str]) -> bool:
    """Return True if needle appears as a contiguous subsequence in haystack."""
    n, h = len(needle), len(haystack)
    if n == 0 or n > h:
        return False
    return any(haystack[i : i + n] == needle for i in range(h - n + 1))


def _name_match_strength(
    name_tokens: list[str], rooms: list, *, is_folder: bool
) -> tuple[int, str] | None:
    """Best (strength, room) for a path component or filename; None when nothing matches.

    Strength 2: the tokens equal a room name or keyword exactly. Strength 1: a room
    name or keyword appears inside the tokens (``ui_components`` contains keyword
    ``components``). A component that is only part of a room name (``acme`` inside
    room ``acme_web``) never matches, so an unrelated folder cannot claim a room.
    Ties go to the room listed first in mempalace.yaml.

    A folder room (``Files from <dir>/``) matches only a folder (*is_folder*) whose
    name equals its name or a keyword, so it never claims ``mempalace_notes.md`` or a
    ``mempalace_old/`` folder.
    """
    if not name_tokens:
        return None
    best: tuple[int, str] | None = None
    for room in rooms:
        folder_room = _is_folder_room(room)
        if folder_room and not is_folder:
            continue
        for candidate in [room["name"]] + room.get("keywords", []):
            candidate_tokens = _tokenize(candidate) if candidate else []
            if not candidate_tokens:
                continue
            if candidate_tokens == name_tokens:
                strength = 2
            elif not folder_room and _token_seq_in(candidate_tokens, name_tokens):
                strength = 1
            else:
                continue
            if best is None or strength > best[0]:
                best = (strength, room["name"])
    return best


def _count_keyword_occurrences(text_tokens: list[str], kw_tokens: list[str]) -> int:
    """Count non-overlapping occurrences of kw_tokens as a contiguous sequence in text_tokens."""
    if not kw_tokens or not text_tokens:
        return 0
    n, h = len(kw_tokens), len(text_tokens)
    count, i = 0, 0
    while i <= h - n:
        if text_tokens[i : i + n] == kw_tokens:
            count += 1
            i += n
        else:
            i += 1
    return count


def detect_room(
    filepath: Path,
    content: str,
    rooms: list,
    project_path: Path,
    csproj_room_map: "dict[Path, str] | None" = None,
) -> str:
    """
    Route a file to the right room.
    Priority:
    0. .csproj-derived map lookup (when dotnet_structure is enabled)
    1. Folder path matches a room name or keyword (separator-bounded tokens)
    2. Filename matches a room name or keyword (separator-bounded tokens)
    3. Content keyword scoring (bounded token occurrences); a tie is not a signal.
    Folder rooms (described "Files from <dir>/") take only files inside a folder named
    exactly like the room or one of its keywords: they skip steps 2 and 3.
    4. Fallback: "general"
    """
    # Priority 0: .csproj-derived room map
    if csproj_room_map:
        check = filepath.parent.resolve()
        while check != project_path and check != check.parent:
            if check in csproj_room_map:
                return csproj_room_map[check]
            check = check.parent
        if project_path in csproj_room_map:
            return csproj_room_map[project_path]

    relative = str(filepath.relative_to(project_path)).lower()
    filename = filepath.stem.lower()
    content_lower = content[:2000].lower()

    # Priority 1: folder path matches room name or keywords. The outermost folder
    # with an exact match wins; otherwise the outermost partial match.
    path_parts = relative.replace("\\", "/").split("/")
    folder_matches = [
        match
        for match in (
            _name_match_strength(_tokenize(part), rooms, is_folder=True) for part in path_parts[:-1]
        )
        if match is not None
    ]
    if folder_matches:
        strongest = max(strength for strength, _room in folder_matches)
        return next(room for strength, room in folder_matches if strength == strongest)

    # Priority 2: filename matches room name or keyword
    filename_match = _name_match_strength(_tokenize(filename), rooms, is_folder=False)
    if filename_match is not None:
        return filename_match[1]

    # Priority 3: keyword scoring from room keywords + name
    scores = defaultdict(int)
    content_tokens = _tokenize(content_lower)
    for room in rooms:
        if _is_folder_room(room):
            continue
        keywords = room.get("keywords", []) + [room["name"]]
        for kw in keywords:
            kw_tokens = _tokenize(kw)
            scores[room["name"]] += _count_keyword_occurrences(content_tokens, kw_tokens)

    if scores:
        best = max(scores, key=lambda k: scores[k])
        tied = sum(1 for score in scores.values() if score == scores[best])
        if scores[best] > 0 and tied == 1:
            return best

    return "general"


def detect_projects(parent_dir: str) -> list:
    """Scan immediate subdirectories of *parent_dir* for software projects.

    A directory is considered a project if it contains at least one safe
    PROJECT_MARKERS / PROJECT_MARKER_GLOBS match or a safe INIT_MARKERS file.
    Hidden directories (names starting with ``"."``) are skipped as candidates.

    Returns a list of dicts sorted by folder name::

        [
            {
                "path": "/abs/path/to/project",
                "markers": [".git", "pyproject.toml"],
                "initialized": True,   # mempalace.yaml / mempal.yaml present
            },
            ...
        ]
    """
    parent = Path(parent_dir).expanduser().resolve()
    results = []

    try:
        entries = sorted(os.listdir(parent))
    except OSError:
        return results

    for name in entries:
        if name.startswith("."):
            continue  # skip hidden directories

        candidate = parent / name
        if not candidate.is_dir():
            continue

        root_kind, found_markers = classify_project_root(candidate)
        if root_kind == "parent":
            continue

        results.append(
            {
                "path": str(candidate),
                "markers": found_markers,
                "initialized": root_kind == "initialized",
            }
        )

    return results


def derive_wing_name(project_dir: str) -> str:
    """Derive a wing name for *project_dir*.

    When *project_dir* is a repository root (it has a ``.git`` entry), tries
    ``git -C <dir> remote get-url origin`` first and parses the URL to extract the
    repository name (strips ``.git`` suffix).  Falls back to the folder basename for
    subdirectories of a repository, when git is unavailable, or when the remote is
    not set.

    The returned name is lowercased and normalized so that spaces and hyphens
    become underscores and characters other than letters, digits and underscores
    (of any script) are stripped.
    ``init`` writes this name into a new ``mempalace.yaml``, so ``mine``, ``mine-all``
    and the ``mine-all --dry-run`` preview agree.
    """
    import subprocess

    project_path = Path(project_dir).expanduser().resolve()

    # Only a repository root is named after its origin: subprojects of a monorepo keep
    # their own folder names instead of every one of them sharing the repository's wing.
    if not os.path.lexists(project_path / ".git"):
        return _normalize_wing_name(project_path.name)

    # Attempt to get the repo name from the git remote URL
    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Parse HTTPS: https://github.com/user/repo.git
            # Parse SSH:   git@github.com:user/repo.git
            repo_name = url.rstrip("/").split("/")[-1].split(":")[-1]
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]
            if repo_name:
                return _normalize_wing_name(repo_name)
    except Exception:
        pass

    return _normalize_wing_name(project_path.name)


def resolve_wing_for_project(project_dir: str) -> str:
    """Resolve wing name for a project directory using this priority order:

    1. Explicit ``wing:`` key in ``mempalace.yaml`` / ``mempal.yaml`` (normalized).
    2. Git origin repo name, via :func:`derive_wing_name`.
    3. Normalized folder name, via :func:`derive_wing_name`.

    Raises :class:`InvalidProjectConfigError` (a :class:`ValueError` subclass) if a
    config file exists but cannot be parsed (e.g. invalid YAML) or its top-level
    content is not a mapping, so callers can report the error rather than silently
    falling back to an unrelated wing name.
    """
    project_path = Path(project_dir).expanduser().resolve()

    for config_name in ("mempalace.yaml", "mempal.yaml"):
        config_path = project_path / config_name
        if not config_path.exists():
            continue
        config = _validated_project_config(
            _load_yaml_mapping(config_path), config_path, project_path
        )
        return configured_wing(config)

    return derive_wing_name(project_dir)


def configured_wing(config: dict) -> str:
    """Return the wing a validated project config selects, normalized as ``mine`` stores it.

    An explicit ``wing:`` always wins; :func:`load_config` fills a missing one (the root
    ``.sln`` name for ``dotnet_structure``). .NET wings use the .sln normalization.
    """
    wing = config["wing"]
    if config.get("dotnet_structure", False):
        return _normalize_wing_name(wing.strip())
    return _normalize_configured_wing(wing)


def _name_characters(name: str, *, hyphen: str) -> str:
    """Lowercase *name* (Unicode NFC) and keep only letters, digits, marks, ``_`` and ``-``.

    Whitespace becomes ``_``; a hyphen becomes *hyphen*. Letters of every script survive
    (``café``, ``日本語``), so two non-ASCII names never collapse to the same fallback.
    """
    name = unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).lower())
    kept = []
    for char in name:
        if char.isspace():
            kept.append("_")
        elif char == "-":
            kept.append(hyphen)
        elif char == "_" or char.isalnum() or unicodedata.category(char).startswith("M"):
            kept.append(char)
    return "".join(kept)


def _normalize_wing_name(name: str) -> str:
    """Lowercase, replace spaces/hyphens with underscores, strip other special chars."""
    return _name_characters(name, hyphen="_") or "project"


def _normalize_configured_wing(name: str) -> str:
    """Canonicalize an explicit non-.NET wing while preserving hyphens."""
    return _name_characters(name.strip(), hyphen="-") or "project"


def mine_wing(config: dict, wing_override: str | None = None) -> str:
    """Return the wing a mine files into: ``--wing`` when given, else the config's wing.

    ``--wing`` is normalized exactly like a ``wing:`` in mempalace.yaml, so ``"Other Wing"``,
    ``"other wing"`` and ``other_wing`` name one wing. An empty override falls back to the
    config. A blank override or one containing ``/``, ``\\`` or a control character raises
    :class:`~mempalace_code.errors.InvalidArgumentError` naming ``wing``.
    """
    if not wing_override:
        return configured_wing(config)
    return configured_wing({**config, "wing": clean_write_name(wing_override, "wing")})


def validate_mine_arguments(wing_override: str | None, agent: str) -> None:
    """Refuse a blank or unsafe ``--wing`` and a blank ``--agent`` before anything is mined."""
    if wing_override:
        clean_write_name(wing_override, "wing")
    if not isinstance(agent, str) or not agent.strip():
        raise InvalidArgumentError("agent must not be blank", argument="agent")


def settle_mine_wing(
    existing_wings,
    wing: str,
    wing_override: str | None = None,
    *,
    retry_command: Callable[[str], str] | None = None,
) -> str:
    """Return the wing to file into, refusing a new wing that re-spells an existing one.

    *existing_wings* are the palace's wing names. A wing that already exists is used as is.
    A ``--wing`` that names an existing wing exactly (such as one stored verbatim by an
    older release) keeps filing into that wing. A new wing that differs from an existing
    wing only by case, spacing or punctuation raises
    :class:`~mempalace_code.errors.InvalidArgumentError` naming the existing wing and, when
    *retry_command* is given, the command that files under it (the rule
    ``diary write --wing`` and ``mempalace_add_drawer`` apply).
    """
    existing = set(existing_wings)
    raw = wing_override.strip() if wing_override else ""
    if raw and raw in existing:
        return raw
    if wing in existing:
        return wing
    similar = near_duplicate_names(wing, existing)
    if not similar:
        return wing
    target = similar[0]
    source = "--wing" if wing_override else "the mempalace.yaml wing"
    retry = (
        f"run {retry_command(target)}"
        if retry_command is not None
        else f"pass --wing {shlex.quote(target)}"
    )
    yaml_retry = ""
    if configured_wing({"wing": target}) == target:
        import yaml

        yaml_config = yaml.safe_dump({"wing": target}, allow_unicode=True).strip()
        yaml_retry = f" (or set {yaml_config!r} in mempalace.yaml)"
    raise InvalidArgumentError(
        f"wing {wing!r} (from {source}) differs from the existing wing {target!r} only by "
        f"case, spacing or punctuation; to file under the existing wing {retry}{yaml_retry}, "
        f"or choose a clearly different name",
        argument="wing",
    )


def _normalize_room_name(name: str) -> str:
    """Normalize a project name to a room name.

    Lowercases, replaces dots/hyphens/spaces with underscores, strips other chars.
    E.g. MyApp.Infrastructure -> myapp_infrastructure, My-Project.Api -> my_project_api.
    """
    return _name_characters(name.replace(".", "_"), hyphen="_") or "general"


def _detect_sln_wing(project_path: Path):
    """Return a normalized wing name derived from the root-level .sln file, or None.

    If multiple .sln files exist, pick the one with the most contained projects;
    ties are broken alphabetically.
    """
    sln_files = sorted(path for path in project_path.glob("*.sln") if is_regular_source_path(path))
    if not sln_files:
        return None
    if len(sln_files) == 1:
        return _normalize_wing_name(sln_files[0].stem)
    # Multiple .sln files — sort by (-project_count, name) and take first
    ranked = sorted(sln_files, key=lambda f: (-len(parse_sln_file(f)), f.name.lower()))
    return _normalize_wing_name(ranked[0].stem)


def _build_csproj_room_map(project_path: Path) -> "dict[Path, str]":
    """Build a mapping of {project_folder: room_name} from .csproj/.fsproj/.vbproj files.

    The key is the resolved parent directory of each project file.
    The value is the normalized room name derived from the project file stem.
    """
    proj_files: list = []
    for pattern in ("**/*.csproj", "**/*.fsproj", "**/*.vbproj"):
        proj_files.extend(
            path for path in project_path.glob(pattern) if is_regular_source_path(path)
        )

    room_map: dict = {}
    for pf in proj_files:
        folder = pf.parent.resolve()
        room_name = _normalize_room_name(pf.stem)
        room_map[folder] = room_name
    return room_map
