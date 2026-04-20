"""Canonical language catalog shared by mining and code search."""

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

SHEBANG_LANGUAGES = {
    "python",
    "javascript",
    "ruby",
    "shell",
    "perl",
}

SUPPORTED_CODE_SEARCH_LANGUAGES = frozenset(
    set(EXTENSION_LANG_MAP.values()) | set(FILENAME_LANG_MAP.values()) | SHEBANG_LANGUAGES
)


def code_search_language_description() -> str:
    """Return the MCP schema description for the language filter."""
    langs = ", ".join(sorted(SUPPORTED_CODE_SEARCH_LANGUAGES))
    return f"Filter by language (e.g. {langs})"
