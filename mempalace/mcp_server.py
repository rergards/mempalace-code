#!/usr/bin/env python3
"""
MemPalace MCP Server — read/write palace access for Claude Code
================================================================
Install: claude mcp add mempalace -- python -m mempalace.mcp_server

Tools (read):
  mempalace_status          — total drawers, wing/room breakdown
  mempalace_list_wings      — all wings with drawer counts
  mempalace_list_rooms      — rooms within a wing
  mempalace_get_taxonomy    — full wing → room → count tree
  mempalace_search          — semantic search, optional wing/room filter
  mempalace_code_search     — code-optimized search with symbol/language/file filters
  mempalace_check_duplicate — check if content already exists before filing

Tools (architecture — queries pre-mined KG type relationships):
  mempalace_find_implementations  — find all types implementing a given interface
  mempalace_find_references       — find all usages of a type (implementors, subclasses, deps)
  mempalace_show_project_graph    — project-level dependency graph, optionally filtered by solution
  mempalace_show_type_dependencies — inheritance/implementation chain for a type (ancestors + descendants)

Tools (write):
  mempalace_add_drawer      — file verbatim content into a wing/room
  mempalace_delete_drawer   — remove a drawer by ID
"""

import os
import sys
import json
import logging
import hashlib
import uuid
from datetime import datetime
from typing import Optional

from .config import MempalaceConfig
from .version import __version__
from .searcher import code_search, search_memories
from .palace_graph import traverse, find_tunnels, graph_stats
from .storage import open_store, DrawerStore, LanceStore

from .knowledge_graph import KnowledgeGraph

_kg = KnowledgeGraph()

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("mempalace_mcp")

_config = MempalaceConfig()

# Singleton store — opened once, reused across all tool calls
_store: Optional[DrawerStore] = None


def _get_store(create=False) -> Optional[DrawerStore]:
    """Return the drawer store, or None on failure."""
    global _store
    if _store is not None:
        return _store
    try:
        new_store = open_store(_config.palace_path, create=create)
        # Don't cache a LanceStore whose backing table is missing: a subsequent
        # call with create=True would get the stub and fail.  Keep retrying
        # until the palace is actually initialised.
        if not (isinstance(new_store, LanceStore) and new_store._table is None):
            _store = new_store
        return new_store
    except Exception:
        return None


def _no_palace():
    return {
        "error": "No palace found",
        "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
    }


_DEGRADED_HINT = "Run: mempalace health && mempalace repair --rollback --dry-run"


def _degraded_response(exc: Exception, **extra) -> dict:
    """Return a structured degraded-palace response when taxonomy calls fail but count() works."""
    return {
        "error": f"palace degraded: {exc}",
        "hint": _DEGRADED_HINT,
        **extra,
    }


# ==================== READ TOOLS ====================


def tool_status():
    col = _get_store()
    if not col:
        return _no_palace()
    count = col.count()
    wings: dict = {}
    rooms: dict = {}
    try:
        taxonomy = col.count_by_pair("wing", "room")
        for w, room_counts in taxonomy.items():
            wings[w] = sum(room_counts.values())
            for r, c in room_counts.items():
                rooms[r] = rooms.get(r, 0) + c
    except Exception as e:
        return _degraded_response(e, total_drawers=count, palace_path=_config.palace_path)
    result = {
        "total_drawers": count,
        "wings": wings,
        "rooms": rooms,
        "palace_path": _config.palace_path,
    }
    if os.environ.get("MEMPALACE_AAAK") == "1":
        result["protocol"] = PALACE_PROTOCOL
        result["aaak_dialect"] = AAAK_SPEC
    return result


# ── AAAK Dialect Spec ─────────────────────────────────────────────────────────
# Included in status response only when MEMPALACE_AAAK=1 (opt-in).
# Not exposed as an MCP tool in v1.0 — kept dormant.

