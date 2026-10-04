"""mempalace_code.mcp.tools.kg — Knowledge-graph query/add/invalidate/timeline/stats handlers."""

from .. import runtime

_DEFAULT_PAGE = 100
_MAX_PAGE = 1000


def _page_bounds(limit: int | None, offset: int | None) -> tuple[int, int] | dict:
    """Return (limit, offset) for a paginated KG tool, or an error payload."""
    limit = _DEFAULT_PAGE if limit is None else limit
    offset = 0 if offset is None else offset
    if not 1 <= limit <= _MAX_PAGE:
        return {"error": f"limit must be between 1 and {_MAX_PAGE}", "limit": limit}
    if offset < 0:
        return {"error": "offset must be 0 or greater", "offset": offset}
    return limit, offset


def _page_fields(total: int, offset: int, returned: int) -> dict:
    truncated = offset + returned < total
    return {
        "count": returned,
        "total": total,
        "offset": offset,
        "truncated": truncated,
        "next_offset": offset + returned if truncated else None,
    }


def tool_kg_query(
    entity: str,
    as_of: str | None = None,
    direction: str = "both",
    limit: int | None = None,
    offset: int | None = None,
):
    """Query the knowledge graph for an entity's relationships."""
    bounds = _page_bounds(limit, offset)
    if isinstance(bounds, dict):
        return bounds
    limit, offset = bounds
    results = runtime._get_kg().query_entity(entity, as_of=as_of, direction=direction)
    page = results[offset : offset + limit]
    return {
        "entity": entity,
        "as_of": as_of,
        "facts": page,
        **_page_fields(len(results), offset, len(page)),
    }


def tool_kg_add(
    subject: str,
    predicate: str,
    object: str,
    valid_from: str | None = None,
    valid_to: str | None = None,
    source_closet: str | None = None,
    source_file: str | None = None,
):
    """Add a relationship to the knowledge graph."""
    report = runtime._get_kg().add_triple_report(
        subject,
        predicate,
        object,
        valid_from=valid_from,
        valid_to=valid_to,
        source_closet=source_closet,
        source_file=source_file,
    )
    result = {
        "success": True,
        "created": report["created"],
        "triple_id": report["triple_id"],
        "fact": f"{report['subject']} → {report['predicate']} → {report['object']}",
        "valid_from": report["valid_from"],
        "valid_to": report["valid_to"],
        "other_current": report["other_current"],
    }
    notes = []
    if report.get("same_fact_current"):
        result["same_fact_current"] = report["same_fact_current"]
        notes.append(
            "This fact is already current with the stored validity window above, which "
            "overlaps the requested one; nothing was added. To set its end date, call "
            "mempalace_kg_invalidate with ended; to record a different window, invalidate "
            "it first."
        )
    elif not report["created"]:
        notes.append(
            "An identical fact is already stored; nothing changed and the stored "
            "validity window above was kept."
        )
    if report["other_current"]:
        notes.append(
            "Other facts are current for this subject and predicate. If this fact "
            "replaces one of them, retire it with mempalace_kg_invalidate (omit ended, "
            "or pass the day before the new valid_from)."
        )
    if notes:
        result["note"] = " ".join(notes)
    return result


def tool_kg_invalidate(subject: str, predicate: str, object: str, ended: str | None = None):
    """Mark a fact as no longer true (set end date)."""
    report = runtime._get_kg().invalidate(subject, predicate, object, ended=ended)
    fact = f"{report['subject']} → {report['predicate']} → {report['object']}"
    if report["invalidated"]:
        return {
            "success": True,
            "fact": fact,
            "invalidated": report["invalidated"],
            "ended": report["ended"],
        }
    return {
        "success": False,
        "error": "no_current_fact",
        "message": "No open fact matched this subject, predicate, and object; nothing changed.",
        "fact": fact,
        "invalidated": 0,
        "already_ended": report["already_ended"],
        "current_objects": report["current_objects"],
        "hint": (
            "Query the entity with mempalace_kg_query and pass the exact stored subject, "
            "predicate, and object of a fact whose current field is true."
        ),
    }


def tool_kg_timeline(
    entity: str | None = None, limit: int | None = None, offset: int | None = None
):
    """Get chronological timeline of facts, optionally for one entity."""
    bounds = _page_bounds(limit, offset)
    if isinstance(bounds, dict):
        return bounds
    limit, offset = bounds
    kg = runtime._get_kg()
    results = kg.timeline(entity, limit=limit, offset=offset)
    return {
        "entity": entity or "all",
        "timeline": results,
        **_page_fields(kg.timeline_total(entity), offset, len(results)),
    }


