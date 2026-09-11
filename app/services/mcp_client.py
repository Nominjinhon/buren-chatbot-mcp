"""Wrapper for calling the MCP server from the agent/services layer.

The server is spawned as a stdio subprocess: `python -m app.mcp_servers.server`
by default, or `python <path>` if MCP_SERVER_PATH is set. One connection is
opened via `start()` (called from the FastAPI app's lifespan) and reused for
the process's lifetime; `stop()` tears it down on shutdown.

`start()` also caches the server's advertised tools (via `list_tools()`),
exposed synchronously through `all_tools()` - this is what
`agent/nodes.py`'s `build_agent_tools()` reads to build the LLM-facing tool
list directly from the real MCP server, instead of a hand-maintained mirror.
"""

import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import StdioServerParameters
from mcp.client import Client
from mcp_types import Tool

from app.config.settings import get_settings

_DEFAULT_MODULE = "app.mcp_servers.server"


def _server_params(configured_path: str) -> StdioServerParameters:
    # The MCP SDK only inherits a restricted safe-list of env vars into the
    # child process by default (not DATABASE_URL) - this is our own server,
    # not a third-party one, so pass the full environment through explicitly,
    # or it falls back to settings.py's hardcoded default DB URL.
    env = dict(os.environ)
    if configured_path:
        return StdioServerParameters(command=sys.executable, args=[configured_path], env=env)
    return StdioServerParameters(command=sys.executable, args=["-m", _DEFAULT_MODULE], env=env)


class MCPClient:
    def __init__(self) -> None:
        self._exit_stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self._tools: list[Tool] = []

    async def start(self) -> None:
        if self._exit_stack is not None:
            return

        settings = get_settings()
        exit_stack = AsyncExitStack()
        try:
            client = Client(_server_params(settings.mcp_server_path))
            await exit_stack.enter_async_context(client)
            tools = (await client.list_tools()).tools
        except BaseException:
            await exit_stack.aclose()
            raise

        self._exit_stack = exit_stack
        self._client = client
        self._tools = tools

    async def stop(self) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._client = None
            self._tools = []

    def all_tools(self) -> list[Tool]:
        """The server's advertised tools, cached at `start()` time."""
        return self._tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if self._client is None:
            raise RuntimeError("MCPClient not started - call start() first.")

        result = await self._client.call_tool(tool_name, arguments)
        if result.is_error:
            message = "; ".join(
                content.text for content in result.content if hasattr(content, "text")
            )
            raise RuntimeError(f"MCP tool '{tool_name}' failed: {message}")
        return result.structured_content


mcp_client = MCPClient()
