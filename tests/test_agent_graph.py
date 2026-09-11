"""LangGraph graph tests, fully isolated from the real LLM and MCP servers.

The graph is a native tool-calling loop (agent <-> call_tools): the LLM
picks which tools to call itself, rather than a separate deterministic
intent-classification step. `ScriptedToolCallingLLM` below is a small
hand-rolled stand-in for `llm.bind_tools(...).ainvoke(...)` - LangChain's
built-in fake chat models don't implement tool-calling well enough for this,
same reasoning as the old FakeStructuredLLM it replaces.

`nodes.build_agent_tools()` derives its LLM-facing tool list from
`mcp_client.all_tools()` (real MCP tool metadata), so `mock_mcp_client`
below stubs that with FAKE_MCP_TOOLS - a small fake registry shaped like
what the real (single) MCP server advertises, covering the same tools
`nodes._EXPOSED_TOOLS` allows through. Tool names used in scripts below are
the real MCP tool names (e.g. "get_active_loans"), since there's no longer a
separate hand-written schema class name to distinguish them from.
"""

import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agent.graph import build_agent_graph
from app.agent.nodes import build_initial_messages

CUSTOMER_ID = str(uuid.uuid4())


@dataclass
class FakeMCPTool:
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)


def _customer_id_schema() -> dict:
    return {
        "type": "object",
        "properties": {"customer_id": {"type": "string"}},
        "required": ["customer_id"],
    }


FAKE_MCP_TOOLS: list[FakeMCPTool] = [
    FakeMCPTool("get_active_loans", "Get active loans.", _customer_id_schema()),
    FakeMCPTool("get_overdue_payments", "Get overdue payments.", _customer_id_schema()),
    FakeMCPTool("calculate_dti", "Compute DTI.", _customer_id_schema()),
    FakeMCPTool("get_customer_profile", "Get profile.", _customer_id_schema()),
]


class ScriptedToolCallingLLM:
    """Stands in for a tool-bound chat model across a scripted sequence of turns.

    Each step is either a list of tool calls to request in parallel or a plain
    string, which ends the loop as a final text-only response (no tool_calls).
    A tool call is a bare name (args={}) or a (name, args) tuple.
    """

    def __init__(self, steps: list[list[str | tuple[str, dict]] | str]):
        self._steps = list(steps)
        self._call_count = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        step = self._steps[self._call_count]
        self._call_count += 1
        if isinstance(step, str):
            return AIMessage(content=step)
        tool_calls = [
            {
                "name": spec[0] if isinstance(spec, tuple) else spec,
                "args": spec[1] if isinstance(spec, tuple) else {},
                "id": f"call_{self._call_count}_{i}",
            }
            for i, spec in enumerate(step)
        ]
        return AIMessage(content="", tool_calls=tool_calls)


@pytest.fixture(autouse=True)
def mock_mcp_client():
    with patch("app.agent.nodes.mcp_client") as mock_client:
        mock_client.call_tool = AsyncMock()
        mock_client.all_tools.return_value = FAKE_MCP_TOOLS
        yield mock_client


async def test_active_loans_tool_call_returns_response(mock_mcp_client):
    mock_mcp_client.call_tool.return_value = {
        "result": [{"id": "loan-1", "loan_type": "car", "monthly_payment": 100000}]
    }
    llm = ScriptedToolCallingLLM([["get_active_loans"], "Таны идэвхтэй зээл байна."])
    graph = build_agent_graph(llm)

    result = await graph.ainvoke(
        {
            "customer_id": CUSTOMER_ID,
            "messages": build_initial_messages("Миний идэвхтэй зээлүүд юу вэ?"),
        }
    )

    assert result["messages"][-1].content == "Таны идэвхтэй зээл байна."
    assert result["tool_results"]["get_active_loans"][0]["loan_type"] == "car"
    mock_mcp_client.call_tool.assert_awaited_once_with(
        "get_active_loans", {"customer_id": CUSTOMER_ID}
    )


async def test_dti_tool_call_returns_response(mock_mcp_client):
    mock_mcp_client.call_tool.return_value = {
        "customer_id": CUSTOMER_ID,
        "monthly_income": 2000000,
        "total_monthly_debt_payments": 500000,
        "dti_ratio": 25.0,
    }
    llm = ScriptedToolCallingLLM([["calculate_dti"], "Your DTI ratio is 25%."])
    graph = build_agent_graph(llm)

    result = await graph.ainvoke(
        {
            "customer_id": CUSTOMER_ID,
            "messages": build_initial_messages("What's my debt-to-income ratio?"),
        }
    )

    assert result["tool_results"]["calculate_dti"]["dti_ratio"] == 25.0
    mock_mcp_client.call_tool.assert_awaited_once_with(
        "calculate_dti", {"customer_id": CUSTOMER_ID}
    )


async def test_overdue_payments_tool_call_returns_response(mock_mcp_client):
    mock_mcp_client.call_tool.return_value = {"result": [{"loan_id": "loan-9", "is_late": True}]}
    llm = ScriptedToolCallingLLM(
        [["get_overdue_payments"], "Танд хугацаа хэтэрсэн төлбөр байна."]
    )
    graph = build_agent_graph(llm)

    result = await graph.ainvoke(
        {
            "customer_id": CUSTOMER_ID,
            "messages": build_initial_messages("Надад хугацаа хэтэрсэн төлбөр байна уу?"),
        }
    )

    assert len(result["tool_results"]["get_overdue_payments"]) == 1
    mock_mcp_client.call_tool.assert_awaited_once_with(
        "get_overdue_payments", {"customer_id": CUSTOMER_ID}
    )


async def test_general_summary_style_question_calls_all_four_data_tools(mock_mcp_client):
    async def side_effect(tool_name, arguments):
        return {
            "get_active_loans": {"result": []},
            "get_overdue_payments": {"result": []},
            "calculate_dti": {"dti_ratio": 10.0},
            "get_customer_profile": {"full_name": "Test"},
        }[tool_name]

    mock_mcp_client.call_tool.side_effect = side_effect
    llm = ScriptedToolCallingLLM(
        [
            ["get_active_loans", "get_overdue_payments", "calculate_dti", "get_customer_profile"],
            "Таны ерөнхий тойм.",
        ]
    )
    graph = build_agent_graph(llm)

    result = await graph.ainvoke(
        {
            "customer_id": CUSTOMER_ID,
            "messages": build_initial_messages("Миний зээлийн ерөнхий байдлыг хэлж өгөөч"),
        }
    )

    called_tools = {call.args[0] for call in mock_mcp_client.call_tool.await_args_list}
    assert called_tools == {
        "get_active_loans",
        "get_overdue_payments",
        "calculate_dti",
        "get_customer_profile",
    }
    assert set(result["tool_results"]) == {
        "get_active_loans",
        "get_overdue_payments",
        "calculate_dti",
        "get_customer_profile",
    }


async def test_no_tool_calls_skips_call_tools_and_returns_response_directly(mock_mcp_client):
    llm = ScriptedToolCallingLLM(
        ["Уучлаарай, би зөвхөн таны зээлийн мэдээлэлтэй холбоотой асуултад хариулах боломжтой."]
    )
    graph = build_agent_graph(llm)

    result = await graph.ainvoke(
        {
            "customer_id": CUSTOMER_ID,
            "messages": build_initial_messages("Цаг агаар ямар байна?"),
        }
    )

    assert result.get("tool_results", {}) == {}
    assert "лавлагааны зорилготой" not in result["messages"][-1].content
    mock_mcp_client.call_tool.assert_not_awaited()
