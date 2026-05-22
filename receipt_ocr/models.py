"""SQLModel tables for persisting receipts and their line items."""
from datetime import date, datetime, timezone
from enum import Enum

from sqlmodel import Field, Relationship, SQLModel


class ReceiptStatus(str, Enum):
    """Whether an extracted receipt passed validation or needs a human look."""

    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"


class Receipt(SQLModel, table=True):
    """A receipt header row.

    image_sha256 is unique so the same photo is never ingested twice.
    """

    id: int | None = Field(default=None, primary_key=True)
    source_image_path: str
    image_sha256: str = Field(index=True, unique=True)
    merchant: str | None = None
    purchased_at: date | None = None
    subtotal: float | None = None
    tax: float | None = None
    tip: float | None = None
    total: float | None = None
    status: ReceiptStatus = Field(default=ReceiptStatus.NEEDS_REVIEW)
    review_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    line_items: list["LineItem"] = Relationship(back_populates="receipt")


class LineItem(SQLModel, table=True):
    """A single purchased item belonging to a receipt."""

    id: int | None = Field(default=None, primary_key=True)
    receipt_id: int | None = Field(default=None, foreign_key="receipt.id")
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None

    receipt: Receipt | None = Relationship(back_populates="line_items")