PALACE_PROTOCOL = """IMPORTANT — MemPalace Memory Protocol:
1. ON WAKE-UP: Call mempalace_status to load palace overview + AAAK spec.
2. BEFORE RESPONDING about any person, project, or past event: call mempalace_kg_query or mempalace_search FIRST. Never guess — verify.
3. IF UNSURE about a fact (name, gender, age, relationship): say "let me check" and query the palace. Wrong is worse than slow.
4. AFTER EACH SESSION: call mempalace_diary_write to record what happened, what you learned, what matters.
5. WHEN FACTS CHANGE: call mempalace_kg_invalidate on the old fact, mempalace_kg_add for the new one.

This protocol ensures the AI KNOWS before it speaks. Storage is not memory — but storage + this protocol = memory."""

AAAK_SPEC = """AAAK is a compressed memory dialect that MemPalace uses for efficient storage.
It is designed to be readable by both humans and LLMs without decoding.

FORMAT:
  ENTITIES: 3-letter uppercase codes. ALC=Alice, JOR=Jordan, RIL=Riley, MAX=Max, BEN=Ben.
  EMOTIONS: *action markers* before/during text. *warm*=joy, *fierce*=determined, *raw*=vulnerable, *bloom*=tenderness.
  STRUCTURE: Pipe-separated fields. FAM: family | PROJ: projects | ⚠: warnings/reminders.
  DATES: ISO format (2026-03-31). COUNTS: Nx = N mentions (e.g., 570x).
  IMPORTANCE: ★ to ★★★★★ (1-5 scale).
  HALLS: hall_facts, hall_events, hall_discoveries, hall_preferences, hall_advice.
  WINGS: wing_user, wing_agent, wing_team, wing_code, wing_myproject, wing_hardware, wing_ue5, wing_ai_research.
  ROOMS: Hyphenated slugs representing named ideas (e.g., chromadb-setup, gpu-pricing).

EXAMPLE:
  FAM: ALC→♡JOR | 2D(kids): RIL(18,sports) MAX(11,chess+swimming) | BEN(contributor)

Read AAAK naturally — expand codes mentally, treat *markers* as emotional context.
When WRITING AAAK: use entity codes, mark emotions, keep structure tight."""


def tool_list_wings():
    col = _get_store()
    if not col:
        return _no_palace()
    try:
        wings = col.count_by("wing")
    except Exception as e:
        return _degraded_response(e, wings={})
    return {"wings": wings}


def tool_list_rooms(wing: str = None):
    col = _get_store()
    if not col:
        return _no_palace()
    rooms: dict = {}
    try:
        taxonomy = col.count_by_pair("wing", "room")
        if wing:
            rooms = taxonomy.get(wing, {})
        else:
            for wing_rooms in taxonomy.values():
                for r, c in wing_rooms.items():
                    rooms[r] = rooms.get(r, 0) + c
    except Exception as e:
        return _degraded_response(e, wing=wing or "all", rooms={})
    return {"wing": wing or "all", "rooms": rooms}


def tool_get_taxonomy():
    col = _get_store()
    if not col:
        return _no_palace()
    try:
        taxonomy = col.count_by_pair("wing", "room")
    except Exception as e:
        return _degraded_response(e, taxonomy={})
    return {"taxonomy": taxonomy}


def tool_search(query: str, limit: int = 5, wing: str = None, room: str = None):
    return search_memories(
        query,
        palace_path=_config.palace_path,
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
):
    return code_search(
        palace_path=_config.palace_path,
        query=query,
        language=language,
        symbol_name=symbol_name,
        symbol_type=symbol_type,
        file_glob=file_glob,
        wing=wing,
        n_results=n_results,
    )


def tool_check_duplicate(content: str, threshold: float = 0.9):
    col = _get_store()
    if not col:
        return _no_palace()
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


def tool_get_aaak_spec():
    """Return the AAAK dialect specification."""
    return {"aaak_spec": AAAK_SPEC}


