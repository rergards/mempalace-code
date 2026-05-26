"""
MCP tool profile definitions and startup-time selector resolution.

Profiles are static, declarative subsets of the full TOOLS registry.
They are resolved once at server startup; no runtime tool negotiation.

Design rationale (GitHub issue #6): exposing all 29 tools to every connected
client adds a persistent prompt/tool-surface cost per session. Static profiles
let users reduce that surface while preserving stable named-tool trigger patterns
in their usage rules.
"""

from __future__ import annotations

import fnmatch
from typing import Optional

# Full-name tool sets per named profile.
# "full" is a sentinel (empty frozenset) — resolved to all_tool_names at call time.
PROFILES: dict[str, frozenset[str]] = {
    "minimal": frozenset(
        {
            "mempalace_status",
            "mempalace_search",
            "mempalace_check_duplicate",
            "mempalace_add_drawer",
        }
    ),
    "kg": frozenset(
        {
            "mempalace_status",
            "mempalace_search",
            "mempalace_check_duplicate",
            "mempalace_add_drawer",
            "mempalace_kg_query",
            "mempalace_kg_add",
            "mempalace_kg_invalidate",
            "mempalace_kg_timeline",
        }
    ),
    "code": frozenset(
        {
            "mempalace_status",
            "mempalace_code_search",
            "mempalace_file_context",
            "mempalace_find_implementations",
            "mempalace_find_references",
            "mempalace_show_project_graph",
            "mempalace_show_type_dependencies",
            "mempalace_explain_subsystem",
            "mempalace_extract_reusable",
            "mempalace_mine",
        }
    ),
    "notes": frozenset(
        {
            "mempalace_status",
            "mempalace_search",
            "mempalace_add_drawer",
            "mempalace_check_duplicate",
            "mempalace_list_wings",
            "mempalace_list_rooms",
            "mempalace_get_taxonomy",
            "mempalace_traverse",
            "mempalace_find_tunnels",
            "mempalace_graph_stats",
            "mempalace_diary_write",
            "mempalace_diary_read",
        }
    ),
    "full": frozenset(),  # sentinel: resolved to all_tool_names at call time
}

KNOWN_PROFILES: frozenset[str] = frozenset(PROFILES)


def _expand_one_selector(selector: str, all_tool_names: frozenset[str]) -> frozenset[str]:
    """Expand one selector string to a set of matching full tool names.

    Accepts:
    - Full name: ``mempalace_search`` → ``{mempalace_search}``
    - Short name: ``search`` → ``{mempalace_search}``
    - Wildcard on full name: ``mempalace_diary_*`` → matching names
    - Wildcard on short name: ``diary_*`` → ``mempalace_diary_*`` matching names

    Raises ``ValueError`` if the selector matches no known tool.
    """
    if "*" in selector:
        patterns = [selector]
        if not selector.startswith("mempalace_"):
            patterns.append("mempalace_" + selector)
        matches: frozenset[str] = frozenset()
        for pattern in patterns:
            matches = matches | frozenset(n for n in all_tool_names if fnmatch.fnmatch(n, pattern))
        if not matches:
            raise ValueError(
                f"Unknown MCP tool selector: {selector!r} (wildcard matches no known tools)"
            )
        return matches

    # Exact name — try full name first, then with mempalace_ prefix.
    candidates = [selector]
    if not selector.startswith("mempalace_"):
        candidates.append("mempalace_" + selector)
    for candidate in candidates:
        if candidate in all_tool_names:
            return frozenset({candidate})

    raise ValueError(f"Unknown MCP tool selector: {selector!r}")


def expand_selectors(selectors: list[str], all_tool_names: frozenset[str]) -> frozenset[str]:
    """Expand a list of selectors to full tool names. Raises ``ValueError`` on any unknown."""
    result: set[str] = set()
    for sel in selectors:
        result.update(_expand_one_selector(sel, all_tool_names))
    return frozenset(result)


def resolve_active_tools(
    all_tool_names: frozenset[str],
    profile: str = "full",
    tools: Optional[list[str]] = None,
    include: Optional[list[str]] = None,
    exclude: Optional[list[str]] = None,
) -> frozenset[str]:
    """Resolve the active tool set from profile/tools/include/exclude flags.

    Precedence (applied in order):
    1. ``--profile`` establishes the base set (default: ``full``).
    2. ``--tools`` *replaces* the profile base set entirely.
       Cannot be combined with ``--include`` (ambiguous semantics).
    3. ``--include`` adds selectors to the profile base set.
    4. ``--exclude`` removes selectors last; it wins over everything else.

    Raises ``ValueError`` on any invalid input (unknown profile, unknown selector,
    wildcard matching nothing, conflicting flags, empty result).
    """
    if profile not in PROFILES:
        raise ValueError(
            f"Invalid MCP tool profile: {profile!r}. Known profiles: {sorted(KNOWN_PROFILES)}"
        )

    if tools is not None and include is not None:
        raise ValueError(
            "--tools and --include cannot be combined: "
            "--tools replaces the profile base set while --include adds to it"
        )

    if tools is not None:
        active = expand_selectors(tools, all_tool_names)
    else:
        if profile == "full":
            active: frozenset[str] = frozenset(all_tool_names)
        else:
            active = PROFILES[profile]
            unknown = active - all_tool_names
            if unknown:
                raise ValueError(f"Profile {profile!r} references unknown tools: {sorted(unknown)}")

        if include is not None:
            active = active | expand_selectors(include, all_tool_names)

    if exclude is not None:
        excluded = expand_selectors(exclude, all_tool_names)
        active = active - excluded

    if not active:
        raise ValueError(
            "Active MCP tool set is empty after applying profile/include/exclude filters"
        )

    return active
