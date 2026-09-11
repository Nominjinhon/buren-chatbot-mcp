import uuid
from datetime import date, timedelta

from app.database.models import Customer, Loan, LoanStatus, LoanType, Payment
from app.services import loan_service


def make_loan(customer_id, status, loan_type=LoanType.CONSUMER, monthly_payment=100_000):
    today = date.today()
    return Loan(
        id=uuid.uuid4(),
        customer_id=customer_id,
        loan_type=loan_type,
        principal_amount=1_000_000,
        remaining_balance=500_000 if status != LoanStatus.CLOSED else 0,
        monthly_payment=monthly_payment,
        interest_rate=15.0,
        status=status,
        start_date=today - timedelta(days=365),
        end_date=today + timedelta(days=365),
        days_overdue=30 if status == LoanStatus.OVERDUE else 0,
    )


async def seed_customer_with_loans(session):
    customer = Customer(
        id=uuid.uuid4(),
        full_name="Test Customer",
        monthly_income=2_000_000,
    )
    session.add(customer)

    active_loan = make_loan(customer.id, LoanStatus.ACTIVE, monthly_payment=150_000)
    overdue_loan = make_loan(customer.id, LoanStatus.OVERDUE, monthly_payment=200_000)
    closed_loan = make_loan(customer.id, LoanStatus.CLOSED, monthly_payment=999_999)
    session.add_all([active_loan, overdue_loan, closed_loan])

    unpaid_late_payment = Payment(
        id=uuid.uuid4(),
        loan_id=overdue_loan.id,
        due_date=date.today() - timedelta(days=30),
        paid_date=None,
        amount=overdue_loan.monthly_payment,
        is_late=True,
    )
    older_unpaid_late_payment = Payment(
        id=uuid.uuid4(),
        loan_id=overdue_loan.id,
        due_date=date.today() - timedelta(days=60),
        paid_date=None,
        amount=overdue_loan.monthly_payment,
        is_late=True,
    )
    paid_on_time_payment = Payment(
        id=uuid.uuid4(),
        loan_id=active_loan.id,
        due_date=date.today() - timedelta(days=30),
        paid_date=date.today() - timedelta(days=30),
        amount=active_loan.monthly_payment,
        is_late=False,
    )
    session.add_all([unpaid_late_payment, older_unpaid_late_payment, paid_on_time_payment])

    await session.commit()
    return customer, active_loan, overdue_loan, closed_loan


async def test_get_active_loans_includes_overdue_but_excludes_closed(session):
    customer, active_loan, overdue_loan, closed_loan = await seed_customer_with_loans(session)

    active_loans = await loan_service.get_active_loans(session, customer.id)

    assert {loan.id for loan in active_loans} == {active_loan.id, overdue_loan.id}


async def test_get_all_loans_includes_every_status(session):
    customer, active_loan, overdue_loan, closed_loan = await seed_customer_with_loans(session)

    all_loans = await loan_service.get_all_loans(session, customer.id)

    assert {loan.id for loan in all_loans} == {active_loan.id, overdue_loan.id, closed_loan.id}


async def test_get_loan_by_id_returns_none_for_unknown_id(session):
    result = await loan_service.get_loan_by_id(session, uuid.uuid4())
    assert result is None


async def test_get_loan_by_id_returns_matching_loan(session):
    customer, active_loan, _, _ = await seed_customer_with_loans(session)

    loan = await loan_service.get_loan_by_id(session, active_loan.id)

    assert loan is not None
    assert loan.id == active_loan.id
    assert loan.monthly_payment == 150_000


async def test_get_overdue_payments_only_returns_unpaid_late_payments(session):
    customer, active_loan, overdue_loan, closed_loan = await seed_customer_with_loans(session)

    overdue_payments = await loan_service.get_overdue_payments(session, customer.id)

    assert len(overdue_payments) == 2
    for payment in overdue_payments:
        assert payment.loan_id == overdue_loan.id
        assert payment.paid_date is None
        assert payment.is_late is True


async def test_get_overdue_payments_computes_days_overdue_per_payment(session):
    """Regression test: days_overdue used to be copied from the loan's single
    field, so two unpaid payments a month apart showed the same day count and
    looked like the same payment duplicated."""
    customer, active_loan, overdue_loan, closed_loan = await seed_customer_with_loans(session)

    overdue_payments = await loan_service.get_overdue_payments(session, customer.id)

    by_due_date = {payment.due_date: payment.days_overdue for payment in overdue_payments}
    assert by_due_date[date.today() - timedelta(days=30)] == 30
    assert by_due_date[date.today() - timedelta(days=60)] == 60


async def test_get_customer_profile_returns_none_for_unknown_customer(session):
    profile = await loan_service.get_customer_profile(session, uuid.uuid4())
    assert profile is None


async def test_get_customer_profile_returns_matching_customer(session):
    customer, *_ = await seed_customer_with_loans(session)

    profile = await loan_service.get_customer_profile(session, customer.id)

    assert profile is not None
    assert profile.full_name == "Test Customer"
    assert profile.monthly_income == 2_000_000
