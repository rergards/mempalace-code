#!/usr/bin/env python3
"""
searcher.py — Semantic search; verbatim stored text.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

import fnmatch
import logging
import os
import sys
from typing import Any, TypeGuard

from .cli_invocation import cli_command, degraded_palace_next_step, no_palace_next_step
from .config import expand_palace_path
from .errors import InvalidArgumentError
from .language_catalog import searchable_languages
from .storage import (
    CHROMA_RUNTIME_RETIRED_MESSAGE,
    CanonicalModelCacheError,
    ChromaRuntimeRetiredError,
    PalaceReadError,
    distance_to_similarity,
    is_legacy_chroma_palace,
    open_store,
)
from .taxonomy_filters import TaxonomyValidationError, validate_taxonomy_filters

logger = logging.getLogger("mempalace_mcp")

# Upper bound on hits per search call (CLI --results, MCP limit, code_search n_results).
MAX_SEARCH_RESULTS = 50

# Longest query the MCP search tools accept. The embedder reads only the first
# 256 tokens, so a longer query cannot rank differently; it would only be echoed back.
MAX_QUERY_CHARS = 10_000

# Markdown section fields; a hit carries them only when its drawer has section metadata.
_MARKDOWN_TEXT_FIELDS = ("heading", "heading_path", "doc_section_type")
_MARKDOWN_FLAG_FIELDS = ("contains_mermaid", "contains_code", "contains_table")


def no_palace_payload(palace_path: str | None) -> dict:
    """Programmatic/MCP missing-palace payload; mcp.runtime._no_palace() returns it too.

    A legacy ChromaDB palace is not missing: it names the migration instead of init/mine.
    """
    if palace_path and is_legacy_chroma_palace(palace_path):
        return {
            "error": "Legacy ChromaDB palace needs migration",
            "error_code": "chroma_migration_required",
            "hint": CHROMA_RUNTIME_RETIRED_MESSAGE,
        }
    return {"error": "No palace found", "hint": f"Next: {no_palace_next_step(palace_path)}"}


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def _taxonomy_where(wing: str | None, room: str | None) -> dict | None:
    """Return the LanceDB where filter for optional wing/room scoping."""
    if wing and room:
        return {"$and": [{"wing": wing}, {"room": room}]}
    if wing:
        return {"wing": wing}
    if room:
        return {"room": room}
    return None


def _query_rows(store, query: str, n_results: int, where: dict | None, *, intent_rerank: bool):
    """Run one vector query and return (ids, documents, metadatas, distances)."""
    kwargs: dict[str, Any] = {
        "query_texts": [query],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
        "intent_rerank": intent_rerank,
    }
    if where:
        kwargs["where"] = where
    results = store.query(**kwargs)
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]
    ids = (results.get("ids") or [[]])[0] or []
    ids = list(ids) + [None] * (len(docs) - len(ids))
    return ids, docs, metas, dists


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

    Results are in descending cosine similarity (plain vector order; the
    code-retrieval intent rerank is used only by ``code_search``).
    """
    palace_path = expand_palace_path(palace_path)
    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}", file=sys.stderr)
        print(f"  Next: {no_palace_next_step(palace_path)}.", file=sys.stderr)
        raise SearchError(f"No palace found at {palace_path}")

    error_payload = validate_taxonomy_filters(palace_path, wing=wing, room=room)
    if error_payload is not None:
        raise TaxonomyValidationError(error_payload)

    try:
        store = open_store(palace_path, create=False)
    except ChromaRuntimeRetiredError:
        raise  # names the migration; the CLI prints it without a traceback
    except Exception:
        print(f"\n  No palace found at {palace_path}", file=sys.stderr)
        print(f"  Next: {no_palace_next_step(palace_path)}.", file=sys.stderr)
        raise SearchError(f"No palace found at {palace_path}")

    try:
        ids, docs, metas, dists = _query_rows(
            store, query, n_results, _taxonomy_where(wing, room), intent_rerank=False
        )
    except Exception as e:
        print(f"\n  Search error: {e}", file=sys.stderr)
        # A missing model cache names its own fetch-model recovery (palace repair cannot
        # help), and an unreadable palace names its own recovery: print one Next line.
        if not isinstance(e, (CanonicalModelCacheError, PalaceReadError)):
            print(f"  Next: {degraded_palace_next_step(palace_path, 'search')}", file=sys.stderr)
        raise SearchError(f"Search error: {e}") from e

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
        similarity = distance_to_similarity(dist)
        source = meta.get("source_file") or "?"
        wing_name = meta.get("wing", "?")
        room_name = meta.get("room", "?")
        line_range = _compact_line_range(meta)

        print(f"  [{i}] {wing_name} / {room_name}")
        print(f"      Source: {source}")
        print(f"      Match:  {similarity}")
        if line_range is not None:
            print(f"      Lines:  {line_range[0]}-{line_range[1]}")
        if compact:
            print()
            preview = doc.strip().replace("\n", " ")
            if len(preview) > 300:
                preview = f"{preview[:297]}..."
            print(f"      {preview}")
            print(f"      Recovery: {_recovery_text(meta, line_range, palace_path)}")
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


