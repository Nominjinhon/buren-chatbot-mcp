"""Deterministic financial analytics.

All numbers here are computed with plain arithmetic, never by an LLM. The
LangGraph agent only reads and narrates the results of these functions.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Customer, Loan, LoanStatus
from app.schemas.analytics import DTIResult


def compute_dti_ratio(total_monthly_debt_payments: float, monthly_income: float) -> float:
    """DTI = (total monthly debt payments / monthly income) * 100."""
    if monthly_income <= 0:
        return 0.0
    return round((total_monthly_debt_payments / monthly_income) * 100, 2)


async def get_customer_income(session: AsyncSession, customer_id: UUID) -> float | None:
    customer = await session.get(Customer, customer_id)
    if customer is None:
        return None
    return float(customer.monthly_income)


async def calculate_dti(session: AsyncSession, customer_id: UUID) -> DTIResult | None:
    customer = await session.get(Customer, customer_id)
    if customer is None:
        return None

    stmt = select(Loan.monthly_payment).where(
        Loan.customer_id == customer_id,
        Loan.status.in_([LoanStatus.ACTIVE, LoanStatus.OVERDUE]),
    )
    result = await session.scalars(stmt)
    total_monthly_debt_payments = round(sum(float(payment) for payment in result.all()), 2)

    monthly_income = float(customer.monthly_income)
    dti_ratio = compute_dti_ratio(total_monthly_debt_payments, monthly_income)

    return DTIResult(
        customer_id=customer_id,
        monthly_income=monthly_income,
        total_monthly_debt_payments=total_monthly_debt_payments,
        dti_ratio=dti_ratio,
    )
