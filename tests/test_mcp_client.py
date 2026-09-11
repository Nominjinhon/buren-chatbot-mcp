"""Regression test for the MCP subprocess environment bug.

The `mcp` SDK only inherits a restricted safe-list of env vars into a spawned
stdio server subprocess by default (not DATABASE_URL) - since this is our
own trusted server, not a third-party one, `_server_params` must pass the
current process's environment through explicitly, or the server silently
falls back to settings.py's hardcoded default DB URL. This only ever showed
up running inside Docker (bare-metal dev happened to have a working default
by coincidence), so it's worth pinning with a test rather than relying on
manual container checks alone.
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

from app.services.mcp_client import MCPClient, _server_params


class _FakeClient:
    """Stands in for `mcp.client.Client` as an async context manager."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name="fake_tool")])


async def test_start_caches_the_servers_advertised_tools():
    """nodes.build_agent_tools() reads this cache to build the agent's
    LLM-facing tool list - if start() stopped populating it, the agent would
    silently see zero tools."""
    client = MCPClient()

    with patch("app.services.mcp_client.Client", _FakeClient):
        await client.start()
        try:
            tools = client.all_tools()
            assert [tool.name for tool in tools] == ["fake_tool"]
        finally:
            await client.stop()

    assert client.all_tools() == []


def test_server_params_passes_through_current_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://marker:marker@example.invalid/db")

    params = _server_params(configured_path="")

    assert params.env is not None
    assert params.env.get("DATABASE_URL") == "postgresql+psycopg://marker:marker@example.invalid/db"


def test_server_params_uses_default_module_when_no_path_configured():
    params = _server_params(configured_path="")

    assert params.args == ["-m", "app.mcp_servers.server"]


def test_server_params_uses_configured_path_when_given():
    params = _server_params(configured_path="/custom/server.py")

    assert params.args == ["/custom/server.py"]
    assert params.env == dict(os.environ)