def tool_traverse_graph(start_room: str, max_hops: int = 2):
    """Walk the palace graph from a room. Find connected ideas across wings."""
    col = _get_store()
    if not col:
        return _no_palace()
    return traverse(start_room, col=col, max_hops=max_hops)


def tool_find_tunnels(wing_a: str = None, wing_b: str = None):
    """Find rooms that bridge two wings — the hallways connecting domains."""
    col = _get_store()
    if not col:
        return _no_palace()
    return find_tunnels(wing_a, wing_b, col=col)


def tool_graph_stats():
    """Palace graph overview: nodes, tunnels, edges, connectivity."""
    col = _get_store()
    if not col:
        return _no_palace()
    return graph_stats(col=col)


# ==================== WRITE TOOLS ====================


def tool_add_drawer(
    wing: str, room: str, content: str, source_file: str = None, added_by: str = "mcp"
):
    """File verbatim content into a wing/room. Checks for duplicates first."""
    col = _get_store(create=True)
    if not col:
        return _no_palace()

    # Duplicate check
    dup = tool_check_duplicate(content, threshold=0.9)
    if dup.get("is_duplicate"):
        return {
            "success": False,
            "reason": "duplicate",
            "matches": dup["matches"],
        }

    drawer_id = f"drawer_{wing}_{room}_{hashlib.md5((content[:100] + datetime.now().isoformat()).encode()).hexdigest()[:16]}"

    try:
        col.add(
            ids=[drawer_id],
            documents=[content],
            metadatas=[
                {
                    "wing": wing,
                    "room": room,
                    "source_file": source_file or "",
                    "chunk_index": 0,
                    "added_by": added_by,
                    "filed_at": datetime.now().isoformat(),
                    "extractor_version": __version__,
                    "chunker_strategy": "manual_v1",
                }
            ],
        )
        logger.info(f"Filed drawer: {drawer_id} → {wing}/{room}")
        return {"success": True, "drawer_id": drawer_id, "wing": wing, "room": room}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_delete_drawer(drawer_id: str):
    """Delete a single drawer by ID."""
    col = _get_store()
    if not col:
        return _no_palace()
    existing = col.get(ids=[drawer_id])
    if not existing["ids"]:
        return {"success": False, "error": f"Drawer not found: {drawer_id}"}
    try:
        col.delete(ids=[drawer_id])
        logger.info(f"Deleted drawer: {drawer_id}")
        return {"success": True, "drawer_id": drawer_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_delete_wing(wing: str):
    """Delete all drawers in a wing. Irreversible."""
    col = _get_store()
    if not col:
        return _no_palace()
    existing = col.get(where={"wing": wing}, limit=1)
    if not existing["ids"]:
        return {"success": False, "error": f"Wing not found: {wing}"}
    try:
        deleted_count = col.delete_wing(wing)
        logger.info(f"Deleted wing: {wing} ({deleted_count} drawers)")
        return {"success": True, "wing": wing, "deleted_count": deleted_count}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== KNOWLEDGE GRAPH ====================


def tool_kg_query(entity: str, as_of: str = None, direction: str = "both"):
    """Query the knowledge graph for an entity's relationships."""
    results = _kg.query_entity(entity, as_of=as_of, direction=direction)
    return {"entity": entity, "as_of": as_of, "facts": results, "count": len(results)}


def tool_kg_add(
    subject: str, predicate: str, object: str, valid_from: str = None, source_closet: str = None
):
    """Add a relationship to the knowledge graph."""
    triple_id = _kg.add_triple(
        subject, predicate, object, valid_from=valid_from, source_closet=source_closet
    )
    return {"success": True, "triple_id": triple_id, "fact": f"{subject} → {predicate} → {object}"}


def tool_kg_invalidate(subject: str, predicate: str, object: str, ended: str = None):
    """Mark a fact as no longer true (set end date)."""
    _kg.invalidate(subject, predicate, object, ended=ended)
    return {
        "success": True,
        "fact": f"{subject} → {predicate} → {object}",
        "ended": ended or "today",
    }


def tool_kg_timeline(entity: str = None):
    """Get chronological timeline of facts, optionally for one entity."""
    results = _kg.timeline(entity)
    return {"entity": entity or "all", "timeline": results, "count": len(results)}


def tool_kg_stats():
    """Knowledge graph overview: entities, triples, relationship types."""
    return _kg.stats()


# ==================== ARCHITECTURE TOOLS ====================


def tool_find_implementations(interface: str) -> dict:
    """Find all types that implement a given interface in the KG."""
    facts = _kg.query_entity(interface, direction="incoming")
    implementations = []
    for f in facts:
        if f["predicate"] == "implements" and f["current"]:
            entry = {"type": f["subject"]}
            if f.get("source_closet"):
                entry["source_closet"] = f["source_closet"]
            implementations.append(entry)
    return {
        "interface": interface,
        "implementations": implementations,
        "count": len(implementations),
    }


def tool_find_references(type_name: str) -> dict:
    """Find all usages of a type — incoming and outgoing KG relationships grouped by category."""
    facts = _kg.query_entity(type_name, direction="both")
    current_facts = [f for f in facts if f["current"]]

    # Map (direction, predicate) → canonical category name
    category_map = {
        ("incoming", "implements"): "implementors",
        ("incoming", "inherits"): "subclasses",
        ("incoming", "extends"): "sub_interfaces",
        ("outgoing", "implements"): "implements",
        ("outgoing", "inherits"): "inherits",
        ("outgoing", "extends"): "extends",
        ("incoming", "depends_on"): "depended_by",
        ("incoming", "references_project"): "referenced_by",
        ("outgoing", "depends_on"): "depends_on",
        ("outgoing", "references_project"): "references_project",
    }

    categories: dict = {}
    for fact in current_facts:
        key = (fact["direction"], fact["predicate"])
        cat = category_map.get(key)
        if cat is None:
            continue
        entry_type = fact["subject"] if fact["direction"] == "incoming" else fact["object"]
        categories.setdefault(cat, []).append({"type": entry_type})

    return {
        "type": type_name,
        "references": categories,
        "total": sum(len(v) for v in categories.values()),
    }


def tool_show_project_graph(solution: str = None) -> dict:
    """Show project-level dependency graph from the KG, optionally filtered by solution."""
    PROJECT_PREDICATES = [
        "depends_on",
        "references_project",
        "targets_framework",
        "has_output_type",
        "contains_project",
    ]

    all_triples: dict = {}
    for pred in PROJECT_PREDICATES:
        rows = _kg.query_relationship(pred)
        all_triples[pred] = [r for r in rows if r["current"]]

    if solution is not None:
        sol_id = _kg._entity_id(solution)
        # Projects contained in this solution
        contained_projects = {
            r["object"]
            for r in all_triples.get("contains_project", [])
            if _kg._entity_id(r["subject"]) == sol_id
        }
        filtered: dict = {}
        for pred in PROJECT_PREDICATES:
            if pred == "contains_project":
                filtered[pred] = [
                    r for r in all_triples[pred] if _kg._entity_id(r["subject"]) == sol_id
                ]
            else:
                filtered[pred] = [
                    r for r in all_triples[pred] if r["subject"] in contained_projects
                ]
        all_triples = filtered

    return {
        "solution": solution,
        "graph": {pred: triples for pred, triples in all_triples.items() if triples},
    }


def tool_show_type_dependencies(type_name: str, max_depth: int = 3) -> dict:
    """Show inheritance/implementation chain for a type — ancestors and descendants."""
    return _kg.type_dependency_chain(type_name, max_depth=max_depth)


# ==================== AGENT DIARY ====================


def tool_diary_write(agent_name: str, entry: str, topic: str = "general"):
    """
    Write a diary entry for this agent. Each agent gets its own wing
    with a diary room. Entries are timestamped and accumulate over time.

    This is the agent's personal journal — observations, thoughts,
    what it worked on, what it noticed, what it thinks matters.
    """
    wing = f"wing_{agent_name.lower().replace(' ', '_')}"
    room = "diary"
    col = _get_store(create=True)
    if not col:
        return _no_palace()

    now = datetime.now()
    entry_id = f"diary_{wing}_{uuid.uuid4().hex}"

    try:
        col.add(
            ids=[entry_id],
            documents=[entry],
            metadatas=[
                {
                    "wing": wing,
                    "room": room,
                    "hall": "hall_diary",
                    "topic": topic,
                    "type": "diary_entry",
                    "agent": agent_name,
                    "filed_at": now.isoformat(),
                    "date": now.strftime("%Y-%m-%d"),
                    "extractor_version": __version__,
                    "chunker_strategy": "diary_v1",
                }
            ],
        )
        logger.info(f"Diary entry: {entry_id} → {wing}/diary/{topic}")
        return {
            "success": True,
            "entry_id": entry_id,
            "agent": agent_name,
            "topic": topic,
            "timestamp": now.isoformat(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_diary_read(agent_name: str, last_n: int = 10):
    """
    Read an agent's recent diary entries. Returns the last N entries
    in chronological order — the agent's personal journal.
    """
    wing = f"wing_{agent_name.lower().replace(' ', '_')}"
    col = _get_store()
    if not col:
        return _no_palace()

    try:
        results = col.get(
            where={"$and": [{"wing": wing}, {"room": "diary"}]},
            include=["documents", "metadatas"],
            limit=col.count(),
        )

        if not results["ids"]:
            return {"agent": agent_name, "entries": [], "message": "No diary entries yet."}

        # Combine and sort by timestamp
        entries = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            entries.append(
                {
                    "date": meta.get("date", ""),
                    "timestamp": meta.get("filed_at", ""),
                    "topic": meta.get("topic", ""),
                    "content": doc,
                }
            )

        entries.sort(key=lambda x: x["timestamp"], reverse=True)
        entries = entries[:last_n]

        return {
            "agent": agent_name,
            "entries": entries,
            "total": len(results["ids"]),
            "showing": len(entries),
        }
    except Exception as e:
        return {"error": str(e)}


# ==================== MCP PROTOCOL ====================

TOOLS = {
    "mempalace_status": {
        "description": "Palace overview — total drawers, wing and room counts",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_status,
    },
    "mempalace_list_wings": {
        "description": "List all wings with drawer counts",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_list_wings,
    },
    "mempalace_list_rooms": {
        "description": "List rooms within a wing (or all rooms if no wing given)",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string", "description": "Wing to list rooms for (optional)"},
            },
        },
        "handler": tool_list_rooms,
    },
    "mempalace_get_taxonomy": {
        "description": "Full taxonomy: wing → room → drawer count",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_get_taxonomy,
    },
    "mempalace_kg_query": {
        "description": "Query the knowledge graph for an entity's relationships. Returns typed facts with temporal validity. E.g. 'Max' → child_of Alice, loves chess, does swimming. Filter by date with as_of to see what was true at a point in time.",
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
                    "description": "outgoing (entity→?), incoming (?→entity), or both (default: both)",
                },
            },
            "required": ["entity"],
        },
        "handler": tool_kg_query,
    },
    "mempalace_kg_add": {
        "description": "Add a fact to the knowledge graph. Subject → predicate → object with optional time window. E.g. ('Max', 'started_school', 'Year 7', valid_from='2026-09-01').",
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
                    "description": "When this became true (YYYY-MM-DD, optional)",
                },
                "source_closet": {
                    "type": "string",
                    "description": "Closet ID where this fact appears (optional)",
                },
            },
            "required": ["subject", "predicate", "object"],
        },
        "handler": tool_kg_add,
    },
    "mempalace_kg_invalidate": {
        "description": "Mark a fact as no longer true. E.g. ankle injury resolved, job ended, moved house.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Entity"},
                "predicate": {"type": "string", "description": "Relationship"},
                "object": {"type": "string", "description": "Connected entity"},
                "ended": {
                    "type": "string",
                    "description": "When it stopped being true (YYYY-MM-DD, default: today)",
                },
            },
            "required": ["subject", "predicate", "object"],
        },
        "handler": tool_kg_invalidate,
    },
    "mempalace_kg_timeline": {
        "description": "Chronological timeline of facts. Shows the story of an entity (or everything) in order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "Entity to get timeline for (optional — omit for full timeline)",
                },
            },
        },
        "handler": tool_kg_timeline,
    },
    "mempalace_kg_stats": {
        "description": "Knowledge graph overview: entities, triples, current vs expired facts, relationship types.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_kg_stats,
    },
    "mempalace_find_implementations": {
        "description": (
            "Find all types that implement a given interface in the knowledge graph. "
            "Queries pre-mined .NET type relationships — requires DOTNET-SYMBOL-GRAPH mining."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "interface": {
                    "type": "string",
                    "description": "Interface name to find implementations of (e.g. 'IService', 'IDisposable')",
                },
            },
            "required": ["interface"],
        },
        "handler": tool_find_implementations,
    },
    "mempalace_find_references": {
        "description": (
            "Find all usages of a type/interface — implementors, subclasses, dependencies. "
            "Returns relationships grouped by category: implementors, subclasses, sub_interfaces, "
            "implements, inherits, extends, depended_by, referenced_by, depends_on, references_project. "
            "Empty categories are omitted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type_name": {
                    "type": "string",
                    "description": "Type or project name to find references for",
                },
            },
            "required": ["type_name"],
        },
        "handler": tool_find_references,
    },
    "mempalace_show_project_graph": {
        "description": (
            "Show project-level dependency graph from the knowledge graph. "
            "Returns all depends_on, references_project, targets_framework, has_output_type, "
            "and contains_project triples. Optionally filtered to a single solution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "solution": {
                    "type": "string",
                    "description": "Filter to projects contained in this solution (optional)",
                },
            },
        },
        "handler": tool_show_project_graph,
    },
    "mempalace_show_type_dependencies": {
        "description": (
            "Show the inheritance/implementation chain for a type. "
            "Returns ancestors (what it inherits/implements/extends) and descendants "
            "(what inherits/implements it) as flat lists with depth metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type_name": {
                    "type": "string",
                    "description": "Type (class/interface) to show dependencies for",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Max inheritance depth to traverse (default 3)",
                },
            },
            "required": ["type_name"],
        },
        "handler": tool_show_type_dependencies,
    },
    "mempalace_traverse": {
        "description": "Walk the palace graph from a room. Shows connected ideas across wings — the tunnels. Like following a thread through the palace: start at 'chromadb-setup' in wing_code, discover it connects to wing_myproject (planning) and wing_user (feelings about it).",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_room": {
                    "type": "string",
                    "description": "Room to start from (e.g. 'chromadb-setup', 'riley-school')",
                },
                "max_hops": {
                    "type": "integer",
                    "description": "How many connections to follow (default: 2)",
                },
            },
            "required": ["start_room"],
        },
        "handler": tool_traverse_graph,
    },
    "mempalace_find_tunnels": {
        "description": "Find rooms that bridge two wings — the hallways connecting different domains. E.g. what topics connect wing_code to wing_team?",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing_a": {"type": "string", "description": "First wing (optional)"},
                "wing_b": {"type": "string", "description": "Second wing (optional)"},
            },
        },
        "handler": tool_find_tunnels,
    },
    "mempalace_graph_stats": {
        "description": "Palace graph overview: total rooms, tunnel connections, edges between wings.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_graph_stats,
    },
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
                    "description": (
                        "Filter by language (e.g. python, go, typescript, rust, java, cpp, c, "
                        "csharp, fsharp, vbnet, xaml, dotnet-solution, "
                        "sql, html, css, yaml, json, toml, terraform, hcl, dockerfile, make, "
                        "gotemplate, jinja2, conf, ini, markdown, text, csv)"
                    ),
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
                        "record, enum, property, event, module, union, type, view, exception)"
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
            },
            "required": ["query"],
        },
        "handler": tool_code_search,
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
    "mempalace_add_drawer": {
        "description": "File verbatim content into the palace. Checks for duplicates first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string", "description": "Wing (project name)"},
                "room": {
                    "type": "string",
                    "description": "Room (aspect: backend, decisions, meetings...)",
                },
                "content": {
                    "type": "string",
                    "description": "Verbatim content to store — exact words, never summarized",
                },
                "source_file": {"type": "string", "description": "Where this came from (optional)"},
                "added_by": {"type": "string", "description": "Who is filing this (default: mcp)"},
            },
            "required": ["wing", "room", "content"],
        },
        "handler": tool_add_drawer,
    },
    "mempalace_delete_drawer": {
        "description": "Delete a drawer by ID. Irreversible.",
        "input_schema": {
            "type": "object",
            "properties": {
                "drawer_id": {"type": "string", "description": "ID of the drawer to delete"},
            },
            "required": ["drawer_id"],
        },
        "handler": tool_delete_drawer,
    },
    "mempalace_delete_wing": {
        "description": "Delete ALL drawers in a wing. IRREVERSIBLE — use before re-mining a project to clear stale data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {
                    "type": "string",
                    "description": "Wing name whose drawers should be deleted",
                },
            },
            "required": ["wing"],
        },
        "handler": tool_delete_wing,
    },
    "mempalace_diary_write": {
        "description": "Write a session diary entry for an agent. Record observations, thoughts, what you worked on, what matters. Each agent has their own diary wing with full history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Your name — each agent gets their own diary wing",
                },
                "entry": {
                    "type": "string",
                    "description": "Your diary entry — plain text",
                },
                "topic": {
                    "type": "string",
                    "description": "Topic tag (optional, default: general)",
                },
            },
            "required": ["agent_name", "entry"],
        },
        "handler": tool_diary_write,
    },
    "mempalace_diary_read": {
        "description": "Read your recent diary entries. See what past versions of yourself recorded — your journal across sessions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Your name — each agent gets their own diary wing",
                },
                "last_n": {
                    "type": "integer",
                    "description": "Number of recent entries to read (default: 10)",
                },
            },
            "required": ["agent_name"],
        },
        "handler": tool_diary_read,
    },
}


def handle_request(request):
    method = request.get("method", "")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mempalace", "version": __version__},
            },
        }
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {"name": n, "description": t["description"], "inputSchema": t["input_schema"]}
                    for n, t in TOOLS.items()
                ]
            },
        }
    elif method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }
        # Coerce argument types based on input_schema.
        # MCP JSON transport may deliver integers as floats or strings;
        # ChromaDB and Python slicing require native int.
        schema_props = TOOLS[tool_name]["input_schema"].get("properties", {})
        for key, value in list(tool_args.items()):
            prop_schema = schema_props.get(key, {})
            declared_type = prop_schema.get("type")
            if declared_type == "integer" and not isinstance(value, int):
                tool_args[key] = int(value)
            elif declared_type == "number" and not isinstance(value, (int, float)):
                tool_args[key] = float(value)
        try:
            result = TOOLS[tool_name]["handler"](**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        except Exception:
            logger.exception(f"Tool error in {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": "Internal tool error"},
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main():
    logger.info("MemPalace MCP Server starting...")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Server error: {e}")


if __name__ == "__main__":
    main()
