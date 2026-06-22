"""Project-wide configuration defaults for the receipt OCR pipeline."""
from __future__ import annotations

from dataclasses import dataclass


# The fixed set of allowable line-item categories, in dropdown display order.
# This is the single source of truth: the manual-entry page builds its dropdown
# from this list (via GET /api/categories) and the web layer validates submitted
# categories against it. A line item's category is optional (may be left blank).
ITEM_CATEGORIES: tuple[str, ...] = (
    "fruits and vegetables",
    "meat",
    "seafood",
    "dairy",
    "bakery",
    "frozen meals",
    "snacks",
    "beverages",
    "pantry / dry goods",
    "alcohol",
    "household",
    "personal care",
    "other",
)


@dataclass(frozen=True)
class Settings:
    """Default settings for the pipeline.

    Attributes:
        default_model: Ollama vision model used for extraction.
        default_db_path: SQLite file path used when none is supplied.
        reconcile_tolerance: Max allowed difference (in currency units) when
            checking that subtotal + tax + tip equals the total.
        item_categories: Allowable line-item category labels (see ITEM_CATEGORIES).
    """

    default_model: str = "ministral-3:3b"
    default_db_path: str = "data/receipts.db"
    reconcile_tolerance: float = 0.01
    item_categories: tuple[str, ...] = ITEM_CATEGORIES


settings = Settings()
