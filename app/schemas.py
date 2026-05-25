"""Pydantic schemas describing the JSON the vision model must return.

These are intentionally permissive (mostly optional fields) so a partial read still
validates. The parsing stage decides whether the extracted data is complete enough.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LineItemExtraction(BaseModel):
    """A single line item as read from the receipt."""

    description: str = Field(min_length=1)
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, v: str) -> str:
        """Reject descriptions that are empty or entirely whitespace."""
        if not v.strip():
            raise ValueError("description must not be blank or whitespace-only")
        return v.strip()


class ReceiptExtraction(BaseModel):
    """The full receipt as read from the image."""

    merchant: str | None = None
    # Raw string from the receipt image. The parsing stage must convert this to
    # datetime.date before assigning it to Receipt.purchased_at.
    purchased_at: str | None = Field(
        default=None, description="Raw date/time string as printed on the receipt."
    )
    subtotal: float | None = None
    tax: float | None = None
    tip: float | None = None
    total: float | None = None
    line_items: list[LineItemExtraction] = Field(default_factory=list)
