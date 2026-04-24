#!/usr/bin/env python3
"""
miner.py — Files everything into the palace.

Reads mempalace.yaml from the project directory to know the wing + rooms.
Routes each file to the right room based on content.
Stores verbatim chunks as drawers. No summaries. Ever.
"""

import os
import re
import sys
import time
import hashlib
import fnmatch
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional

from .storage import open_store
from .treesitter import get_parser
from .version import __version__
from .config import MempalaceConfig

EXTENSION_LANG_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".fs": "fsharp",
    ".fsi": "fsharp",
    ".vb": "vbnet",
    ".swift": "swift",
    ".csproj": "xml",
    ".fsproj": "xml",
    ".vbproj": "xml",
    ".sln": "dotnet-solution",
    ".xaml": "xaml",
    ".sh": "shell",
    ".sql": "sql",
    ".md": "markdown",
    ".txt": "text",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".html": "html",
    ".css": "css",
    ".csv": "csv",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".php": "php",
    ".scala": "scala",
    ".sc": "scala",
    ".dart": "dart",
    # devops / infrastructure
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".hcl": "hcl",
    ".tpl": "gotemplate",
    ".j2": "jinja2",
    ".jinja2": "jinja2",
    ".conf": "conf",
    ".cfg": "conf",
    ".ini": "ini",
    ".mk": "make",
}

FILENAME_LANG_MAP = {
    "Dockerfile": "dockerfile",
    "Containerfile": "dockerfile",
    "Makefile": "make",
    "GNUmakefile": "make",
    "Vagrantfile": "ruby",
}

KNOWN_FILENAMES = set(FILENAME_LANG_MAP.keys())

SHEBANG_PATTERNS = [
    (re.compile(r"python[0-9.]*"), "python"),
    (re.compile(r"node(js)?"), "javascript"),
    (re.compile(r"ruby"), "ruby"),
    (re.compile(r"bash|sh|zsh"), "shell"),
    (re.compile(r"perl"), "perl"),
]

READABLE_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".css",
    ".java",
    ".kt",
    ".kts",
    ".cs",
    ".fs",
    ".fsi",
    ".vb",
    ".swift",
    ".csproj",
    ".fsproj",
    ".vbproj",
    ".sln",
    ".xaml",
    ".go",
    ".rs",
    ".rb",
    ".sh",
    ".csv",
    ".sql",
    ".toml",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".php",
    ".scala",
    ".sc",
    ".dart",
    # devops / infrastructure
    ".tf",
    ".tfvars",
    ".hcl",
    ".tpl",
    ".j2",
    ".jinja2",
    ".conf",
    ".cfg",
    ".ini",
    ".mk",
}

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
    ".mempalace",
    ".ruff_cache",
    ".mypy_cache",
    ".pytest_cache",
    ".cache",
    ".tox",
    ".nox",
    ".vs",
    "obj",
    "vendor",
    ".idea",
    ".vscode",
    ".ipynb_checkpoints",
    ".eggs",
    "htmlcov",
    "target",
    ".terraform",
}

SKIP_FILENAMES = {
    "mempalace.yaml",
    "mempalace.yml",
    "mempal.yaml",
    "mempal.yml",
    ".gitignore",
    "package-lock.json",
}

MIN_CHUNK = 100  # chars — skip tiny fragments
TARGET_MIN = 400  # chars — merge threshold for small chunks
TARGET_MAX = 2500  # chars — ideal max for a logical unit
HARD_MAX = 4000  # chars — absolute max before forced split


def _detect_batch_size() -> int:
    """Return an appropriate batch size based on the available compute device.

    | Device            | Batch | Reason                                      |
    |-------------------|-------|---------------------------------------------|
    | CUDA              |   256 | GPU VRAM handles larger batches efficiently |
    | MPS (Apple Si)    |   256 | Unified memory, similar capacity to CUDA    |
    | CPU (>4 GB RAM)   |   128 | Proven default on MacBook                   |
    | CPU (<=4 GB RAM)  |    64 | Conservative for low-RAM devices            |

    Falls back to 128 on any detection failure.
    """
    try:
        import torch

        if torch.backends.mps.is_available():
            return 256
        if torch.cuda.is_available():
            return 256
        # CPU fallback — check available RAM via os.sysconf (no new dependency)
        try:
            mem_bytes = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            return 128 if mem_bytes / (1024**3) > 4 else 64
        except (AttributeError, ValueError, OSError):
            return 128
    except Exception:
        return 128


BATCH_SIZE = _detect_batch_size()


# =============================================================================
# IGNORE MATCHING
# =============================================================================


class GitignoreMatcher:
    """Lightweight matcher for one directory's .gitignore patterns."""

    def __init__(self, base_dir: Path, rules: list):
        self.base_dir = base_dir
        self.rules = rules

    @classmethod
    def from_dir(cls, dir_path: Path):
        gitignore_path = dir_path / ".gitignore"
        if not gitignore_path.is_file():
            return None

        try:
            lines = gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return None

        rules = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("\\#") or line.startswith("\\!"):
                line = line[1:]
            elif line.startswith("#"):
                continue

            negated = line.startswith("!")
            if negated:
                line = line[1:]

            anchored = line.startswith("/")
            if anchored:
                line = line.lstrip("/")

            dir_only = line.endswith("/")
            if dir_only:
                line = line.rstrip("/")

            if not line:
                continue

            rules.append(
                {
                    "pattern": line,
                    "anchored": anchored,
                    "dir_only": dir_only,
                    "negated": negated,
                }
            )

        if not rules:
            return None

        return cls(dir_path, rules)

    def matches(self, path: Path, is_dir: bool = None):
        try:
            relative = path.relative_to(self.base_dir).as_posix().strip("/")
        except ValueError:
            return None

        if not relative:
            return None

        if is_dir is None:
            is_dir = path.is_dir()

        ignored = None
        for rule in self.rules:
            if self._rule_matches(rule, relative, is_dir):
                ignored = not rule["negated"]
        return ignored

    def _rule_matches(self, rule: dict, relative: str, is_dir: bool) -> bool:
        pattern = rule["pattern"]
        parts = relative.split("/")
        pattern_parts = pattern.split("/")

        if rule["dir_only"]:
            target_parts = parts if is_dir else parts[:-1]
            if not target_parts:
                return False
            if rule["anchored"] or len(pattern_parts) > 1:
                return self._match_from_root(target_parts, pattern_parts)
            return any(fnmatch.fnmatch(part, pattern) for part in target_parts)

        if rule["anchored"] or len(pattern_parts) > 1:
            return self._match_from_root(parts, pattern_parts)

        return any(fnmatch.fnmatch(part, pattern) for part in parts)

    def _match_from_root(self, target_parts: list, pattern_parts: list) -> bool:
        def matches(path_index: int, pattern_index: int) -> bool:
            if pattern_index == len(pattern_parts):
                return True

            if path_index == len(target_parts):
                return all(part == "**" for part in pattern_parts[pattern_index:])

            pattern_part = pattern_parts[pattern_index]
            if pattern_part == "**":
                return matches(path_index, pattern_index + 1) or matches(
                    path_index + 1, pattern_index
                )

            if not fnmatch.fnmatch(target_parts[path_index], pattern_part):
                return False

            return matches(path_index + 1, pattern_index + 1)

        return matches(0, 0)


def load_gitignore_matcher(dir_path: Path, cache: dict):
    """Load and cache one directory's .gitignore matcher."""
    if dir_path not in cache:
        cache[dir_path] = GitignoreMatcher.from_dir(dir_path)
    return cache[dir_path]


def is_gitignored(path: Path, matchers: list, is_dir: bool = False) -> bool:
    """Apply active .gitignore matchers in ancestor order; last match wins."""
    ignored = False
    for matcher in matchers:
        decision = matcher.matches(path, is_dir=is_dir)
        if decision is not None:
            ignored = decision
    return ignored


_DOTNET_MARKERS = (
    "*.sln",
    "*.csproj",
    "*.fsproj",
    "*.vbproj",
    "*/*.csproj",
    "*/*.fsproj",
    "*/*.vbproj",
)


def _is_dotnet_project(project_path: Path) -> bool:
    """Return True if *project_path* looks like a .NET project.

    Checks for .sln at root level and .csproj/.fsproj/.vbproj at root or one
    level deep (the standard layout: Solution.sln at root, Project/Project.csproj
    in a subdirectory).  Uses early-exit to minimise filesystem round-trips.
    """
    return any(next(project_path.glob(pat), None) is not None for pat in _DOTNET_MARKERS)


def should_skip_dir(dirname: str) -> bool:
    """Skip known generated/cache directories before gitignore matching."""
    return dirname in SKIP_DIRS or dirname.endswith(".egg-info")


def normalize_include_paths(include_ignored: list) -> set:
    """Normalize comma-parsed include paths into project-relative POSIX strings."""
    normalized = set()
    for raw_path in include_ignored or []:
        candidate = str(raw_path).strip().strip("/")
        if candidate:
            normalized.add(Path(candidate).as_posix())
    return normalized


def is_exact_force_include(path: Path, project_path: Path, include_paths: set) -> bool:
    """Return True when a path exactly matches an explicit include override."""
    if not include_paths:
        return False

    try:
        relative = path.relative_to(project_path).as_posix().strip("/")
    except ValueError:
        return False

    return relative in include_paths


def is_force_included(path: Path, project_path: Path, include_paths: set) -> bool:
    """Return True when a path or one of its ancestors/descendants was explicitly included."""
    if not include_paths:
        return False

    try:
        relative = path.relative_to(project_path).as_posix().strip("/")
    except ValueError:
        return False

    if not relative:
        return False

    for include_path in include_paths:
        if relative == include_path:
            return True
        if relative.startswith(f"{include_path}/"):
            return True
        if include_path.startswith(f"{relative}/"):
            return True

    return False


# =============================================================================
# CONFIG
# =============================================================================


def load_config(project_dir: str) -> dict:
    """Load mempalace.yaml from project directory (falls back to mempal.yaml)."""
    import yaml

    config_path = Path(project_dir).expanduser().resolve() / "mempalace.yaml"
    if not config_path.exists():
        # Fallback to legacy name
        legacy_path = Path(project_dir).expanduser().resolve() / "mempal.yaml"
        if legacy_path.exists():
            config_path = legacy_path
        else:
            print(f"ERROR: No mempalace.yaml found in {project_dir}")
            print(f"Run: mempalace init {project_dir}")
            sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


# =============================================================================
# FILE ROUTING — which room does this file belong to?
# =============================================================================


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
    1. Folder path matches a room name
    2. Filename matches a room name or keyword
    3. Content keyword scoring
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
        for room in rooms:
            candidates = [room["name"].lower()] + [k.lower() for k in room.get("keywords", [])]
            if any(part == c or c in part or part in c for c in candidates):
                return room["name"]

    # Priority 2: filename matches room name
    for room in rooms:
        if room["name"].lower() in filename or filename in room["name"].lower():
            return room["name"]

    # Priority 3: keyword scoring from room keywords + name
    scores = defaultdict(int)
    for room in rooms:
        keywords = room.get("keywords", []) + [room["name"]]
        for kw in keywords:
            count = content_lower.count(kw.lower())
            scores[room["name"]] += count

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best

    return "general"


# =============================================================================
# CHUNKING — boundary regexes
# =============================================================================

# TypeScript / JavaScript structural boundaries
TS_BOUNDARY = re.compile(
    r"^(?:"
    r"export\s+(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|enum|const|let|var)\b"
    r"|(?:async\s+)?function\s+\w+"
    r"|class\s+\w+"
    r"|interface\s+\w+"
    r"|type\s+\w+\s*[=<]"
    r"|enum\s+\w+"
    r"|const\s+\w+\s*[:=]"
    r"|let\s+\w+\s*[:=]"
    r"|var\s+\w+\s*[:=]"
    r"|(?:describe|it|test|beforeEach|afterEach|beforeAll|afterAll)\s*\("
    r"|module\.exports"
    r"|exports\.\w+"
    r")",
    re.MULTILINE,
)

# Import block detection for TS/JS (group all imports together)
TS_IMPORT = re.compile(r"^(?:import\s|from\s|require\s*\()", re.MULTILINE)

# Python structural boundaries
PY_BOUNDARY = re.compile(
    r"^(?:"
    r"(?:async\s+)?def\s+\w+"
    r"|class\s+\w+"
    r"|@\w+"
    r")",
    re.MULTILINE,
)

# Go structural boundaries
GO_BOUNDARY = re.compile(
    r"^(?:"
    r"func\s+(?:\(.*?\)\s*)?\w+"
    r"|type\s+\w+"
    r"|var\s+\("
    r"|const\s+\("
    r")",
    re.MULTILINE,
)

# Rust structural boundaries
RUST_BOUNDARY = re.compile(
    r"^(?:"
    r"(?:pub(?:\(crate\))?\s+)?(?:async\s+)?fn\s+\w+"
    r"|(?:pub(?:\(crate\))?\s+)?(?:struct|enum|trait|impl|mod|type)\s+\w+"
    r"|#\["
    r")",
    re.MULTILINE,
)

# Java structural boundaries — matches against stripped lines (indented methods inside classes).
# Deliberately excludes bare `@\w+` to avoid spurious boundaries on annotations inside method
# bodies (e.g. @SuppressWarnings("unchecked") on a local variable).  Class-level annotations
# will appear in the preamble or be merged by adaptive_merge_split.
JAVA_BOUNDARY = re.compile(
    r"^(?:"
    r"(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*(?:class|interface|enum|record)\s+\w+"
    r"|(?:(?:public|protected)\s+)?@interface\s+\w+"
    r"|(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|transient|volatile)\s+)+(?:<[^>]+>\s+)?[\w<>\[\],? ]+(?:\[\])*\s+\w+\s*\("
    r")",
    re.MULTILINE,
)

