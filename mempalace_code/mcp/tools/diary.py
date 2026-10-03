"""mempalace_code.mcp.tools.diary — Diary write/read handlers."""

from ... import diary
from ...errors import InvalidArgumentError
from .. import runtime
from .write import MAX_DRAWER_CHARS


def tool_diary_write(agent_name: str | None = None, entry: str = "", topic: str = "general"):
    """
    Write a diary entry for this agent. Each agent gets its own wing
    with a diary room. Entries are timestamped and accumulate over time.
    ``agent_name`` defaults to MEMPALACE_AGENT_NAME from the server environment.
    """
    # Validated before the palace is opened or the model loads.
    diary.prepare_entry(agent_name, entry, topic)
    return _diary_write(agent_name, entry, topic)


@runtime.holds_embedding_write_lease
def _diary_write(agent_name: str | None, entry: str, topic: str):
    col = runtime._get_store(create=True)
    if not col:
        return runtime._no_palace()
    # Under the lease: keep the agent's diary in the wing that already holds it.
    entry_id, metadata = diary.prepare_entry(agent_name, entry, topic, store=col)

    try:
        col.add(ids=[entry_id], documents=[entry], metadatas=[metadata])
        runtime.logger.info(
            f"Diary entry: {entry_id} → {metadata['wing']}/diary/{metadata['topic']}"
        )
        return {
            "success": True,
            "entry_id": entry_id,
            "agent": metadata["agent"],
            "wing": metadata["wing"],
            "topic": metadata["topic"],
            "timestamp": metadata["filed_at"],
        }
    except Exception as e:
        return runtime._write_failure(e)


def tool_diary_read(agent_name: str | None = None, last_n: int = 10):
    """
    Read an agent's recent diary entries, newest first, from its default diary
    wing and from any wing an entry for the same agent was filed under.
    ``agent_name`` defaults to MEMPALACE_AGENT_NAME from the server environment.
    """
    agent = diary.resolve_agent_name(agent_name)
    col = runtime._get_store()
    if not col:
        return runtime._no_palace()

    try:
        return diary.read_entries(col, agent, last_n)
    except InvalidArgumentError:
        raise
    except Exception as e:
        return {"error": str(e)}


_AGENT_NAME_DESCRIPTION = (
    "Your agent identity. Optional when the MCP server's environment sets "
    "MEMPALACE_AGENT_NAME; the response's agent field shows the identity used. Matched "
    "ignoring case, with spaces, hyphens and underscores alike ('Claude Code' = 'claude-code')."
)


TOOL_SPECS = {
    "mempalace_diary_write": {
        "description": "Write a session diary entry for an agent. Record observations, thoughts, what you worked on, what matters. Each agent has their own diary wing with full history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": _AGENT_NAME_DESCRIPTION},
                "entry": {
                    "type": "string",
                    "maxLength": MAX_DRAWER_CHARS,
                    "description": "Your diary entry — plain text",
                },
                "topic": {
                    "type": "string",
                    "description": "Topic tag (optional, default: general; must not be blank)",
                },
            },
            "required": ["entry"],
        },
        "handler": tool_diary_write,
    },
    "mempalace_diary_read": {
        "description": (
            "Read your recent diary entries, newest first. See what past versions of yourself "
            "recorded — your journal across sessions, including entries filed from the CLI "
            "under a custom wing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": _AGENT_NAME_DESCRIPTION},
                "last_n": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Number of recent entries to read (default: 10)",
                },
            },
            "required": [],
        },
        "handler": tool_diary_read,
    },
}
