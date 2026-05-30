"""Pydantic schemas describing the JSON the vision model must return.

These are intentionally permissive (mostly optional fields) so a partial read still
validates. The parsing stage decides whether the extracted data is complete enough.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LineItemExtraction(BaseModel):
    """A single line item as read from the receipt."""

    # Field descriptions double as per-field hints for the vision model: Ollama
    # sends this schema (via model_json_schema) to the model, so concise, concrete
    # guidance here is one of the most effective ways to steer a small model.
    description: str = Field(
        min_length=1, description="Name of the purchased product, as printed."
    )
    quantity: float | None = Field(
        default=None, description="How many units were bought. Null if not shown."
    )
    unit_price: float | None = Field(
        default=None, description="Price for one unit. Null if not shown."
    )
    line_total: float | None = Field(
        default=None,
        description="Total for this line (quantity x unit_price). Null if not shown.",
    )

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, v: str) -> str:
        """Reject descriptions that are empty or entirely whitespace."""
        if not v.strip():
            raise ValueError("description must not be blank or whitespace-only")
        return v.strip()


class ReceiptExtraction(BaseModel):
    """The full receipt as read from the image."""

    merchant: str | None = Field(
        default=None,
        description="Business name, printed as the large header at the top. Null if unreadable.",
    )
    # Raw string from the receipt image. The parsing stage must convert this to
    # datetime.date before assigning it to Receipt.purchased_at.
    purchased_at: str | None = Field(
        default=None,
        description="Purchase date as printed, preferably as YYYY-MM-DD. Null if not shown.",
    )
    subtotal: float | None = Field(
        default=None, description="Items total before tax. Plain decimal. Null if not shown."
    )
    tax: float | None = Field(
        default=None, description="Tax amount. Plain decimal. Null if not shown."
    )
    tip: float | None = Field(
        default=None, description="Tip or gratuity amount. Plain decimal. Null if not shown."
    )
    total: float | None = Field(
        default=None,
        description=(
            "Final amount paid: the grand total, usually the largest value near the "
            "bottom. Plain decimal. Null if not shown."
        ),
    )
    line_items: list[LineItemExtraction] = Field(
        default_factory=list, description="One entry per purchased product."
    )
