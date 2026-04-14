"""
treesitter.py — Optional tree-sitter parser factory.

Provides get_parser(language) which returns a cached Parser for the given
language, or None when tree-sitter is not installed or the grammar package
for the requested language is unavailable.

All tree-sitter logic is isolated here so the rest of the codebase imports
this module unconditionally — it is always safe to import, it just returns
None when the optional dependency is absent.
"""

import warnings
from typing import Optional

try:
    from tree_sitter import Language, Parser

    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

# Module-level parser cache: language → Parser (lazily populated).
_parser_cache: "dict[str, Parser]" = {}

# Grammar loaders — each lambda imports the grammar package on demand and
# returns a Language object compatible with the pinned tree-sitter version.
# Wrapped in try/except at call-time so a missing package yields None, not
# an ImportError propagated to the caller.
_GRAMMAR_LOADERS = {
    "python": lambda: __import__("tree_sitter_python").language(),
    "typescript": lambda: __import__("tree_sitter_typescript").language_typescript(),
    "javascript": lambda: __import__("tree_sitter_typescript").language_typescript(),
    "tsx": lambda: __import__("tree_sitter_typescript").language_tsx(),
    "jsx": lambda: __import__("tree_sitter_typescript").language_tsx(),
    "go": lambda: __import__("tree_sitter_go").language(),
    "rust": lambda: __import__("tree_sitter_rust").language(),
}


def get_parser(language: str) -> "Optional[Parser]":
    """Return a cached Parser for *language*, or None if unavailable.

    Returns None when:
    - tree-sitter is not installed (TREE_SITTER_AVAILABLE is False)
    - the grammar package for *language* is not installed
    - *language* is not in the supported grammar set
    Never raises ImportError or any grammar-loading exception.
    """
    if not TREE_SITTER_AVAILABLE:
        return None

    if language in _parser_cache:
        return _parser_cache[language]

    loader = _GRAMMAR_LOADERS.get(language)
    if loader is None:
        return None

    try:
        lang_obj = loader()
        parser = Parser(Language(lang_obj))
        _parser_cache[language] = parser
        return parser
    except Exception as exc:
        warnings.warn(
            f"mempalace: tree-sitter grammar for '{language}' could not be loaded "
            f"({type(exc).__name__}: {exc}). Falling back to regex chunking.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
