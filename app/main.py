"""FastAPI app entrypoint."""

from contextlib import asynccontextmanager

import gradio as gr
from fastapi import FastAPI

from app.api.routes import chat
from app.services.mcp_client import mcp_client
from app.ui import build_demo


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mcp_client.start()
    try:
        yield
    finally:
        await mcp_client.stop()


app = FastAPI(title="Buren Loan Chatbot", lifespan=lifespan)

app.include_router(chat.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# mount_gradio_app wraps this lifespan around Gradio's own, so mcp_client
# still starts/stops on the app's single event loop - see app/ui.py's
# docstring for why a standalone `demo.launch()` can't do the same safely.
app = gr.mount_gradio_app(app, build_demo(), path="/ui")