# Kotlin structural boundaries — matches against stripped lines.
# Deliberately excludes `companion object` to avoid splitting enclosing class chunks.
# Properties (val/var) are also excluded — too noisy as boundaries.
KOTLIN_BOUNDARY = re.compile(
    r"^(?:"
    r"(?:(?:public|internal|protected|private|abstract|final|open|sealed|data|inner|value|annotation)\s+)*(?:class|interface|object)\s+\w+"
    r"|(?:(?:public|internal|protected|private)\s+)*enum\s+class\s+\w+"
    r"|(?:(?:public|internal|protected|private|abstract|open|final|override|inline|infix|operator|tailrec|suspend|external|expect|actual)\s+)*fun\s+"
    r"|(?:(?:public|internal|protected|private)\s+)*typealias\s+\w+"
    r")",
    re.MULTILINE,
)

# C# structural boundaries — matches against stripped lines (members are indented inside
# classes/namespaces). Requires at least one access modifier for methods/properties to avoid
# false positives on field declarations and local variables.
# Deliberately excludes: namespace declarations (wrap entire files), bare field declarations
# (too noisy), using directives (import-like), and #region/#endregion (IDE-only markers).
CSHARP_BOUNDARY = re.compile(
    r"^(?:"
    # Type declarations: class, struct, interface, record (covers partial, sealed, abstract, static)
    r"(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe)\s+)*"
    r"(?:class|struct|interface|record)\s+\w+"
    # Enum (bare enum, not 'enum class' like Kotlin)
    r"|(?:(?:public|private|protected|internal|new)\s+)*enum\s+\w+"
    # Events — event keyword is the unique anchor
    r"|(?:(?:public|private|protected|internal|static|virtual|override|sealed|new|abstract)\s+)*event\s+"
    # Methods and constructors: at least one modifier required; return type optional for constructors
    r"|(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe|async|partial)\s+)+"
    r"(?:[\w<>\[\],?\s]+\s+)?\w+\s*[\(<]"
    # Properties: at least one modifier, distinguished from fields by trailing { or =>
    r"|(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe)\s+)+"
    r"[\w<>\[\],? ]+(?:\[\])*\s+\w+\s*(?:\{|=>)"
    r")",
    re.MULTILINE,
)

# F# structural boundaries — top-level and member declarations.
# F# is whitespace-significant; top-level declarations start at column 0,
# members may be indented. All boundary types are matched.
FSHARP_BOUNDARY = re.compile(
    r"^(?:"
    r"module\s+\w+"
    r"|type\s+\w+"
    r"|let\s+(?:rec\s+)?(?:inline\s+)?\w+"
    r"|member\s+(?:\w+)\.\w+"
    r"|interface\s+\w+"
    r"|exception\s+\w+"
    r")",
    re.MULTILINE,
)

# VB.NET structural boundaries. VB.NET keywords are case-insensitive.
# Boundaries fire at the *opening* declaration; End Class / End Sub are not boundaries.
VBNET_BOUNDARY = re.compile(
    r"^(?:"
    # Class with optional access + type modifiers
    r"(?:(?:Public|Private|Protected\s+Friend|Private\s+Protected|Protected|Friend)\s+)?"
    r"(?:(?:MustInherit|NotInheritable|Partial)\s+)*"
    r"Class\s+\w+"
    # Module
    r"|(?:(?:Public|Friend)\s+)?Module\s+\w+"
    # Structure
    r"|(?:(?:Public|Private|Protected|Friend)\s+)?Structure\s+\w+"
    # Interface
    r"|(?:(?:Public|Private|Protected|Friend)\s+)?Interface\s+\w+"
    # Enum
    r"|(?:(?:Public|Private|Protected|Friend)\s+)?Enum\s+\w+"
    # Sub/Function with optional access + method modifiers
    r"|(?:(?:Public|Private|Protected\s+Friend|Private\s+Protected|Protected|Friend)\s+)?"
    r"(?:(?:Shared|Overridable|MustOverride|NotOverridable|Overrides|Overloads|Async|Static)\s+)*"
    r"(?:Sub|Function)\s+\w+"
    # Property
    r"|(?:(?:Public|Private|Protected|Friend)\s+)?(?:(?:Shared|ReadOnly|WriteOnly)\s+)?Property\s+\w+"
    r")",
    re.MULTILINE | re.IGNORECASE,
)

# Swift structural boundaries.
# Handles: class, struct, enum, protocol, actor, extension, func, typealias.
# Excludes var/let properties (too noisy, same rationale as Kotlin).
# Optional inline attribute prefix (e.g. `@propertyWrapper struct Clamped`) is
# handled by the `(?:@\w+...)*` arm so single-line annotation+declaration lines
# are correctly detected as boundaries.
SWIFT_BOUNDARY = re.compile(
    r"^(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:(?:public|private|fileprivate|internal|open|final|static|class|override|"
    r"mutating|nonmutating|nonisolated|indirect|async|distributed)\s+)*"
    r"(?:class|struct|enum|protocol|actor|extension|func|typealias)\s+",
    re.MULTILINE,
)

# Matches a line that consists only of Swift attribute annotations with no trailing
# declaration (e.g. `@objc`, `@MainActor`, `@available(iOS 14, *)`).
# Used to prevent greedy lookback from swallowing `@Published var x = 0` lines.
_SWIFT_PURE_ATTR = re.compile(r"^(?:@\w+(?:\([^)]*\))?\s*)+$")

# Markdown heading boundaries
HEADING_MD = re.compile(r"^#{1,4}\s+.+", re.MULTILINE)

# HCL / Terraform top-level block boundaries
HCL_BOUNDARY = re.compile(
    r"^(?:resource|data|module|variable|output|locals|provider|terraform|moved|import|check|removed)"
    r"(?=\s+[^=\s])",
    re.MULTILINE,
)

# PHP structural boundaries — classes, interfaces, traits, enums, namespaces, functions.
# Handles: abstract/final/readonly class modifiers (PHP 8.2 readonly class),
# PHP 8.1 enums with optional backing type, and access/static modifiers on methods.
PHP_BOUNDARY = re.compile(
    r"^(?:"
    r"(?:(?:abstract|final|readonly)\s+)*(?:class|interface|trait|enum)\s+\w+"
    r"|namespace\s+[\w\\]+"
    r"|(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+\w+"
    r")",
    re.MULTILINE,
)

# Scala structural boundaries (.scala and .sc files).
# Handles: class, case class, object, case object, trait, enum (Scala 3), def, type alias.
# Modifier chain tolerates: private[pkg], protected[pkg], sealed, abstract, final, override,
# implicit, lazy, inline (Scala 3), opaque (Scala 3), open (Scala 3).
# Annotations (@tailrec, @main, etc.) before the modifier chain are also covered.
# val/var/given are intentionally excluded (too noisy as top-level boundaries).
SCALA_BOUNDARY = re.compile(
    r"^(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:(?:private|protected|final|sealed|abstract|override|implicit|lazy|inline|opaque|open|case)"
    r"(?:\[[\w.]+\])?\s+)*"
    r"(?:case\s+class|case\s+object|class|object|trait|enum|def|type)\s+\w+",
    re.MULTILINE,
)

# Dart structural boundaries (.dart files).
# Pattern ordering (per plan §Pattern ordering):
#   1. extension type  (Dart 3.3+) — before plain extension
#   2. mixin class     — before class and mixin
#   3. mixin           — before class
#   4. enum / typedef  — disjoint keywords, order flexible
#   5. class           — with optional modifier chain (abstract/base/final/interface/sealed)
#   6. factory constructor — unique `factory` anchor, before generic function arm
#   7. typed top-level function — loosest pattern, last
DART_BOUNDARY = re.compile(
    r"^(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:"
    # extension type (Dart 3.3+) — MUST precede plain extension
    r"(?:(?:abstract|base|final|interface|sealed|mixin)\s+)*extension\s+type\s+\w+"
    r"|(?:(?:abstract|base|final|interface|sealed|mixin)\s+)*extension\s+\w+"
    # mixin class — before class and plain mixin
    r"|(?:(?:abstract|base|final|interface|sealed)\s+)*mixin\s+class\s+\w+"
    # plain mixin
    r"|(?:base\s+)?mixin\s+\w+"
    # enum
    r"|enum\s+\w+"
    # typedef
    r"|typedef\s+\w+"
    # class with optional modifier prefix chain
    r"|(?:(?:abstract|base|final|interface|sealed)\s+)*class\s+\w+"
    # factory constructor (const factory or plain factory); generic params before named suffix
    r"|(?:const\s+)?factory\s+\w+(?:<[^>]*>)?(?:\.\w+)?\s*\("
    # typed top-level function: optional modifiers, return type, name, (
    # Return type uses explicit lowercase primitives (int/double/bool/num/dynamic/never) rather
    # than a greedy [a-z]\w* to avoid matching Dart keywords like const/var/final/return.
    r"|(?:(?:external|static|abstract)\s+)*"
    r"(?:void|int|double|num|bool|dynamic|never"
    r"|Future(?:<[^>]*>)?|Stream(?:<[^>]*>)?|[A-Z]\w*(?:<[^>]*>)?)"
    r"\??\s+\w+\s*(?:<[^>]*>)?\s*\("
    r")",
    re.MULTILINE,
)


def get_boundary_pattern(language: str):
    """Return the appropriate structural boundary regex for a language string or file extension."""
    mapping = {
        "python": PY_BOUNDARY,
        ".py": PY_BOUNDARY,
        "typescript": TS_BOUNDARY,
        ".ts": TS_BOUNDARY,
        "tsx": TS_BOUNDARY,
        ".tsx": TS_BOUNDARY,
        "javascript": TS_BOUNDARY,
        ".js": TS_BOUNDARY,
        "jsx": TS_BOUNDARY,
        ".jsx": TS_BOUNDARY,
        "go": GO_BOUNDARY,
        ".go": GO_BOUNDARY,
        "rust": RUST_BOUNDARY,
        ".rs": RUST_BOUNDARY,
        "java": JAVA_BOUNDARY,
        ".java": JAVA_BOUNDARY,
        "kotlin": KOTLIN_BOUNDARY,
        ".kt": KOTLIN_BOUNDARY,
        ".kts": KOTLIN_BOUNDARY,
        "csharp": CSHARP_BOUNDARY,
        ".cs": CSHARP_BOUNDARY,
        "fsharp": FSHARP_BOUNDARY,
        ".fs": FSHARP_BOUNDARY,
        ".fsi": FSHARP_BOUNDARY,
        "vbnet": VBNET_BOUNDARY,
        ".vb": VBNET_BOUNDARY,
        "swift": SWIFT_BOUNDARY,
        ".swift": SWIFT_BOUNDARY,
        "terraform": HCL_BOUNDARY,
        ".tf": HCL_BOUNDARY,
        ".tfvars": HCL_BOUNDARY,
        "hcl": HCL_BOUNDARY,
        ".hcl": HCL_BOUNDARY,
        "php": PHP_BOUNDARY,
        ".php": PHP_BOUNDARY,
        "scala": SCALA_BOUNDARY,
        ".scala": SCALA_BOUNDARY,
        ".sc": SCALA_BOUNDARY,
        "dart": DART_BOUNDARY,
        ".dart": DART_BOUNDARY,
    }
    return mapping.get(language)


# =============================================================================
# LANGUAGE DETECTION
# =============================================================================


def _is_k8s_manifest(content: str) -> bool:
    """Return True if content looks like a Kubernetes manifest (has both apiVersion: and kind: lines)."""
    return bool(
        re.search(r"^apiVersion:\s", content, re.MULTILINE)
        and re.search(r"^kind:\s", content, re.MULTILINE)
    )


def detect_language(filepath: Path, content: str = "") -> str:
    """
    Detect the programming language for a file.

    Resolution order:
    1. File extension lookup via EXTENSION_LANG_MAP.
    2. Filename lookup via FILENAME_LANG_MAP (for extensionless files like Dockerfile, Makefile).
    3. Shebang inspection on the first line (for extensionless files).
    4. Content-based K8s detection: YAML files with apiVersion+kind become 'kubernetes'.
    5. Returns "unknown" if neither matches.
    """
    ext = filepath.suffix.lower()
    lang = None
    if ext in EXTENSION_LANG_MAP:
        lang = EXTENSION_LANG_MAP[ext]
    elif filepath.name in FILENAME_LANG_MAP:
        lang = FILENAME_LANG_MAP[filepath.name]
    else:
        # Shebang fallback — only for files with no recognized extension
        first_line = content.split("\n")[0] if content else ""
        if first_line.startswith("#!"):
            parts = first_line[2:].strip().split()
            if parts:
                basename = parts[0].split("/")[-1]
                if basename == "env" and len(parts) > 1:
                    interp = parts[1].split("/")[-1]
                else:
                    interp = basename
                for pattern, interp_lang in SHEBANG_PATTERNS:
                    if pattern.fullmatch(interp):
                        lang = interp_lang
                        break

    if lang is None:
        return "unknown"

    # Content-based K8s override: YAML files that are K8s manifests
    if lang == "yaml" and content and _is_k8s_manifest(content):
        return "kubernetes"

    return lang


# =============================================================================
# SYMBOL EXTRACTION
# =============================================================================

