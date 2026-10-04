"""Diary command handlers: diary write and diary dispatch."""

import os
import shlex
import sys
from typing import NoReturn

from ..cli_invocation import cli_command
from ..config import MempalaceConfig


def _bounded_search_clue(entry: str, topic: str) -> str:
    """Return a useful search clue that never reproduces the complete entry."""
    normalized = " ".join(entry.split())
    if len(normalized) <= 1:
        return topic
    return normalized[: min(48, len(normalized) - 1)]


def _required_fields_try(palace: str | None) -> str:
    """The example write command, run by this installation against the user's palace."""
    example = cli_command(
        "diary", "write", "--agent", "agent-name", "--entry", "your diary entry", palace=palace
    )
    return f"Try: {example}"


_OPTION_FOR_ARGUMENT = {
    "agent_name": "--agent",
    "entry": "--entry",
    "topic": "--topic",
    "wing": "--wing",
}
_TRY_FOR_ARGUMENT = {
    "topic": "Try: omit --topic to use 'general', or pass a non-blank topic.",
    "wing": (
        "Try: omit --wing to use the agent's diary wing, or pass a non-blank wing name "
        "without '/', '\\' or control characters."
    ),
}


def _refuse(option: str, detail: str, hint: str) -> NoReturn:
    print(f"Error: {option} {detail}.", file=sys.stderr)
    print(hint, file=sys.stderr)
    sys.exit(2)


def _refuse_respelled_wing(store, wing: str) -> None:
    """Exit 2 when a new --wing only re-spells an existing wing (the add_drawer rule)."""
    from ..taxonomy_filters import near_duplicate_names

    try:
        taxonomy = store.count_by_pair("wing", "room")
    except Exception:
        return  # degraded taxonomy read: the write itself reports real failures
    similar = near_duplicate_names(wing, taxonomy)
    if similar:
        _refuse(
            "--wing",
            f"{wing!r} differs from the existing wing {similar[0]!r} only by case, spacing "
            "or punctuation; wing names are case-sensitive",
            f"Try: --wing {shlex.quote(similar[0])} to file under the existing wing, "
            "or choose a clearly different name.",
        )


def cmd_diary_write(args):
    for option, value in (("--agent", args.agent), ("--entry", args.entry)):
        if not value.strip():
            _refuse(option, "must not be blank", _required_fields_try(args.palace))

    from ..diary import DIARY_ROOM, prepare_entry
    from ..errors import InvalidArgumentError
    from ..storage import open_store

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    entry = args.entry
    try:
        entry_id, metadata = prepare_entry(args.agent, entry, args.topic, args.wing)
    except InvalidArgumentError as exc:
        argument = exc.argument or ""
        _refuse(
            _OPTION_FOR_ARGUMENT.get(argument, argument),
            str(exc).removeprefix(argument).strip(),
            _TRY_FOR_ARGUMENT.get(argument) or _required_fields_try(args.palace),
        )
    wing = metadata["wing"]
    topic = metadata["topic"]
    room = DIARY_ROOM

    try:
        store = open_store(palace_path, create=True)
    except Exception as e:
        print(f"Cannot open palace at {palace_path}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.wing is not None:
        _refuse_respelled_wing(store, wing)
    else:
        # Keep the agent's diary in the wing that already holds it (any spelling).
        entry_id, metadata = prepare_entry(args.agent, entry, args.topic, store=store)
        wing = metadata["wing"]

    try:
        store.add(ids=[entry_id], documents=[entry], metadatas=[metadata])
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    recovery_command = cli_command(
        "search",
        _bounded_search_clue(entry, topic),
        "--wing",
        wing,
        "--room",
        room,
        "--results",
        "10",
        "--json",
        palace=palace_path,
    )
    print("Diary entry stored.")
    print(f"  ID: {entry_id}")
    print(f"  Wing: {wing}")
    print(f"  Room: {room}")
    print(f"  Topic: {topic}")
    print("  Verify before retry:")
    print(f"    {recovery_command}")
    # The clue is deliberately partial, so a short entry can rank beside a similar
    # one; the stored ID is the exact test.
    print(f"    Success means a hit whose id is {entry_id}; a similar entry is not a match.")


def cmd_diary(args):
    if args.diary_command == "write":
        cmd_diary_write(args)
    else:
        args._diary_parser.print_help()
        sys.exit(2)
