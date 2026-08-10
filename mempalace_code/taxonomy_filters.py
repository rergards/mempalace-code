"""taxonomy_filters.py — Shared explicit wing/room filter validation contract.

Every public retrieval surface (CLI search/read, the Python searcher/reader
APIs, and the MCP search/read/architecture tools) validates explicit wing and
room filters against the palace taxonomy *before* running semantic search or
resolving source candidates. This module is the single place that decides
what "unknown" means and how it is reported so all surfaces agree.

Contract:
  - Validation is metadata-only: it opens the store read-only and calls
    count_by_pair("wing", "room") — it never initializes an embedder or runs
    a vector query.
  - A missing palace (nothing on disk yet) or a degraded palace (taxonomy
    read fails) is NOT reported as an unknown-taxonomy error — callers keep
    their existing no-palace/degraded-palace handling for those cases.
  - Suggestions are advisory only. They may rank a close identifier higher,
    but the supplied filter value is never rewritten, normalized, or
    silently substituted.

Error payload shape (returned as a dict, propagated unchanged by every
caller):
    {"error": "unknown_wing" | "unknown_room" | "unknown_wing_room",
     "filter": "wing" | "room" | "wing_room",
     "value": <original supplied value(s), unmodified>,
     "suggestions": [<at most 3 candidate identifiers>]}
"""

from __future__ import annotations

import difflib
import re
from typing import Any

_SUGGESTION_LIMIT = 3
_SUGGESTION_MIN_RATIO = 0.4

_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def _normalize_for_suggestion(value: str) -> str:
    """Casefold and strip punctuation so 'migrate_openclaw' ~ 'migrate-openclaw'."""
    return _PUNCT_RE.sub("", value.lower())


def _rank_suggestions(value: str, candidates: list[str]) -> list[str]:
    """Rank *candidates* by normalized similarity to *value*; bounded to 3.

    Ranking is for suggestion ordering only — it never feeds back into the
    requested filter value or the returned `value` field.
    """
    norm_value = _normalize_for_suggestion(value)
    if not norm_value:
        return []

    scored = []
    for candidate in sorted(set(candidates)):
        norm_candidate = _normalize_for_suggestion(candidate)
        if not norm_candidate:
            continue
        ratio = difflib.SequenceMatcher(None, norm_value, norm_candidate).ratio()
        if ratio >= _SUGGESTION_MIN_RATIO:
            scored.append((ratio, candidate))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [candidate for _, candidate in scored[:_SUGGESTION_LIMIT]]


def _load_taxonomy(store: Any) -> dict[str, dict[str, int]] | None:
    """Return the wing -> room -> count taxonomy from *store*, or None on failure."""
    try:
        return store.count_by_pair("wing", "room")
    except Exception:
        return None


def validate_wing_room_against_taxonomy(
    taxonomy: dict[str, dict[str, int]],
    wing: str | None = None,
    room: str | None = None,
) -> dict | None:
    """Validate explicit *wing*/*room* against an already-loaded taxonomy snapshot.

    Validation order: unknown wing first, then room-only global existence,
    then exact wing/room pair existence. Returns None when the supplied
    filters are valid (or none were supplied); otherwise a structured error
    dict with a stable error code, filter name, supplied value, and bounded
    advisory suggestions.

    An empty taxonomy (palace initialized but nothing mined yet, or every
    drawer removed) has no wings or rooms to validate against — this is
    treated the same as a missing/degraded palace and skips validation,
    rather than reporting every supplied filter as unknown.
    """
    if not wing and not room:
        return None

    if not taxonomy:
        return None

    if wing and wing not in taxonomy:
        return {
            "error": "unknown_wing",
            "filter": "wing",
            "value": wing,
            "suggestions": _rank_suggestions(wing, list(taxonomy.keys())),
        }

    if room:
        all_rooms = {r for rooms in taxonomy.values() for r in rooms}
        if room not in all_rooms:
            return {
                "error": "unknown_room",
                "filter": "room",
                "value": room,
                "suggestions": _rank_suggestions(room, sorted(all_rooms)),
            }

    if wing and room:
        wing_rooms = taxonomy.get(wing, {})
        if room not in wing_rooms:
            return {
                "error": "unknown_wing_room",
                "filter": "wing_room",
                "value": {"wing": wing, "room": room},
                "suggestions": _rank_suggestions(room, sorted(wing_rooms.keys())),
            }

    return None


def validate_taxonomy_filters(
    palace_path: str, wing: str | None = None, room: str | None = None
) -> dict | None:
    """Validate explicit wing/room filters against the palace taxonomy.

    Opens the store read-only for a metadata-only taxonomy read — never
    initializes an embedder. Returns None (skip validation) when no filters
    are supplied, when the palace does not exist on disk yet, or when the
    taxonomy read fails; those cases are left to each caller's existing
    no-palace/degraded-palace handling.
    """
    if not wing and not room:
        return None

    from .storage import LanceStore, open_store

    try:
        store = open_store(palace_path, create=False, read_only=True)
    except Exception:
        return None

    if isinstance(store, LanceStore) and store._db is None:
        return None

    taxonomy = _load_taxonomy(store)
    if taxonomy is None:
        return None

    return validate_wing_room_against_taxonomy(taxonomy, wing=wing, room=room)


def validate_wing_against_store(store: Any, wing: str | None) -> dict | None:
    """Validate an explicit wing filter against a taxonomy loaded from an open *store*.

    For callers that already hold an open store (e.g. read_slice) rather than
    a palace_path — avoids opening a second store handle.
    """
    if not wing:
        return None
    taxonomy = _load_taxonomy(store)
    if taxonomy is None:
        return None
    return validate_wing_room_against_taxonomy(taxonomy, wing=wing)


class TaxonomyValidationError(Exception):
    """Raised by print-oriented search() when an explicit taxonomy filter is unknown.

    Carries the structured validation payload so the CLI wrapper can print
    it and exit with status 2.
    """

    def __init__(self, payload: dict):
        self.payload = payload
        super().__init__(payload.get("error", "taxonomy_validation_error"))


def format_cli_lines(payload: dict) -> list[str]:
    """Return actionable stderr lines for a taxonomy validation error payload."""
    code = payload.get("error")
    value = payload.get("value")
    suggestions = payload.get("suggestions") or []

    if code == "unknown_wing_room":
        wing = value.get("wing") if isinstance(value, dict) else value
        room = value.get("room") if isinstance(value, dict) else None
        lines = [f"\n  Unknown wing/room pair: wing={wing!r} room={room!r}"]
    elif code == "unknown_room":
        lines = [f"\n  Unknown room: {value!r}"]
    else:
        lines = [f"\n  Unknown wing: {value!r}"]

    if suggestions:
        lines.append(f"  Did you mean: {', '.join(suggestions)}?")

    lines.append(
        "  Next: run mempalace-code status, or check mempalace_list_wings / "
        "mempalace_list_rooms / mempalace_get_taxonomy for valid taxonomy identifiers "
        "— filters are validated against the palace taxonomy and suggestions are advisory only."
    )
    return lines
