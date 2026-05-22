"""Extraction stage: read a receipt image with a local Ollama vision model.

Uses Ollama structured outputs: the model is given our Pydantic JSON schema via the
`format` parameter and must return JSON matching it, which we then validate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from receipt_ocr.config import settings
from receipt_ocr.schemas import ReceiptExtraction

PROMPT = (
    "You are reading a photo of a purchase receipt. Extract its data and return it as "
    "JSON matching the provided schema. Rules:\n"
    "- Numbers must be plain decimals with no currency symbols or thousands separators "
    "(e.g. 12.50, not $12.50).\n"
    "- Use the date printed on the receipt for purchased_at; prefer ISO format "
    "(YYYY-MM-DD) if you can.\n"
    "- Add one entry to line_items per purchased item, with its description and, when "
    "legible, quantity, unit_price, and line_total.\n"
    "- If a value is not legible or not present, use null. Do not invent values."
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
