from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CustomerProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    monthly_income: float
    created_at: datetime
