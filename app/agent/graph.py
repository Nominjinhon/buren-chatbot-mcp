"""LangGraph StateGraph definition for the loan chatbot agent.

agent -> (call_tools, if the model requested tool calls) -> agent -> ... -> END
The model itself decides which tools to call and when to stop (native
tool-calling), instead of a separate deterministic intent-classification step.
"""

from functools import partial

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent import nodes
from app.agent.state import AgentState
from app.config.settings import get_settings


def _route_after_agent(state: AgentState) -> str:
    last_message = state["messages"][-1]
    return "call_tools" if getattr(last_message, "tool_calls", None) else END


def get_default_llm() -> BaseChatModel:
    """The real Gemini model, configured from app settings/env vars."""
    settings = get_settings()
    return ChatGoogleGenerativeAI(model=settings.model, api_key=settings.model_api_key)


def build_agent_graph(llm: BaseChatModel | None = None) -> CompiledStateGraph:
    llm = llm or get_default_llm()
    tool_schemas = nodes.build_agent_tools()
    llm_with_tools = llm.bind_tools(tool_schemas)

    graph = StateGraph(AgentState)
    graph.add_node("agent", partial(nodes.agent_node, llm=llm_with_tools))
    graph.add_node("call_tools", nodes.call_tools)

    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent", _route_after_agent, {"call_tools": "call_tools", END: END}
    )
    graph.add_edge("call_tools", "agent")

    return graph.compile()
