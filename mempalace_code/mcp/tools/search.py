"""mempalace_code.mcp.tools.search — Semantic search, code search, duplicate check, file context."""

from typing import Any

from ...errors import InvalidArgumentError
from ...language_catalog import code_search_language_description
from ...searcher import MAX_QUERY_CHARS, MAX_SEARCH_RESULTS
from ...storage import distance_to_similarity
from .. import runtime
from .write import MAX_DRAWER_CHARS


def tool_search(
    query: str,
    limit: int | None = None,
    wing: str | None = None,
    room: str | None = None,
    *,
    max_results: int | None = None,
):
    from ...searcher import search_memories

    if limit is not None and max_results is not None and limit != max_results:
        raise InvalidArgumentError(
            "limit and max_results must match when both are supplied", argument="max_results"
        )
    result_limit = limit if limit is not None else max_results
    if result_limit is None:
        result_limit = 5
    return search_memories(
        query,
        palace_path=runtime._config.palace_path,
        wing=wing,
        room=room,
        n_results=result_limit,
    )


def tool_code_search(
    query: str,
    language: str | None = None,
    symbol_name: str | None = None,
    symbol_type: str | None = None,
    file_glob: str | None = None,
    wing: str | None = None,
    n_results: int = 10,
    rerank: str | None = None,
):
    from ...searcher import code_search

    return code_search(
        palace_path=runtime._config.palace_path,
        query=query,
        language=language,
        symbol_name=symbol_name,
        symbol_type=symbol_type,
        file_glob=file_glob,
        wing=wing,
        n_results=n_results,
        rerank=rerank,
    )


def tool_check_duplicate(content: str, threshold: float = 0.9) -> dict[str, Any]:
    col = runtime._get_store()
    if not col:
        return runtime._no_palace()
    try:
        results = col.query(
            query_texts=[content],
            n_results=5,
            include=["metadatas", "documents", "distances"],
            intent_rerank=False,
        )
        duplicates = []
        if results["ids"] and results["ids"][0]:
            for i, drawer_id in enumerate(results["ids"][0]):
                dist = results["distances"][0][i]
                similarity = distance_to_similarity(dist)
                if similarity >= threshold:
                    meta = results["metadatas"][0][i]
                    doc = results["documents"][0][i]
                    duplicates.append(
                        {
                            "id": drawer_id,
                            "wing": meta.get("wing", "?"),
                            "room": meta.get("room", "?"),
                            "similarity": similarity,
                            "content": doc[:200] + "..." if len(doc) > 200 else doc,
                        }
                    )
        return {
            "is_duplicate": len(duplicates) > 0,
            "matches": duplicates,
        }
    except Exception as e:
        return {"error": str(e)}


FILE_CONTEXT_DEFAULT_LIMIT = 20
FILE_CONTEXT_MAX_LIMIT = 100


