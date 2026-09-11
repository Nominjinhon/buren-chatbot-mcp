"""FastAPI app entrypoint."""

from contextlib import AsyncExitStack, asynccontextmanager

import gradio as gr
from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.routes import chat
from app.config.settings import get_settings
from app.mcp_servers.server import mcp as mcp_server
from app.services.mcp_client import mcp_client
from app.ui import build_demo

settings = get_settings()


class _BearerAuth:
    """Gates an ASGI app behind a single shared bearer token.

    The MCP SDK's built-in auth is full OAuth - overkill for one shared
    secret protecting a demo endpoint, so this is a minimal hand-rolled
    wrapper instead.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            if headers.get(b"authorization") != self._expected:
                await JSONResponse({"error": "Unauthorized"}, status_code=401)(
                    scope, receive, send
                )
                return
        await self._app(scope, receive, send)


# Same tools the agent already calls internally over stdio (see
# app/mcp_servers/server.py), additionally exposed over HTTP for external
# MCP clients (e.g. a ChatGPT connector). Only built/mounted when a token is
# configured - see app/config/settings.py's mcp_http_token docstring.
#
# streamable_http_app() defaults host="127.0.0.1", which auto-enables DNS
# rebinding protection restricted to localhost - every real request through
# Railway's public domain gets "Invalid Host header" rejected. This is a
# public endpoint gated by _BearerAuth below, not a local dev server, so
# disable it explicitly.
mcp_http_app = (
    mcp_server.streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    if settings.mcp_http_token
    else None
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        await mcp_client.start()
        stack.push_async_callback(mcp_client.stop)
        if mcp_http_app is not None:
            await stack.enter_async_context(
                mcp_http_app.router.lifespan_context(mcp_http_app)
            )
        yield


app = FastAPI(title="Buren Loan Chatbot", lifespan=lifespan)

app.include_router(chat.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if mcp_http_app is not None:
    app.mount("/mcp", _BearerAuth(mcp_http_app, settings.mcp_http_token))


# mount_gradio_app wraps this lifespan around Gradio's own, so mcp_client
# still starts/stops on the app's single event loop - see app/ui.py's
# docstring for why a standalone `demo.launch()` can't do the same safely.
app = gr.mount_gradio_app(app, build_demo(), path="/ui")
