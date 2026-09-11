"""Idempotent mock-data seed script.

Populates 5 customers with 5-10 loans each (a realistic mix of active,
overdue and closed loans, all amounts in MNT) plus recent payment history
for each loan. Safe to run multiple times: if customers already exist it
skips seeding unless --reset is passed.

Usage:
    python -m app.database.seed
    python -m app.database.seed --reset
"""

import argparse
import asyncio
import calendar
import random
import uuid
from datetime import date, timedelta

from sqlalchemy import delete, func, select

from app.database.models import Customer, Loan, LoanStatus, LoanType, Payment
from app.database.session import AsyncSessionLocal

SEED = 42
# Fixed namespace so customer UUIDs are stable across re-seeds (handy for
# manual testing / README curl examples).
NAMESPACE = uuid.UUID("6b6f4b2a-6f0e-4f3b-9a3d-6a5e8d2c9b10")

CUSTOMERS = [
    {"name": "Бат-Эрдэнэ Дорж", "monthly_income": 950_000},
    {"name": "Сарнай Ганбаатар", "monthly_income": 1_600_000},
    {"name": "Түмэн-Өлзий Баясгалан", "monthly_income": 2_300_000},
    {"name": "Оюунчимэг Хишигт", "monthly_income": 3_400_000},
    {"name": "Ганзориг Мөнхбат", "monthly_income": 4_800_000},
]

# These two are guaranteed at least one overdue loan each, per spec.
RISKY_CUSTOMER_NAMES = {"Бат-Эрдэнэ Дорж", "Сарнай Ганбаатар"}

LOAN_TERM_MONTHS_RANGE = {
    LoanType.MORTGAGE: (120, 360),
    LoanType.CAR: (24, 72),
    LoanType.CONSUMER: (6, 36),
    LoanType.BUSINESS: (12, 60),
    LoanType.CREDIT_CARD: (12, 24),
}

# Monthly payment as a fraction of the customer's monthly income. Sizing loan
# amounts off income (rather than a fixed absolute range) keeps the resulting
# DTI ratios in a plausible band regardless of which loan types a customer
# happens to be assigned.
LOAN_INCOME_FRACTION_RANGE = {
    LoanType.MORTGAGE: (0.20, 0.35),
    LoanType.CAR: (0.06, 0.15),
    LoanType.CONSUMER: (0.03, 0.08),
    LoanType.BUSINESS: (0.05, 0.12),
    LoanType.CREDIT_CARD: (0.02, 0.05),
}

# At most this many loans of a given type per customer, so e.g. nobody ends
# up with three mortgages. Types not listed are unbounded.
LOAN_TYPE_CAPS = {
    LoanType.MORTGAGE: 1,
    LoanType.BUSINESS: 1,
    LoanType.CAR: 2,
}

LOAN_INTEREST_RANGE = {
    LoanType.MORTGAGE: (8.0, 14.0),
    LoanType.CAR: (10.0, 18.0),
    LoanType.CONSUMER: (14.0, 24.0),
    LoanType.BUSINESS: (10.0, 20.0),
    LoanType.CREDIT_CARD: (18.0, 24.0),
}

MAX_PAYMENT_HISTORY_MONTHS = 12


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def invert_principal(monthly_payment: float, annual_rate: float, term_months: int) -> float:
    """Back out a principal that amortizes to the given monthly payment."""
    monthly_rate = annual_rate / 100 / 12
    if monthly_rate == 0:
        return round(monthly_payment * term_months, -3)
    factor = (1 + monthly_rate) ** term_months
    principal = monthly_payment * (factor - 1) / (monthly_rate * factor)
    return round(principal, -3)


def choose_statuses(num_loans: int, is_risky: bool) -> list[LoanStatus]:
    weights = [0.40, 0.25, 0.35] if is_risky else [0.55, 0.30, 0.15]
    statuses = random.choices(
        [LoanStatus.ACTIVE, LoanStatus.CLOSED, LoanStatus.OVERDUE],
        weights=weights,
        k=num_loans,
    )
    if is_risky and LoanStatus.OVERDUE not in statuses:
        statuses[0] = LoanStatus.OVERDUE
    return statuses


def choose_loan_types(num_loans: int) -> list[LoanType]:
    """Pick loan types respecting LOAN_TYPE_CAPS (capped/unbounded types)."""
    unbounded = [t for t in LoanType if t not in LOAN_TYPE_CAPS]
    remaining_caps = dict(LOAN_TYPE_CAPS)
    chosen: list[LoanType] = []

    for _ in range(num_loans):
        available = unbounded + [t for t, cap in remaining_caps.items() if cap > 0]
        loan_type = random.choice(available)
        if loan_type in remaining_caps:
            remaining_caps[loan_type] -= 1
        chosen.append(loan_type)

    random.shuffle(chosen)
    return chosen


