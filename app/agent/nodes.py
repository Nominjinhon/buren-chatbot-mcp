"""LangGraph nodes for the loan chatbot agent.

The agent picks which MCP-backed tools to call itself (native tool-calling)
via `agent_node`, instead of a separate deterministic intent-classification
step - see AGENT_SYSTEM_PROMPT in prompts.py for the rules governing both
tool selection and final reply wording. `call_tools` executes whatever the
model requested against the real MCP servers, injecting `customer_id`
server-side (never model-controlled).

`build_agent_tools()` derives each exposed tool's schema/description
directly from what the MCP server advertises via `list_tools()` (cached in
`mcp_client` at `start()` time) - a tool's docstring/signature is edited in
exactly one place and the agent picks it up automatically, no separate
hand-maintained Pydantic mirror to keep in sync.

_EXPOSED_TOOLS is still an explicit, hand-maintained *allowlist of names*
(not a schema mirror) - the MCP server can expose tools that must never be
agent-reachable. `get_loan_by_id`, for example, takes a raw `loan_id` with
no ownership check against the calling customer (`loan_service.get_loan_by_id`
does a bare `session.get(Loan, loan_id)`) - if it were auto-exposed like the
others, the model could fetch ANY customer's loan by id, not just the caller's.
Unlike `customer_id`, that argument has no generic name to filter out
automatically, so which tools are agent-reachable stays a deliberate decision.
"""

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.prompts import AGENT_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.services.mcp_client import mcp_client

# Arguments every MCP tool takes but that the model must never supply itself -
# always injected server-side in call_tools (same "don't let the model pick
# whose data it's reading/writing" posture documented in AGENTS.md).
_HIDDEN_ARGS = {"customer_id"}

# Only these MCP tools are reachable by the agent - see the module docstring
# for why this allowlist exists despite everything else here being automatic.
_EXPOSED_TOOLS = {
    "get_active_loans",
    "get_overdue_payments",
    "calculate_dti",
    "get_customer_profile",
}


def _strip_hidden_args(input_schema: dict) -> dict:
    schema = dict(input_schema)
    schema["properties"] = {
        name: prop
        for name, prop in schema.get("properties", {}).items()
        if name not in _HIDDEN_ARGS
    }
    required = [name for name in schema.get("required", []) if name not in _HIDDEN_ARGS]
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)
    return schema


def build_agent_tools() -> list[dict]:
    """Build the LLM-facing tool schemas from the real MCP server's
    advertised tools, restricted to the explicit allowlist."""
    tool_schemas: list[dict] = []

    for tool in mcp_client.all_tools():
        if tool.name not in _EXPOSED_TOOLS:
            continue
        tool_schemas.append(
            {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": _strip_hidden_args(tool.input_schema),
            }
        )

    return tool_schemas


def build_initial_messages(user_message: str) -> list[BaseMessage]:
    return [SystemMessage(content=AGENT_SYSTEM_PROMPT), HumanMessage(content=user_message)]


def _unwrap_list(structured_content: Any) -> list:
    if isinstance(structured_content, dict) and "result" in structured_content:
        return structured_content["result"]
    return structured_content


def extract_text(content: Any) -> str:
    """Normalize a chat message's `.content` to plain text.

    Some providers (e.g. Gemini via langchain-google-genai) return a list of
    content blocks - [{"type": "text", "text": "...", "extras": {...}}] -
    instead of a plain string; others (Anthropic, the fake test models)
    return a plain string directly.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


async def agent_node(state: AgentState, llm: BaseChatModel) -> dict:
    response = await llm.ainvoke(state["messages"])
    return {"messages": [response]}


async def call_tools(state: AgentState) -> dict:
    customer_id = state["customer_id"]
    last_message = state["messages"][-1]
    tool_results = dict(state.get("tool_results", {}))
    tool_messages: list[BaseMessage] = []

    for call in last_message.tool_calls:
        tool_name = call["name"]
        arguments = {"customer_id": customer_id, **call["args"]}
        result = _unwrap_list(await mcp_client.call_tool(tool_name, arguments))
        tool_results[tool_name] = result
        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, default=str, ensure_ascii=False),
                tool_call_id=call["id"],
                name=tool_name,
            )
        )

    return {"messages": tool_messages, "tool_results": tool_results}