# Per-language extraction patterns: list of (compiled_regex, symbol_type).
# Each regex has exactly one capture group for the symbol name.
# Ordered most-specific first within each language.

_PY_EXTRACT = [
    (re.compile(r"^(?:async\s+)?def\s+(\w+)", re.MULTILINE), "function"),
    (re.compile(r"^class\s+(\w+)", re.MULTILINE), "class"),
]

_TS_EXTRACT = [
    (re.compile(r"^export\s+default\s+(?:async\s+)?function\s+(\w+)", re.MULTILINE), "function"),
    (re.compile(r"^export\s+default\s+class\s+(\w+)", re.MULTILINE), "class"),
    (re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE), "function"),
    (re.compile(r"^(?:export\s+)?class\s+(\w+)", re.MULTILINE), "class"),
    (re.compile(r"^(?:export\s+)?interface\s+(\w+)", re.MULTILINE), "interface"),
    (re.compile(r"^(?:export\s+)?type\s+(\w+)\s*[=<]", re.MULTILINE), "type"),
    (re.compile(r"^(?:export\s+)?enum\s+(\w+)", re.MULTILINE), "enum"),
    (re.compile(r"^(?:export\s+)?const\s+(\w+)\s*[:=]", re.MULTILINE), "const"),
]

_TS_IMPORT_RE = re.compile(r"^(?:import\s|from\s|require\s*\()", re.MULTILINE)

_GO_EXTRACT = [
    (re.compile(r"^func\s+\(.*?\)\s+(\w+)", re.MULTILINE), "method"),
    (re.compile(r"^func\s+(\w+)", re.MULTILINE), "function"),
    (re.compile(r"^type\s+(\w+)\s+struct", re.MULTILINE), "struct"),
    (re.compile(r"^type\s+(\w+)\s+interface", re.MULTILINE), "interface"),
    (re.compile(r"^type\s+(\w+)\b", re.MULTILINE), "type"),
]

_RUST_EXTRACT = [
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)", re.MULTILINE), "function"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?struct\s+(\w+)", re.MULTILINE), "struct"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?enum\s+(\w+)", re.MULTILINE), "enum"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?trait\s+(\w+)", re.MULTILINE), "trait"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?impl(?:\s*<[^>]*>)?\s+(\w+)", re.MULTILINE), "impl"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)", re.MULTILINE), "mod"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?type\s+(\w+)", re.MULTILINE), "type"),
]

_C_EXTRACT = [
    (re.compile(r"^struct\s+(\w+)", re.MULTILINE), "struct"),
    (re.compile(r"^enum\s+(\w+)", re.MULTILINE), "enum"),
    # heuristic: word chars, optional *, then name( — matches most top-level C defs
    # [\s*]+ allows pointer return types like `char *func()` with no space before name
    (re.compile(r"^[\w][\w\s*]+[\s*]+(\w+)\s*\([^;]*\)\s*\{", re.MULTILINE), "function"),
]

_CPP_EXTRACT = [
    (re.compile(r"^class\s+(\w+)", re.MULTILINE), "class"),
    (re.compile(r"^struct\s+(\w+)", re.MULTILINE), "struct"),
    (re.compile(r"^enum\s+(?:class\s+)?(\w+)", re.MULTILINE), "enum"),
    # [\s*]+ allows pointer return types like `std::string *getName()`
    (re.compile(r"^[\w][\w\s*:<>]+[\s*]+(\w+)\s*\([^;]*\)\s*\{", re.MULTILINE), "function"),
]

_JAVA_EXTRACT = [
    # @interface must precede class/interface checks (annotation type declaration)
    (re.compile(r"^(?:(?:public|protected)\s+)?@interface\s+(\w+)", re.MULTILINE), "annotation"),
    # record before class (Java 16+; record Foo(...) doesn't start with 'class')
    (
        re.compile(
            r"^(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*record\s+(\w+)",
            re.MULTILINE,
        ),
        "record",
    ),
    (
        re.compile(
            r"^(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*interface\s+(\w+)",
            re.MULTILINE,
        ),
        "interface",
    ),
    (
        re.compile(
            r"^(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    (
        re.compile(
            r"^(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # method: modifiers are optional so package-private methods are extracted.
    # Statement keywords are excluded because the zero-modifier path can otherwise
    # resemble return/call statements inside a chunk.
    (
        re.compile(
            r"^(?!(?:return|if|for|while|switch|catch|throw|new|else|do|try|case|assert|break|continue)\b)(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|transient|volatile)\s+)*(?:<[^>]+>\s+)?[\w<>\[\],? ]+(?:\[\])*\s+(\w+)\s*\(",
            re.MULTILINE,
        ),
        "method",
    ),
]

_KOTLIN_EXTRACT = [
    # Most-specific compound keywords first — must precede plain `class`/`interface`/`object`.
    (re.compile(r"data\s+class\s+(\w+)", re.MULTILINE), "data_class"),
    (re.compile(r"sealed\s+class\s+(\w+)", re.MULTILINE), "sealed_class"),
    (re.compile(r"sealed\s+interface\s+(\w+)", re.MULTILINE), "sealed_interface"),
    # enum class (Kotlin uses `enum class`, not bare `enum`)
    (re.compile(r"enum\s+class\s+(\w+)", re.MULTILINE), "enum"),
    # interface/class before companion_object — companion objects appear *inside* class chunks,
    # so checking class/interface first avoids misclassifying an enclosing class as companion_object.
    (
        re.compile(
            r"^(?:(?:public|internal|protected|private|abstract|open|final|override|inline|infix|operator|tailrec|suspend|external|expect|actual)\s+)*interface\s+(\w+)",
            re.MULTILINE,
        ),
        "interface",
    ),
    (
        re.compile(
            r"^(?:(?:public|internal|protected|private|abstract|open|final|override|inline|infix|operator|tailrec|suspend|external|expect|actual|inner|value|annotation)\s+)*class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # companion object — capture optional name (unnamed companions return "")
    (re.compile(r"companion\s+object\s*(\w*)", re.MULTILINE), "companion_object"),
    # standalone object declarations — after companion_object to avoid partial match on "object Foo" inside "companion object Foo"
    (re.compile(r"object\s+(\w+)", re.MULTILINE), "object"),
    # fun — optional type params (e.g. `fun <T> identity(…)`) and optional receiver type
    # (e.g. `fun String.isEmpty()` → `isEmpty`, `fun <T> List<T>.map()` → `map`).
    # Uses (?:[^<>]|<[^<>]*>)* instead of [^>]+ to handle depth-2 generic nesting, e.g.
    # `fun <T : Comparable<T>> …` and `fun Map<String, List<Int>>.flatten()`.
    (
        re.compile(
            r"^(?:(?:public|internal|protected|private|abstract|open|final|override|inline|infix|operator|tailrec|suspend|external|expect|actual)\s+)*fun\s+(?:<(?:[^<>]|<[^<>]*>)*>\s+)?(?:\w+(?:<(?:[^<>]|<[^<>]*>)*>)?\.)?(\w+)",
            re.MULTILINE,
        ),
        "function",
    ),
    (re.compile(r"typealias\s+(\w+)", re.MULTILINE), "typealias"),
]

_CSHARP_EXTRACT = [
    # record struct — most specific; must precede struct and bare record.
    # ^\s* + modifiers anchors to line start so "record" in comments/strings is never matched.
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe|readonly)\s+)*"
            r"record\s+struct\s+(\w+)",
            re.MULTILINE,
        ),
        "record",
    ),
    # record class — must precede class and bare record
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe)\s+)*"
            r"record\s+class\s+(\w+)",
            re.MULTILINE,
        ),
        "record",
    ),
    # bare record Foo (implicitly a record class)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe)\s+)*"
            r"record\s+(\w+)",
            re.MULTILINE,
        ),
        "record",
    ),
    # enum — before class/struct; ^\s* handles members indented inside namespace blocks
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|new)\s+)*enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    # struct — before class (more specific keyword)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|new|readonly|unsafe)\s+)*struct\s+(\w+)",
            re.MULTILINE,
        ),
        "struct",
    ),
    # interface — before class
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|new)\s+)*interface\s+(\w+)",
            re.MULTILINE,
        ),
        "interface",
    ),
    # class (covers sealed, abstract, static, partial, etc.)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe)\s+)*"
            r"class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # event — before methods; event keyword is unique anchor
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|sealed|new|abstract)\s+)*"
            r"event\s+[\w<>\[\],? ]+\s+(\w+)",
            re.MULTILINE,
        ),
        "event",
    ),
    # property: at least one modifier, anchored by trailing { or =>
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe)\s+)+"
            r"[\w<>\[\],? ]+(?:\[\])*\s+(\w+)\s*(?:\{|=>)",
            re.MULTILINE,
        ),
        "property",
    ),
    # method/constructor: at least one modifier; return type optional for constructors
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe|async|partial)\s+)+"
            r"(?:[\w<>\[\],? ]+\s+)?(\w+)\s*[\(<]",
            re.MULTILINE,
        ),
        "method",
    ),
]

_FSHARP_EXTRACT = [
    # Discriminated union: type Foo = | ... or type Foo =\n    | ...
    # Most specific — must precede record (type = {) and type catch-all.
    (re.compile(r"^type\s+(\w+)\s*=\s*(?:\||\n\s*\|)", re.MULTILINE), "union"),
    # Record: type Foo = {
    (re.compile(r"^type\s+(\w+)\s*=\s*\{", re.MULTILINE), "record"),
    # Interface with [<Interface>] attribute on preceding line
    (
        re.compile(r"\[<Interface>\][^\n]*\n\s*type\s+(\w+)", re.MULTILINE | re.IGNORECASE),
        "interface",
    ),
    # Interface: type Foo = interface
    (re.compile(r"^type\s+(\w+)\s*=\s*interface", re.MULTILINE | re.IGNORECASE), "interface"),
    # Module
    (re.compile(r"^module\s+(\w+)", re.MULTILINE), "module"),
    # Exception
    (re.compile(r"^exception\s+(\w+)", re.MULTILINE), "exception"),
    # Type (catch-all: class, struct, abbreviation, etc.) — after all specific type patterns
    (re.compile(r"^type\s+(\w+)", re.MULTILINE), "type"),
    # Member function (indented: member this.Foo or member x.Foo)
    (re.compile(r"^\s*member\s+(?:\w+)\.(\w+)", re.MULTILINE), "method"),
    # Top-level let binding (function or value)
    (re.compile(r"^let\s+(?:rec\s+)?(?:inline\s+)?(\w+)", re.MULTILINE), "function"),
]

_VBNET_EXTRACT = [
    # Enum — before structure/class to avoid false matches on e.g. `Class EnumHelper`
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:Shared|Shadows|Partial)\s+)*Enum\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "enum",
    ),
    # Structure — before class
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:Partial|Shadows)\s+)*Structure\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "struct",
    ),
    # Interface — before class
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:Partial|Shadows)\s+)*Interface\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "interface",
    ),
    # Module — limited access (Public or Friend only)
    (
        re.compile(
            r"^\s*(?:(?:Public|Friend)\s+)?Module\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "module",
    ),
    # Class
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:MustInherit|NotInheritable|Partial|Shadows)\s+)*Class\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "class",
    ),
    # Property — before Sub/Function
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:Shared|Default|ReadOnly|WriteOnly|Shadows|Overridable|NotOverridable|Overrides|Overloads)\s+)*"
            r"Property\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "property",
    ),
    # Sub/Function
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:Shared|Overridable|MustOverride|NotOverridable|Overrides|Overloads|Async|Static|Default|Shadows)\s+)*"
            r"(?:Sub|Function)\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "method",
    ),
]

_SWIFT_EXTRACT = [
    # extension — capture type name; `where` constraints and generics are ignored.
    # Must precede class/struct to avoid matching `extension` inside class modifiers.
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|open|final)\s+)*"
            r"extension\s+(\w+)",
            re.MULTILINE,
        ),
        "extension",
    ),
    # actor — first-class concurrency primitive (Swift 5.5+)
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|open|final|distributed)\s+)*"
            r"actor\s+(\w+)",
            re.MULTILINE,
        ),
        "actor",
    ),
    # protocol — before class (both are nominal types)
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal)\s+)*"
            r"protocol\s+(\w+)",
            re.MULTILINE,
        ),
        "protocol",
    ),
    # enum — before struct/class (avoids swallowing `indirect` prefix)
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|indirect)\s+)*"
            r"enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    # struct
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|final)\s+)*"
            r"struct\s+(\w+)",
            re.MULTILINE,
        ),
        "struct",
    ),
    # class — covers `final class`, `open class`, bare `class`, etc.
    # Negative lookahead prevents matching `class func` or `class var` where `class`
    # acts as a declaration modifier rather than introducing a type declaration.
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|open|final)\s+)*"
            r"class\s+(?!(?:func|var|let|struct|enum|protocol|actor|extension|typealias)\b)(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # func — optional modifiers including `class func`, `static func`, `async func`.
    # Generic type params appear AFTER the name in Swift (`func foo<T>(...)`), so no
    # pre-name generic arm is needed; `(\w+)` captures the name directly after `func `.
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|open|final|static|class|override|"
            r"mutating|nonmutating|nonisolated|async)\s+)*"
            r"func\s+(\w+)",
            re.MULTILINE,
        ),
        "function",
    ),
    # typealias
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal)\s+)*"
            r"typealias\s+(\w+)",
            re.MULTILINE,
        ),
        "typealias",
    ),
]

