"""Agent state schema for the LangGraph loan-chatbot graph.

The agent now drives a native tool-calling loop (see graph.py) instead of a
separate deterministic intent-classification step, so state is built around
a `messages` list rather than an `intent` field.
"""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    customer_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    tool_results: dict[str, Any]
