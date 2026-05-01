"""Canonical language metadata for mining, search validation, and MCP hints."""

import re
from types import MappingProxyType

_EXTENSION_LANG_MAP = {
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

_FILENAME_LANG_MAP = {
    "Dockerfile": "dockerfile",
    "Containerfile": "dockerfile",
    "Makefile": "make",
    "GNUmakefile": "make",
    "Vagrantfile": "ruby",
}

_SHEBANG_PATTERNS = (
    (re.compile(r"python[0-9.]*"), "python"),
    (re.compile(r"node(js)?"), "javascript"),
    (re.compile(r"ruby"), "ruby"),
    (re.compile(r"bash|sh|zsh"), "shell"),
    (re.compile(r"perl"), "perl"),
)

_READABLE_EXTENSIONS = frozenset(
    {
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
)

_SYNTHETIC_DETECTED_LANGUAGES = frozenset({"kubernetes"})

_SEARCHABLE_LANGUAGES = frozenset(
    {
        "python",
        "go",
        "javascript",
        "jsx",
        "typescript",
        "tsx",
        "rust",
        "java",
        "kotlin",
        "cpp",
        "c",
        "shell",
        "ruby",
        # .NET
        "csharp",
        "fsharp",
        "vbnet",
        "xaml",
        "dotnet-solution",
        "xml",
        # Apple / Swift
        "swift",
        # PHP
        "php",
        # JVM
        "scala",
        # Dart / Flutter
        "dart",
        # web
        "html",
        "css",
        # data / query
        "sql",
        # config / infrastructure manifests
        "yaml",
        "json",
        "toml",
        "kubernetes",
        # devops / infrastructure
        "terraform",
        "hcl",
        "dockerfile",
        "make",
        "gotemplate",
        "jinja2",
        "conf",
        "ini",
        # prose / data
        "markdown",
        "text",
        "csv",
        "perl",
    }
)

EXTENSION_LANG_MAP = MappingProxyType(_EXTENSION_LANG_MAP)
FILENAME_LANG_MAP = MappingProxyType(_FILENAME_LANG_MAP)
KNOWN_FILENAMES = frozenset(_FILENAME_LANG_MAP)
SHEBANG_PATTERNS = _SHEBANG_PATTERNS
READABLE_EXTENSIONS = _READABLE_EXTENSIONS
SEARCHABLE_LANGUAGES = _SEARCHABLE_LANGUAGES


def extension_language_map() -> dict[str, str]:
    """Return a mutable copy of the extension-to-language detector map."""
    return dict(EXTENSION_LANG_MAP)


def filename_language_map() -> dict[str, str]:
    """Return a mutable copy of the exact-filename language detector map."""
    return dict(FILENAME_LANG_MAP)


def known_filenames() -> set[str]:
    """Return a mutable copy of known extensionless source filenames."""
    return set(KNOWN_FILENAMES)


def shebang_patterns() -> tuple[tuple[re.Pattern, str], ...]:
    """Return shebang interpreter patterns in detector precedence order."""
    return SHEBANG_PATTERNS


def readable_extensions() -> set[str]:
    """Return a mutable copy of extensions considered readable by the miner."""
    return set(READABLE_EXTENSIONS)


def detected_languages() -> set[str]:
    """Return all language labels that miner detection can emit."""
    return (
        set(EXTENSION_LANG_MAP.values())
        | set(FILENAME_LANG_MAP.values())
        | {language for _pattern, language in SHEBANG_PATTERNS}
        | set(_SYNTHETIC_DETECTED_LANGUAGES)
    )


def searchable_languages() -> set[str]:
    """Return language labels accepted by code_search(language=...)."""
    return set(SEARCHABLE_LANGUAGES)


def sorted_searchable_languages() -> tuple[str, ...]:
    """Return searchable language labels in deterministic display order."""
    return tuple(sorted(SEARCHABLE_LANGUAGES))


def searchable_language_csv() -> str:
    """Return the searchable language labels as a parseable comma-separated list."""
    return ", ".join(sorted_searchable_languages())


def code_search_language_description() -> str:
    """Return the MCP language-filter description generated from the catalog."""
    return f"Filter by language. Supported languages: {searchable_language_csv()}"
