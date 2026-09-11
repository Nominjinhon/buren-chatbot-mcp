from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.loan import LoanType


class OverduePayment(BaseModel):
    """A single overdue payment, enriched with the parent loan's identifying info."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    loan_id: UUID
    loan_type: LoanType
    due_date: date
    paid_date: date | None = None
    amount: float
    is_late: bool
    days_overdue: int = 0
