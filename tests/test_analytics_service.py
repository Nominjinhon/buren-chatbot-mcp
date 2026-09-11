import uuid
from datetime import date, timedelta

import pytest

from app.database.models import Customer, Loan, LoanStatus, LoanType
from app.services import analytics_service


@pytest.mark.parametrize(
    "total_monthly_debt_payments,monthly_income,expected",
    [
        (500_000, 2_000_000, 25.0),
        (0, 2_000_000, 0.0),
        (1_000_000, 1_000_000, 100.0),
        (300_000, 0, 0.0),  # guard against division by zero
    ],
)
def test_compute_dti_ratio_known_values(
    total_monthly_debt_payments, monthly_income, expected
):
    assert (
        analytics_service.compute_dti_ratio(total_monthly_debt_payments, monthly_income)
        == expected
    )


def make_loan(customer_id, status, monthly_payment):
    today = date.today()
    return Loan(
        id=uuid.uuid4(),
        customer_id=customer_id,
        loan_type=LoanType.CONSUMER,
        principal_amount=1_000_000,
        remaining_balance=500_000,
        monthly_payment=monthly_payment,
        interest_rate=15.0,
        status=status,
        start_date=today - timedelta(days=365),
        end_date=today + timedelta(days=365),
        days_overdue=30 if status == LoanStatus.OVERDUE else 0,
    )


async def test_calculate_dti_sums_active_and_overdue_but_not_closed(session):
    customer = Customer(
        id=uuid.uuid4(),
        full_name="Test Customer",
        monthly_income=2_000_000,
    )
    session.add(customer)
    session.add_all(
        [
            make_loan(customer.id, LoanStatus.ACTIVE, 300_000),
            make_loan(customer.id, LoanStatus.OVERDUE, 200_000),
            make_loan(customer.id, LoanStatus.CLOSED, 999_999),
        ]
    )
    await session.commit()

    result = await analytics_service.calculate_dti(session, customer.id)

    assert result is not None
    assert result.customer_id == customer.id
    assert result.monthly_income == 2_000_000
    assert result.total_monthly_debt_payments == 500_000
    assert result.dti_ratio == 25.0


async def test_calculate_dti_returns_none_for_unknown_customer(session):
    result = await analytics_service.calculate_dti(session, uuid.uuid4())
    assert result is None


async def test_get_customer_income_returns_monthly_income(session):
    customer = Customer(
        id=uuid.uuid4(),
        full_name="Test Customer",
        monthly_income=1_234_567,
    )
    session.add(customer)
    await session.commit()

    income = await analytics_service.get_customer_income(session, customer.id)

    assert income == 1_234_567