_XAML_EXTRACT = [
    # Extract view name from root element's x:Class attribute (fully-qualified → short name).
    # Only the first chunk (root element) will match; subsequent chunks get ("", "").
    (re.compile(r'x:Class="(?:[\w.]+\.)?(\w+)"'), "view"),
]

# PHP extraction patterns.
# Order matters: interface → trait → enum → class → function → namespace (last).
# namespace uses [\w\\]+ to capture qualified names like App\Http\Controllers.
# abstract/final/readonly are valid class/interface/trait/enum modifiers.
# namespace is last so that when a small namespace chunk merges with a class chunk,
# the class/interface/trait/enum takes priority as the primary symbol.
# A pure namespace-only chunk still extracts as 'namespace' because no other pattern matches.
_PHP_EXTRACT = [
    # interface — before class (both are type declarations; interface is more specific)
    (
        re.compile(
            r"^(?:(?:abstract|final|readonly)\s+)*interface\s+(\w+)",
            re.MULTILINE,
        ),
        "interface",
    ),
    # trait — before class
    (
        re.compile(
            r"^(?:(?:abstract|final|readonly)\s+)*trait\s+(\w+)",
            re.MULTILINE,
        ),
        "trait",
    ),
    # enum (PHP 8.1+) — optional backing type (`: string`, `: int`) is ignored
    (
        re.compile(
            r"^(?:(?:abstract|final|readonly)\s+)*enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    # class — covers abstract class, final class, readonly class (PHP 8.2+)
    (
        re.compile(
            r"^(?:(?:abstract|final|readonly)\s+)*class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # function — standalone functions and methods (access/static modifiers optional)
    (
        re.compile(
            r"^(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+(\w+)",
            re.MULTILINE,
        ),
        "function",
    ),
    # namespace — last; only extracted when no type declaration is present in the chunk.
    # Uses [\w\\]+ to capture fully-qualified names like App\Http\Controllers.
    (re.compile(r"^namespace\s+([\w\\]+)", re.MULTILINE), "namespace"),
]

# Scala extraction patterns (.scala and .sc files).
# Order is strict: case_class before class, case_object before object (plan §Pattern ordering).
# type alias requires a following `=` so type params in generic signatures are never matched.
_SCALA_MODIFIERS = (
    r"(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:(?:private|protected|final|sealed|abstract|override|implicit|lazy|inline|opaque|open)"
    r"(?:\[[\w.]+\])?\s+)*"
)

_SCALA_EXTRACT = [
    # case class — before class (most specific; avoids class swallowing the case form)
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"case\s+class\s+(\w+)",
            re.MULTILINE,
        ),
        "case_class",
    ),
    # case object — before object
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"case\s+object\s+(\w+)",
            re.MULTILINE,
        ),
        "case_object",
    ),
    # trait
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"trait\s+(\w+)",
            re.MULTILINE,
        ),
        "trait",
    ),
    # object — standalone singleton object declarations
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"object\s+(\w+)",
            re.MULTILINE,
        ),
        "object",
    ),
    # class — covers implicit class, sealed abstract class, open class, etc.
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # enum (Scala 3)
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    # def — covers implicit def, override def, inline def, etc.
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"def\s+(\w+)",
            re.MULTILINE,
        ),
        "function",
    ),
    # type alias — the `[^=\n]*=` suffix handles type params of arbitrary nesting depth while
    # requiring an `=` so that abstract type members (type T <: Bound) are not matched.
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"type\s+(\w+)[^=\n]*=",
            re.MULTILINE,
        ),
        "type",
    ),
]

# Dart extraction patterns (.dart files).
# Order is strict (per plan §Pattern ordering):
#   1. extension type — before extension (Dart 3.3+; zero-cost wrapper distinct from extension)
#   2. mixin class    — before class and mixin (mixin here is a modifier on class)
#   3. mixin          — before class
#   4. enum / typedef — disjoint keywords
#   5. class          — with optional Dart 3 modifier chain
#   6. factory constructor — unique `factory` anchor keyword
#   7. typed top-level function — loosest pattern, last
_DART_MODIFIERS = r"(?:@\w+(?:\([^)]*\))?\s+)*"
_DART_CLASS_MOD = r"(?:(?:abstract|base|final|interface|sealed|mixin)\s+)*"