def tool_kg_stats():
    """Knowledge graph overview: entities, triples, relationship types."""
    return runtime._get_kg().stats()


_LIMIT_SCHEMA = {
    "type": "integer",
    "minimum": 1,
    "maximum": _MAX_PAGE,
    "description": f"Maximum facts to return (default {_DEFAULT_PAGE}, max {_MAX_PAGE})",
}
_OFFSET_SCHEMA = {
    "type": "integer",
    "minimum": 0,
    "description": "Facts to skip, e.g. the next_offset of the previous page (default 0)",
}

TOOL_SPECS = {
    "mempalace_kg_query": {
        "description": (
            "Query an entity's typed relationships. Without as_of, returns historical, "
            "current, and future facts; for present state, filter the returned facts where "
            "the current output field is true (current is not an input argument). With as_of, "
            "filters facts to that date while the current output field still reports present "
            "wall-clock state. Entity names are case-insensitive; facts show the stored "
            "display names. Results are paged: limit (default 100, max 1000) and offset; "
            "total, truncated, and next_offset report what remains."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "Entity to query (e.g. 'Max', 'MyProject', 'Alice')",
                },
                "as_of": {
                    "type": "string",
                    "description": "Date filter — only facts valid at this date (YYYY-MM-DD, optional)",
                },
                "direction": {
                    "type": "string",
                    "enum": ["outgoing", "incoming", "both"],
                    "description": "outgoing (entity→?), incoming (?→entity), or both (default: both)",
                },
                "limit": _LIMIT_SCHEMA,
                "offset": _OFFSET_SCHEMA,
            },
            "required": ["entity"],
        },
        "handler": tool_kg_query,
    },
    "mempalace_kg_add": {
        "description": (
            "Add a fact to the knowledge graph. Subject → predicate → object with optional "
            "time window. E.g. ('Max', 'started_school', 'Year 7', valid_from='2026-09-01'). "
            "The response echoes the stored fact: entity names are case-insensitive and keep "
            "their first stored spelling, predicates are lowercased with spaces as "
            "underscores, and other_current lists the other current facts for the same subject "
            "and predicate (empty when none). created is false when an identical fact already "
            "existed, or when a current copy of the same fact overlaps the requested window "
            "(same_fact_current lists it; end it with the knowledge-graph invalidate tool)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "The entity doing/being something"},
                "predicate": {
                    "type": "string",
                    "description": "The relationship type (e.g. 'loves', 'works_on', 'daughter_of')",
                },
                "object": {"type": "string", "description": "The entity being connected to"},
                "valid_from": {
                    "type": "string",
                    "description": "When this became true (YYYY-MM-DD or UTC datetime, optional)",
                },
                "valid_to": {
                    "type": "string",
                    "description": "When this stopped being true (YYYY-MM-DD or UTC datetime, optional)",
                },
                "source_closet": {
                    "type": "string",
                    "description": "Closet ID where this fact appears (optional)",
                },
                "source_file": {
                    "type": "string",
                    "description": "Source file path where this fact was extracted (optional)",
                },
            },
            "required": ["subject", "predicate", "object"],
        },
        "handler": tool_kg_add,
    },
    "mempalace_kg_invalidate": {
        "description": (
            "Mark a fact as no longer true. E.g. ankle injury resolved, job ended, moved "
            "house. Only an open fact with this exact subject, predicate, and object changes; "
            "the response reports how many facts were invalidated and the stored end time, "
            "or success false with the current objects when nothing matched."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Entity"},
                "predicate": {"type": "string", "description": "Relationship"},
                "object": {"type": "string", "description": "Connected entity"},
                "ended": {
                    "type": "string",
                    "description": (
                        "When it stopped being true (YYYY-MM-DD or UTC ISO datetime; omit for "
                        "now). A date is an inclusive end-of-day bound, so the fact stays "
                        "current for the rest of that UTC day."
                    ),
                },
            },
            "required": ["subject", "predicate", "object"],
        },
        "handler": tool_kg_invalidate,
    },
    "mempalace_kg_timeline": {
        "description": (
            "Chronological timeline of facts. Shows the story of an entity (or everything) "
            "ordered by valid_from, undated facts last. Results are paged: limit (default "
            "100, max 1000) and offset; total, truncated, and next_offset report what remains."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "Entity to get timeline for (optional — omit for full timeline)",
                },
                "limit": _LIMIT_SCHEMA,
                "offset": _OFFSET_SCHEMA,
            },
        },
        "handler": tool_kg_timeline,
    },
    "mempalace_kg_stats": {
        "description": "Knowledge graph overview: entities, triples, current, expired, and future facts, relationship types.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_kg_stats,
    },
}
