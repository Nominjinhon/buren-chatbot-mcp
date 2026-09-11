from uuid import UUID

from pydantic import BaseModel


class DTIResult(BaseModel):
    """Deterministic debt-to-income calculation result. Never produced by an LLM."""

    customer_id: UUID
    monthly_income: float
    total_monthly_debt_payments: float
    dti_ratio: float
