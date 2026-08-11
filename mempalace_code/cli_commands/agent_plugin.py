"""agent-plugin command handler: locate the installed Agent Plugin directory."""

from __future__ import annotations

import json
import sys

from ..agent_plugins import get_agent_plugin_root


def cmd_agent_plugin(args) -> None:
    """Handle ``mempalace-code agent-plugin`` subcommands."""
    if not getattr(args, "agent_plugin_command", None):
        args._agent_plugin_parser.print_help()
        sys.exit(2)
    if args.agent_plugin_command == "path":
        _cmd_agent_plugin_path(args)
        return
    raise RuntimeError(f"unknown agent-plugin command: {args.agent_plugin_command}")


def _cmd_agent_plugin_path(args) -> None:
    try:
        root = get_agent_plugin_root()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps({"path": str(root)}, sort_keys=True))
    else:
        print(root)