_DART_EXTRACT = [
    # extension type (Dart 3.3+) — distinct from plain extension
    (
        re.compile(
            r"^" + _DART_MODIFIERS + _DART_CLASS_MOD + r"extension\s+type\s+(\w+)",
            re.MULTILINE,
        ),
        "extension_type",
    ),
    # plain extension — named extension on a type
    (
        re.compile(
            r"^" + _DART_MODIFIERS + _DART_CLASS_MOD + r"extension\s+(\w+)\s+on\b",
            re.MULTILINE,
        ),
        "extension",
    ),
    # mixin class — before class and plain mixin (mixin is a class modifier here)
    (
        re.compile(
            r"^"
            + _DART_MODIFIERS
            + r"(?:(?:abstract|base|final|interface|sealed)\s+)*mixin\s+class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # plain mixin (standalone mixin declaration)
    (
        re.compile(
            r"^" + _DART_MODIFIERS + r"(?:base\s+)?mixin\s+(\w+)\b",
            re.MULTILINE,
        ),
        "mixin",
    ),
    # enum
    (
        re.compile(
            r"^" + _DART_MODIFIERS + r"enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    # typedef — emits symbol_type='type' (consistent with Scala/Swift typealias)
    (
        re.compile(
            r"^typedef\s+(\w+)",
            re.MULTILINE,
        ),
        "type",
    ),
    # class with optional Dart 3 modifier chain
    (
        re.compile(
            r"^" + _DART_MODIFIERS + _DART_CLASS_MOD + r"class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # factory constructor — const or plain factory; captures ClassName or ClassName.named
    (
        re.compile(
            r"^\s*(?:const\s+)?factory\s+(\w+(?:\.\w+)?)\s*[(<]",
            re.MULTILINE,
        ),
        "constructor",
    ),
    # typed top-level function — requires explicit return type; uses explicit lowercase primitives
    # (int/double/bool/num/dynamic/never) to avoid matching Dart keywords (const/var/final/return)
    # as false-positive return types.
    (
        re.compile(
            r"^(?:(?:external|static|abstract)\s+)*"
            r"(?:void|int|double|num|bool|dynamic|never"
            r"|Future(?:<[^>]*>)?|Stream(?:<[^>]*>)?|[A-Z]\w*(?:<[^>]*>)?)"
            r"\??\s+(\w+)\s*(?:<[^>]*>)?\s*\(",
            re.MULTILINE,
        ),
        "function",
    ),
]

_LANG_EXTRACT_MAP = {
    "python": _PY_EXTRACT,
    "typescript": _TS_EXTRACT,
    "javascript": _TS_EXTRACT,
    "tsx": _TS_EXTRACT,
    "jsx": _TS_EXTRACT,
    "go": _GO_EXTRACT,
    "rust": _RUST_EXTRACT,
    "c": _C_EXTRACT,
    "cpp": _CPP_EXTRACT,
    "java": _JAVA_EXTRACT,
    "kotlin": _KOTLIN_EXTRACT,
    "csharp": _CSHARP_EXTRACT,
    "fsharp": _FSHARP_EXTRACT,
    "vbnet": _VBNET_EXTRACT,
    "swift": _SWIFT_EXTRACT,
    "xaml": _XAML_EXTRACT,
    "php": _PHP_EXTRACT,
    "scala": _SCALA_EXTRACT,
    "dart": _DART_EXTRACT,
}


def _extract_k8s_symbol(content: str) -> tuple:
    """Extract kind and metadata.name from a single K8s manifest document."""
    kind_m = re.search(r"^kind:\s*(\w+)", content, re.MULTILINE)
    if not kind_m:
        return ("", "")
    kind = kind_m.group(1)
    name_m = re.search(r"^\s{2}name:\s*(\S+)", content, re.MULTILINE)
    if name_m:
        return (f"{kind}/{name_m.group(1)}", kind.lower())
    return (kind, kind.lower())


def extract_symbol(content: str, language: str) -> tuple:
    """
    Extract the primary symbol defined in a code chunk.
    Returns (symbol_name, symbol_type) or ("", "") if none found.
    Non-code languages (markdown, text, json, yaml, unknown, etc.) return ("", "").
    TS/JS import-only chunks return ("", "import").
    """
    if language == "kubernetes":
        return _extract_k8s_symbol(content)

    patterns = _LANG_EXTRACT_MAP.get(language)
    if patterns is None:
        return ("", "")

    # TS/JS: detect import-only chunks (first non-empty line starts with an import keyword)
    is_import_chunk = False
    if language in ("typescript", "javascript", "tsx", "jsx"):
        first_non_empty = next((line for line in content.splitlines() if line.strip()), "")
        is_import_chunk = bool(_TS_IMPORT_RE.match(first_non_empty.strip()))

    for pattern, sym_type in patterns:
        m = re.search(pattern, content)
        if m:
            return (m.group(1), sym_type)

    return ("", "import") if is_import_chunk else ("", "")


# =============================================================================
# CHUNKING — strategies
# =============================================================================


def _chunk_k8s_manifest(content: str, source_file: str) -> list:
    """Split a K8s YAML file on --- document separators, one chunk per resource."""
    raw_docs = re.split(r"(?:^|\n)---\s*(?:\n|$)", content)
    all_chunks = []
    for doc in raw_docs:
        doc = doc.strip()
        if len(doc) < MIN_CHUNK:
            continue
        all_chunks.extend(adaptive_merge_split([doc], source_file))
    # Re-index chunk_index across all documents
    return [{"content": c["content"], "chunk_index": i} for i, c in enumerate(all_chunks)]


def chunk_file(content: str, ext: str, source_file: str, language: str = None) -> list:
    """Dispatcher — route to the right chunking strategy based on language."""
    if language is None:
        language = EXTENSION_LANG_MAP.get(ext, "unknown")

    if language in (
        "python",
        "typescript",
        "javascript",
        "tsx",
        "jsx",
        "go",
        "rust",
        "java",
        "kotlin",
        "csharp",
        "fsharp",
        "vbnet",
        "swift",
        "php",
        "scala",
        "dart",
    ):
        return chunk_code(content, language, source_file)
    elif language in ("terraform", "hcl"):
        return chunk_code(content, language, source_file)
    elif language in ("markdown", "text"):
        return chunk_prose(content, source_file)
    elif language == "kubernetes":
        return _chunk_k8s_manifest(content, source_file)
    else:
        return chunk_adaptive_lines(content, source_file)


def _chunk_python_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware Python chunker using tree-sitter.

    Extracts function_definition, class_definition, and decorated_definition
    nodes as chunk boundaries. Attaches immediately adjacent leading comment
    siblings (no blank-line gap) to their definition. Feeds raw text chunks
    through adaptive_merge_split() and tags each result with
    chunker_strategy='treesitter_v1'.

    Falls back to chunk_adaptive_lines() when no definition nodes are found
    (e.g. plain-assignment modules).
    """
    DEFINITION_TYPES = frozenset(
        {"function_definition", "class_definition", "decorated_definition"}
    )

    source_bytes = content.encode("utf-8")
    tree = parser.parse(source_bytes)
    children = tree.root_node.children

    # Build boundary_indices: for each definition node, track the start child
    # index after pulling in any immediately preceding comment siblings.
    boundary_indices: list = []
    for i, child in enumerate(children):
        if child.type in DEFINITION_TYPES:
            start_i = i
            j = i - 1
            while j >= 0:
                prev = children[j]
                if prev.type == "comment":
                    # No blank line between this comment and the node after it?
                    gap = source_bytes[prev.end_byte : children[j + 1].start_byte]
                    if b"\n\n" in gap:
                        break
                    start_i = j
                    j -= 1
                else:
                    break
            boundary_indices.append(start_i)

    if not boundary_indices:
        # No top-level definitions found (e.g. plain-assignment module).
        # Tag explicitly so _collect_specs_for_file doesn't mislabel as
        # regex_structural_v1 — the regex structural path was never executed.
        fallback = chunk_adaptive_lines(content, source_file)
        for chunk in fallback:
            chunk["chunker_strategy"] = "treesitter_adaptive_v1"
        return fallback

    raw_chunks: list = []

    # Preamble: all content before the first boundary (imports, module docstring, etc.)
    first_start_byte = children[boundary_indices[0]].start_byte
    if first_start_byte > 0:
        preamble = source_bytes[:first_start_byte].decode("utf-8").strip()
        if preamble:
            raw_chunks.append(preamble)

    # Each definition chunk: from its start_byte to the next boundary's start_byte
    for k, start_child_idx in enumerate(boundary_indices):
        start_byte = children[start_child_idx].start_byte
        end_byte = (
            children[boundary_indices[k + 1]].start_byte
            if k + 1 < len(boundary_indices)
            else len(source_bytes)
        )
        text = source_bytes[start_byte:end_byte].decode("utf-8").strip()
        if text:
            raw_chunks.append(text)

    merged = adaptive_merge_split(raw_chunks, source_file)
    for chunk in merged:
        chunk["chunker_strategy"] = "treesitter_v1"
    return merged


def _chunk_typescript_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware TypeScript/JavaScript/TSX/JSX chunker using tree-sitter.

    Extracts top-level export_statement, function_declaration, class_declaration,
    interface_declaration, type_alias_declaration, enum_declaration,
    lexical_declaration, and expression_statement nodes as chunk boundaries.
    Leading import_statement nodes are collected into a preamble chunk. Attaches
    immediately adjacent leading comment siblings (no blank-line gap) to their
    definition. Feeds raw text chunks through adaptive_merge_split() and tags
    each result with chunker_strategy='treesitter_v1'.

    Falls back to chunk_adaptive_lines() when no definition nodes are found
    (e.g. barrel files that only re-export or pure-import files).
    """
    DEFINITION_TYPES = frozenset(
        {
            "export_statement",
            "function_declaration",
            "class_declaration",
            "interface_declaration",
            "type_alias_declaration",
            "enum_declaration",
            "lexical_declaration",
            "expression_statement",
        }
    )

    source_bytes = content.encode("utf-8")
    tree = parser.parse(source_bytes)
    children = tree.root_node.children

    # Build boundary_indices: for each definition node, track the start child
    # index after pulling in any immediately preceding comment siblings.
    boundary_indices: list = []
    for i, child in enumerate(children):
        if child.type in DEFINITION_TYPES:
            start_i = i
            j = i - 1
            while j >= 0:
                prev = children[j]
                if prev.type == "comment":
                    # No blank line between this comment and the node after it?
                    gap = source_bytes[prev.end_byte : children[j + 1].start_byte]
                    if b"\n\n" in gap:
                        break
                    start_i = j
                    j -= 1
                else:
                    break
            boundary_indices.append(start_i)

    if not boundary_indices:
        # No top-level definitions found (e.g. barrel/config file with only imports).
        fallback = chunk_adaptive_lines(content, source_file)
        for chunk in fallback:
            chunk["chunker_strategy"] = "treesitter_adaptive_v1"
        return fallback

    raw_chunks: list = []

    # Preamble: all content before the first boundary (imports, license header, etc.)
    first_start_byte = children[boundary_indices[0]].start_byte
    if first_start_byte > 0:
        preamble = source_bytes[:first_start_byte].decode("utf-8").strip()
        if preamble:
            raw_chunks.append(preamble)

    # Each definition chunk: from its start_byte to the next boundary's start_byte
    for k, start_child_idx in enumerate(boundary_indices):
        start_byte = children[start_child_idx].start_byte
        end_byte = (
            children[boundary_indices[k + 1]].start_byte
            if k + 1 < len(boundary_indices)
            else len(source_bytes)
        )
        text = source_bytes[start_byte:end_byte].decode("utf-8").strip()
        if text:
            raw_chunks.append(text)

    merged = adaptive_merge_split(raw_chunks, source_file)
    for chunk in merged:
        chunk["chunker_strategy"] = "treesitter_v1"
    return merged


def _chunk_go_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware Go chunker using tree-sitter.

    Extracts function_declaration, method_declaration, type_declaration,
    const_declaration, and var_declaration nodes as chunk boundaries.
    Attaches immediately adjacent leading comment siblings (no blank-line
    gap) to their declaration. Feeds raw text chunks through
    adaptive_merge_split() and tags each result with
    chunker_strategy='treesitter_v1'.

    Falls back to chunk_adaptive_lines() when no declaration nodes are
    found (e.g. package-only files).
    """
    DEFINITION_TYPES = frozenset(
        {
            "function_declaration",
            "method_declaration",
            "type_declaration",
            "const_declaration",
            "var_declaration",
        }
    )

    source_bytes = content.encode("utf-8")
    tree = parser.parse(source_bytes)
    children = tree.root_node.children

    # Build boundary_indices: for each declaration node, track the start child
    # index after pulling in any immediately preceding comment siblings.
    boundary_indices: list = []
    for i, child in enumerate(children):
        if child.type in DEFINITION_TYPES:
            start_i = i
            j = i - 1
            while j >= 0:
                prev = children[j]
                if prev.type == "comment":
                    # No blank line between this comment and the node after it?
                    gap = source_bytes[prev.end_byte : children[j + 1].start_byte]
                    if b"\n\n" in gap:
                        break
                    start_i = j
                    j -= 1
                else:
                    break
            boundary_indices.append(start_i)

    if not boundary_indices:
        fallback = chunk_adaptive_lines(content, source_file)
        for chunk in fallback:
            chunk["chunker_strategy"] = "treesitter_adaptive_v1"
        return fallback

    raw_chunks: list = []

    # Preamble: all content before the first boundary (package clause, imports, etc.)
    first_start_byte = children[boundary_indices[0]].start_byte
    if first_start_byte > 0:
        preamble = source_bytes[:first_start_byte].decode("utf-8").strip()
        if preamble:
            raw_chunks.append(preamble)

    # Each declaration chunk: from its start_byte to the next boundary's start_byte
    for k, start_child_idx in enumerate(boundary_indices):
        start_byte = children[start_child_idx].start_byte
        end_byte = (
            children[boundary_indices[k + 1]].start_byte
            if k + 1 < len(boundary_indices)
            else len(source_bytes)
        )
        text = source_bytes[start_byte:end_byte].decode("utf-8").strip()
        if text:
            raw_chunks.append(text)

    merged = adaptive_merge_split(raw_chunks, source_file)
    for chunk in merged:
        chunk["chunker_strategy"] = "treesitter_v1"
    return merged


def _chunk_rust_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware Rust chunker using tree-sitter.

    Extracts function_item, struct_item, enum_item, trait_item, impl_item,
    mod_item, type_item, const_item, and static_item nodes as chunk boundaries. Attaches immediately
    adjacent leading attribute_item (#[...]) and comment siblings (no
    blank-line gap) to their item — critical because tree-sitter-rust keeps
    #[derive(...)] as a separate attribute_item sibling rather than wrapping
    it with the item. Feeds raw text chunks through adaptive_merge_split()
    and tags each result with chunker_strategy='treesitter_v1'.

    Falls back to chunk_adaptive_lines() when no item nodes are found.
    """
    DEFINITION_TYPES = frozenset(
        {
            "function_item",
            "struct_item",
            "enum_item",
            "trait_item",
            "impl_item",
            "mod_item",
            "type_item",
            "const_item",
            "static_item",
        }
    )
    # Nodes that can precede a definition and should be attached to it
    LEADING_TYPES = frozenset({"attribute_item", "line_comment", "block_comment"})

    source_bytes = content.encode("utf-8")
    tree = parser.parse(source_bytes)
    children = tree.root_node.children

    # Build boundary_indices: for each item node, track the start child
    # index after pulling in any immediately preceding attribute/comment siblings.
    boundary_indices: list = []
    for i, child in enumerate(children):
        if child.type in DEFINITION_TYPES:
            start_i = i
            j = i - 1
            while j >= 0:
                prev = children[j]
                if prev.type in LEADING_TYPES:
                    # No blank line between this node and the node after it?
                    gap = source_bytes[prev.end_byte : children[j + 1].start_byte]
                    if b"\n\n" in gap:
                        break
                    start_i = j
                    j -= 1
                else:
                    break
            boundary_indices.append(start_i)

    if not boundary_indices:
        fallback = chunk_adaptive_lines(content, source_file)
        for chunk in fallback:
            chunk["chunker_strategy"] = "treesitter_adaptive_v1"
        return fallback

    raw_chunks: list = []

    # Preamble: all content before the first boundary (use declarations, etc.)
    first_start_byte = children[boundary_indices[0]].start_byte
    if first_start_byte > 0:
        preamble = source_bytes[:first_start_byte].decode("utf-8").strip()
        if preamble:
            raw_chunks.append(preamble)

    # Each item chunk: from its start_byte to the next boundary's start_byte
    for k, start_child_idx in enumerate(boundary_indices):
        start_byte = children[start_child_idx].start_byte
        end_byte = (
            children[boundary_indices[k + 1]].start_byte
            if k + 1 < len(boundary_indices)
            else len(source_bytes)
        )
        text = source_bytes[start_byte:end_byte].decode("utf-8").strip()
        if text:
            raw_chunks.append(text)

    merged = adaptive_merge_split(raw_chunks, source_file)
    for chunk in merged:
        chunk["chunker_strategy"] = "treesitter_v1"
    return merged


def chunk_code(content: str, language: str, source_file: str) -> list:
    """
    Split code at structural boundaries (function/class/export declarations).
    Groups imports. Attaches leading comments immediately adjacent to declarations.
    Falls back to chunk_adaptive_lines() if no boundaries are detected.

    `language` accepts canonical language strings ("python", "typescript") or
    raw file extensions (".py", ".ts") for backward compatibility.

    When tree-sitter is installed and the language is Python, TypeScript, JavaScript,
    TSX, JSX, Go, or Rust, AST-based chunking is used. All other languages still
    use the regex path below.
    """
    canonical = EXTENSION_LANG_MAP.get(language, language)
    parser = get_parser(canonical)
    if parser is not None:
        if canonical == "python":
            return _chunk_python_treesitter(parser, content, source_file)
        if canonical in ("typescript", "javascript", "tsx", "jsx"):
            return _chunk_typescript_treesitter(parser, content, source_file)
        if canonical == "go":
            return _chunk_go_treesitter(parser, content, source_file)
        if canonical == "rust":
            return _chunk_rust_treesitter(parser, content, source_file)

    boundary = get_boundary_pattern(language)
    if not boundary:
        return chunk_adaptive_lines(content, source_file)

    is_ts_js = language in (
        "typescript",
        "javascript",
        "tsx",
        "jsx",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
    )

    lines = content.split("\n")
    boundaries = []
    in_import_block = False

    # C# attributes ([HttpGet], [Serializable], etc.) appear immediately before declarations
    # and must be kept in the same chunk. Extend the lookback prefix set for csharp so that
    # lines starting with '[' are treated like comment lines during the lookback scan.
    comment_prefixes = ("//", "/*", "*", "*/", "#", '"""', "'''", "/**")
    if canonical in ("csharp", "fsharp"):
        # C# uses [Attribute], F# uses [<Attribute>] — both start with '['.
        comment_prefixes = comment_prefixes + ("[",)
    if canonical == "swift":
        # Swift uses @Attribute decorators (e.g. @propertyWrapper, @MainActor) before
        # declarations. Extend the lookback so these lines attach to their declaration chunk.
        comment_prefixes = comment_prefixes + ("@",)
    if canonical == "php":
        # PHP 8.1+ uses #[Attribute] syntax immediately before declarations.
        # Extend the lookback so attribute lines attach to their declaration chunk.
        comment_prefixes = comment_prefixes + ("#[",)
    if canonical == "scala":
        # Scala uses @Annotation decorators (e.g. @tailrec, @main, @deprecated) before
        # declarations. Extend the lookback so these lines attach to their declaration chunk.
        comment_prefixes = comment_prefixes + ("@",)
    if canonical == "dart":
        # Dart uses @override, @deprecated, @immutable, @pragma annotations before
        # declarations. Extend the lookback so these lines attach to their declaration chunk.
        comment_prefixes = comment_prefixes + ("@",)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if in_import_block:
                in_import_block = False
            continue

        if TS_IMPORT.match(stripped) and is_ts_js:
            if not in_import_block:
                boundaries.append(("import", i))
                in_import_block = True
            continue
        in_import_block = False

        # For TS/JS, match against the original line so indented `const`/`let` inside
        # function bodies (e.g., `    const x = ...`) don't trigger false boundaries.
        # For Python/Go/Rust, match against the stripped line because methods are indented.
        match_target = line if is_ts_js else stripped
        if boundary.match(match_target):
            # Look back for leading comments immediately adjacent (no blank-line gap).
            comment_start = i
            j = i - 1
            while j >= 0:
                prev = lines[j].strip()
                if prev.startswith(comment_prefixes):
                    # Swift/Scala: reject mixed @Attribute+declaration lines
                    # (e.g. `@Published var count = 0`) — they belong to
                    # the enclosing type body, not to the following func.
                    # Only pure attribute-only lines (e.g. `@MainActor`,
                    # `@objc`, `@available(iOS 14, *)`) should attach.
                    if (
                        canonical in ("swift", "scala", "dart")
                        and prev.startswith("@")
                        and not _SWIFT_PURE_ATTR.match(prev)
                    ):
                        break
                    comment_start = j
                    j -= 1
                else:
                    break  # stop at blank lines or non-comment lines
            boundaries.append(("decl", comment_start))

    if not boundaries:
        return chunk_adaptive_lines(content, source_file)

    raw_chunks = []

    # Preamble before the first boundary (file header, license, etc.)
    if boundaries[0][1] > 0:
        preamble = "\n".join(lines[: boundaries[0][1]]).strip()
        if preamble:
            raw_chunks.append(preamble)

    for idx, (_kind, start) in enumerate(boundaries):
        end = boundaries[idx + 1][1] if idx + 1 < len(boundaries) else len(lines)
        text = "\n".join(lines[start:end]).strip()
        if text:
            raw_chunks.append(text)

    # adaptive_merge_split handles final MIN_CHUNK filtering and merging of small pieces.
    return adaptive_merge_split(raw_chunks, source_file)


def chunk_prose(content: str, source_file: str) -> list:
    """
    Split prose at markdown heading boundaries (#–####).
    Falls back to paragraph chunking if no headings are found.
    """
    lines = content.split("\n")
    heading_lines = [i for i, line in enumerate(lines) if HEADING_MD.match(line.strip())]

    if not heading_lines:
        # Paragraph fallback — let adaptive_merge_split handle MIN_CHUNK filtering.
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        return adaptive_merge_split(paragraphs, source_file) if paragraphs else []

    raw_chunks = []

    # Preamble before the first heading
    if heading_lines[0] > 0:
        preamble = "\n".join(lines[: heading_lines[0]]).strip()
        if preamble:
            raw_chunks.append(preamble)

    for idx, start in enumerate(heading_lines):
        end = heading_lines[idx + 1] if idx + 1 < len(heading_lines) else len(lines)
        section = "\n".join(lines[start:end]).strip()
        if section:
            raw_chunks.append(section)

    return adaptive_merge_split(raw_chunks, source_file)


def chunk_adaptive_lines(content: str, source_file: str) -> list:
    """
    Fallback for files without dedicated structural patterns.
    Split at blank lines with adaptive sizing.
    """
    blocks = re.split(r"\n\s*\n", content)
    raw = [b.strip() for b in blocks if len(b.strip()) >= MIN_CHUNK]
    if not raw:
        if len(content.strip()) >= MIN_CHUNK:
            return [{"content": content.strip(), "chunk_index": 0}]
        return []
    return adaptive_merge_split(raw, source_file)


def adaptive_merge_split(raw_chunks: list, source_file: str) -> list:
    """
    Post-process raw chunks:
    - Merge adjacent small chunks (< TARGET_MIN) up to TARGET_MAX.
    - Split oversized chunks (> HARD_MAX) at paragraph/line sub-boundaries.
    Returns list of {"content": str, "chunk_index": int}.
    """
    if not raw_chunks:
        return []

    result = []
    buffer = ""

    for chunk in raw_chunks:
        if len(chunk) > HARD_MAX:
            if buffer.strip():
                result.append(buffer.strip())
                buffer = ""
            result.extend(_split_oversized(chunk))
        elif len(buffer) + len(chunk) + 2 <= TARGET_MAX:
            buffer = f"{buffer}\n\n{chunk}" if buffer else chunk
        else:
            if buffer.strip():
                result.append(buffer.strip())
            buffer = chunk

    if buffer.strip():
        result.append(buffer.strip())

    filtered = [text for text in result if len(text) >= MIN_CHUNK]
    return [{"content": text, "chunk_index": i} for i, text in enumerate(filtered)]


def _split_oversized(text: str) -> list:
    """Split a chunk exceeding HARD_MAX at the best available sub-boundary."""
    # Try paragraph breaks first
    parts = re.split(r"\n\s*\n", text)
    if len(parts) > 1:
        merged = []
        buf = ""
        for part in parts:
            if len(buf) + len(part) + 2 <= TARGET_MAX:
                buf = f"{buf}\n\n{part}" if buf else part
            else:
                if buf.strip():
                    merged.append(buf.strip())
                buf = part
        if buf.strip():
            merged.append(buf.strip())
        return merged

    # Fall back to line-based splitting
    lines_list = text.split("\n")
    merged = []
    buf = ""
    for line in lines_list:
        if len(buf) + len(line) + 1 <= TARGET_MAX:
            buf = f"{buf}\n{line}" if buf else line
        else:
            if buf.strip():
                merged.append(buf.strip())
            buf = line
    if buf.strip():
        merged.append(buf.strip())
    return merged


# =============================================================================
# INCREMENTAL MINING HELPERS
# =============================================================================


def _file_hash(path: Path) -> str:
    """Return blake2b hex digest (32 chars) of raw file bytes."""
    h = hashlib.blake2b(digest_size=16)
    h.update(path.read_bytes())
    return h.hexdigest()


def _bulk_existing_file_hashes(collection, wing: str) -> dict:
    """Return {source_file: source_hash} for all drawers in wing.

    Delegates to collection.get_source_file_hashes() (LanceDB column projection,
    no vector scan). Returns an empty dict on unsupported backends or empty palace.
    """
    result = collection.get_source_file_hashes(wing)
    return result if result is not None else {}


# =============================================================================
# PALACE — ChromaDB operations
# =============================================================================


def get_collection(palace_path: str):
    """Open (or create) the drawer store for a palace."""
    os.makedirs(palace_path, exist_ok=True)
    return open_store(palace_path, create=True)


def file_already_mined(collection, source_file: str) -> bool:
    """Fast check: has this file been filed before?"""
    try:
        results = collection.get(where={"source_file": source_file}, limit=1)
        return len(results.get("ids", [])) > 0
    except Exception:
        return False


def add_drawer(
    collection,
    wing: str,
    room: str,
    content: str,
    source_file: str,
    chunk_index: int,
    agent: str,
    language: str = "unknown",
    symbol_name: str = "",
    symbol_type: str = "",
):
    """Add one drawer to the palace."""
    drawer_id = f"drawer_{wing}_{room}_{hashlib.md5((source_file + str(chunk_index)).encode(), usedforsecurity=False).hexdigest()[:16]}"
    try:
        collection.add(
            documents=[content],
            ids=[drawer_id],
            metadatas=[
                {
                    "wing": wing,
                    "room": room,
                    "source_file": source_file,
                    "chunk_index": chunk_index,
                    "added_by": agent,
                    "filed_at": datetime.now().isoformat(),
                    "language": language,
                    "symbol_name": symbol_name,
                    "symbol_type": symbol_type,
                }
            ],
        )
        return True
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            return False
        raise


# =============================================================================
# BATCH HELPERS
# =============================================================================


def _collect_specs_for_file(
    filepath: Path,
    project_path: Path,
    collection,
    wing: str,
    rooms: list,
    agent: str,
    mined_files: Optional[set] = None,
    source_hash: str = "",
    csproj_room_map: Optional[dict] = None,
) -> list:
    """Read, chunk, and prepare drawer specs for one file without writing.

    Returns [] if the file is already mined, unreadable, or below MIN_CHUNK.
    Each spec dict has keys: id, content, metadata.
    IDs and filed_at timestamps are set at spec-creation time.

    If *mined_files* is provided (a set of source_file strings pre-fetched for the
    wing), membership is checked in O(1) instead of issuing a per-file LanceDB query.
    Falls back to file_already_mined() when mined_files is None.

    *source_hash* is the blake2b digest of the file bytes (computed once in mine()).
    Stored verbatim on every drawer for incremental change detection.
    """
    source_file = str(filepath)
    if mined_files is not None:
        if source_file in mined_files:
            return []
    elif file_already_mined(collection, source_file):
        return []

    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    content = content.strip()
    if len(content) < MIN_CHUNK:
        return []

    language = detect_language(filepath, content)
    room = detect_room(filepath, content, rooms, project_path, csproj_room_map=csproj_room_map)
    chunks = chunk_file(content, filepath.suffix.lower(), source_file, language=language)

    specs = []
    for chunk in chunks:
        symbol_name, symbol_type = extract_symbol(chunk["content"], language)
        drawer_id = f"drawer_{wing}_{room}_{hashlib.md5((source_file + str(chunk['chunk_index'])).encode(), usedforsecurity=False).hexdigest()[:16]}"
        specs.append(
            {
                "id": drawer_id,
                "content": chunk["content"],
                "metadata": {
                    "wing": wing,
                    "room": room,
                    "source_file": source_file,
                    "chunk_index": chunk["chunk_index"],
                    "added_by": agent,
                    "filed_at": datetime.now().isoformat(),
                    "language": language,
                    "symbol_name": symbol_name,
                    "symbol_type": symbol_type,
                    "source_hash": source_hash,
                    "extractor_version": __version__,
                    "chunker_strategy": chunk.get("chunker_strategy", "regex_structural_v1"),
                },
            }
        )
    return specs


def add_drawers_batch(collection, specs: list) -> int:
    """Embed and upsert a batch of drawer specs. Idempotent: re-mining the same
    file updates existing drawers in place instead of appending duplicates."""
    if not specs:
        return 0
    collection.upsert(
        ids=[s["id"] for s in specs],
        documents=[s["content"] for s in specs],
        metadatas=[s["metadata"] for s in specs],
    )
    return len(specs)


# =============================================================================
# PROCESS ONE FILE
# =============================================================================


def process_file(
    filepath: Path,
    project_path: Path,
    collection,
    wing: str,
    rooms: list,
    agent: str,
    dry_run: bool,
    csproj_room_map: Optional[dict] = None,
) -> int:
    """Read, chunk, route, and file one file. Returns drawer count."""

    if dry_run:
        specs = _collect_specs_for_file(
            filepath,
            project_path,
            None,
            wing,
            rooms,
            agent,
            mined_files=set(),
            csproj_room_map=csproj_room_map,
        )
        if specs:
            room = specs[0]["metadata"]["room"]
            print(f"    [DRY RUN] {filepath.name} → room:{room} ({len(specs)} drawers)")
        return len(specs)

    specs = _collect_specs_for_file(
        filepath, project_path, collection, wing, rooms, agent, csproj_room_map=csproj_room_map
    )
    return add_drawers_batch(collection, specs)


# =============================================================================
# SCAN PROJECT
# =============================================================================


def scan_project(
    project_dir: str,
    respect_gitignore: bool = True,
    include_ignored: list = None,
) -> list:
    """Return list of all readable file paths."""
    project_path = Path(project_dir).expanduser().resolve()
    files = []
    active_matchers = []
    matcher_cache = {}
    include_paths = normalize_include_paths(include_ignored)
    dotnet_project = _is_dotnet_project(project_path)

    for root, dirs, filenames in os.walk(project_path):
        root_path = Path(root)

        if respect_gitignore:
            active_matchers = [
                matcher
                for matcher in active_matchers
                if root_path == matcher.base_dir or matcher.base_dir in root_path.parents
            ]
            current_matcher = load_gitignore_matcher(root_path, matcher_cache)
            if current_matcher is not None:
                active_matchers.append(current_matcher)

        dirs[:] = [
            d
            for d in dirs
            if is_force_included(root_path / d, project_path, include_paths)
            or not (should_skip_dir(d) or (dotnet_project and d == "bin"))
        ]
        if respect_gitignore and active_matchers:
            dirs[:] = [
                d
                for d in dirs
                if is_force_included(root_path / d, project_path, include_paths)
                or not is_gitignored(root_path / d, active_matchers, is_dir=True)
            ]

        for filename in filenames:
            filepath = root_path / filename
            force_include = is_force_included(filepath, project_path, include_paths)
            exact_force_include = is_exact_force_include(filepath, project_path, include_paths)

            if not force_include and filename in SKIP_FILENAMES:
                continue
            if filepath.suffix.lower() not in READABLE_EXTENSIONS and not exact_force_include:
                if filename not in KNOWN_FILENAMES:
                    continue
            if respect_gitignore and active_matchers and not force_include:
                if is_gitignored(filepath, active_matchers, is_dir=False):
                    continue
            files.append(filepath)
    return files


# =============================================================================
# .NET PROJECT FILE PARSING — KG triple extraction
# =============================================================================

# =============================================================================
# .NET SOURCE FILE TYPE-RELATIONSHIP EXTRACTION
# =============================================================================

# Ordered matcher list for C# type declarations with inheritance/implementation.
# Most-specific patterns first (record struct > record class > bare record > struct > interface > class).
# Each tuple: (compiled_regex, type_kind) — type_kind drives predicate assignment.
# Regex groups: group(1) = type name, group(2) = raw base-type list (post-processed below).
_CSHARP_TYPE_REL_MATCHERS = [
    # record struct — must precede struct and bare record
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
            r"new|unsafe|readonly)\s+)*"
            r"record\s+struct\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"(?:\s*\([^)]*\))?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "struct",
    ),
    # record class — must precede class and bare record
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
            r"new|unsafe)\s+)*"
            r"record\s+class\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"(?:\s*\([^)]*\))?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # bare record (implicitly a record class)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
            r"new|unsafe)\s+)*"
            r"record\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"(?:\s*\([^)]*\))?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # struct — before class (struct cannot inherit classes in C#, only implements interfaces)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
            r"new|unsafe|readonly)\s+)*"
            r"struct\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "struct",
    ),
    # interface — before class
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|new)\s+)*"
            r"interface\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "interface",
    ),
    # class (covers sealed, abstract, static, partial, etc.)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
            r"new|unsafe)\s+)*"
            r"class\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "class",
    ),
]


