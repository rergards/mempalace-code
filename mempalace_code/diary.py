"""mempalace_code.diary — Agent diary entries shared by the CLI and the MCP tools.

One owner for how a diary entry is validated, identified, stored, and read
back, so an entry written with ``mempalace-code diary write`` (including one
filed under ``--wing``) is the entry ``mempalace_diary_read`` returns.

Identity: an entry records its agent name. Writes and reads match that name
ignoring case and treating spaces, hyphens, and underscores alike, so ``Claude
Code``, ``claude-code`` and ``claude_code`` share one diary and one default wing.
A write without an explicit wing reuses the diary wing that already holds the
agent's entries (such as ``wing_claude-code`` from releases before 1.15.0, which
kept hyphens); only an agent with no diary yet gets ``wing_<agent key>``
(``wing_claude_code``). Entries without agent metadata are still found in either
spelling of the default wing.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime

from .errors import InvalidArgumentError
from .taxonomy_filters import clean_write_name
from .version import __version__

AGENT_NAME_ENV = "MEMPALACE_AGENT_NAME"
DIARY_ROOM = "diary"
DEFAULT_TOPIC = "general"


def resolve_agent_name(agent_name: str | None) -> str:
    """Return the explicit agent name, else ``MEMPALACE_AGENT_NAME``; trimmed and validated."""
    if agent_name is None:
        env_value = os.environ.get(AGENT_NAME_ENV, "")
        if not env_value.strip():
            raise InvalidArgumentError(
                f"agent_name is required: pass it, or set {AGENT_NAME_ENV} in the environment "
                "of the process that runs the MCP server",
                argument="agent_name",
            )
        try:
            return clean_write_name(env_value, AGENT_NAME_ENV)
        except InvalidArgumentError as exc:
            # The caller omitted agent_name; blame the variable it fell back to.
            raise InvalidArgumentError(
                f"{exc}; pass agent_name, or fix {AGENT_NAME_ENV} in the environment of the "
                "process that runs the MCP server",
                argument=AGENT_NAME_ENV,
            ) from None
    return clean_write_name(agent_name, "agent_name")


def diary_wing(agent_name: str) -> str:
    """The default wing for *agent_name*'s diary: one wing per agent identity."""
    return f"wing_{agent_key(agent_name)}"


def existing_diary_wing(store, agent_name: str) -> str | None:
    """The diary wing that already holds *agent_name*'s entries, if any.

    A wing counts when its name is ``wing_<name>`` with the same agent key and it has a
    diary room; with several, the one holding the most diary entries wins, then the
    ``diary_wing`` spelling, then by name.
    """
    key = agent_key(agent_name)
    canonical = diary_wing(agent_name)
    try:
        taxonomy = store.count_by_pair("wing", "room")
    except Exception:
        return None  # degraded taxonomy read: fall back to the default wing
    matches = [
        (count, wing)
        for wing, rooms in taxonomy.items()
        if isinstance(wing, str)
        and wing.startswith("wing_")
        and agent_key(wing[len("wing_") :]) == key
        and (count := rooms.get(DIARY_ROOM, 0)) > 0
    ]
    if not matches:
        return None
    return min(matches, key=lambda item: (-item[0], item[1] != canonical, item[1]))[1]


def _legacy_diary_wing(agent_name: str) -> str:
    """The default wing releases before 1.15.0 derived (hyphens kept)."""
    return f"wing_{agent_name.lower().replace(' ', '_')}"


def agent_key(agent_name: str) -> str:
    """Comparison key for diary identity: case-insensitive, spaces/hyphens/underscores alike."""
    return re.sub(r"[\s_-]+", "_", agent_name.strip().casefold())


def prepare_entry(
    agent_name: str | None,
    entry: str,
    topic: str = DEFAULT_TOPIC,
    wing: str | None = None,
    store=None,
) -> tuple[str, dict]:
    """Validate a diary entry and return ``(entry_id, metadata)`` for ``store.add``.

    Without *wing*, the entry goes to the agent's existing diary wing in *store* (when
    one is given and holds one), else to ``diary_wing(agent)``.

    Raises ``InvalidArgumentError`` (naming ``agent_name``, ``entry``, ``topic``,
    or ``wing``) before anything is written. The entry text itself is stored
    verbatim by the caller; only the agent, topic, and wing names are trimmed.
    """
    agent = resolve_agent_name(agent_name)
    if not entry.strip():
        raise InvalidArgumentError("entry must not be blank", argument="entry")
    topic_name = topic.strip()
    if not topic_name:
        raise InvalidArgumentError("topic must not be blank", argument="topic")
    if wing is not None:
        wing_name = clean_write_name(wing, "wing")
    else:
        existing = existing_diary_wing(store, agent) if store is not None else None
        wing_name = existing or diary_wing(agent)
    now = datetime.now()
    metadata = {
        "wing": wing_name,
        "room": DIARY_ROOM,
        "hall": "hall_diary",
        "topic": topic_name,
        "type": "diary_entry",
        "agent": agent,
        "filed_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "extractor_version": __version__,
        "chunker_strategy": "diary_v1",
    }
    return f"diary_{wing_name}_{uuid.uuid4().hex}", metadata


def read_entries(store, agent_name: str | None, last_n: int = 10) -> dict:
    """Return *agent_name*'s most recent diary entries, newest first, from any wing."""
    agent = resolve_agent_name(agent_name)
    if last_n < 1:
        raise InvalidArgumentError("last_n must be at least 1", argument="last_n")
    wings = {diary_wing(agent), _legacy_diary_wing(agent)}
    key = agent_key(agent)
    wing_filters: list[dict] = [{"wing": name} for name in sorted(wings)]
    results = store.get(
        where={"$and": [{"room": DIARY_ROOM}, {"$or": [*wing_filters, {"type": "diary_entry"}]}]},
        include=["documents", "metadatas"],
        limit=store.count(),
    )
    entries = [
        {
            "date": meta.get("date", ""),
            "timestamp": meta.get("filed_at", ""),
            "topic": meta.get("topic", ""),
            "wing": meta.get("wing", ""),
            "content": doc,
        }
        for doc, meta in zip(results["documents"], results["metadatas"])
        if meta.get("wing") in wings
        or (meta.get("type") == "diary_entry" and agent_key(meta.get("agent") or "") == key)
    ]
    if not entries:
        return {"agent": agent, "entries": [], "message": "No diary entries yet."}
    entries.sort(key=lambda item: item["timestamp"], reverse=True)
    return {
        "agent": agent,
        "entries": entries[:last_n],
        "total": len(entries),
        "showing": min(last_n, len(entries)),
    }
