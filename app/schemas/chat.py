from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ChatRequest(BaseModel):
    customer_id: UUID
    message: str


class ChatResponse(BaseModel):
    response: str
    tools_used: list[str] = []
    data: dict[str, Any] = {}