def tool_file_context(
    source_file: str,
    wing: str | None = None,
    limit: int = FILE_CONTEXT_DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Return one page of the indexed chunks for a source file, ordered by chunk_index.

    source_file resolves like mempalace_read (exact, symlinked/normalized, or a
    unique suffix); an unknown file is not_found and a shared suffix is
    ambiguous_source rather than an empty success.
    """
    if not source_file:
        return {
            "error": "source_file must be a non-empty path",
            "hint": "Provide an exact file path like 'mempalace/storage.py'",
        }
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError):
        return {"error": "invalid_page", "detail": "limit and offset must be integers"}
    if offset < 0:
        return {"error": "invalid_page", "detail": "offset must be >= 0"}
    limit = max(1, min(FILE_CONTEXT_MAX_LIMIT, limit))

    col = runtime._get_store()
    if not col:
        return runtime._no_palace()

    if wing:
        from ...taxonomy_filters import validate_wing_against_store

        taxonomy_error = validate_wing_against_store(col, wing)
        if taxonomy_error is not None:
            return taxonomy_error

    from ...reader import SourceRows, resolve_source_rows

    rows = resolve_source_rows(col, source_file, wing)
    if not isinstance(rows, SourceRows):
        if rows["error"] == "store_error":
            return {**rows, "hint": runtime._degraded_hint()}
        return dict(rows)

    chunks = []
    for drawer_id, doc, meta in zip(rows.ids, rows.documents, rows.metadatas):
        ls = int(meta.get("line_start", 0) or 0)
        le = int(meta.get("line_end", 0) or 0)
        chunks.append(
            {
                "id": drawer_id,
                "chunk_index": meta.get("chunk_index", 0),
                "content": doc,
                "symbol_name": meta.get("symbol_name", ""),
                "symbol_type": meta.get("symbol_type", ""),
                "wing": meta.get("wing", ""),
                "room": meta.get("room", ""),
                "language": meta.get("language", ""),
                "line_range": {"start": ls, "end": le} if ls > 0 and le >= ls else None,
            }
        )

    chunks.sort(key=lambda x: x["chunk_index"])
    page = chunks[offset : offset + limit]
    next_offset = offset + len(page)

    return {
        "source_file": rows.source_file,
        "wing": wing,
        "total": len(chunks),
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset if next_offset < len(chunks) else None,
        "chunks": page,
    }


def tool_read(
    source_file: str,
    start_line: int,
    end_line: int,
    wing: str | None = None,
) -> dict[str, Any]:
    """Surgical read: return only the stored lines in [start_line, end_line] for source_file."""
    if not source_file:
        return {
            "error": "invalid_range",
            "detail": "source_file must be a non-empty path",
        }

    col = runtime._get_store()
    if not col:
        return runtime._no_palace()

    from ...reader import read_slice

    result = read_slice(col, source_file, start_line, end_line, wing=wing)
    if result.get("error") == "store_error":
        return {**result, "hint": runtime._degraded_hint()}
    return result


TOOL_SPECS = {
    "mempalace_search": {
        "description": (
            "Semantic search. Returns verbatim drawer content with similarity scores, in "
            "descending similarity. Each hit includes the drawer id, wing, room, source_file "
            "(null for drawers filed without a source), symbol_name, symbol_type, "
            "language, line_range, and similarity; Markdown hits add heading, heading_level, "
            "heading_path, doc_section_type, and contains_mermaid/code/table. "
            "An explicit wing/room filter is validated against the palace taxonomy before search; "
            "an unknown wing/room returns a structured error with advisory suggestions, while a "
            "valid empty scope returns a successful {results: []}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "maxLength": MAX_QUERY_CHARS,
                    "description": "What to search for",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_SEARCH_RESULTS,
                    "description": "Max results, 1–50 (default 5)",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_SEARCH_RESULTS,
                    "description": (
                        "Alias for limit, 1 to 50 (default 5). "
                        "If both are supplied, their values must match."
                    ),
                },
                "wing": {
                    "type": "string",
                    "description": (
                        "Filter by wing (optional) — validated against the palace taxonomy; "
                        "unknown values return a structured error with advisory suggestions"
                    ),
                },
                "room": {
                    "type": "string",
                    "description": (
                        "Filter by room (optional) — validated against the palace taxonomy; "
                        "unknown values return a structured error with advisory suggestions"
                    ),
                },
            },
            "required": ["query"],
        },
        "handler": tool_search,
    },
    "mempalace_code_search": {
        "description": (
            "Code-optimized search. Returns the drawer id, symbol name, type, language, file "
            "path, line_range, Markdown section fields for Markdown hits, and ranking evidence "
            "per hit. All filters (language, symbol_name, symbol_type, file_glob, wing) narrow "
            "the rows before ranking, so a filter finds every matching indexed chunk. "
            "Results use storage-ranked order by default; ranking.storage_rank "
            "is the position in this call's returned candidate pool and ranking.vector_distance "
            "is the storage distance. Storage order is cosine order except that .NET "
            "project-file and CamelCase symbol-intent queries get a deterministic bonus rerank, "
            "so similarity is not always monotonic. Hybrid reranking additionally reports "
            "lexical_score, input_rank_score, and hybrid_score. Prefer this over plain "
            "semantic search when looking for code symbols, functions, or files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "maxLength": MAX_QUERY_CHARS,
                    "description": "What to search for",
                },
                "language": {
                    "type": "string",
                    "description": code_search_language_description(),
                },
                "symbol_name": {
                    "type": "string",
                    "description": "Filter by symbol name — case-insensitive substring match",
                },
                "symbol_type": {
                    "type": "string",
                    "description": (
                        "Filter by symbol type "
                        "(function, class, method, struct, interface, "
                        "record, enum, property, event, module, union, type, view, exception, "
                        "typealias, protocol, actor, extension, trait, namespace, "
                        "object, case_class, case_object, "
                        "mixin, extension_type, constructor, "
                        "local_function, "
                        "deployment, service, configmap, secret, ingress, customresourcedefinition, "
                        "helm_chart, helm_values, "
                        "ansible_play, ansible_task, ansible_handler, ansible_role, "
                        "ansible_vars, ansible_inventory, "
                        "resource, data, variable, output, check, provider)"
                    ),
                },
                "file_glob": {
                    "type": "string",
                    "description": (
                        "Filter by file path glob, e.g. src/*.py, storage.py, or */tests/*. "
                        "A glob that does not start with '/' or '*' matches the end of the "
                        "stored path at a '/' boundary (repo-relative paths work); '*' also "
                        "matches '/'. An absolute glob matches the whole stored path"
                    ),
                },
                "wing": {
                    "type": "string",
                    "description": (
                        "Filter by wing (optional) — validated against the palace taxonomy; "
                        "unknown values return a structured error with advisory suggestions"
                    ),
                },
                "n_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_SEARCH_RESULTS,
                    "description": "Max results to return, 1–50 (default 10)",
                },
                "rerank": {
                    "type": "string",
                    "description": (
                        "Optional reranker. Use 'hybrid' for token-overlap reranking with score "
                        "evidence; omit for storage-ranked order."
                    ),
                },
            },
            "required": ["query"],
        },
        "handler": tool_code_search,
    },
    "mempalace_file_context": {
        "description": (
            "Get the indexed chunks for a source file, ordered by chunk_index, one page at a "
            "time. Use to review what was mined for a file, understand deleted/renamed files, "
            "or get ordered file context without reading the file from disk. "
            "Returns {source_file, wing, total, offset, limit, next_offset, chunks} where total "
            "counts every chunk of the file, next_offset is null on the last page, and each "
            "chunk has id, chunk_index, content, symbol_name, symbol_type, wing, room, language, "
            "line_range. source_file may be the stored path, a symlinked or Unicode-normalized "
            "spelling of it, or a unique path suffix; {error: not_found} for an "
            "unknown file, {error: ambiguous_source} when a suffix matches several files, and "
            "{error: store_error, detail, hint} when the palace cannot be read."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_file": {
                    "type": "string",
                    "description": (
                        "Source file: the stored path from a search hit, a symlinked or "
                        "non-normalized spelling of it, or a unique basename/suffix"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": FILE_CONTEXT_MAX_LIMIT,
                    "description": "Chunks per page, 1–100 (default 20)",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Chunks to skip; pass the previous next_offset (default 0)",
                },
                "wing": {
                    "type": "string",
                    "description": (
                        "Filter to a specific wing (optional) — validated against the palace "
                        "taxonomy; unknown values return a structured error with advisory suggestions"
                    ),
                },
            },
            "required": ["source_file"],
        },
        "handler": tool_file_context,
    },
    "mempalace_check_duplicate": {
        "description": "Check if content already exists in the palace before filing",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "maxLength": MAX_DRAWER_CHARS,
                    "description": "Content to check",
                },
                "threshold": {
                    "type": "number",
                    "minimum": -1,
                    "maximum": 1,
                    "description": (
                        "Minimum cosine similarity counted as a duplicate, -1 to 1 "
                        "(1.0 = identical; default 0.9)"
                    ),
                },
            },
            "required": ["content"],
        },
        "handler": tool_check_duplicate,
    },
    "mempalace_read": {
        "description": (
            "Surgical read: return only the stored source lines in the given range for a file. "
            "Use after a code_search or file_context hit to read exactly the lines you need "
            "without loading the whole file. "
            "Returns {source_file, start, end, first_indexed_line, last_indexed_line, lines, "
            "gaps} on success: end is clamped to last_indexed_line and gaps lists requested "
            "lines no stored chunk covers (blank lines between chunks, or lines before "
            "first_indexed_line that mining did not store); unplaced_chunks counts stored "
            "chunks with no line range, whose text only search or file_context shows; "
            "{error: not_found} when the file has no indexed chunks; "
            "{error: ambiguous_source} when a suffix matches several files; "
            "{error: out_of_range} when start is past last_indexed_line (with unplaced_chunks "
            "when later content may sit in chunks without line ranges); "
            "{error: no_line_metadata} when the file's drawers carry no line ranges "
            "(conversation drawers never do) — use search or file_context instead; "
            "{error: invalid_range} for bad line numbers; "
            "{error: store_error, detail, hint} when the palace cannot be read; "
            "{error: unknown_wing} when an explicit wing filter is not in the palace taxonomy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_file": {
                    "type": "string",
                    "description": (
                        "Source file: the stored path from a search hit's source_file field, a "
                        "symlinked or non-normalized spelling of it, or a unique basename/suffix"
                    ),
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to include (1-indexed, inclusive)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to include (1-indexed, inclusive)",
                },
                "wing": {
                    "type": "string",
                    "description": (
                        "Filter to a specific wing (optional) — validated against the palace "
                        "taxonomy; unknown values return a structured error with advisory suggestions"
                    ),
                },
            },
            "required": ["source_file", "start_line", "end_line"],
        },
        "handler": tool_read,
    },
}
