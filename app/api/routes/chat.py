"""POST /chat endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.nodes import build_initial_messages, extract_text
from app.api.deps import get_agent, get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import loan_service

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    agent: CompiledStateGraph = Depends(get_agent),
) -> ChatResponse:
    customer = await loan_service.get_customer_profile(db, request.customer_id)
    if customer is None:
        raise HTTPException(
            status_code=404, detail=f"No customer found with id '{request.customer_id}'."
        )

    result = await agent.ainvoke(
        {
            "customer_id": str(request.customer_id),
            "messages": build_initial_messages(request.message),
        }
    )

    tool_results = result.get("tool_results", {})
    final_message = result["messages"][-1]

    return ChatResponse(
        response=extract_text(final_message.content),
        tools_used=list(tool_results.keys()),
        data=tool_results,
    )
