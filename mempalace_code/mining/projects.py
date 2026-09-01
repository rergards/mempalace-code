"""mining.projects — Config loading, room detection, multi-project discovery, wing derivation."""

import fnmatch
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from ..source_io import is_regular_source_path, read_regular_text
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


def load_config(project_dir: str) -> dict:
    """Load mempalace.yaml from project directory (falls back to mempal.yaml)."""
    config_path = Path(project_dir).expanduser().resolve() / "mempalace.yaml"
    if not config_path.exists():
        # Fallback to legacy name
        legacy_path = Path(project_dir).expanduser().resolve() / "mempal.yaml"
        if legacy_path.exists():
            config_path = legacy_path
        else:
            print(f"ERROR: No mempalace.yaml found in {project_dir}")
            print(f"Run: mempalace-code init {project_dir}")
            sys.exit(1)
    return _load_yaml_mapping(config_path)


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase alphanumeric tokens at separator boundaries."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _token_seq_in(needle: list[str], haystack: list[str]) -> bool:
    """Return True if needle appears as a contiguous subsequence in haystack."""
    n, h = len(needle), len(haystack)
    if n == 0 or n > h:
        return False
    return any(haystack[i : i + n] == needle for i in range(h - n + 1))


def _tokens_match(a_tokens: list[str], b_tokens: list[str]) -> bool:
    """Return True if either token sequence appears contiguously inside the other."""
    if not a_tokens or not b_tokens:
        return False
    return _token_seq_in(a_tokens, b_tokens) or _token_seq_in(b_tokens, a_tokens)


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
    3. Content keyword scoring (bounded token occurrences)
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

    # Priority 1: folder path matches room name or keywords
    path_parts = relative.replace("\\", "/").split("/")
    for part in path_parts[:-1]:  # skip filename itself
        part_tokens = _tokenize(part)
        for room in rooms:
            candidates = [room["name"]] + room.get("keywords", [])
            if any(_tokens_match(part_tokens, _tokenize(c)) for c in candidates if c):
                return room["name"]

    # Priority 2: filename matches room name or keyword
    filename_tokens = _tokenize(filename)
    for room in rooms:
        candidates = [room["name"]] + room.get("keywords", [])
        if any(_tokens_match(filename_tokens, _tokenize(c)) for c in candidates if c):
            return room["name"]

    # Priority 3: keyword scoring from room keywords + name
    scores = defaultdict(int)
    content_tokens = _tokenize(content_lower)
    for room in rooms:
        keywords = room.get("keywords", []) + [room["name"]]
        for kw in keywords:
            kw_tokens = _tokenize(kw)
            scores[room["name"]] += _count_keyword_occurrences(content_tokens, kw_tokens)

    if scores:
        best = max(scores, key=lambda k: scores[k])
        if scores[best] > 0:
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

    Tries ``git -C <dir> remote get-url origin`` first.  Parses the URL to
    extract the repository name (strips ``.git`` suffix).  Falls back to the
    folder basename when git is unavailable or the remote is not set.

    The returned name is lowercased and normalized so that spaces and hyphens
    become underscores and non-alphanumeric/underscore characters are stripped.
    This matches the convention used by ``room_detector_local.detect_rooms_local()``.
    """
    import subprocess

    project_path = Path(project_dir).expanduser().resolve()

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
        config = _load_yaml_mapping(config_path)
        wing = config.get("wing", "")
        if wing and isinstance(wing, str) and wing.strip():
            return _normalize_wing_name(wing.strip())
        # config file exists but has no usable wing — stop looking, fall through
        break

    return derive_wing_name(project_dir)


def _normalize_wing_name(name: str) -> str:
    """Lowercase, replace spaces/hyphens with underscores, strip other special chars."""
    name = name.lower().replace("-", "_").replace(" ", "_")
    name = re.sub(r"[^a-z0-9_]", "", name)
    return name or "project"


def _normalize_room_name(name: str) -> str:
    """Normalize a project name to a room name.

    Lowercases, replaces dots/hyphens/spaces with underscores, strips other chars.
    E.g. MyApp.Infrastructure -> myapp_infrastructure, My-Project.Api -> my_project_api.
    """
    name = name.lower().replace(".", "_").replace("-", "_").replace(" ", "_")
    name = re.sub(r"[^a-z0-9_]", "", name)
    return name or "general"


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