def _split_base_list(base_str: str) -> list:
    """Split a C# base-type list at depth-0 commas, respecting <> nesting.

    Correctly handles nested generics like ``Dictionary<string, List<int>>``
    where inner commas are type-argument separators, not base-type separators.
    """
    parts = []
    depth = 0
    start = 0
    for i, ch in enumerate(base_str):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(base_str[start:i].strip())
            start = i + 1
    parts.append(base_str[start:].strip())
    return [p for p in parts if p]


def _join_continuation_lines(text: str) -> str:
    """Join C# continuation lines for multi-line base-type declarations.

    When a line ends with ':' or ',' (after rstrip), the next non-empty line's
    stripped content is merged onto it with a single space.  Merging continues
    while the accumulated line still ends with ','.  Stops early when the next
    non-empty line starts with '{' or is a bare ';'.
    """
    lines = text.splitlines()
    result: list = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        if stripped.endswith(":") or stripped.endswith(","):
            accumulated = stripped
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if not next_stripped:
                    j += 1
                    continue
                if next_stripped.startswith("{") or next_stripped == ";":
                    break
                accumulated = accumulated + " " + next_stripped
                j += 1
                if not accumulated.rstrip().endswith(","):
                    break
            result.append(accumulated)
            i = j
        else:
            result.append(line)
            i += 1
    return "\n".join(result)


