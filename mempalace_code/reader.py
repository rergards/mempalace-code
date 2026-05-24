"""reader.py — Surgical read path: line-range pointer parsing and slice rendering.

Shared by both the MCP mempalace_read tool and the CLI mempalace-code read command.
Always reads from stored palace chunks — never falls back to live disk files.

Possible return shapes:
  Success:          {"source_file": str, "start": int, "end": int, "lines": [{"line": int, "text": str}, ...]}
  Not found:        {"error": "not_found", "source_file": str}
  Stale pointer:    {"error": "stale_pointer", "source_file": str, "detail": str}
  Invalid range:    {"error": "invalid_range", "detail": str}
  Ambiguous source: {"error": "ambiguous_source", "source_file": str, "candidates": [str, ...]}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _validate_range(start: Any, end: Any) -> tuple[int, int] | dict:
    """Return (start, end) as positive ints, or an error dict."""
    try:
        s = int(start)
        e = int(end)
    except (TypeError, ValueError):
        return {"error": "invalid_range", "detail": "start and end must be integers"}
    if s < 1 or e < 1:
        return {"error": "invalid_range", "detail": "start and end must be >= 1"}
    if s > e:
        return {"error": "invalid_range", "detail": f"start ({s}) must be <= end ({e})"}
    return s, e


def _overlaps(chunk_start: int, chunk_end: int, req_start: int, req_end: int) -> bool:
    """True when [chunk_start, chunk_end] and [req_start, req_end] overlap."""
    return chunk_start > 0 and chunk_end > 0 and chunk_start <= req_end and chunk_end >= req_start


def _lines_from_chunk(chunk_text: str, chunk_line_start: int, req_start: int, req_end: int):
    """Yield (file_line_no, line_text) pairs for lines that fall within [req_start, req_end]."""
    for i, line in enumerate(chunk_text.split("\n")):
        file_line_no = chunk_line_start + i
        if req_start <= file_line_no <= req_end:
            yield file_line_no, line


def _macos_var_aliases(path_str: str) -> set[str]:
    """Return the set of {path_str} plus its macOS /var <-> /private/var equivalent."""
    aliases: set[str] = {path_str}
    if path_str.startswith("/var/"):
        aliases.add("/private" + path_str)
    elif path_str.startswith("/private/var/"):
        aliases.add(path_str[len("/private"):])
    return aliases


def _ends_with_components(stored: str, query: str) -> bool:
    """True if the stored path ends with the same path components as query.

    Compares normalized components to avoid substring false-positives.
    E.g. 'auth.py' matches '/src/auth.py' but NOT '/src/my_auth.py'.
    """
    s_parts = Path(stored).parts
    q_parts = Path(query).parts
    if not q_parts or len(q_parts) > len(s_parts):
        return False
    return s_parts[-len(q_parts) :] == q_parts


def _collect_candidates(store: Any, wing: str | None) -> set[str]:
    """Collect all stored source_file values, optionally scoped to wing.

    Uses get_source_files(wing) fast path when the store supports it; falls back
    to a metadata scan otherwise.
    """
    if wing is not None:
        get_src = getattr(store, "get_source_files", None)
        if get_src is not None:
            fast = get_src(wing)
            if fast is not None:
                return fast
    # Fallback: metadata scan
    get_kwargs: dict[str, Any] = {"include": ["metadatas"], "limit": 100000}
    if wing is not None:
        get_kwargs["where"] = {"wing": wing}
    try:
        results = store.get(**get_kwargs)
    except Exception:
        return set()
    sources: set[str] = set()
    for meta in results.get("metadatas") or []:
        if meta:
            sf = meta.get("source_file")
            if sf:
                sources.add(sf)
    return sources


def _resolve_source_file(store: Any, source_file: str, wing: str | None) -> str | dict | None:
    """Resolve source_file input to a canonical stored path.

    Resolution order:
      1. Exact match against all stored source_file values (wing-scoped when provided).
      2. Exact macOS /var <-> /private/var alias match.
      3. Unique path-component suffix match (basename is a one-component suffix).
      4. ambiguous_source dict when multiple suffix candidates match.
      5. None when no candidate matches (caller converts to not_found).

    Invariant: exact matches are always preferred over suffix or alias resolution.
    The returned canonical path is always the value as stored in the palace.
    """
    candidates = _collect_candidates(store, wing)

    # 1. Exact match
    if source_file in candidates:
        return source_file

    # 2. macOS /var alias exact match
    aliases = _macos_var_aliases(source_file)
    alias_matches = aliases & candidates
    if len(alias_matches) == 1:
        return next(iter(alias_matches))
    if len(alias_matches) > 1:
        return {
            "error": "ambiguous_source",
            "source_file": source_file,
            "candidates": sorted(alias_matches),
        }

    # 3. Unique path-component suffix match
    suffix_matches = {c for c in candidates if _ends_with_components(c, source_file)}
    if len(suffix_matches) == 1:
        return next(iter(suffix_matches))
    if len(suffix_matches) > 1:
        return {
            "error": "ambiguous_source",
            "source_file": source_file,
            "candidates": sorted(suffix_matches),
        }

    return None


def read_slice(store, source_file: str, start: Any, end: Any, wing: str | None = None) -> dict:
    """Return the stored source lines in [start, end] for *source_file*.

    Args:
        store: Open DrawerStore instance.
        source_file: Source file to read — the exact stored path from search output,
                     or a unique basename/suffix within the wing.  macOS /var and
                     /private/var spellings of the same path are treated as equivalent.
        start: First line to include (1-indexed, inclusive).
        end: Last line to include (1-indexed, inclusive).
        wing: Optional wing filter passed through to the palace query.

    Returns a dict with one of the shapes documented at the module level.
    Invariant: never broadens to full file_context or live disk reads on failure.
    """
    validated = _validate_range(start, end)
    if isinstance(validated, dict):
        return validated
    req_start, req_end = validated

    resolved = _resolve_source_file(store, source_file, wing)
    if isinstance(resolved, dict):
        return resolved  # ambiguous_source
    if resolved is None:
        return {"error": "not_found", "source_file": source_file}
    canonical = resolved

    where: dict = (
        {"$and": [{"source_file": canonical}, {"wing": wing}]}
        if wing
        else {"source_file": canonical}
    )

    try:
        results = store.get(
            where=where,
            include=["documents", "metadatas"],
            limit=10000,
        )
    except Exception as exc:
        return {"error": "not_found", "source_file": source_file, "detail": str(exc)}

    if not results.get("ids"):
        return {"error": "not_found", "source_file": source_file}

    overlapping: list[tuple[int, int, str]] = []
    for doc, meta in zip(results["documents"], results["metadatas"]):
        ls = int(meta.get("line_start", 0) or 0)
        le = int(meta.get("line_end", 0) or 0)
        if _overlaps(ls, le, req_start, req_end):
            overlapping.append((ls, le, doc or ""))

    if not overlapping:
        return {
            "error": "stale_pointer",
            "source_file": canonical,
            "detail": f"no stored chunk overlaps range [{req_start}, {req_end}]",
        }

    # Sort by start line so output is always ordered
    overlapping.sort(key=lambda t: t[0])

    seen_lines: set[int] = set()
    lines_out: list[dict] = []
    for chunk_start, _chunk_end, chunk_text in overlapping:
        for line_no, line_text in _lines_from_chunk(chunk_text, chunk_start, req_start, req_end):
            if line_no not in seen_lines:
                seen_lines.add(line_no)
                lines_out.append({"line": line_no, "text": line_text})

    lines_out.sort(key=lambda d: d["line"])

    return {
        "source_file": canonical,
        "start": req_start,
        "end": req_end,
        "lines": lines_out,
    }
