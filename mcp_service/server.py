"""Standalone HTTP entrypoint for the real loan/DTI/customer MCP tools.

Reuses the actual tool definitions from app.mcp_servers.server (the same
ones the chatbot agent calls internally over stdio) - this module only
adds the HTTP transport and bearer-token auth needed for an external MCP
client (e.g. a ChatGPT or Claude connector) to reach them directly.

Deployed separately from the main chatbot app so its image stays small
(no Gradio, no LangChain/LangGraph) - see AGENTS.md/mcp_min/ for why that
mattered for this project's Railway deploys.
"""

import os

from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.mcp_servers.server import mcp


class _BearerAuth:
    """Gates the app behind a single shared bearer token.

    /health is exempt and answered directly - Railway's healthcheck has no
    way to supply the token, and this endpoint carries no sensitive data.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            if scope["path"] == "/health":
                await JSONResponse({"status": "ok"})(scope, receive, send)
                return
            headers = dict(scope["headers"])
            if headers.get(b"authorization") != self._expected:
                await JSONResponse({"error": "Unauthorized"}, status_code=401)(
                    scope, receive, send
                )
                return
        await self._app(scope, receive, send)


_inner_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_token = os.environ.get("MCP_HTTP_TOKEN", "")
if not _token:
    raise RuntimeError("MCP_HTTP_TOKEN must be set - this service is publicly reachable.")

app = _BearerAuth(_inner_app, _token)