def _csharp_type_rels(filepath: Path) -> list:
    """Extract inheritance/implementation triples from a C# source file.

    Strips block and line comments first to avoid false-positive declarations.
    Returns a list of (subject, predicate, object) tuples.
    """
    try:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    # Strip block comments, then line comments to suppress false-positive declarations.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    # Join continuation lines so multi-line base-type declarations are matched by the
    # single-line patterns in _CSHARP_TYPE_REL_MATCHERS.
    text = _join_continuation_lines(text)
    triples = []
    seen: set = set()
    for pattern, type_kind in _CSHARP_TYPE_REL_MATCHERS:
        for m in pattern.finditer(text):
            type_name = m.group(1)
            base_list_str = m.group(2)
            # Truncate at generic constraints, block open, statement terminator, or comment.
            for stop in (" where ", "{", ";", "//"):
                idx = base_list_str.find(stop)
                if idx != -1:
                    base_list_str = base_list_str[:idx]
            for base_raw in _split_base_list(base_list_str):
                # Strip generic suffix: IEquatable<Point> -> IEquatable
                base_name = base_raw.split("<")[0].strip()
                if not base_name or not base_name[0].isalpha():
                    continue
                if type_kind == "struct":
                    pred = "implements"
                elif type_kind == "interface":
                    pred = "extends"
                elif len(base_name) >= 2 and base_name[0] == "I" and base_name[1].isupper():
                    pred = "implements"
                else:
                    pred = "inherits"
                key = (type_name, pred, base_name)
                if key not in seen:
                    seen.add(key)
                    triples.append(key)
    return triples


# Module-level compiled patterns for F# line-by-line scanning.
# Allow leading whitespace so that types defined inside explicit modules (indented) are matched.
_FS_TYPE_DECL_RE = re.compile(r"^\s*type\s+(\w+)")
_FS_MODULE_DECL_RE = re.compile(r"^\s*module\s+\w+")
_FS_INHERIT_RE = re.compile(r"^\s+inherit\s+(\w+)")
_FS_IFACE_RE = re.compile(r"^\s+interface\s+(\w+)")


def _fsharp_type_rels(filepath: Path) -> list:
    """Extract inheritance/implementation triples from an F# source file.

    Scans for ``type Name`` declarations (at any indentation level, including types
    inside explicit modules), then collects indented ``inherit Base`` and
    ``interface IFoo with`` lines within the type's scope (until the next
    ``type`` or ``module`` declaration, or EOF).
    """
    try:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    triples = []
    seen: set = set()
    current_type = None
    for line in text.splitlines():
        m = _FS_TYPE_DECL_RE.match(line)
        if m:
            current_type = m.group(1)
            continue
        if _FS_MODULE_DECL_RE.match(line):
            current_type = None
            continue
        if current_type is None:
            continue
        m = _FS_INHERIT_RE.match(line)
        if m:
            key = (current_type, "inherits", m.group(1))
            if key not in seen:
                seen.add(key)
                triples.append(key)
            continue
        m = _FS_IFACE_RE.match(line)
        if m:
            key = (current_type, "implements", m.group(1))
            if key not in seen:
                seen.add(key)
                triples.append(key)
    return triples


# Module-level compiled patterns for VB.NET line-by-line scanning.
_VB_CLASS_RE = re.compile(
    r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
    r"(?:(?:Partial|MustInherit|NotInheritable|Shadows)\s+)*"
    r"Class\s+(\w+)",
    re.IGNORECASE,
)
_VB_STRUCT_RE = re.compile(
    r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
    r"(?:(?:Partial|Shadows)\s+)*"
    r"Structure\s+(\w+)",
    re.IGNORECASE,
)
_VB_IFACE_DECL_RE = re.compile(
    r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
    r"(?:(?:Partial|Shadows)\s+)*"
    r"Interface\s+(\w+)",
    re.IGNORECASE,
)
_VB_INHERITS_RE = re.compile(r"^\s*Inherits\s+(\w+)", re.IGNORECASE)
_VB_IMPLEMENTS_RE = re.compile(r"^\s*Implements\s+(.+)", re.IGNORECASE)
_VB_END_RE = re.compile(r"^\s*End\s+(?:Class|Structure|Interface)\b", re.IGNORECASE)


def _vbnet_type_rels(filepath: Path) -> list:
    """Extract inheritance/implementation triples from a VB.NET source file.

    Scans for Class/Structure/Interface declarations, then collects ``Inherits``
    and ``Implements`` lines within the block (until the matching ``End`` statement).
    """
    try:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    triples = []
    seen: set = set()
    current_type = None
    current_kind = None
    for line in text.splitlines():
        if _VB_END_RE.match(line):
            current_type = None
            current_kind = None
            continue
        m = _VB_CLASS_RE.match(line)
        if m:
            current_type = m.group(1)
            current_kind = "class"
            continue
        m = _VB_STRUCT_RE.match(line)
        if m:
            current_type = m.group(1)
            current_kind = "struct"
            continue
        m = _VB_IFACE_DECL_RE.match(line)
        if m:
            current_type = m.group(1)
            current_kind = "interface"
            continue
        if current_type is None:
            continue
        m = _VB_INHERITS_RE.match(line)
        if m:
            base = m.group(1).strip()
            pred = "extends" if current_kind == "interface" else "inherits"
            key = (current_type, pred, base)
            if key not in seen:
                seen.add(key)
                triples.append(key)
            continue
        m = _VB_IMPLEMENTS_RE.match(line)
        if m:
            for iface_raw in m.group(1).split(","):
                # Strip VB.NET generic suffix: IEquatable(Of T) -> IEquatable
                iface = iface_raw.strip().split("(")[0].strip()
                if iface:
                    key = (current_type, "implements", iface)
                    if key not in seen:
                        seen.add(key)
                        triples.append(key)
    return triples


# Compiled patterns for Python type-relationship extraction.
_PY_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*\(([^)]*)\)\s*:", re.MULTILINE)
_PY_IMPORT_RE = re.compile(r"^import\s+([\w.]+)", re.MULTILINE)
_PY_FROM_IMPORT_RE = re.compile(r"^from\s+([a-zA-Z][\w.]*)\s+import\s+", re.MULTILINE)
# Base class names that receive the 'implements' predicate in Python.
_PY_ABC_BASES = frozenset({"ABC", "ABCMeta", "Protocol"})


def _python_type_rels(filepath: Path) -> list:
    """Extract inheritance/implementation and import triples from a Python source file.

    Strips ``#`` line comments first to avoid false-positive declarations inside comments.
    Returns a list of (subject, predicate, object) tuples.

    Predicates:
      - ``implements``: class inherits from ABC, ABCMeta, or Protocol
      - ``inherits``: class inherits from any other named base class
      - ``depends_on``: module imports another module (``import x`` and ``from x import``)

    Relative imports (``from . import x``, ``from ..foo import bar``) are skipped.
    Multiline class declarations are out of scope; single-line covers >95% of real Python.
    """
    try:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    # Strip # line comments to avoid matching class declarations inside comments.
    text = re.sub(r"#[^\n]*", "", text)
    triples = []
    seen: set = set()

    # Module name: filename stem, or parent directory name for __init__.py.
    stem = filepath.stem
    module_name = filepath.parent.name if stem == "__init__" else stem

    # Class inheritance extraction.
    for m in _PY_CLASS_RE.finditer(text):
        type_name = m.group(1)
        # Pre-strip generic type parameters before splitting by comma to avoid
        # comma-split inside brackets (e.g. Generic[K, V] → Generic, not Generic + V]).
        bases_str = re.sub(r"\[.*?\]", "", m.group(2))
        for base_raw in bases_str.split(","):
            # Strip trailing ] left by nested generics (e.g. Mapping[str, Tuple[int]]).
            base_raw = base_raw.strip().rstrip("]").strip()
            if not base_raw:
                continue
            # Skip keyword arguments: metaclass=ABCMeta, total=False, etc.
            if "=" in base_raw:
                continue
            base_name = base_raw
            if not base_name or not base_name[0].isalpha():
                continue
            pred = "implements" if base_name in _PY_ABC_BASES else "inherits"
            key = (type_name, pred, base_name)
            if key not in seen:
                seen.add(key)
                triples.append(key)

    # Import extraction — emit depends_on triples for module-level imports.
    for m in _PY_IMPORT_RE.finditer(text):
        key = (module_name, "depends_on", m.group(1))
        if key not in seen:
            seen.add(key)
            triples.append(key)
    for m in _PY_FROM_IMPORT_RE.finditer(text):
        key = (module_name, "depends_on", m.group(1))
        if key not in seen:
            seen.add(key)
            triples.append(key)

    return triples


def extract_type_relationships(filepath: Path) -> list:
    """Extract interface-implementation, inheritance, and import triples from source files.

    Supports C# (.cs), F# (.fs/.fsi), VB.NET (.vb), and Python (.py). Uses regex-based
    heuristics (no semantic analysis). Returns a list of (subject, predicate, object) tuples.

    Predicates:
      - ``implements``: class/record/struct implements an interface (C#/VB: I-prefix heuristic;
        Python: base is ABC, ABCMeta, or Protocol)
      - ``inherits``: class/record inherits a base class
      - ``extends``: interface extends another interface (C#/VB only)
      - ``depends_on``: Python module imports another module
    """
    ext = filepath.suffix.lower()
    if ext == ".cs":
        return _csharp_type_rels(filepath)
    if ext in (".fs", ".fsi"):
        return _fsharp_type_rels(filepath)
    if ext == ".vb":
        return _vbnet_type_rels(filepath)
    if ext == ".py":
        return _python_type_rels(filepath)
    return []


# File extensions that trigger KG triple extraction during mining.
_KG_EXTRACT_EXTENSIONS = frozenset(
    {".csproj", ".fsproj", ".vbproj", ".sln", ".xaml", ".cs", ".fs", ".fsi", ".vb", ".py"}
)

# .sln project-line regex: captures (project_name, relative_path)
_SLN_PROJECT_RE = re.compile(
    r'Project\("[^"]*"\)\s*=\s*"([^"]+)",\s*"([^"]+)"',
    re.IGNORECASE,
)

# Extensions that identify real project files within a solution (vs. SolutionFolders)
_SLN_PROJECT_EXTS = frozenset({".csproj", ".fsproj", ".vbproj"})


def parse_dotnet_project_file(filepath: Path) -> list:
    """Parse a .csproj/.fsproj/.vbproj file and return KG triples.

    Returns a list of (subject, predicate, object) tuples.
    Project name is derived from the filename stem.
    Uses stdlib xml.etree.ElementTree; no extra dependencies.
    """
    import xml.etree.ElementTree as ET

    project_name = filepath.stem
    triples = []

    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(content)
    except (ET.ParseError, OSError):
        return triples

    for elem in root.iter():
        # Strip MSBuild namespace prefix if present (e.g. {http://schemas.microsoft.com/...})
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "TargetFramework":
            val = (elem.text or "").strip()
            if val:
                triples.append((project_name, "targets_framework", val))

        elif tag == "TargetFrameworks":
            # Multi-target: <TargetFrameworks>net8.0;net6.0</TargetFrameworks>
            for fw in (elem.text or "").split(";"):
                fw = fw.strip()
                if fw:
                    triples.append((project_name, "targets_framework", fw))

        elif tag == "OutputType":
            val = (elem.text or "").strip()
            if val:
                triples.append((project_name, "has_output_type", val))

        elif tag == "PackageReference":
            name = elem.get("Include", "").strip()
            version = elem.get("Version", "").strip()
            if name:
                obj = f"{name}@{version}" if version else name
                triples.append((project_name, "depends_on", obj))

        elif tag == "ProjectReference":
            include = elem.get("Include", "").strip()
            if include:
                ref_name = Path(include.replace("\\", "/")).stem
                triples.append((project_name, "references_project", ref_name))

    return triples


def parse_sln_file(filepath: Path) -> list:
    """Parse a .sln file and return KG triples.

    Returns a list of (subject, predicate, object) tuples.
    Only real project entries (.csproj/.fsproj/.vbproj) emit triples —
    SolutionFolder entries are excluded.
    Solution name is derived from the filename stem.
    """
    solution_name = filepath.stem
    triples = []

    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return triples

    for match in _SLN_PROJECT_RE.finditer(content):
        project_name = match.group(1)
        project_path_str = match.group(2)
        suffix = Path(project_path_str.replace("\\", "/")).suffix.lower()
        if suffix in _SLN_PROJECT_EXTS:
            triples.append((solution_name, "contains_project", project_name))

    return triples


# =============================================================================
# XAML FILE PARSING — KG triple extraction
# =============================================================================

# XAML namespace URI for the core XAML language (x: prefix by convention).
_XAML_NS = "http://schemas.microsoft.com/winfx/2006/xaml"

# d:DataContext design-time binding — e.g. d:DataContext="{d:DesignInstance Type=vm:MainViewModel}"
_XAML_D_DATACONTEXT_RE = re.compile(
    r'd:DataContext="\{d:DesignInstance\s+(?:Type=)?(?:[\w]+:)?(\w+)',
    re.IGNORECASE,
)

# StaticResource and DynamicResource references inside attribute values
_XAML_RESOURCE_RE = re.compile(r"\{(?:Static|Dynamic)Resource\s+(\w+)\}")

# Command binding — Command="{Binding SaveCommand}" or Command="{Binding Path=SaveCommand}"
_XAML_COMMAND_RE = re.compile(r'Command\s*=\s*"\{Binding\s+(?:Path=)?(\w+)\}"')


