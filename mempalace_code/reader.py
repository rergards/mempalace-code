"""reader.py — Surgical read path: line-range pointer parsing and slice rendering.

Shared by both the MCP mempalace_read tool and the CLI mempalace-code read command.
Always reads from stored palace chunks — never falls back to live disk files.

Possible return shapes:
  Success:       {"source_file": str, "start": int, "end": int, "lines": [{"line": int, "text": str}, ...]}
  Not found:     {"error": "not_found", "source_file": str}
  Stale pointer: {"error": "stale_pointer", "source_file": str, "detail": str}
  Invalid range: {"error": "invalid_range", "detail": str}
"""

from __future__ import annotations

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


def read_slice(store, source_file: str, start: Any, end: Any, wing: str | None = None) -> dict:
    """Return the stored source lines in [start, end] for *source_file*.

    Args:
        store: Open DrawerStore instance.
        source_file: Exact source_file path as stored in the palace.
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

    where: dict = (
        {"$and": [{"source_file": source_file}, {"wing": wing}]}
        if wing
        else {"source_file": source_file}
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
            "source_file": source_file,
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
        "source_file": source_file,
        "start": req_start,
        "end": req_end,
        "lines": lines_out,
    }
