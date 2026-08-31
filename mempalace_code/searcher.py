#!/usr/bin/env python3
"""
searcher.py — Semantic search; verbatim stored text.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

import fnmatch
import logging
import os
import shlex
import sys
from typing import TypeGuard

from .language_catalog import searchable_languages
from .storage import open_store
from .taxonomy_filters import TaxonomyValidationError, validate_taxonomy_filters

logger = logging.getLogger("mempalace_mcp")


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def search(
    query: str,
    palace_path: str,
    wing: str | None = None,
    room: str | None = None,
    n_results: int = 5,
    compact: bool = False,
):
    """
    Search the palace. Returns verbatim drawer content.
    Optionally filter by wing (project) or room (aspect).
    """
    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}", file=sys.stderr)
        print(
            "  Next: run mempalace-code init <dir>, then mempalace-code mine <dir>.",
            file=sys.stderr,
        )
        raise SearchError(f"No palace found at {palace_path}")

    error_payload = validate_taxonomy_filters(palace_path, wing=wing, room=room)
    if error_payload is not None:
        raise TaxonomyValidationError(error_payload)

    try:
        store = open_store(palace_path, create=False)
    except Exception:
        print(f"\n  No palace found at {palace_path}", file=sys.stderr)
        print(
            "  Next: run mempalace-code init <dir>, then mempalace-code mine <dir>.",
            file=sys.stderr,
        )
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
        print(f"\n  Search error: {e}", file=sys.stderr)
        print(
            "  Next: run mempalace-code health; if degraded, run "
            "mempalace-code repair --rollback --dry-run before retrying search.",
            file=sys.stderr,
        )
        raise SearchError(f"Search error: {e}") from e

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    if not docs:
        if compact:
            print("\n  No search results found.")
        else:
            print(f'\n  No results found for: "{query}"')
        return

    print(f"\n{'=' * 60}")
    if compact:
        print("  Search results")
    else:
        print(f'  Results for: "{query}"')
    if wing:
        print(f"  Wing: {wing}")
    if room:
        print(f"  Room: {room}")
    print(f"{'=' * 60}\n")

    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        meta = meta or {}
        doc = doc or ""
        similarity = round(1 - dist, 3)
        source = meta.get("source_file") or "?"
        wing_name = meta.get("wing", "?")
        room_name = meta.get("room", "?")

        print(f"  [{i}] {wing_name} / {room_name}")
        print(f"      Source: {source}")
        print(f"      Match:  {similarity}")
        if compact:
            line_range = _compact_line_range(meta)
            if line_range is not None:
                print(f"      Lines:  {line_range[0]}-{line_range[1]}")
            print()
            preview = doc.strip().replace("\n", " ")
            if len(preview) > 300:
                preview = f"{preview[:297]}..."
            print(f"      {preview}")
            source_file = meta.get("source_file")
            wing_value = meta.get("wing")
            if (
                line_range is not None
                and _usable_recovery_value(source_file)
                and _usable_recovery_value(wing_value)
            ):
                print(
                    "      Recovery: mempalace-code --palace "
                    f"{shlex.quote(palace_path)} read {shlex.quote(source_file)} "
                    f"--start {line_range[0]} "
                    f"--end {line_range[1]} --wing {shlex.quote(wing_value)}"
                )
            else:
                print("      Recovery: unavailable")
            print()
            print(f"  {'─' * 56}")
            continue
        print()
        # Print the verbatim text, indented
        for line in doc.strip().split("\n"):
            print(f"      {line}")
        print()
        print(f"  {'─' * 56}")

    print()


def _compact_line_range(meta: dict) -> tuple[int, int] | None:
    """Return a positive ordered line range without coercing malformed metadata."""
    values = []
    for key in ("line_start", "line_end"):
        value = meta.get(key)
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = int(value.strip())
            except ValueError:
                return None
        else:
            return None
        if parsed <= 0:
            return None
        values.append(parsed)
    if values[1] < values[0]:
        return None
    return values[0], values[1]


def _usable_recovery_value(value: object) -> TypeGuard[str]:
    """Accept only nonblank, non-placeholder strings as recovery arguments."""
    return isinstance(value, str) and bool(value.strip()) and value.strip() != "?"


def search_memories(
    query: str,
    palace_path: str,
    wing: str | None = None,
    room: str | None = None,
    n_results: int = 5,
) -> dict:
    """
    Programmatic search — returns a dict instead of printing.
    Used by the MCP server and other callers that need data.
    """
    error_payload = validate_taxonomy_filters(palace_path, wing=wing, room=room)
    if error_payload is not None:
        return error_payload

    try:
        store = open_store(palace_path, create=False)
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return {
            "error": "No palace found",
            "hint": "Run: mempalace-code init <dir> && mempalace-code mine <dir>",
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
        meta = meta or {}
        doc = doc or ""
        ls = int(meta.get("line_start", 0) or 0)
        le = int(meta.get("line_end", 0) or 0)
        hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": meta.get("source_file", "?"),
                "symbol_name": meta.get("symbol_name", "") or "",
                "symbol_type": meta.get("symbol_type", "") or "",
                "language": meta.get("language", "") or "",
                "heading": meta.get("heading", "") or "",
                "heading_level": meta.get("heading_level", 0) or 0,
                "heading_path": meta.get("heading_path", "") or "",
                "doc_section_type": meta.get("doc_section_type", "") or "",
                "contains_mermaid": bool(meta.get("contains_mermaid", 0)),
                "contains_code": bool(meta.get("contains_code", 0)),
                "contains_table": bool(meta.get("contains_table", 0)),
                "line_range": {"start": ls, "end": le} if ls > 0 and le > 0 else None,
                "similarity": round(1 - dist, 3),
            }
        )

    return {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "results": hits,
    }


SUPPORTED_LANGUAGES = searchable_languages()

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
    # Lua-specific
    "local_function",
    # Kubernetes resource kinds
    "deployment",
    "service",
    "configmap",
    "secret",
    "ingress",
    "customresourcedefinition",
    # Helm-specific
    "helm_chart",
    "helm_values",
    # Ansible-specific
    "ansible_play",
    "ansible_task",
    "ansible_handler",
    "ansible_role",
    "ansible_vars",
    "ansible_inventory",
}


def code_search(
    palace_path: str,
    query: str,
    language: str | None = None,
    symbol_name: str | None = None,
    symbol_type: str | None = None,
    file_glob: str | None = None,
    wing: str | None = None,
    n_results: int = 10,
    rerank: str | None = None,
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

    rerank: Optional reranking mode. Only "hybrid" is accepted. Hybrid mode
        applies BM25-style token overlap reranking before post-filters.
        search_memories and the print-oriented search() are unaffected.
    """
    if rerank is not None and rerank != "hybrid":
        return {
            "error": f"Invalid rerank mode: {rerank!r}",
            "valid_rerank_modes": ["hybrid"],
        }

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

    error_payload = validate_taxonomy_filters(palace_path, wing=wing)
    if error_payload is not None:
        return error_payload

    n_results = max(1, min(50, n_results))

    try:
        store = open_store(palace_path, create=False)
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return {
            "error": "No palace found",
            "hint": "Run: mempalace-code init <dir> && mempalace-code mine <dir>",
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

    if rerank == "hybrid":
        fetch_count = min(n_results * 5, 200)
    else:
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

    # Build raw hit dicts for the full fetched pool (before post-filters)
    raw_hits = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        doc = doc or ""
        sym_name = meta.get("symbol_name", "") or ""
        src_file = meta.get("source_file", "") or ""
        ls = int(meta.get("line_start", 0) or 0)
        le = int(meta.get("line_end", 0) or 0)
        raw_hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": src_file,
                "symbol_name": sym_name,
                "symbol_type": meta.get("symbol_type", "") or "",
                "language": meta.get("language", "") or "",
                "line_range": {"start": ls, "end": le} if ls > 0 and le > 0 else None,
                "similarity": round(1 - dist, 3),
            }
        )

    # Apply hybrid reranking before post-filters so the reranker sees the full pool
    if rerank == "hybrid":
        from .search_reranker import hybrid_rerank

        raw_hits = hybrid_rerank(query, raw_hits)

    # Apply Python post-filters and truncate to n_results
    hits = []
    for hit in raw_hits:
        if symbol_name and symbol_name.lower() not in hit["symbol_name"].lower():
            continue
        if file_glob and not fnmatch.fnmatch(hit["source_file"], file_glob):
            continue
        hits.append(hit)
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
