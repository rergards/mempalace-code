"""mempalace_code.mcp.tools.architecture — Architecture/KG code tools and reusable-extraction logic."""

from collections import deque

from .. import runtime

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

# Maps (direction, predicate) → canonical category name used in find_references and explain_subsystem.
_CATEGORY_MAP: dict = {
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


def tool_find_implementations(interface: str) -> dict:
    """Find all types that implement a given interface in the KG."""
    incoming_facts = runtime._get_kg().query_entity(interface, direction="incoming")

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
    outgoing_facts = runtime._get_kg().query_entity(interface, direction="outgoing")
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
    facts = runtime._get_kg().query_entity(type_name, direction="both")
    current_facts = [f for f in facts if f["current"]]

    categories: dict = {}
    for fact in current_facts:
        key = (fact["direction"], fact["predicate"])
        cat = _CATEGORY_MAP.get(key)
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
        rows = runtime._get_kg().query_relationship(pred)
        all_triples[pred] = [r for r in rows if r["current"]]

    if solution is not None:
        sol_id = runtime._get_kg()._entity_id(solution)
        # Projects contained in this solution
        contained_projects = {
            r["object"]
            for r in all_triples.get("contains_project", [])
            if runtime._get_kg()._entity_id(r["subject"]) == sol_id
        }
        filtered: dict = {}
        for pred in PROJECT_PREDICATES:
            if pred == "contains_project":
                filtered[pred] = [
                    r
                    for r in all_triples[pred]
                    if runtime._get_kg()._entity_id(r["subject"]) == sol_id
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
    return runtime._get_kg().type_dependency_chain(type_name, max_depth=max_depth)


def tool_explain_subsystem(
    query: str,
    wing: str = None,
    language: str = None,
    n_results: int = 5,
) -> dict:
    """Explain how a subsystem works by combining semantic search with KG expansion."""
    store = runtime._get_store()
    if not store:
        return runtime._no_palace()

    n_results = max(1, min(50, n_results))

    # Over-fetch to compensate for post-filtering non-code hits (mixed palace)
    from ...searcher import code_search

    raw = code_search(
        palace_path=runtime._config.palace_path,
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

    symbol_graph: dict = {}
    for symbol in symbols:
        facts = runtime._get_kg().query_entity(symbol, direction="both")
        current_facts = [f for f in facts if f["current"]]
        categories: dict = {}
        for fact in current_facts:
            key = (fact["direction"], fact["predicate"])
            cat = _CATEGORY_MAP.get(key)
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
    """Classify transitive dependencies of entity as core/platform/glue."""
    # Step 1: BFS traversal — collect all reachable entities with their current outgoing facts
    nodes = {}  # name -> {"depth": int, "facts": [current outgoing facts], "via": str|None}
    visited = set()
    queue = deque([(entity, 0, None)])  # (name, depth, via_predicate)

    while queue:
        name, depth, via = queue.popleft()
        if name in visited:
            continue
        visited.add(name)
        facts = runtime._get_kg().query_entity(name, direction="outgoing")
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


TOOL_SPECS = {
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
}
