#!/usr/bin/env python3
"""
MemPalace MCP Server — read/write palace access for Claude Code
================================================================
Install: claude mcp add mempalace-code -- python -m mempalace.mcp_server

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
  mempalace_explain_subsystem     — explain how a subsystem works: semantic search + KG expansion
  mempalace_extract_reusable      — classify transitive deps as core/platform/glue; identify extraction boundary

Tools (write):
  mempalace_add_drawer      — file verbatim content into a wing/room
  mempalace_delete_drawer   — remove a drawer by ID
  mempalace_mine            — trigger re-mining of a project directory
"""

import hashlib
import json
import logging
import os
import sys
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import MempalaceConfig
from .knowledge_graph import KnowledgeGraph
from .language_catalog import code_search_language_description
from .miner import mine
from .palace_graph import find_tunnels, graph_stats, traverse
from .searcher import code_search, search_memories
from .storage import DrawerStore, LanceStore, open_store
from .version import __version__

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
        "hint": "Run: mempalace-code init <dir> && mempalace-code mine <dir>",
    }


_DEGRADED_HINT = "Run: mempalace-code health && mempalace-code repair --rollback --dry-run"


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


def _mine_quiet(**kwargs) -> dict:
    """Run mine() with stdout/stderr suppressed at the fd level; return stats dict.

    Uses os.dup2 to redirect fds 1 and 2 to /dev/null so that C-extension writes
    (e.g. from sentence-transformers) and buffered Python writes do not corrupt
    the MCP stdio JSON-RPC stream.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_out = os.dup(1)
    old_err = os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        return mine(**kwargs) or {}
    finally:
        # Flush Python buffers while fds still point to /dev/null so buffered
        # text does not leak to real stdout on restore.
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(old_out, 1)
        os.dup2(old_err, 2)
        os.close(devnull)
        os.close(old_out)
        os.close(old_err)


def tool_mine(directory: str, wing: str = None, full: bool = False):
    """Trigger re-mining of a project directory from the MCP server.

    Parameters
    ----------
    directory:
        Absolute path to the project root to mine.
    wing:
        Override wing name. When omitted, mine() uses config["wing"] from
        the project's mempalace.yaml, with dotnet_structure projects additionally
        detecting the solution-derived wing.
    full:
        When True, forces a full rebuild (incremental=False). Default False
        (incremental mining — only changed files are re-processed).

    Returns
    -------
    dict
        On success: {success: True, files_processed, files_skipped, drawers_filed, elapsed_secs}
        On failure: {success: False, error: <message>}
    """
    # Validate directory exists and is a directory
    try:
        dir_path = Path(directory).expanduser().resolve()
    except Exception as e:
        return {"success": False, "error": f"Invalid path: {e}"}

    if not dir_path.exists():
        return {"success": False, "error": f"Directory not found: {directory}"}

    if not dir_path.is_dir():
        return {"success": False, "error": f"Path is not a directory: {directory}"}

    # Validate mempalace.yaml or mempal.yaml exists; avoids sys.exit(1) in load_config()
    if not (dir_path / "mempalace.yaml").exists() and not (dir_path / "mempal.yaml").exists():
        return {
            "success": False,
            "error": (
                f"No mempalace.yaml found in {directory}. Run: mempalace-code init {directory}"
            ),
        }

    palace_path = _config.palace_path

    try:
        stats = _mine_quiet(
            project_dir=str(dir_path),
            palace_path=palace_path,
            wing_override=wing,
            incremental=not full,
            kg=_kg,
        )
        return {"success": True, **stats}
    except (Exception, SystemExit) as e:
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

# Predicates followed during outgoing BFS in tool_extract_reusable
EXPANSION_PREDICATES = frozenset(
    {
        "depends_on",
        "references_project",
        "implements",
        "inherits",
        "extends",
        "contains_project",
    }
)

# Entity names (or prefixes thereof) that signal UI/platform coupling
PLATFORM_PACKAGE_PREFIXES = (
    "System.Windows.",
    "Microsoft.WindowsDesktop.",
    "Microsoft.Maui.",
    "Xamarin.",
    "Avalonia.",
    "System.Drawing.",
)

# Substrings in targets_framework values that indicate a platform-specific TFM
PLATFORM_FRAMEWORK_MARKERS = (
    "-windows",
    "-android",
    "-ios",
    "-macos",
    "-maccatalyst",
    "-tizen",
)

# KG predicates that only appear in platform/UI code (XAML bindings etc.)
PLATFORM_KG_PREDICATES = frozenset(
    {
        "binds_viewmodel",
        "has_code_behind",
        "has_named_control",
        "references_resource",
        "uses_command",
    }
)


# Python built-in abstract base names — used to detect user-defined ABCs via an outgoing
# (Interface, implements, ABC/ABCMeta/Protocol) triple.
_PY_ABC_BASES = frozenset({"ABC", "ABCMeta", "Protocol"})


def tool_find_implementations(interface: str) -> dict:
    """Find all types that implement a given interface in the KG."""
    incoming_facts = _kg.query_entity(interface, direction="incoming")

    seen: set = set()
    implementations = []

    for f in incoming_facts:
        if f["predicate"] == "implements" and f["current"]:
            t = f["subject"]
            if t not in seen:
                seen.add(t)
                entry = {"type": t}
                if f.get("source_closet"):
                    entry["source_closet"] = f["source_closet"]
                implementations.append(entry)

    # Python ABC heuristic: if the interface itself has an outgoing implements-to-ABC/Protocol
    # edge, it is a user-defined abstract base class and incoming inherits edges also count.
    outgoing_facts = _kg.query_entity(interface, direction="outgoing")
    is_abc = any(
        f["predicate"] == "implements" and f["object"] in _PY_ABC_BASES and f["current"]
        for f in outgoing_facts
    )
    if is_abc:
        for f in incoming_facts:
            if f["predicate"] == "inherits" and f["current"]:
                t = f["subject"]
                if t not in seen:
                    seen.add(t)
                    entry = {"type": t}
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


def tool_explain_subsystem(
    query: str,
    wing: str = None,
    language: str = None,
    n_results: int = 5,
) -> dict:
    """Explain how a subsystem works by combining semantic search with KG expansion.

    Algorithm:
    1. Semantic search via code_search() (over-fetch to compensate for post-filter).
    2. Post-filter to code-shaped hits only (non-empty symbol_name).
    3. Expand each discovered symbol via _kg.query_entity(direction='both').
    4. Filter to current KG facts only; categorize using the find_references map.
    5. Return {query, entry_points, symbol_graph, summary}.

    wing/language constrain retrieval only; KG expansion is unconstrained.
    """
    store = _get_store()
    if not store:
        return _no_palace()

    n_results = max(1, min(50, n_results))

    # Over-fetch to compensate for post-filtering non-code hits (mixed palace)
    raw = code_search(
        palace_path=_config.palace_path,
        query=query,
        wing=wing,
        language=language,
        n_results=n_results * 2,
    )

    # Propagate errors from code_search (e.g. invalid language)
    if "error" in raw:
        return raw

    all_hits = raw.get("results", [])
    # Post-filter: code-shaped hits have a non-empty symbol_name
    entry_points = [r for r in all_hits if r.get("symbol_name")]
    entry_points = entry_points[:n_results]

    # Extract unique symbol names for KG expansion
    symbols = {ep["symbol_name"] for ep in entry_points}

    # (direction, predicate) → canonical category — same map as tool_find_references
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

    symbol_graph: dict = {}
    for symbol in symbols:
        facts = _kg.query_entity(symbol, direction="both")
        current_facts = [f for f in facts if f["current"]]
        categories: dict = {}
        for fact in current_facts:
            key = (fact["direction"], fact["predicate"])
            cat = category_map.get(key)
            if cat is None:
                continue
            entry_type = fact["subject"] if fact["direction"] == "incoming" else fact["object"]
            categories.setdefault(cat, []).append(entry_type)
        symbol_graph[symbol] = categories

    relationships_found = sum(
        len(v) for sym_cats in symbol_graph.values() for v in sym_cats.values()
    )

    return {
        "query": query,
        "entry_points": entry_points,
        "symbol_graph": symbol_graph,
        "summary": {
            "entry_point_count": len(entry_points),
            "symbols_found": len(symbols),
            "relationships_found": relationships_found,
        },
    }


def tool_extract_reusable(entity: str, max_depth: int = 3) -> dict:
    """Classify transitive dependencies of entity as core/platform/glue and identify the minimal
    public interface for extraction.

    Algorithm:
    1. BFS from entity following EXPANSION_PREDICATES (outgoing only, current facts only).
       Cycle-safe via visited set. Capped at max_depth.
    2. Classify each reachable entity:
       a. Package leaf: name matches PLATFORM_PACKAGE_PREFIXES → platform
       b. Outgoing depends_on objects matching PLATFORM_PACKAGE_PREFIXES → platform
       c. targets_framework containing PLATFORM_FRAMEWORK_MARKERS → platform
       d. Any PLATFORM_KG_PREDICATES (binds_viewmodel etc.) → platform
       Otherwise: core (tentative)
    3. Promote core→glue: entity implements a core interface AND depends_on or
       references_project a platform entity.
    4. Extract boundary_interfaces: core interfaces implemented by glue entities.
    5. Return {entity, graph: {core, platform, glue}, boundary_interfaces, summary}.
    """
    # Step 1: BFS traversal — collect all reachable entities with their current outgoing facts
    nodes = {}  # name -> {"depth": int, "facts": [current outgoing facts], "via": str|None}
    visited = set()
    queue = deque([(entity, 0, None)])  # (name, depth, via_predicate)

    while queue:
        name, depth, via = queue.popleft()
        if name in visited:
            continue
        visited.add(name)
        facts = _kg.query_entity(name, direction="outgoing")
        current_facts = [f for f in facts if f["current"]]
        nodes[name] = {"depth": depth, "facts": current_facts, "via": via}

        if depth < max_depth:
            for fact in current_facts:
                if fact["predicate"] in EXPANSION_PREDICATES:
                    neighbor = fact["object"]
                    if neighbor not in visited:
                        queue.append((neighbor, depth + 1, fact["predicate"]))

    # Step 2: Classify each entity
    classification = {}  # name -> "platform" | "core"
    evidence = {}  # name -> list[str] (for platform) or dict (for glue after step 3)

    for name, node_data in nodes.items():
        facts = node_data["facts"]

        # a. Package leaf: entity name itself matches a platform prefix
        matched_prefix = next((p for p in PLATFORM_PACKAGE_PREFIXES if name.startswith(p)), None)
        if matched_prefix is not None:
            classification[name] = "platform"
            evidence[name] = [f"package name matches platform prefix {matched_prefix}"]
            continue

        # b/c/d: Inspect outgoing facts for platform signals
        platform_evidence = []
        for fact in facts:
            pred = fact["predicate"]
            obj = fact["object"]
            # b. depends_on a platform package
            if pred == "depends_on":
                for prefix in PLATFORM_PACKAGE_PREFIXES:
                    if obj.startswith(prefix):
                        platform_evidence.append(f"depends_on platform package: {obj}")
                        break
            # c. targets a platform framework
            elif pred == "targets_framework":
                for marker in PLATFORM_FRAMEWORK_MARKERS:
                    if marker in obj:
                        platform_evidence.append(f"targets platform framework: {obj}")
                        break
            # d. uses a platform-only KG predicate
            if pred in PLATFORM_KG_PREDICATES:
                platform_evidence.append(f"uses platform predicate: {pred}")

        if platform_evidence:
            classification[name] = "platform"
            evidence[name] = platform_evidence
        else:
            classification[name] = "core"
            evidence[name] = []

    # Step 3: Promote → glue
    # An entity is glue if it implements a core-classified interface AND depends on a platform entity.
    # Project references are first-class coupling signals here, equivalent to package references.
    # This overrides any previous classification (core or platform): a type that bridges a core
    # contract and platform dependencies is always glue, regardless of step-2 result.
    # Only `implements` (not `inherits`) triggers promotion — contracts, not base classes.
    for name, node_data in nodes.items():
        if classification.get(name) == "glue":
            continue  # already glue
        facts = node_data["facts"]

        core_interfaces = [
            f["object"]
            for f in facts
            if f["predicate"] == "implements" and classification.get(f["object"]) == "core"
        ]
        if not core_interfaces:
            continue

        platform_dependency_predicates = {"depends_on", "references_project"}
        platform_deps = [
            f["object"]
            for f in facts
            if f["predicate"] in platform_dependency_predicates
            and classification.get(f["object"]) == "platform"
        ]
        if platform_deps:
            classification[name] = "glue"
            evidence[name] = {"core_interfaces": core_interfaces, "platform_deps": platform_deps}

    # Step 4: Extract boundary interfaces
    # For each glue entity, collect the core interfaces it `implements`.
    # These are the swappable contracts at the core/platform boundary.
    boundary_map: dict = {}  # interface_name -> list of {entity, classification}
    for name, node_data in nodes.items():
        if classification.get(name) != "glue":
            continue
        for fact in node_data["facts"]:
            if fact["predicate"] == "implements":
                iface = fact["object"]
                if classification.get(iface) == "core":
                    boundary_map.setdefault(iface, []).append(
                        {"entity": name, "classification": "glue"}
                    )

    boundary_interfaces = [
        {"interface": iface, "implemented_by": implementors}
        for iface, implementors in boundary_map.items()
    ]

    # Step 5: Build partitioned graph response (root entity excluded from lists)
    core_list = []
    platform_list = []
    glue_list = []

    for name, node_data in nodes.items():
        if name == entity:
            continue  # root entity is the query subject, not a dependency
        depth = node_data["depth"]
        via = node_data["via"]
        cls = classification.get(name, "core")

        if cls == "core":
            core_list.append({"entity": name, "depth": depth, "via": via})
        elif cls == "platform":
            platform_list.append(
                {
                    "entity": name,
                    "depth": depth,
                    "evidence": evidence.get(name, []),
                }
            )
        elif cls == "glue":
            glue_ev = evidence.get(name, {})
            glue_list.append(
                {
                    "entity": name,
                    "depth": depth,
                    "core_interfaces": glue_ev.get("core_interfaces", [])
                    if isinstance(glue_ev, dict)
                    else [],
                    "platform_deps": glue_ev.get("platform_deps", [])
                    if isinstance(glue_ev, dict)
                    else [],
                }
            )

    total_entities = len(nodes) - 1  # exclude root

    return {
        "entity": entity,
        "graph": {
            "core": core_list,
            "platform": platform_list,
            "glue": glue_list,
        },
        "boundary_interfaces": boundary_interfaces,
        "summary": {
            "total_entities": total_entities,
            "core_count": len(core_list),
            "platform_count": len(platform_list),
            "glue_count": len(glue_list),
            "boundary_interface_count": len(boundary_interfaces),
        },
    }


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


# ==================== FILE CONTEXT ====================


def tool_file_context(source_file: str, wing: str = None):
    """Return all indexed chunks for a source file, ordered by chunk_index."""
    if not source_file:
        return {
            "error": "source_file must be a non-empty path",
            "hint": "Provide an exact file path like 'mempalace/storage.py'",
        }

    col = _get_store()
    if not col:
        return _no_palace()

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
        return {"error": str(e), "hint": _DEGRADED_HINT}

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
    "mempalace_explain_subsystem": {
        "description": (
            "Explain how a subsystem works by combining semantic code search with KG expansion. "
            "Finds code entry points matching the query, then expands each discovered symbol "
            "through the knowledge graph to surface its relationships (implements, inherits, "
            "subclasses, dependencies). "
            "Use for queries like 'how does the storage backend work?' or "
            "'how is authentication implemented?'. "
            "Returns {entry_points, symbol_graph, summary}. "
            "wing/language filter entry points only; KG relationships are always unconstrained."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural language question about a subsystem "
                        "(e.g. 'how does vector storage work?')"
                    ),
                },
                "wing": {
                    "type": "string",
                    "description": "Restrict entry point search to this wing/project (optional)",
                },
                "language": {
                    "type": "string",
                    "description": (
                        "Restrict entry point search to this language "
                        "(e.g. python, go, typescript) (optional)"
                    ),
                },
                "n_results": {
                    "type": "integer",
                    "description": "Max entry points to return, 1–50 (default 5)",
                },
            },
            "required": ["query"],
        },
        "handler": tool_explain_subsystem,
    },
    "mempalace_extract_reusable": {
        "description": (
            "Classify transitive dependencies of a symbol, project, or solution as core, platform, or glue. "
            "BFS-expands outgoing KG edges (depends_on, implements, inherits, extends, references_project, "
            "contains_project) and partitions reachable entities using built-in .NET/WPF/MAUI/Xamarin "
            "platform markers. Identifies boundary interfaces — the minimal public contracts needed to "
            "extract core logic from platform coupling. "
            "Requires pre-mined KG data (DOTNET-SYMBOL-GRAPH mining). "
            "Returns {entity, graph: {core, platform, glue}, boundary_interfaces, summary}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": (
                        "Root entity to analyse (type, project, or solution name as stored in the KG, "
                        "e.g. 'MyService', 'CoreLib', 'MySolution')"
                    ),
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum BFS depth to traverse (default 3)",
                },
            },
            "required": ["entity"],
        },
        "handler": tool_extract_reusable,
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
    "mempalace_mine": {
        "description": (
            "Trigger re-mining of a project directory. "
            "Re-indexes the project's source files into the palace so the agent can "
            "search recently added or modified code without restarting the MCP server. "
            "Uses incremental mining by default (only changed files are re-processed). "
            "The project must have a mempalace.yaml (run: mempalace-code init <dir> first). "
            "Returns {success, files_processed, files_skipped, drawers_filed, elapsed_secs}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Absolute path to the project root to mine",
                },
                "wing": {
                    "type": "string",
                    "description": (
                        "Override wing name. When omitted, mine() uses config['wing'] "
                        "from the project's mempalace.yaml (optional)"
                    ),
                },
                "full": {
                    "type": "boolean",
                    "description": (
                        "Force full rebuild — re-process all files regardless of hash. "
                        "Default false (incremental)"
                    ),
                },
            },
            "required": ["directory"],
        },
        "handler": tool_mine,
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
                "serverInfo": {"name": "mempalace-code", "version": __version__},
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
