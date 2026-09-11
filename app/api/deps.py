"""FastAPI dependencies: DB session and the compiled agent graph."""

from collections.abc import AsyncGenerator
from functools import lru_cache

from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_agent_graph
from app.database.session import get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


@lru_cache
def get_agent() -> CompiledStateGraph:
    """Built once (real Gemini model) and reused across requests."""
    return build_agent_graph()
