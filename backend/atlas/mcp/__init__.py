"""The Atlas MCP server (atlas-beliefs ticket 15): the research session's tools over the
existing `/api/v1` routes, streamable HTTP at `/mcp`. Transport, session rule and call record
in `server`; the tools and the rules they enforce for the session's as-of time in `tools`;
the quote placement in `locate`; the in-process route client in `api`."""

from atlas.mcp import bear_tools as bear_tools  # registers its tool
from atlas.mcp import signal_tools as signal_tools  # registers its tool
from atlas.mcp import tradingview_tools as tradingview_tools  # registers its tool
from atlas.mcp import watch_sources as watch_sources  # registers its tools
from atlas.mcp.server import McpServer, mcp_router

__all__ = ["McpServer", "mcp_router"]
