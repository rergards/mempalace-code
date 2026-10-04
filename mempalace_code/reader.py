"""reader.py — Surgical read path: line-range pointer parsing and slice rendering.

Shared by the MCP mempalace_read and mempalace_file_context tools and the CLI
mempalace-code read command. Always reads from stored palace chunks — never
falls back to live disk files.

Possible read_slice return shapes:
  Success:          {"source_file": str, "start": int, "end": int,
                     "first_indexed_line": int, "last_indexed_line": int,
                     "lines": [{"line": int, "text": str}, ...],
                     "gaps": [{"start": int, "end": int}, ...]}
                    plus "unplaced_chunks": int when some stored chunks of the file carry
                    no line range. "end" is clamped to last_indexed_line; "gaps" lists the
                    requested lines no stored chunk covers (blank separator lines between
                    chunks, or lines before first_indexed_line that mining did not store).
  Not found:        {"error": "not_found", "source_file": str}
  Store error:      {"error": "store_error", "source_file": str, "detail": str}
  Out of range:     {"error": "out_of_range", "source_file": str, "detail": str,
                     "last_indexed_line": int}
                    plus "unplaced_chunks": int when some stored chunks of the file carry
                    no line range (content after last_indexed_line may be stored in them).
  No line metadata: {"error": "no_line_metadata", "source_file": str, "detail": str,
                     "chunks": int, "conversation": bool}
  Invalid range:    {"error": "invalid_range", "detail": str}
  Ambiguous source: {"error": "ambiguous_source", "source_file": str, "candidates": [str, ...]}
  Unknown wing:      {"error": "unknown_wing", "filter": "wing", "value": str, "suggestions": [str, ...]}
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypedDict, cast

from . import taxonomy_filters

if TYPE_CHECKING:
    from collections.abc import Iterator


class _TaxonomyFiltersModule(Protocol):
    def validate_wing_against_store(
        self, store: Any, wing: str | None
    ) -> dict[str, Any] | None: ...


# taxonomy_filters.py sits outside the strict slice and declares a bare `dict`
# return type. This local cast re-declares the boundary so its Unknown component
# doesn't leak into this file's strict-checked results.
_taxonomy_filters = cast("_TaxonomyFiltersModule", taxonomy_filters)
_validate_wing_against_store = _taxonomy_filters.validate_wing_against_store

# Upper bound per metadata query; follow offsets to retrieve the complete source.
_MAX_SOURCE_ROWS = 10000


class ReaderStore(Protocol):
    """Structural boundary for the palace store methods read_slice depends on.

    Any DrawerStore backend (currently LanceStore) satisfies this
    structurally — reader.py never imports a concrete store class.
    """

    def get(
        self,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
        limit: int = 10000,
        offset: int = 0,
    ) -> dict[str, list[Any]]: ...

    def get_source_files(self, wing: str) -> set[str] | None: ...

    def count_by(self, column: str) -> dict[str, int]: ...


class ReadLine(TypedDict):
    line: int
    text: str


class ReadGap(TypedDict):
    start: int
    end: int


class _ReadSuccessRequired(TypedDict):
    source_file: str
    start: int
    end: int
    first_indexed_line: int
    last_indexed_line: int
    lines: list[ReadLine]
    gaps: list[ReadGap]


class ReadSuccess(_ReadSuccessRequired, total=False):
    """unplaced_chunks is present only when some stored chunks carry no line range."""

    unplaced_chunks: int


class ReadNotFound(TypedDict):
    error: Literal["not_found"]
    source_file: str


class ReadStoreError(TypedDict):
    """store.get() raised: the palace could not be read, which is not a missing file."""

    error: Literal["store_error"]
    source_file: str
    detail: str


class _ReadOutOfRangeRequired(TypedDict):
    error: Literal["out_of_range"]
    source_file: str
    detail: str
    last_indexed_line: int


class ReadOutOfRange(_ReadOutOfRangeRequired, total=False):
    """unplaced_chunks is present only when some stored chunks carry no line range."""

    unplaced_chunks: int


class ReadNoLineMetadata(TypedDict):
    error: Literal["no_line_metadata"]
    source_file: str
    detail: str
    chunks: int
    conversation: bool


class ReadInvalidRange(TypedDict):
    error: Literal["invalid_range"]
    detail: str


class ReadAmbiguousSource(TypedDict):
    error: Literal["ambiguous_source"]
    source_file: str
    candidates: list[str]


class ReadUnknownWing(TypedDict):
    error: Literal["unknown_wing"]
    filter: str
    value: str
    suggestions: list[str]


ReadError = (
    ReadNotFound
    | ReadStoreError
    | ReadOutOfRange
    | ReadNoLineMetadata
    | ReadInvalidRange
    | ReadAmbiguousSource
    | ReadUnknownWing
)
ReadResult = ReadSuccess | ReadError


@dataclass(frozen=True)
class SourceRows:
    """Every stored chunk of one resolved source file."""

    source_file: str
    ids: list[str]
    documents: list[str]
    metadatas: list[dict[str, Any]]


def _validate_range(start: Any, end: Any) -> tuple[int, int] | ReadInvalidRange:
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


def _lines_from_chunk(
    chunk_text: str, chunk_line_start: int, req_start: int, req_end: int
) -> Iterator[tuple[int, str]]:
    """Yield (file_line_no, line_text) pairs for lines that fall within [req_start, req_end]."""
    for i, line in enumerate(chunk_text.split("\n")):
        file_line_no = chunk_line_start + i
        if req_start <= file_line_no <= req_end:
            yield file_line_no, line


def _rejoin_long_lines(
    chunks: list[tuple[int, int, str, int, str]],
) -> dict[tuple[str, int], str]:
    """Return {(wing, line): full text} for source lines stored as several pieces.

    Mining cuts a line longer than its hard split into consecutive chunks that
    each cover only that line; joining them in chunk_index order restores the
    line verbatim. *chunks* are (line_start, line_end, wing, chunk_index, text).
    """
    pieces: dict[tuple[str, int], dict[int, str]] = {}
    for line_start, line_end, wing, index, text in chunks:
        if line_start == line_end and "\n" not in text:
            pieces.setdefault((wing, line_start), {}).setdefault(index, text)
    joined: dict[tuple[str, int], str] = {}
    for key, by_index in pieces.items():
        order = sorted(by_index)
        if len(order) > 1 and order == list(range(order[0], order[0] + len(order))):
            joined[key] = "".join(by_index[i] for i in order)
    return joined


def _macos_var_aliases(path_str: str) -> set[str]:
    """Return the set of {path_str} plus its macOS /var,/tmp <-> /private/var,/private/tmp equivalents."""
    aliases: set[str] = {path_str}
    if path_str.startswith("/var/"):
        aliases.add("/private" + path_str)
    elif path_str.startswith("/private/var/"):
        aliases.add(path_str[len("/private") :])
    elif path_str.startswith("/tmp/"):
        aliases.add("/private" + path_str)
    elif path_str.startswith("/private/tmp/"):
        aliases.add(path_str[len("/private") :])
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


def _exact_candidates(source_file: str) -> list[str]:
    """Return the exact stored-path spellings *source_file* may have, most literal first.

    The input as given, its normalized form (``a/../b`` and ``./`` collapsed),
    the symlink-resolved absolute path (mine stores resolved project paths and
    resolves a relative project path against the working directory), and the
    macOS /var and /tmp aliases of each, each also in Unicode NFC and NFD form
    (a path pasted on macOS is often NFD while the stored path is NFC).
    """
    spellings = [source_file, os.path.normpath(source_file)]
    try:
        spellings.append(os.path.realpath(source_file))
    except OSError:  # a relative input needs the working directory, which may be gone
        pass
    ordered: list[str] = []
    for spelling in spellings:
        for candidate in [spelling, *sorted(_macos_var_aliases(spelling) - {spelling})]:
            for form in (
                candidate,
                unicodedata.normalize("NFC", candidate),
                unicodedata.normalize("NFD", candidate),
            ):
                if form not in ordered:
                    ordered.append(form)
    return ordered


def _collect_candidates(store: ReaderStore, wing: str | None) -> set[str]:
    """Collect every stored source_file value, optionally scoped to wing.

    Both paths are projected metadata scans with no row cap. Store errors
    propagate: LanceStore.get() returns no rows on a degraded table, so this scan
    is where a damaged palace shows up during path resolution.
    """
    if wing is not None:
        scoped = store.get_source_files(wing)
        if scoped is not None:
            return scoped
    return {source for source in store.count_by("source_file") if source}


def _scoped_where(source_where: dict[str, Any], wing: str | None) -> dict[str, Any]:
    return {"$and": [source_where, {"wing": wing}]} if wing else source_where


def _rows_for(
    store: ReaderStore, source_where: dict[str, Any], wing: str | None
) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = {"ids": [], "documents": [], "metadatas": []}
    offset = 0
    while True:
        batch = store.get(
            where=_scoped_where(source_where, wing),
            include=["documents", "metadatas"],
            limit=_MAX_SOURCE_ROWS,
            offset=offset,
        )
        for column in result:
            result[column].extend(batch.get(column) or [])
        count = len(batch.get("ids") or [])
        if count < _MAX_SOURCE_ROWS:
            return result
        offset += count


def _source_rows(results: dict[str, list[Any]], source_file: str) -> SourceRows:
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    for drawer_id, doc, meta in zip(
        results.get("ids") or [], results.get("documents") or [], results.get("metadatas") or []
    ):
        meta_dict = cast("dict[str, Any]", meta or {})
        if meta_dict.get("source_file") != source_file:
            continue
        ids.append(str(drawer_id))
        documents.append(str(doc or ""))
        metadatas.append(meta_dict)
    return SourceRows(source_file, ids, documents, metadatas)


def resolve_source_rows(
    store: ReaderStore, source_file: str, wing: str | None = None
) -> SourceRows | ReadNotFound | ReadStoreError | ReadAmbiguousSource:
    """Resolve *source_file* to one stored path and return all of its stored chunks.

    Resolution order:
      1. Exact match of the input, its normalized form, its symlink-resolved absolute
         form (a relative input resolves against the working directory, like mine),
         or a macOS /var and /tmp alias — one filtered lookup, no full scan.
      2. Unique path-component suffix match of the normalized input (a basename is
         a one-component suffix) against every stored source_file (wing-scoped when
         provided).
      3. ambiguous_source when several stored paths share that suffix.
      4. not_found when nothing matches.

    A store read failure is store_error (with the exception text as detail), never
    not_found: a degraded palace is not a missing file.

    Invariant: exact matches are always preferred over suffix resolution, and the
    returned path is always the value as stored in the palace.
    """
    exact = _exact_candidates(source_file)
    try:
        results = _rows_for(store, {"source_file": {"$in": exact}}, wing)
    except Exception as exc:
        return {"error": "store_error", "source_file": source_file, "detail": str(exc)}
    found = {
        str(cast("dict[str, Any]", meta).get("source_file"))
        for meta in results.get("metadatas") or []
        if meta
    }
    for candidate in exact:
        if candidate in found:
            return _source_rows(results, candidate)

    try:
        candidates = _collect_candidates(store, wing)
    except Exception as exc:
        return {"error": "store_error", "source_file": source_file, "detail": str(exc)}
    query = unicodedata.normalize("NFC", os.path.normpath(source_file))
    suffix_matches = {
        c for c in candidates if _ends_with_components(unicodedata.normalize("NFC", c), query)
    }
    if len(suffix_matches) > 1:
        return {
            "error": "ambiguous_source",
            "source_file": source_file,
            "candidates": sorted(suffix_matches),
        }
    if not suffix_matches:
        return {"error": "not_found", "source_file": source_file}
    canonical = next(iter(suffix_matches))
    try:
        results = _rows_for(store, {"source_file": canonical}, wing)
    except Exception as exc:
        return {"error": "store_error", "source_file": canonical, "detail": str(exc)}
    rows = _source_rows(results, canonical)
    if not rows.ids:
        return {"error": "not_found", "source_file": canonical}
    return rows


def _line_bounds(meta: dict[str, Any]) -> tuple[int, int]:
    try:
        return int(meta.get("line_start", 0) or 0), int(meta.get("line_end", 0) or 0)
    except (TypeError, ValueError):
        return 0, 0


def _missing_runs(start: int, end: int, present: set[int]) -> list[ReadGap]:
    """Return maximal runs of line numbers in [start, end] that are not in *present*."""
    gaps: list[ReadGap] = []
    run_start: int | None = None
    for line_no in range(start, end + 1):
        if line_no in present:
            if run_start is not None:
                gaps.append({"start": run_start, "end": line_no - 1})
                run_start = None
        elif run_start is None:
            run_start = line_no
    if run_start is not None:
        gaps.append({"start": run_start, "end": end})
    return gaps


def _no_line_metadata(rows: SourceRows) -> ReadNoLineMetadata:
    conversation = all(meta.get("ingest_mode") == "convos" for meta in rows.metadatas)
    count = len(rows.ids)
    if conversation:
        detail = (
            f"{rows.source_file} holds {count} conversation drawer(s); conversation drawers "
            "have no line ranges, so read cannot address lines. Use search to see their text."
        )
    else:
        detail = (
            f"none of the {count} stored chunk(s) of {rows.source_file} carry a line range, "
            "so read cannot address lines. Use search or mempalace_file_context to see "
            "their text."
        )
    return {
        "error": "no_line_metadata",
        "source_file": rows.source_file,
        "detail": detail,
        "chunks": count,
        "conversation": conversation,
    }


def read_slice(
    store: ReaderStore, source_file: str, start: Any, end: Any, wing: str | None = None
) -> dict[str, Any]:
    """Return the stored source lines in [start, end] for *source_file*.

    Declared as ``dict[str, Any]`` rather than the narrower ``ReadResult`` union so
    existing CLI/MCP callers can keep branching on ``result["error"]`` without
    exhaustive TypedDict narrowing at every call site (see ReadResult for the
    documented shape of each variant).

    Args:
        store: Open DrawerStore instance.
        source_file: Source file to read — the exact stored path from search output,
                     a symlinked or non-normalized spelling of it, or a unique
                     basename/suffix within the wing. macOS /var and /private/var
                     spellings of the same path are treated as equivalent.
        start: First line to include (1-indexed, inclusive).
        end: Last line to include (1-indexed, inclusive); clamped to the last
             indexed line.
        wing: Optional wing filter passed through to the palace query.

    Returns a dict with one of the shapes documented at the module level.
    Invariant: never broadens to full file_context or live disk reads on failure.
    """
    validated = _validate_range(start, end)
    if isinstance(validated, dict):
        return cast("dict[str, Any]", validated)
    req_start, req_end = validated

    if wing is not None:
        taxonomy_error = _validate_wing_against_store(store, wing)
        if taxonomy_error is not None:
            return taxonomy_error

    rows = resolve_source_rows(store, source_file, wing)
    if not isinstance(rows, SourceRows):
        return cast("dict[str, Any]", rows)

    placed: list[tuple[int, int, str, int, str]] = []
    for doc, meta in zip(rows.documents, rows.metadatas):
        ls, le = _line_bounds(meta)
        if ls > 0 and le >= ls:
            index = int(meta.get("chunk_index", 0) or 0)
            placed.append((ls, le, str(meta.get("wing") or ""), index, doc or ""))
    unplaced = len(rows.ids) - len(placed)

    if not placed:
        return cast("dict[str, Any]", _no_line_metadata(rows))

    first_line = min(chunk[0] for chunk in placed)
    last_line = max(chunk[1] for chunk in placed)
    if req_start > last_line:
        detail = (
            f"range [{req_start}, {req_end}] starts after the last indexed line "
            f"{last_line} of {rows.source_file}"
        )
        if unplaced:
            detail += (
                f"; {unplaced} more stored chunk(s) of this file carry no line range, so "
                f"content after line {last_line} may be stored but cannot be read by line "
                "number. Use search or mempalace_file_context to see those chunks."
            )
        out_of_range: ReadOutOfRange = {
            "error": "out_of_range",
            "source_file": rows.source_file,
            "detail": detail,
            "last_indexed_line": last_line,
        }
        if unplaced:
            out_of_range["unplaced_chunks"] = unplaced
        return cast("dict[str, Any]", out_of_range)
    read_end = min(req_end, last_line)

    # Sort by start line (then wing and chunk order) so output is always ordered; the
    # first chunk to cover a line wins. A long line stored as several pieces is rejoined.
    overlapping = [chunk for chunk in placed if _overlaps(chunk[0], chunk[1], req_start, read_end)]
    overlapping.sort(key=lambda t: (t[0], t[2], t[3]))
    long_lines = _rejoin_long_lines(overlapping)
    texts: dict[int, str] = {}
    for chunk_start, chunk_end, chunk_wing, _index, chunk_text in overlapping:
        if chunk_start == chunk_end and (chunk_wing, chunk_start) in long_lines:
            chunk_text = long_lines[(chunk_wing, chunk_start)]
        for line_no, line_text in _lines_from_chunk(chunk_text, chunk_start, req_start, read_end):
            texts.setdefault(line_no, line_text)

    lines_out: list[ReadLine] = [
        {"line": line_no, "text": texts[line_no]} for line_no in sorted(texts)
    ]
    success: ReadSuccess = {
        "source_file": rows.source_file,
        "start": req_start,
        "end": read_end,
        "first_indexed_line": first_line,
        "last_indexed_line": last_line,
        "lines": lines_out,
        "gaps": _missing_runs(req_start, read_end, set(texts)),
    }
    if unplaced:
        success["unplaced_chunks"] = unplaced
    return cast("dict[str, Any]", success)
