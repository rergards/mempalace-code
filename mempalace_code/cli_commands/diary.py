"""Diary command handlers: diary write and diary dispatch."""

import os
import shlex
import sys

from ..config import MempalaceConfig


def _bounded_search_clue(entry: str, topic: str) -> str:
    """Return a useful search clue that never reproduces the complete entry."""
    normalized = " ".join(entry.split())
    if len(normalized) <= 1:
        return topic
    return normalized[: min(48, len(normalized) - 1)]


def cmd_diary_write(args):
    for option, value in (("--agent", args.agent), ("--entry", args.entry)):
        if not value.strip():
            print(f"Error: {option} must not be blank.", file=sys.stderr)
            print(
                "Try: mempalace-code diary write --agent agent-name --entry 'your diary entry'",
                file=sys.stderr,
            )
            sys.exit(2)

    import uuid
    from datetime import datetime

    from ..storage import open_store
    from ..version import __version__

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    agent_name = args.agent
    entry = args.entry
    topic = args.topic
    wing = args.wing or f"wing_{agent_name.lower().replace(' ', '_')}"
    room = "diary"

    try:
        store = open_store(palace_path, create=True)
    except Exception as e:
        print(f"Cannot open palace at {palace_path}: {e}", file=sys.stderr)
        sys.exit(1)

    now = datetime.now()
    entry_id = f"diary_{wing}_{uuid.uuid4().hex}"

    try:
        store.add(
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
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    recovery_command = shlex.join(
        [
            "mempalace-code",
            "--palace",
            palace_path,
            "search",
            _bounded_search_clue(entry, topic),
            "--wing",
            wing,
            "--room",
            room,
            "--results",
            "10",
        ]
    )
    print("Diary entry stored.")
    print(f"  ID: {entry_id}")
    print(f"  Wing: {wing}")
    print(f"  Room: {room}")
    print(f"  Topic: {topic}")
    print("  Verify before retry:")
    print(f"    {recovery_command}")


def cmd_diary(args):
    if args.diary_command == "write":
        cmd_diary_write(args)
    else:
        args._diary_parser.print_help()
        sys.exit(2)
