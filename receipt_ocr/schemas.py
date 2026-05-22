"""Pydantic schemas describing the JSON the vision model must return.

These are intentionally permissive (mostly optional fields) so a partial read still
validates. The parsing stage decides whether the extracted data is complete enough.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LineItemExtraction(BaseModel):
    """A single line item as read from the receipt."""

    description: str
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None


class ReceiptExtraction(BaseModel):
    """The full receipt as read from the image."""

    merchant: str | None = None
    purchased_at: str | None = Field(
        default=None, description="Raw date/time string as printed on the receipt."
    )
    subtotal: float | None = None
    tax: float | None = None
    tip: float | None = None
    total: float | None = None
    line_items: list[LineItemExtraction] = Field(default_factory=list)
