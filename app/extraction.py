"""Extraction stage: read a receipt image with a local Ollama vision model.

Uses Ollama structured outputs: the model is given our Pydantic JSON schema via the
`format` parameter and must return JSON matching it, which we then validate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from app.config import settings
from app.schemas import ReceiptExtraction

# This prompt is tuned for small (3-4B) vision models. Guidelines applied:
# - Short, single-idea sentences (small models lose rules buried in long clauses).
# - Positive instructions over negation ("pick the largest TOTAL" beats "not the
#   subtotal", "use null" beats "never guess"), because small models often drop the "not".
# Per-field hints also live in the Pydantic schema (app/schemas.py); Ollama sends
# that schema to the model, so the two work together.
PROMPT = (
    "You read a photo of a store receipt and return its data as JSON.\n"
    "\n"
    "Read every line of the image.\n"
    "\n"
    "Fields:\n"
    "- merchant: the business name. It is the big header at the top.\n"
    "- purchased_at: the purchase date. Use the format YYYY-MM-DD.\n"
    "- subtotal: the items total before tax.\n"
    "- tax: the total tax charged.\n"
    "- tip: the tip or gratuity amount.\n"
    "- total: the final amount the customer paid. "
    "The value sits near the bottom. Sometimes it is called grand total.\n"
    "- line_items: one entry per purchased product. Copy each product description "
    "exactly as printed. Include its quantity, unit_price, and line_total when "
    "you can read them.\n"
    "\n"
    "Rules for numbers:\n"
    "- Write money as a plain decimal: 12.50, not $12.50 or 12,50.\n"
    "- Remove currency symbols and thousands separators: 1,299.00 becomes 1299.00.\n"
    "\n"
    "If a value is missing or you cannot read it, use null."
)


class ChatClient(Protocol):
    """Minimal interface we need from the Ollama client (eases testing)."""

    def chat(self, *args: Any, **kwargs: Any) -> Any: ...


class ExtractionError(RuntimeError):
    """Raised when the model response can't be parsed into a ReceiptExtraction."""


def extract(
    image_path: str | Path,
    model: str | None = None,
    client: ChatClient | None = None,
) -> ReceiptExtraction:
    """Extract structured receipt data from an image via an Ollama vision model.

    Args:
        image_path: Path to the receipt image.
        model: Ollama model name. Defaults to settings.default_model.
        client: Object exposing `.chat(...)`. Defaults to the `ollama` module.
            Injectable so tests can pass a fake client.

    Returns:
        A validated ReceiptExtraction.

    Raises:
        ExtractionError: If the model returns content that fails JSON/schema validation.
    """
    if client is None:
        import ollama  # imported lazily so tests need not have a server running

        client = ollama

    model_name = model or settings.default_model

    # The chat call can fail before we ever see content: the Ollama server may be
    # down, the model not pulled, etc. Translate those into ExtractionError so the
    # pipeline reports a clean error instead of crashing with a raw traceback.
    try:
        response = client.chat(
            model=model_name,
            format=ReceiptExtraction.model_json_schema(),
            messages=[
                {
                    "role": "user",
                    "content": PROMPT,
                    "images": [str(image_path)],
                }
            ],
            options={"temperature": 0},
        )
    except Exception as exc:  # noqa: BLE001 - any client/transport failure is an extraction failure
        raise ExtractionError(f"Vision model call failed: {exc}") from exc

    content = response.message.content
    try:
        return ReceiptExtraction.model_validate_json(content)
    except ValidationError as exc:
        raise ExtractionError(
            f"Model returned data that did not match the schema: {exc}"
        ) from exc