def _recovery_text(meta: dict, line_range: tuple[int, int] | None, palace_path: str) -> str:
    """Return the compact-mode read command for one hit, or why none can be built."""
    source_file = meta.get("source_file")
    wing_value = meta.get("wing")
    if line_range is None:
        if meta.get("ingest_mode") == "convos":
            return "unavailable (conversation drawers have no line range; drop --compact for full text)"
        return "unavailable (this drawer has no stored line range; drop --compact for full text)"
    if not _usable_recovery_value(source_file):
        return "unavailable (this drawer has no stored source path)"
    if not _usable_recovery_value(wing_value):
        return "unavailable (this drawer has no stored wing)"
    return cli_command(
        "read",
        source_file,
        "--start",
        str(line_range[0]),
        "--end",
        str(line_range[1]),
        "--wing",
        wing_value,
        palace=palace_path,
    )


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


def _clamp_results(n_results: int) -> int:
    """Reject a hit count below 1; bound a larger one to MAX_SEARCH_RESULTS."""
    if isinstance(n_results, bool) or not isinstance(n_results, int) or n_results < 1:
        raise InvalidArgumentError(
            f"n_results must be an integer from 1 to {MAX_SEARCH_RESULTS} (got {n_results!r})",
            argument="n_results",
        )
    return min(MAX_SEARCH_RESULTS, n_results)


def _missing_palace_payload(palace_path: str, query: str, signature: str) -> dict:
    """The missing-palace payload; names the argument order when the two look swapped."""
    payload = no_palace_payload(palace_path)
    try:
        swapped = isinstance(query, str) and os.path.isdir(
            os.path.join(expand_palace_path(query), "lance")
        )
    except (OSError, ValueError):
        swapped = False
    if swapped:
        payload["hint"] = (
            f"The query argument is a palace directory: the signature is {signature}. "
            "Pass both by keyword (palace_path=..., query=...)."
        )
    return payload


def _file_glob_matches(source_file: str, file_glob: str) -> bool:
    """Match *file_glob* against a stored source path.

    A glob that starts with ``/`` or ``*`` matches the whole path. Any other glob
    (``src/*.py``, ``storage.py``) also matches the end of the path at a ``/``
    boundary, so a repo-relative path finds the absolute path mining stored.
    """
    if fnmatch.fnmatch(source_file, file_glob):
        return True
    if file_glob.startswith(("/", "*")):
        return False
    return fnmatch.fnmatch(source_file, f"*/{file_glob}")


