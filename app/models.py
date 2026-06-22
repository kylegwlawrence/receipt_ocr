"""SQLModel tables for persisting receipts and their line items."""
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import Column, DateTime
from sqlmodel import Field, Relationship, SQLModel


class ReceiptStatus(str, Enum):
    """Whether an extracted receipt passed validation or needs a human look."""

    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"


class Receipt(SQLModel, table=True):
    """A receipt header row.

    One row per pipeline run. image_sha256 is indexed but NOT unique: the same
    photo may be processed by several models (or several times), producing one row
    each. The model column records which Ollama model produced this extraction.
    """

    id: int | None = Field(default=None, primary_key=True)
    source_image_path: str
    image_sha256: str = Field(index=True)
    model: str  # Ollama model that produced this extraction, e.g. "qwen2.5vl:3b"
    merchant: str | None = None
    # The parsing stage converts ReceiptExtraction.purchased_at (raw str) to date before loading.
    purchased_at: date | None = None
    subtotal: float | None = None
    tax: float | None = None
    tip: float | None = None
    total: float | None = None
    status: ReceiptStatus = Field(default=ReceiptStatus.NEEDS_REVIEW)
    review_reason: str | None = None
    # DateTime(timezone=True) stores the UTC offset so the value roundtrips as tz-aware.
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    line_items: list["LineItem"] = Relationship(
        back_populates="receipt",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class LineItem(SQLModel, table=True):
    """A single purchased item belonging to a receipt."""

    id: int | None = Field(default=None, primary_key=True)
    receipt_id: int | None = Field(default=None, foreign_key="receipt.id")
    description: str
    # Optional grocery category (e.g. "dairy"), assigned by hand on the manual-entry
    # page. Constrained to app.config.ITEM_CATEGORIES at the web layer; null when
    # unset or for model-extracted receipts, which don't categorize items.
    category: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None
    # Per-item verification: flagged when quantity x unit_price disagrees with the
    # printed line_total. Defaults to NEEDS_REVIEW (fail-safe), mirroring the header.
    status: ReceiptStatus = Field(default=ReceiptStatus.NEEDS_REVIEW)
    review_reason: str | None = None

    receipt: Receipt | None = Relationship(back_populates="line_items")
