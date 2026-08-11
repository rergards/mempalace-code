"""Installed console-script entry point for the MemPalace MCP stdio server."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> None:
    """Run the existing MCP server using the installed package import path."""
    from .mcp_server import main as mcp_main

    mcp_main(argv)


if __name__ == "__main__":
    main()
