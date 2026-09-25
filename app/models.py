from datetime import datetime
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    plan: str = "free"
    invoices_used: int = 0
    invoices_limit: int = 10
    usage_period_start: datetime = Field(default_factory=datetime.utcnow)

    google_id: Optional[str] = Field(default=None, index=True)
    github_id: Optional[str] = Field(default=None, index=True)

    # Billing: internal balance (USD-equivalent) + subscription window
    balance: float = 0.0
    subscription_status: str = "free"  # free|active|past_due|cancelled|expired
    subscription_started_at: Optional[datetime] = None
    subscription_expires_at: Optional[datetime] = None
    subscription_cancelled_at: Optional[datetime] = None

    documents: list["Document"] = Relationship(back_populates="user")
    topups: list["TopUp"] = Relationship(back_populates="user")
    transactions: list["Transaction"] = Relationship(back_populates="user")


class TopUp(SQLModel, table=True):
    """A single payment attempt.

    Used for both balance top-ups AND direct Pro subscription payments.
    Old rows (created before the Trybit migration) keep `provider="cryptobot"`
    and `cryptobot_invoice_id` populated; new rows use `provider="trybit"`.
    """

    __tablename__ = "topups"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)

    order_id: str = Field(unique=True, index=True)
    amount: float = 0.0
    currency: str = "USD"
    status: str = "pending"  # pending|paid|failed|expired|cancelled
    created_at: datetime = Field(default_factory=datetime.utcnow)
    paid_at: Optional[datetime] = None

    # --- provider-agnostic fields (new) ---
    provider: str = Field(default="cryptobot", index=True)
    provider_payment_id: Optional[str] = Field(default=None, index=True)
    purpose: str = Field(default="topup", index=True)  # topup | subscription

    # --- legacy column kept for historical CryptoBot rows ---
    cryptobot_invoice_id: Optional[int] = None

    user: Optional[User] = Relationship(back_populates="topups")
class Transaction(SQLModel, table=True):
    """Full ledger of balance movements: top-ups and subscription charges."""

    __tablename__ = "transactions"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)

    kind: str  # topup|subscription_charge|refund|adjustment
    amount: float  # positive = credit, negative = debit
    balance_after: float
    description: str = ""
    related_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    user: Optional[User] = Relationship(back_populates="transactions")


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(
        default=None, foreign_key="users.id", index=True
    )
    filename: str
    filepath: str
    status: str = "uploaded"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    user: Optional[User] = Relationship(back_populates="documents")
    invoice: Optional["InvoiceRecord"] = Relationship(back_populates="document")


class InvoiceRecord(SQLModel, table=True):
    __tablename__ = "invoices"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="documents.id")

    supplier_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    document: Optional[Document] = Relationship(back_populates="invoice")
    line_items: list["LineItemRecord"] = Relationship(back_populates="invoice")
    validation: Optional["ValidationRecord"] = Relationship(back_populates="invoice")


class LineItemRecord(SQLModel, table=True):
    __tablename__ = "line_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoices.id")

    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total: Optional[float] = None

    invoice: Optional[InvoiceRecord] = Relationship(back_populates="line_items")


class ValidationRecord(SQLModel, table=True):
    __tablename__ = "validation_results"

    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoices.id", unique=True)

    status: str
    errors: str = ""
    warnings: str = ""

    invoice: Optional[InvoiceRecord] = Relationship(back_populates="validation")