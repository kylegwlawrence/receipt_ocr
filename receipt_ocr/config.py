"""Project-wide configuration defaults for the receipt OCR pipeline."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Default settings for the pipeline.

    Attributes:
        default_model: Ollama vision model used for extraction.
        default_db_path: SQLite file path used when none is supplied.
        reconcile_tolerance: Max allowed difference (in currency units) when
            checking that subtotal + tax + tip equals the total.
    """

    default_model: str = "qwen2.5vl:3b"
    default_db_path: str = "receipts.db"
    reconcile_tolerance: float = 0.01


settings = Settings()
