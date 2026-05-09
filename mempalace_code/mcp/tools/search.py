"""mempalace_code.mcp.tools.search — Semantic search, code search, duplicate check, file context."""

from ...language_catalog import code_search_language_description
from .. import runtime


def tool_search(query: str, limit: int = 5, wing: str = None, room: str = None):
    from ...searcher import search_memories

    return search_memories(
        query,
        palace_path=runtime._config.palace_path,
        wing=wing,
        room=room,
        n_results=limit,
    )


def tool_code_search(
    query: str,
    language: str = None,
    symbol_name: str = None,
    symbol_type: str = None,
    file_glob: str = None,
    wing: str = None,
    n_results: int = 10,
    rerank: str = None,
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


def tool_check_duplicate(content: str, threshold: float = 0.9):
    col = runtime._get_store()
    if not col:
        return runtime._no_palace()
    try:
        results = col.query(
            query_texts=[content],
            n_results=5,
            include=["metadatas", "documents", "distances"],
        )
        duplicates = []
        if results["ids"] and results["ids"][0]:
            for i, drawer_id in enumerate(results["ids"][0]):
                dist = results["distances"][0][i]
                similarity = round(1 - dist, 3)
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


def tool_file_context(source_file: str, wing: str = None):
    """Return all indexed chunks for a source file, ordered by chunk_index."""
    if not source_file:
        return {
            "error": "source_file must be a non-empty path",
            "hint": "Provide an exact file path like 'mempalace/storage.py'",
        }

    col = runtime._get_store()
    if not col:
        return runtime._no_palace()

    where = (
        {"$and": [{"source_file": source_file}, {"wing": wing}]}
        if wing
        else {"source_file": source_file}
    )

    try:
        results = col.get(
            where=where,
            include=["documents", "metadatas"],
            limit=10000,
        )
    except Exception as e:
        return {"error": str(e), "hint": runtime._DEGRADED_HINT}

    if not results["ids"]:
        return {"source_file": source_file, "wing": wing, "total": 0, "chunks": []}

    chunks = []
    for doc, meta in zip(results["documents"], results["metadatas"]):
        chunks.append(
            {
                "chunk_index": meta.get("chunk_index", 0),
                "content": doc,
                "symbol_name": meta.get("symbol_name", ""),
                "symbol_type": meta.get("symbol_type", ""),
                "wing": meta.get("wing", ""),
                "room": meta.get("room", ""),
                "language": meta.get("language", ""),
                "line_range": None,
            }
        )

    chunks.sort(key=lambda x: x["chunk_index"])

    return {"source_file": source_file, "wing": wing, "total": len(chunks), "chunks": chunks}


TOOL_SPECS = {
    "mempalace_search": {
        "description": "Semantic search. Returns verbatim drawer content with similarity scores. Each hit includes wing, room, source_file, symbol_name, symbol_type, language, and similarity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
                "wing": {"type": "string", "description": "Filter by wing (optional)"},
                "room": {"type": "string", "description": "Filter by room (optional)"},
            },
            "required": ["query"],
        },
        "handler": tool_search,
    },
    "mempalace_code_search": {
        "description": (
            "Code-optimized search. Returns symbol name, type, language, and file path per hit. "
            "Use this instead of mempalace_search when looking for code symbols, functions, or files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
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
                        "deployment, service, configmap, secret, ingress, customresourcedefinition)"
                    ),
                },
                "file_glob": {
                    "type": "string",
                    "description": "Filter by file path glob (e.g. */mempalace/*.py)",
                },
                "wing": {"type": "string", "description": "Filter by wing (optional)"},
                "n_results": {
                    "type": "integer",
                    "description": "Max results to return, 1–50 (default 10)",
                },
                "rerank": {
                    "type": "string",
                    "description": "Optional reranker. Use 'hybrid' for BM25-style token overlap reranking; omit for vector order.",
                },
            },
            "required": ["query"],
        },
        "handler": tool_code_search,
    },
    "mempalace_file_context": {
        "description": (
            "Get all indexed chunks for a source file, ordered by chunk_index. "
            "Use to review what was mined for a file, understand deleted/renamed files, "
            "or get ordered file context without reading the file from disk. "
            "Returns {source_file, wing, total, chunks} where each chunk has "
            "chunk_index, content, symbol_name, symbol_type, wing, room, language, line_range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_file": {
                    "type": "string",
                    "description": "Exact source file path to retrieve chunks for",
                },
                "wing": {
                    "type": "string",
                    "description": "Filter to a specific wing (optional)",
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
                "content": {"type": "string", "description": "Content to check"},
                "threshold": {
                    "type": "number",
                    "description": "Similarity threshold 0-1 (default 0.9)",
                },
            },
            "required": ["content"],
        },
        "handler": tool_check_duplicate,
    },
}
