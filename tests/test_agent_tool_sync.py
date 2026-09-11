"""Tests for nodes.build_agent_tools(), which derives the LLM-facing tool
schemas directly from what the MCP server advertises via list_tools(),
instead of a hand-maintained mirror.

Two properties matter enough to pin down explicitly, both security-relevant
rather than just convenience: `customer_id` must never reach the model as a
tool argument (it's injected server-side), and only an explicit allowlist of
tool names is exposed at all - a real MCP tool on this server
(get_loan_by_id) has no ownership check against the calling customer, so
auto-exposing every advertised tool would let the model fetch another
customer's data.
"""

from unittest.mock import patch

from app.agent import nodes
from tests.test_agent_graph import FakeMCPTool


def test_customer_id_is_stripped_from_every_exposed_tool_schema():
    fake_tools = [
        FakeMCPTool(
            "get_active_loans",
            "Get active loans.",
            {
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
            },
        ),
        # A fabricated schema for this test only - the real get_customer_profile
        # tool takes just customer_id, but stripping needs a case with an
        # extra non-customer_id property to prove it's preserved.
        FakeMCPTool(
            "get_customer_profile",
            "Get profile.",
            {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "loan_type_hint": {"type": "string"},
                },
                "required": ["customer_id", "loan_type_hint"],
            },
        ),
    ]

    with patch("app.agent.nodes.mcp_client") as mock_client:
        mock_client.all_tools.return_value = fake_tools
        tool_schemas = nodes.build_agent_tools()

    by_name = {schema["name"]: schema for schema in tool_schemas}
    assert set(by_name) == {"get_active_loans", "get_customer_profile"}

    active_loans_params = by_name["get_active_loans"]["parameters"]
    assert "customer_id" not in active_loans_params["properties"]
    assert "required" not in active_loans_params  # only customer_id was required

    profile_params = by_name["get_customer_profile"]["parameters"]
    assert "customer_id" not in profile_params["properties"]
    assert set(profile_params["properties"]) == {"loan_type_hint"}
    assert profile_params["required"] == ["loan_type_hint"]


def test_only_the_explicit_allowlist_is_exposed_even_if_the_server_advertises_more():
    fake_tools = [
        FakeMCPTool("get_active_loans", "Get active loans.", {"properties": {}}),
        # No ownership check against the calling customer - must never be
        # agent-reachable even though the server advertises it.
        FakeMCPTool("get_loan_by_id", "Get one loan by id.", {"properties": {"loan_id": {}}}),
    ]

    with patch("app.agent.nodes.mcp_client") as mock_client:
        mock_client.all_tools.return_value = fake_tools
        tool_schemas = nodes.build_agent_tools()

    assert [schema["name"] for schema in tool_schemas] == ["get_active_loans"]
