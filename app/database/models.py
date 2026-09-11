import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LoanType(str, enum.Enum):
    MORTGAGE = "mortgage"
    CAR = "car"
    CONSUMER = "consumer"
    BUSINESS = "business"
    CREDIT_CARD = "credit_card"


class LoanStatus(str, enum.Enum):
    ACTIVE = "active"
    OVERDUE = "overdue"
    CLOSED = "closed"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    monthly_income: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    loans: Mapped[list["Loan"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class Loan(Base):
    __tablename__ = "loans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    loan_type: Mapped[LoanType] = mapped_column(
        Enum(
            LoanType,
            name="loan_type",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    principal_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    remaining_balance: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    monthly_payment: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    interest_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    status: Mapped[LoanStatus] = mapped_column(
        Enum(
            LoanStatus,
            name="loan_status",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_overdue: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    customer: Mapped["Customer"] = relationship(back_populates="loans")
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="loan", cascade="all, delete-orphan"
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("loans.id"), nullable=False, index=True
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    is_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    loan: Mapped["Loan"] = relationship(back_populates="payments")