def _project_hit(drawer_id, doc, meta, dist, *, missing_source: str | None) -> dict:
    """Return the public search-hit shape shared by search_memories() and code_search().

    Every hit carries its drawer ``id`` (for mempalace_delete_drawer corrections).
    Markdown section fields appear only on hits whose drawer has section metadata.
    """
    meta = meta or {}
    line_range = _compact_line_range(meta)
    hit: dict[str, Any] = {
        "id": drawer_id,
        "text": doc or "",
        "wing": meta.get("wing", "unknown"),
        "room": meta.get("room", "unknown"),
        "source_file": meta.get("source_file", missing_source) or missing_source,
        "symbol_name": meta.get("symbol_name", "") or "",
        "symbol_type": meta.get("symbol_type", "") or "",
        "language": meta.get("language", "") or "",
    }
    if any(meta.get(field) for field in _MARKDOWN_TEXT_FIELDS):
        hit.update({field: meta.get(field, "") or "" for field in _MARKDOWN_TEXT_FIELDS})
        hit["heading_level"] = meta.get("heading_level", 0) or 0
        hit.update({field: bool(meta.get(field, 0)) for field in _MARKDOWN_FLAG_FIELDS})
    hit["line_range"] = (
        {"start": line_range[0], "end": line_range[1]} if line_range is not None else None
    )
    hit["similarity"] = distance_to_similarity(dist)
    return hit


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

    ``n_results`` must be at least 1 (``InvalidArgumentError`` otherwise); values
    above MAX_SEARCH_RESULTS are clamped to it. Hits are in descending cosine
    similarity; each carries its drawer ``id``, and ``source_file`` is None for a
    drawer filed without a source (a manual or diary drawer).
    """
    n_results = _clamp_results(n_results)
    error_payload = validate_taxonomy_filters(palace_path, wing=wing, room=room)
    if error_payload is not None:
        return error_payload

    try:
        store = open_store(palace_path, create=False)
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return _missing_palace_payload(
            palace_path, query, "search_memories(query, palace_path, ...)"
        )

    try:
        ids, docs, metas, dists = _query_rows(
            store,
            query,
            n_results,
            _taxonomy_where(wing, room),
            intent_rerank=False,
        )
    except Exception as e:
        return {"error": f"Search error: {e}"}

    hits = [
        _project_hit(drawer_id, doc, meta, dist, missing_source=None)
        for drawer_id, doc, meta, dist in zip(ids, docs, metas, dists)
    ]

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
    # Terraform/HCL blocks (module is listed above)
    "resource",
    "data",
    "variable",
    "output",
    "check",
    "provider",
}


def _matching_values(store, column: str, keep) -> list[str]:
    """Return the distinct stored values of *column* accepted by *keep* (metadata-only scan)."""
    return sorted(value for value in store.count_by(column) if value and keep(value))


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

    Every filter narrows the rows *before* the vector scan ranks them, so a
    filter never misses a matching chunk that ranks outside the top candidates:
      - wing, language, symbol_type: LanceDB where equality.
      - symbol_name (case-insensitive substring) and file_glob (fnmatch against
        the stored source_file path; a glob not starting with ``/`` or ``*`` also
        matches a trailing part of the path, so ``src/*.py`` works): the matching
        distinct stored values are
        found with a metadata-only column scan and applied as a LanceDB
        ``IN`` prefilter. No matching value means an empty result without a
        vector query.

    Results are storage-ranked by default. ``ranking.storage_rank`` is the
    1-based position within this call's returned storage candidate pool;
    ``ranking.vector_distance`` is the unrounded distance returned by storage.
    Storage order is cosine order, except that .NET project-file and CamelCase
    symbol-intent queries get a deterministic bonus rerank (retrieval_rerank.py),
    so ``similarity`` is not always monotonic for those queries.

    rerank: Optional reranking mode. Only "hybrid" is accepted. Hybrid mode
        applies token-overlap reranking to the candidate pool and adds its score
        components under ``ranking``.
        search_memories and the print-oriented search() are unaffected.
    """
    n_results = _clamp_results(n_results)
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

    try:
        store = open_store(palace_path, create=False)
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return _missing_palace_payload(palace_path, query, "code_search(palace_path, query, ...)")

    envelope: dict[str, Any] = {
        "query": query,
        "filters": {
            "language": language,
            "symbol_name": symbol_name,
            "symbol_type": symbol_type,
            "file_glob": file_glob,
            "wing": wing,
        },
        "results": [],
    }

    # Build LanceDB where clause for pre-query filtering
    conditions: list[dict[str, Any]] = []
    if wing:
        conditions.append({"wing": wing})
    if language:
        conditions.append({"language": language})
    if symbol_type:
        conditions.append({"symbol_type": symbol_type})
    try:
        if symbol_name:
            needle = symbol_name.lower()
            names = _matching_values(store, "symbol_name", lambda v: needle in v.lower())
            if not names:
                return envelope
            conditions.append({"symbol_name": {"$in": names}})
        if file_glob:
            files = _matching_values(
                store, "source_file", lambda v: _file_glob_matches(v, file_glob)
            )
            if not files:
                return envelope
            conditions.append({"source_file": {"$in": files}})
    except Exception as e:
        return {"error": f"Search error: {e}"}

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
        ids, docs, metas, dists = _query_rows(store, query, fetch_count, where, intent_rerank=True)
    except Exception as e:
        return {"error": f"Search error: {e}"}

    # Build hit dicts for the full fetched pool
    raw_hits = []
    for storage_rank, (drawer_id, doc, meta, dist) in enumerate(
        zip(ids, docs, metas, dists), start=1
    ):
        hit = _project_hit(drawer_id, doc, meta, dist, missing_source="")
        hit["ranking"] = {"storage_rank": storage_rank, "vector_distance": dist}
        raw_hits.append(hit)

    if rerank == "hybrid":
        from .search_reranker import hybrid_rerank

        raw_hits = hybrid_rerank(query, raw_hits)

    # The prefilter already restricted rows; this exact re-check keeps the
    # documented semantics for any store that ignores the where clause.
    hits = []
    for hit in raw_hits:
        if symbol_name and symbol_name.lower() not in hit["symbol_name"].lower():
            continue
        if file_glob and not _file_glob_matches(hit["source_file"], file_glob):
            continue
        hits.append(hit)
        if len(hits) >= n_results:
            break

    envelope["results"] = hits
    return envelope