def parse_xaml_file(filepath: Path) -> list:
    """Parse a .xaml file and return KG triples.

    Returns a list of (subject, predicate, object) tuples.
    Subject is the view name: short name from x:Class or filename stem.
    Uses xml.etree.ElementTree for structured traversal (x:Class, x:Name, plain Name=,
    DataContext element syntax) and regex for markup extension values
    ({Binding}, {StaticResource}, {DynamicResource}, d:DataContext) that
    ET treats as opaque attribute strings.
    """
    import xml.etree.ElementTree as ET

    triples = []

    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return triples

    if not content.strip():
        return triples

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return triples

    # Determine view name: x:Class short name or filename stem
    view_name = filepath.stem
    xclass_attr = f"{{{_XAML_NS}}}Class"
    raw_class = root.get(xclass_attr, "")
    if not raw_class:
        # Fallback: scan first 5 lines for raw x:Class text (namespace edge cases)
        for line in content.splitlines()[:5]:
            m = re.search(r'x:Class="([\w.]+)"', line)
            if m:
                raw_class = m.group(1)
                break
    if raw_class:
        view_name = raw_class.rsplit(".", 1)[-1]

    # 1. Code-behind link (only when an adjacent .xaml.cs file exists on disk)
    code_behind = filepath.parent / (filepath.name + ".cs")
    if code_behind.exists():
        triples.append((view_name, "has_code_behind", code_behind.name))

    # 2. ViewModel from element DataContext:
    #    <Window.DataContext><local:MainViewModel /></Window.DataContext>
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag.endswith(".DataContext"):
            for child in elem:
                child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                # Strip namespace prefix (e.g. "local:MainViewModel" → "MainViewModel")
                vm_name = child_tag.rsplit(":", 1)[-1] if ":" in child_tag else child_tag
                if vm_name:
                    triples.append((view_name, "binds_viewmodel", vm_name))

    # 3. Named controls (x:Name or plain Name= attribute)
    # WPF's FrameworkElement exposes both as equivalent shorthands; collect both
    # into a set per element so a duplicate value on the same element emits only one triple.
    xname_attr = f"{{{_XAML_NS}}}Name"
    for elem in root.iter():
        names: set = set()
        xname_val = elem.get(xname_attr, "")
        if xname_val:
            names.add(xname_val)
        plain_name_val = elem.get("Name", "")
        if plain_name_val:
            names.add(plain_name_val)
        for name_val in names:
            triples.append((view_name, "has_named_control", name_val))

    # 4. ViewModel from d:DataContext design-time attribute (regex — markup extension)
    m = _XAML_D_DATACONTEXT_RE.search(content)
    if m:
        vm_name = m.group(1)
        existing_vms = {t[2] for t in triples if t[0] == view_name and t[1] == "binds_viewmodel"}
        if vm_name not in existing_vms:
            triples.append((view_name, "binds_viewmodel", vm_name))

    # 5. Resource references (StaticResource and DynamicResource — deduplicated)
    seen_resources: set = set()
    for rm in _XAML_RESOURCE_RE.finditer(content):
        key = rm.group(1)
        if key not in seen_resources:
            triples.append((view_name, "references_resource", key))
            seen_resources.add(key)

    # 6. Command bindings (deduplicated)
    seen_commands: set = set()
    for cm in _XAML_COMMAND_RE.finditer(content):
        cmd = cm.group(1)
        if cmd not in seen_commands:
            triples.append((view_name, "uses_command", cmd))
            seen_commands.add(cmd)

    return triples


# =============================================================================
# MAIN: MINE
# =============================================================================


def mine(
    project_dir: str,
    palace_path: str,
    wing_override: str = None,
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
    respect_gitignore: bool = True,
    include_ignored: list = None,
    incremental: bool = True,
    kg=None,
    skip_optimize: bool = False,
):
    """Mine a project directory into the palace.

    When *incremental* is True (default), only files whose content hash has changed
    since the last mine are re-chunked. Deleted files are swept after a full walk.
    Pass *incremental=False* (or --full from the CLI) to force a clean rebuild.

    *kg* is an optional KnowledgeGraph instance. When provided, .NET project files
    (.csproj, .fsproj, .vbproj) and solution files (.sln) are also parsed for
    structured dependency triples that are written to the knowledge graph.

    When *skip_optimize* is True, post-mine storage compaction is skipped.  Callers
    (e.g. the watcher) that run many mine() calls in sequence should skip optimize
    on each call and run a single optimize at the end.
    """

    project_path = Path(project_dir).expanduser().resolve()
    config = load_config(project_dir)

    wing = wing_override or config["wing"]
    rooms = config.get("rooms", [{"name": "general", "description": "All project files"}])

    dotnet_structure = config.get("dotnet_structure", False)
    csproj_room_map: dict = {}
    if dotnet_structure:
        if not wing_override:
            sln_wing = _detect_sln_wing(project_path)
            if sln_wing:
                wing = sln_wing
        csproj_room_map = _build_csproj_room_map(project_path)

    files = scan_project(
        project_dir,
        respect_gitignore=respect_gitignore,
        include_ignored=include_ignored,
    )
    if limit > 0:
        files = files[:limit]

    mine_start = time.time()

    print(f"\n{'=' * 55}")
    print("  MemPalace Mine")
    print(f"{'=' * 55}")
    print(f"  Wing:    {wing}")
    print(f"  Rooms:   {', '.join(r['name'] for r in rooms)}")
    print(f"  Files:   {len(files)}")
    print(f"  Palace:  {palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    if not incremental:
        print("  Mode:    FULL REBUILD (--full)")
    if not respect_gitignore:
        print("  .gitignore: DISABLED")
    if include_ignored:
        print(f"  Include: {', '.join(sorted(normalize_include_paths(include_ignored)))}")
    print(f"{'─' * 55}\n")

    if not dry_run:
        print("  Loading embedding model...", flush=True)
        collection = get_collection(palace_path)
        collection.warmup()
        print("  Model ready.\n", flush=True)
        existing_hashes = _bulk_existing_file_hashes(collection, wing)
    else:
        collection = None
        existing_hashes = {}

    total_drawers = 0
    files_skipped = 0
    room_counts = defaultdict(int)
    batch_buffer: list = []
    batch_num = 0
    walked_paths: set = set()

    def flush_batch() -> None:
        nonlocal total_drawers, batch_num
        batch_num += 1
        count = len(batch_buffer)
        print(
            f"  >> Embedding batch {batch_num} ({count} chunks)...",
            end="",
            flush=True,
        )
        t0 = time.time()
        total_drawers += add_drawers_batch(collection, batch_buffer)
        elapsed = time.time() - t0
        print(f" done ({elapsed:.1f}s)", flush=True)
        batch_buffer.clear()

    try:
        for i, filepath in enumerate(files, 1):
            source_file = str(filepath)
            walked_paths.add(source_file)

            if dry_run:
                drawers = process_file(
                    filepath=filepath,
                    project_path=project_path,
                    collection=collection,
                    wing=wing,
                    rooms=rooms,
                    agent=agent,
                    dry_run=True,
                    csproj_room_map=csproj_room_map if csproj_room_map else None,
                )
                total_drawers += drawers
                room = detect_room(
                    filepath, "", rooms, project_path, csproj_room_map=csproj_room_map
                )
                room_counts[room] += 1
                continue

            # Print scanning progress every 100 files so large repos aren't silent
            if i % 100 == 0 or i == 1:
                print(
                    f"  Scanning [{i:4}/{len(files)}]...",
                    end="\r",
                    flush=True,
                )

            current_hash = _file_hash(filepath)

            if incremental:
                stored_hash = existing_hashes.get(source_file, "")
                if stored_hash == current_hash and stored_hash != "":
                    # File unchanged — skip
                    files_skipped += 1
                    continue
                # Hash mismatch or new file — delete old drawers then re-mine
                if source_file in existing_hashes:
                    collection.delete_by_source_file(source_file, wing)
                    if kg is not None and filepath.suffix.lower() in _KG_EXTRACT_EXTENSIONS:
                        kg.invalidate_by_source_file(source_file)
            else:
                # --full mode: unconditionally delete existing drawers and re-mine
                collection.delete_by_source_file(source_file, wing)
                if kg is not None and filepath.suffix.lower() in _KG_EXTRACT_EXTENSIONS:
                    kg.invalidate_by_source_file(source_file)

            specs = _collect_specs_for_file(
                filepath,
                project_path,
                collection,
                wing,
                rooms,
                agent,
                mined_files=None,
                source_hash=current_hash,
                csproj_room_map=csproj_room_map if csproj_room_map else None,
            )

            # KG triple emission for project/config/XAML/source files
            if kg is not None and filepath.suffix.lower() in _KG_EXTRACT_EXTENSIONS:
                ext = filepath.suffix.lower()
                if ext == ".sln":
                    triples = parse_sln_file(filepath)
                elif ext == ".xaml":
                    triples = parse_xaml_file(filepath)
                elif ext in (".cs", ".fs", ".fsi", ".vb", ".py"):
                    triples = extract_type_relationships(filepath)
                else:
                    triples = parse_dotnet_project_file(filepath)
                for subj, pred, obj in triples:
                    kg.add_triple(subj, pred, obj, source_file=source_file)

            if not specs:
                files_skipped += 1
                continue

            room = specs[0]["metadata"]["room"]
            room_counts[room] += 1
            print(f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} +{len(specs)}")

            batch_buffer.extend(specs)
            if len(batch_buffer) >= BATCH_SIZE:
                flush_batch()

        if not dry_run:
            if batch_buffer:
                flush_batch()

            # Stale-file sweep: remove drawers for files no longer on disk.
            # Only safe when the full file set was walked (limit == 0).
            if incremental and limit == 0:
                stale_paths = set(existing_hashes.keys()) - walked_paths
                for stale_path in stale_paths:
                    collection.delete_by_source_file(stale_path, wing)
                    if kg is not None and Path(stale_path).suffix.lower() in _KG_EXTRACT_EXTENSIONS:
                        kg.invalidate_by_source_file(stale_path)

            config = MempalaceConfig()
            if skip_optimize:
                pass  # caller will optimize later
            elif config.optimize_after_mine:
                t0 = time.time()
                backup_first = config.backup_before_optimize
                if backup_first:
                    print("  >> Backing up before optimize...", flush=True)
                print("  >> Optimizing storage...", end="", flush=True)
                if hasattr(collection, "safe_optimize"):
                    success = collection.safe_optimize(palace_path, backup_first=backup_first)
                    if success:
                        print(f" done ({time.time() - t0:.1f}s)", flush=True)
                    else:
                        print(
                            f"\n  !! WARNING: optimize failed or verification error ({time.time() - t0:.1f}s)",
                            flush=True,
                        )
                else:
                    collection.optimize()
                    print(f" done ({time.time() - t0:.1f}s)", flush=True)
            else:
                print("  >> Skipping optimize (disabled in config)", flush=True)
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Flushing pending batch...", flush=True)
        if batch_buffer and not dry_run:
            flush_batch()
        print(f"  {total_drawers} drawers filed before interrupt.")

    elapsed = time.time() - mine_start
    mins, secs = divmod(int(elapsed), 60)

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Files processed: {len(files) - files_skipped}")
    print(f"  Files skipped (already filed): {files_skipped}")
    print(f"  Drawers filed: {total_drawers}")
    print(f"  Time: {mins}m {secs}s")
    print("\n  By room:")
    for room, count in sorted(room_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"    {room:20} {count} files")
    print('\n  Next: mempalace search "what you\'re looking for"')
    print(f"{'=' * 55}\n")

    return {
        "files_processed": len(files) - files_skipped,
        "files_skipped": files_skipped,
        "drawers_filed": total_drawers,
        "elapsed_secs": elapsed,
    }


# =============================================================================
# MULTI-PROJECT DETECTION
# =============================================================================

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


def detect_projects(parent_dir: str) -> list:
    """Scan immediate subdirectories of *parent_dir* for software projects.

    A directory is considered a project if it contains at least one file or
    directory matching PROJECT_MARKERS or PROJECT_MARKER_GLOBS.  Hidden
    directories (names starting with ``"."``) are skipped as candidates.

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

        # Collect matching markers
        found_markers: list = []
        try:
            dir_contents = set(os.listdir(candidate))
        except OSError:
            continue

        for marker in PROJECT_MARKERS:
            if marker in dir_contents:
                found_markers.append(marker)

        for pattern in PROJECT_MARKER_GLOBS:
            for item in dir_contents:
                if fnmatch.fnmatch(item, pattern):
                    found_markers.append(item)
                    break  # one match per glob pattern is enough

        if not found_markers:
            continue

        initialized = bool(dir_contents & INIT_MARKERS)
        results.append(
            {
                "path": str(candidate),
                "markers": sorted(found_markers),
                "initialized": initialized,
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


def _detect_sln_wing(project_path: Path) -> Optional[str]:
    """Return a normalized wing name derived from the root-level .sln file, or None.

    If multiple .sln files exist, pick the one with the most contained projects;
    ties are broken alphabetically.
    """
    sln_files = sorted(project_path.glob("*.sln"))
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
        proj_files.extend(project_path.glob(pattern))

    room_map: dict = {}
    for pf in proj_files:
        folder = pf.parent.resolve()
        room_name = _normalize_room_name(pf.stem)
        room_map[folder] = room_name
    return room_map


# =============================================================================
# STATUS
# =============================================================================


def status(palace_path: str):
    """Show what's been filed in the palace."""
    try:
        store = open_store(palace_path, create=False)
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        return

    # Count by wing and room
    total = store.count()
    wing_rooms = store.count_by_pair("wing", "room")

    print(f"\n{'=' * 55}")
    print(f"  MemPalace Status — {total} drawers")
    print(f"{'=' * 55}\n")
    for wing, rooms in sorted(wing_rooms.items()):
        print(f"  WING: {wing}")
        for room, count in sorted(rooms.items(), key=lambda x: x[1], reverse=True):
            print(f"    ROOM: {room:20} {count:5} drawers")
        print()
    print(f"{'=' * 55}\n")
