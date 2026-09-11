"""Minimal standalone MCP server, isolated from the main app's dependencies.

Exists purely to test Railway deployment/proxy-registration behavior without
Gradio, LangChain, or a database in the mix. Not part of the loan chatbot -
see app/mcp_servers/server.py for the real one.
"""

from mcp.server import MCPServer

mcp = MCPServer("buren_minimal")


@mcp.tool()
def ping() -> str:
    """Diagnostic tool - returns pong."""
    return "pong"


app = mcp.streamable_http_app(streamable_http_path="/mcp")