def build_loan(
    customer_id: uuid.UUID,
    loan_type: LoanType,
    status: LoanStatus,
    monthly_income: float,
    today: date,
) -> tuple[Loan, list[Payment]]:
    term_min, term_max = LOAN_TERM_MONTHS_RANGE[loan_type]
    term_months = random.randint(term_min, term_max)
    interest_rate = round(random.uniform(*LOAN_INTEREST_RANGE[loan_type]), 2)

    income_fraction = random.uniform(*LOAN_INCOME_FRACTION_RANGE[loan_type])
    monthly_payment = round(monthly_income * income_fraction, 2)
    principal = invert_principal(monthly_payment, interest_rate, term_months)

    if status == LoanStatus.CLOSED:
        elapsed_months = term_months
        start_date = add_months(today, -term_months - random.randint(1, 24))
        end_date = add_months(start_date, term_months)
        remaining_balance = 0.0
        days_overdue = 0
    else:
        elapsed_months = random.randint(1, max(term_months - 1, 1))
        start_date = add_months(today, -elapsed_months)
        end_date = add_months(start_date, term_months)
        fraction_paid = elapsed_months / term_months
        remaining_balance = round(
            principal * max(0.05, 1 - fraction_paid) * random.uniform(0.9, 1.05), 2
        )
        remaining_balance = min(remaining_balance, round(principal * 0.98, 2))
        if status == LoanStatus.OVERDUE:
            # Can't be overdue longer than the loan has actually existed.
            max_overdue_days = min(120, elapsed_months * 30)
            days_overdue = random.randint(5, max(5, max_overdue_days))
        else:
            days_overdue = 0

    loan = Loan(
        id=uuid.uuid4(),
        customer_id=customer_id,
        loan_type=loan_type,
        principal_amount=principal,
        remaining_balance=remaining_balance,
        monthly_payment=monthly_payment,
        interest_rate=interest_rate,
        status=status,
        start_date=start_date,
        end_date=end_date,
        days_overdue=days_overdue,
    )

    payments = build_payment_history(loan, elapsed_months)
    return loan, payments


def build_payment_history(loan: Loan, elapsed_months: int) -> list[Payment]:
    history_months = min(elapsed_months, MAX_PAYMENT_HISTORY_MONTHS)
    if history_months <= 0:
        return []

    late_tail = 0
    if loan.status == LoanStatus.OVERDUE:
        late_tail = min(max(1, round(loan.days_overdue / 30)), history_months)

    first_month_index = elapsed_months - history_months + 1
    payments: list[Payment] = []
    for offset, month_index in enumerate(range(first_month_index, elapsed_months + 1), start=1):
        due_date = add_months(loan.start_date, month_index)
        is_unpaid_tail = offset > history_months - late_tail
        if is_unpaid_tail:
            paid_date = None
            is_late = True
        else:
            delay_days = random.choice([0, 0, 0, 0, 1, 2])
            paid_date = due_date + timedelta(days=delay_days)
            is_late = delay_days > 0
        payments.append(
            Payment(
                id=uuid.uuid4(),
                loan_id=loan.id,
                due_date=due_date,
                paid_date=paid_date,
                amount=loan.monthly_payment,
                is_late=is_late,
            )
        )
    return payments


async def seed(reset: bool = False) -> None:
    random.seed(SEED)
    today = date.today()

    async with AsyncSessionLocal() as session:
        existing = await session.scalar(select(func.count()).select_from(Customer))
        if existing and not reset:
            print(
                f"Database already has {existing} customers - skipping seed "
                "(pass --reset to wipe and reseed)."
            )
            return

        if reset and existing:
            await session.execute(delete(Payment))
            await session.execute(delete(Loan))
            await session.execute(delete(Customer))
            await session.commit()

        for customer_data in CUSTOMERS:
            customer_id = uuid.uuid5(NAMESPACE, customer_data["name"])
            session.add(
                Customer(
                    id=customer_id,
                    full_name=customer_data["name"],
                    monthly_income=float(customer_data["monthly_income"]),
                )
            )

            is_risky = customer_data["name"] in RISKY_CUSTOMER_NAMES
            monthly_income = float(customer_data["monthly_income"])
            num_loans = random.randint(5, 10)
            loan_types = choose_loan_types(num_loans)
            statuses = choose_statuses(num_loans, is_risky)

            for loan_type, status in zip(loan_types, statuses):
                loan, payments = build_loan(
                    customer_id, loan_type, status, monthly_income, today
                )
                session.add(loan)
                session.add_all(payments)

        await session.commit()
        print(f"Seeded {len(CUSTOMERS)} customers with loans and payment history.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed mock loan chatbot data.")
    parser.add_argument(
        "--reset", action="store_true", help="Delete existing data before reseeding."
    )
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))


if __name__ == "__main__":
    main()
