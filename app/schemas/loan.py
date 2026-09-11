from datetime import date
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LoanType(str, Enum):
    MORTGAGE = "mortgage"
    CAR = "car"
    CONSUMER = "consumer"
    BUSINESS = "business"
    CREDIT_CARD = "credit_card"


class LoanStatus(str, Enum):
    ACTIVE = "active"
    OVERDUE = "overdue"
    CLOSED = "closed"


class Loan(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    loan_type: LoanType
    principal_amount: float
    remaining_balance: float
    monthly_payment: float
    interest_rate: float
    status: LoanStatus
    start_date: date
    end_date: date
    days_overdue: int = 0
