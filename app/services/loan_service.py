"""Business logic for reading customer, loan and payment data.

MCP servers must go through this module (not the ORM models directly) so the
data-access layer stays in one place.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Customer, Loan, LoanStatus, Payment
from app.schemas.customer import CustomerProfile
from app.schemas.loan import Loan as LoanSchema
from app.schemas.loan import LoanType as LoanTypeSchema
from app.schemas.payment import OverduePayment


async def get_customer_profile(
    session: AsyncSession, customer_id: UUID
) -> CustomerProfile | None:
    customer = await session.get(Customer, customer_id)
    if customer is None:
        return None
    return CustomerProfile.model_validate(customer)


async def get_active_loans(session: AsyncSession, customer_id: UUID) -> list[LoanSchema]:
    """Loans currently in `active` or `overdue` status (excludes closed loans).

    Overdue loans are still open/owed, so they count as part of the
    customer's current loans - only `closed` loans are excluded. See
    AGENTS.md's "Active loans" note for the earlier (now superseded)
    stricter definition.
    """
    stmt = select(Loan).where(
        Loan.customer_id == customer_id,
        Loan.status.in_([LoanStatus.ACTIVE, LoanStatus.OVERDUE]),
    )
    result = await session.scalars(stmt)
    return [LoanSchema.model_validate(loan) for loan in result.all()]


async def get_all_loans(session: AsyncSession, customer_id: UUID) -> list[LoanSchema]:
    """Every loan regardless of status - for display surfaces (e.g. the
    Gradio UI's sidebar), not agent-reachable via any MCP tool."""
    stmt = select(Loan).where(Loan.customer_id == customer_id).order_by(Loan.start_date)
    result = await session.scalars(stmt)
    return [LoanSchema.model_validate(loan) for loan in result.all()]


async def get_loan_by_id(session: AsyncSession, loan_id: UUID) -> LoanSchema | None:
    loan = await session.get(Loan, loan_id)
    if loan is None:
        return None
    return LoanSchema.model_validate(loan)


async def get_overdue_payments(
    session: AsyncSession, customer_id: UUID
) -> list[OverduePayment]:
    """Currently-unpaid late payments on the customer's overdue loans.

    `days_overdue` is computed per payment from its own `due_date` - an
    overdue loan can have several unpaid trailing months, and using the
    loan's single `days_overdue` field for all of them made every payment
    under the same loan show the same day count, which looked like the same
    payment duplicated even though the due dates (and true day counts)
    differ.
    """
    stmt = (
        select(Payment, Loan)
        .join(Loan, Payment.loan_id == Loan.id)
        .where(
            Loan.customer_id == customer_id,
            Loan.status == LoanStatus.OVERDUE,
            Payment.is_late.is_(True),
            Payment.paid_date.is_(None),
        )
        .order_by(Payment.due_date)
    )
    result = await session.execute(stmt)
    today = date.today()

    return [
        OverduePayment(
            id=payment.id,
            loan_id=payment.loan_id,
            loan_type=LoanTypeSchema(loan.loan_type.value),
            due_date=payment.due_date,
            paid_date=payment.paid_date,
            amount=payment.amount,
            is_late=payment.is_late,
            days_overdue=max((today - payment.due_date).days, 0),
        )
        for payment, loan in result.all()
    ]
