"""Entry point: `python -m air_mcp` or `air-mcp-server` console script.

Default transport is stdio (what Claude Code, Cursor, and Codex expect).
streamable-http is available for remote MCP clients via --transport flag.
"""

from __future__ import annotations

import argparse
import sys

from air_mcp.server import mcp


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="air-mcp-server",
        description="MCP server for the Agent Identity Registry — six read-only tools.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="Transport (default: stdio for Claude Code / Cursor / Codex).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for streamable-http transport (ignored for stdio).",
    )
    args = parser.parse_args()

    if args.transport == "streamable-http":
        # FastMCP reads host/port from its settings when running HTTP transports.
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")

    return 0


if __name__ == "__main__":
    sys.exit(main())
