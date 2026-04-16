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


def detect_room(filepath: Path, content: str, rooms: list, project_path: Path) -> str:
    """
    Route a file to the right room.
    Priority:
    1. Folder path matches a room name
    2. Filename matches a room name or keyword
    3. Content keyword scoring
    4. Fallback: "general"
    """
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

# Markdown heading boundaries
HEADING_MD = re.compile(r"^#{1,4}\s+.+", re.MULTILINE)

# HCL / Terraform top-level block boundaries
HCL_BOUNDARY = re.compile(
    r"^(?:resource|data|module|variable|output|locals|provider|terraform)\s+",
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
        "terraform": HCL_BOUNDARY,
        ".tf": HCL_BOUNDARY,
        ".tfvars": HCL_BOUNDARY,
        "hcl": HCL_BOUNDARY,
        ".hcl": HCL_BOUNDARY,
    }
    return mapping.get(language)


# =============================================================================
# LANGUAGE DETECTION
# =============================================================================


def detect_language(filepath: Path, content: str = "") -> str:
    """
    Detect the programming language for a file.

    Resolution order:
    1. File extension lookup via EXTENSION_LANG_MAP.
    2. Filename lookup via FILENAME_LANG_MAP (for extensionless files like Dockerfile, Makefile).
    3. Shebang inspection on the first line (for extensionless files).
    4. Returns "unknown" if neither matches.
    """
    ext = filepath.suffix.lower()
    if ext in EXTENSION_LANG_MAP:
        return EXTENSION_LANG_MAP[ext]

    # Filename-based detection for known extensionless files
    if filepath.name in FILENAME_LANG_MAP:
        return FILENAME_LANG_MAP[filepath.name]

    # Shebang fallback — only for files with no recognized extension
    first_line = content.split("\n")[0] if content else ""
    if first_line.startswith("#!"):
        # Strip "#!" and split by whitespace
        parts = first_line[2:].strip().split()
        if parts:
            # #!/usr/bin/env python3 [-flags...] → env is parts[0], interpreter is parts[1]
            # #!/usr/bin/python3 [-flags...]     → interpreter basename is parts[0]
            basename = parts[0].split("/")[-1]
            if basename == "env" and len(parts) > 1:
                interp = parts[1].split("/")[-1]
            else:
                interp = basename
            for pattern, lang in SHEBANG_PATTERNS:
                if pattern.fullmatch(interp):
                    return lang

    return "unknown"


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
}


def extract_symbol(content: str, language: str) -> tuple:
    """
    Extract the primary symbol defined in a code chunk.
    Returns (symbol_name, symbol_type) or ("", "") if none found.
    Non-code languages (markdown, text, json, yaml, unknown, etc.) return ("", "").
    TS/JS import-only chunks return ("", "import").
    """
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


def chunk_file(content: str, ext: str, source_file: str, language: str = None) -> list:
    """Dispatcher — route to the right chunking strategy based on language."""
    if language is None:
        language = EXTENSION_LANG_MAP.get(ext, "unknown")

    if language in ("python", "typescript", "javascript", "tsx", "jsx", "go", "rust"):
        return chunk_code(content, language, source_file)
    elif language in ("terraform", "hcl"):
        return chunk_code(content, language, source_file)
    elif language in ("markdown", "text"):
        return chunk_prose(content, source_file)
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
    mod_item, and type_item nodes as chunk boundaries. Attaches immediately
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
                if prev.startswith(("//", "/*", "*", "*/", "#", '"""', "'''", "/**")):
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
    room = detect_room(filepath, content, rooms, project_path)
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
) -> int:
    """Read, chunk, route, and file one file. Returns drawer count."""

    if dry_run:
        source_file = str(filepath)
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0
        content = content.strip()
        if len(content) < MIN_CHUNK:
            return 0
        language = detect_language(filepath, content)
        room = detect_room(filepath, content, rooms, project_path)
        chunks = chunk_file(content, filepath.suffix.lower(), source_file, language=language)
        print(f"    [DRY RUN] {filepath.name} → room:{room} ({len(chunks)} drawers)")
        return len(chunks)

    specs = _collect_specs_for_file(filepath, project_path, collection, wing, rooms, agent)
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
            or not should_skip_dir(d)
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
):
    """Mine a project directory into the palace.

    When *incremental* is True (default), only files whose content hash has changed
    since the last mine are re-chunked. Deleted files are swept after a full walk.
    Pass *incremental=False* (or --full from the CLI) to force a clean rebuild.
    """

    project_path = Path(project_dir).expanduser().resolve()
    config = load_config(project_dir)

    wing = wing_override or config["wing"]
    rooms = config.get("rooms", [{"name": "general", "description": "All project files"}])

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
                )
                total_drawers += drawers
                room = detect_room(filepath, "", rooms, project_path)
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
            else:
                # --full mode: unconditionally delete existing drawers and re-mine
                collection.delete_by_source_file(source_file, wing)

            specs = _collect_specs_for_file(
                filepath,
                project_path,
                collection,
                wing,
                rooms,
                agent,
                mined_files=None,
                source_hash=current_hash,
            )
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

            config = MempalaceConfig()
            if config.optimize_after_mine:
                t0 = time.time()
                backup_first = config.backup_before_optimize
                if backup_first:
                    print("  >> Backing up before optimize...", flush=True)
                print("  >> Optimizing storage...", end="", flush=True)
                if hasattr(collection, "safe_optimize"):
                    success = collection.safe_optimize(
                        config.palace_path, backup_first=backup_first
                    )
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
