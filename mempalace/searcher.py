#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

import fnmatch
import logging
from pathlib import Path

from .storage import open_store

logger = logging.getLogger("mempalace_mcp")


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def search(query: str, palace_path: str, wing: str = None, room: str = None, n_results: int = 5):
    """
    Search the palace. Returns verbatim drawer content.
    Optionally filter by wing (project) or room (aspect).
    """
    try:
        store = open_store(palace_path, create=False)
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        raise SearchError(f"No palace found at {palace_path}")

    # Build where filter
    where = {}
    if wing and room:
        where = {"$and": [{"wing": wing}, {"room": room}]}
    elif wing:
        where = {"wing": wing}
    elif room:
        where = {"room": room}

    try:
        kwargs = {
            "query_texts": [query],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = store.query(**kwargs)

    except Exception as e:
        print(f"\n  Search error: {e}")
        raise SearchError(f"Search error: {e}") from e

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    if not docs:
        print(f'\n  No results found for: "{query}"')
        return

    print(f"\n{'=' * 60}")
    print(f'  Results for: "{query}"')
    if wing:
        print(f"  Wing: {wing}")
    if room:
        print(f"  Room: {room}")
    print(f"{'=' * 60}\n")

    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        similarity = round(1 - dist, 3)
        source = Path(meta.get("source_file", "?")).name
        wing_name = meta.get("wing", "?")
        room_name = meta.get("room", "?")

        print(f"  [{i}] {wing_name} / {room_name}")
        print(f"      Source: {source}")
        print(f"      Match:  {similarity}")
        print()
        # Print the verbatim text, indented
        for line in doc.strip().split("\n"):
            print(f"      {line}")
        print()
        print(f"  {'─' * 56}")

    print()


def search_memories(
    query: str, palace_path: str, wing: str = None, room: str = None, n_results: int = 5
) -> dict:
    """
    Programmatic search — returns a dict instead of printing.
    Used by the MCP server and other callers that need data.
    """
    try:
        store = open_store(palace_path, create=False)
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return {
            "error": "No palace found",
            "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
        }

    # Build where filter
    where = {}
    if wing and room:
        where = {"$and": [{"wing": wing}, {"room": room}]}
    elif wing:
        where = {"wing": wing}
    elif room:
        where = {"room": room}

    try:
        kwargs = {
            "query_texts": [query],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = store.query(**kwargs)
    except Exception as e:
        return {"error": f"Search error: {e}"}

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    hits = []
    for doc, meta, dist in zip(docs, metas, dists):
        hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": meta.get("source_file", "?"),
                "symbol_name": meta.get("symbol_name", "") or "",
                "symbol_type": meta.get("symbol_type", "") or "",
                "language": meta.get("language", "") or "",
                "similarity": round(1 - dist, 3),
            }
        )

    return {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "results": hits,
    }


SUPPORTED_LANGUAGES = {
    "python",
    "go",
    "javascript",
    "jsx",
    "typescript",
    "tsx",
    "rust",
    "java",
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
}

VALID_SYMBOL_TYPES = {
    "function",
    "class",
    "method",
    "struct",
    "interface",
    # .NET / cross-language
    "record",
    "enum",
    "property",
    "event",
    "module",
    "union",
    "type",
    "view",
    "exception",
    # Swift/Kotlin — type alias
    "typealias",
    # Swift-specific
    "protocol",
    "actor",
    "extension",
    # PHP-specific
    "trait",
    "namespace",
    # Scala-specific
    "object",
    "case_class",
    "case_object",
    # Dart-specific
    "mixin",
    "extension_type",
    "constructor",
    # Kubernetes resource kinds
    "deployment",
    "service",
    "configmap",
    "secret",
    "ingress",
    "customresourcedefinition",
}


def code_search(
    palace_path: str,
    query: str,
    language: str = None,
    symbol_name: str = None,
    symbol_type: str = None,
    file_glob: str = None,
    wing: str = None,
    n_results: int = 10,
) -> dict:
    """
    Code-optimized semantic search. Returns symbol name, type, language, and
    full file path per hit.

    Filters applied in two stages:
      1. LanceDB where clause (pre-query): wing, language, symbol_type.
      2. Python post-filter: symbol_name (case-insensitive substring),
         file_glob (fnmatch against the stored source_file path).

    Over-fetches n_results*3 (capped at 150) to compensate for post-filter
    discard, then truncates to n_results.
    """
    if language is not None:
        language = language.lower()
        if language not in SUPPORTED_LANGUAGES:
            return {
                "error": f"Unsupported language: {language!r}",
                "supported_languages": sorted(SUPPORTED_LANGUAGES),
            }

    if symbol_type is not None:
        symbol_type = symbol_type.lower()
        if symbol_type not in VALID_SYMBOL_TYPES:
            return {
                "error": f"Invalid symbol_type: {symbol_type!r}",
                "valid_symbol_types": sorted(VALID_SYMBOL_TYPES),
            }

    n_results = max(1, min(50, n_results))

    try:
        store = open_store(palace_path, create=False)
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return {
            "error": "No palace found",
            "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
        }

    # Build LanceDB where clause for pre-query filtering
    conditions = []
    if wing:
        conditions.append({"wing": wing})
    if language:
        conditions.append({"language": language})
    if symbol_type:
        conditions.append({"symbol_type": symbol_type})

    where = None
    if len(conditions) > 1:
        where = {"$and": conditions}
    elif len(conditions) == 1:
        where = conditions[0]

    fetch_count = min(n_results * 3, 150)

    try:
        kwargs = {
            "query_texts": [query],
            "n_results": fetch_count,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = store.query(**kwargs)
    except Exception as e:
        return {"error": f"Search error: {e}"}

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    hits = []
    for doc, meta, dist in zip(docs, metas, dists):
        sym_name = meta.get("symbol_name", "") or ""
        src_file = meta.get("source_file", "") or ""

        if symbol_name and symbol_name.lower() not in sym_name.lower():
            continue

        if file_glob and not fnmatch.fnmatch(src_file, file_glob):
            continue

        hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": src_file,
                "symbol_name": sym_name,
                "symbol_type": meta.get("symbol_type", "") or "",
                "language": meta.get("language", "") or "",
                "line_range": None,
                "similarity": round(1 - dist, 3),
            }
        )

        if len(hits) >= n_results:
            break

    return {
        "query": query,
        "filters": {
            "language": language,
            "symbol_name": symbol_name,
            "symbol_type": symbol_type,
            "file_glob": file_glob,
            "wing": wing,
        },
        "results": hits,
    }
