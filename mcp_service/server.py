"""Standalone HTTP entrypoint for the real loan/DTI/customer MCP tools.

Reuses the actual tool definitions from app.mcp_servers.server (the same
ones the chatbot agent calls internally over stdio) - this module only adds
the HTTP transport. Auth (an OAuth-shaped wrapper around the single
MCP_HTTP_TOKEN secret - see app/mcp_servers/oauth_provider.py for why) and
the /health route are both wired directly onto the shared `mcp` object in
app.mcp_servers.server, since MCPServer bakes auth in at construction time
and can't take it per-call here.

Deployed separately from the main chatbot app so its image stays small
(no Gradio, no LangChain/LangGraph) - see AGENTS.md/mcp_min/ for why that
mattered for this project's Railway deploys.
"""

from mcp.server.transport_security import TransportSecuritySettings

from app.mcp_servers.server import mcp

if mcp.settings.auth is None:
    raise RuntimeError(
        "MCP_HTTP_TOKEN and RAILWAY_PUBLIC_DOMAIN must both be set - this service is publicly reachable."
    )

app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
