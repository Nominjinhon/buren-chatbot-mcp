"""Minimal standalone MCP server, isolated from the main app's dependencies.

Exists purely to test Railway deployment/proxy-registration behavior without
Gradio, LangChain, or a database in the mix. Not part of the loan chatbot -
see app/mcp_servers/server.py for the real one.
"""

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

mcp = MCPServer("buren_minimal")


@mcp.tool()
def ping() -> str:
    """Diagnostic tool - returns pong."""
    return "pong"


# streamable_http_app() defaults host="127.0.0.1", which auto-enables DNS
# rebinding protection restricted to localhost - every real request through
# a public domain gets "Invalid Host header" rejected. This is a public
# endpoint behind its own auth, not a local dev server, so disable it.
app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
