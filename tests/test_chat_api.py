"""Integration tests for the /chat endpoint.

The LLM is faked (never calls the real Gemini API) and the MCP client is
mocked, so this exercises the real route -> real LangGraph graph -> native
tool-calling loop -> correct-tool-called path end to end, over actual HTTP.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent.graph import build_agent_graph
from app.api.deps import get_agent, get_db
from app.database.models import Base, Customer
from app.main import app
from tests.test_agent_graph import FAKE_MCP_TOOLS, ScriptedToolCallingLLM

CUSTOMER_ID = uuid.uuid4()


@pytest.fixture
async def test_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            Customer(
                id=CUSTOMER_ID,
                full_name="Test Customer",
                monthly_income=2_000_000,
            )
        )
        await session.commit()
        yield session

    await engine.dispose()


@pytest.fixture(autouse=True)
def override_db(test_session):
    async def _get_db():
        yield test_session

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def mock_mcp_client():
    with patch("app.agent.nodes.mcp_client") as mock_client:
        mock_client.call_tool = AsyncMock()
        mock_client.all_tools.return_value = FAKE_MCP_TOOLS
        yield mock_client


@pytest.fixture
def override_agent():
    def _use(llm):
        app.dependency_overrides[get_agent] = lambda: build_agent_graph(llm)

    yield _use
    app.dependency_overrides.pop(get_agent, None)


async def test_chat_dti_question_calls_analytics_tool(mock_mcp_client, override_agent):
    mock_mcp_client.call_tool.return_value = {
        "customer_id": str(CUSTOMER_ID),
        "monthly_income": 2_000_000,
        "total_monthly_debt_payments": 500_000,
        "dti_ratio": 25.0,
    }
    override_agent(ScriptedToolCallingLLM([["calculate_dti"], "Your DTI ratio is 25%."]))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/chat",
            json={"customer_id": str(CUSTOMER_ID), "message": "What's my debt-to-income ratio?"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["tools_used"] == ["calculate_dti"]
    assert body["response"] == "Your DTI ratio is 25%."
    assert body["data"]["calculate_dti"]["dti_ratio"] == 25.0
    mock_mcp_client.call_tool.assert_awaited_once_with(
        "calculate_dti", {"customer_id": str(CUSTOMER_ID)}
    )


async def test_chat_active_loans_question_calls_loan_data_tool(mock_mcp_client, override_agent):
    mock_mcp_client.call_tool.return_value = {
        "result": [{"id": "loan-1", "loan_type": "car", "monthly_payment": 100000}]
    }
    override_agent(
        ScriptedToolCallingLLM([["get_active_loans"], "Таны идэвхтэй зээл байна."])
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/chat",
            json={"customer_id": str(CUSTOMER_ID), "message": "Миний идэвхтэй зээлүүд юу вэ?"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["tools_used"] == ["get_active_loans"]
    assert body["data"]["get_active_loans"][0]["loan_type"] == "car"
    mock_mcp_client.call_tool.assert_awaited_once_with(
        "get_active_loans", {"customer_id": str(CUSTOMER_ID)}
    )


async def test_chat_out_of_scope_question_skips_tool_calls(mock_mcp_client, override_agent):
    override_agent(
        ScriptedToolCallingLLM(
            ["Sorry, I can only help with questions about your own loans."]
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/chat",
            json={"customer_id": str(CUSTOMER_ID), "message": "What's the weather like?"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["tools_used"] == []
    assert body["data"] == {}
    mock_mcp_client.call_tool.assert_not_awaited()


async def test_chat_unknown_customer_returns_404(mock_mcp_client, override_agent):
    unknown_id = uuid.uuid4()
    # The agent is never actually invoked on this path (404 happens before
    # that), but Depends(get_agent) is still resolved by FastAPI regardless -
    # override it so this test doesn't need a real MODEL_API_KEY.
    override_agent(ScriptedToolCallingLLM(["irrelevant - never invoked"]))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/chat", json={"customer_id": str(unknown_id), "message": "hi"}
        )

    assert response.status_code == 404
    mock_mcp_client.call_tool.assert_not_awaited()


async def test_chat_invalid_body_returns_422(override_agent):
    override_agent(ScriptedToolCallingLLM(["irrelevant - never invoked"]))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"customer_id": "not-a-uuid"})

    assert response.status_code == 422


async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
