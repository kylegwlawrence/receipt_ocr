# Phase 3 — Extraction (Ollama structured output)

## Goal

Send the receipt image to the local vision model and get back a validated `ReceiptExtraction`.
Reliability comes from **structured output**: we pass the Pydantic JSON schema to Ollama's
`format` parameter, so the model is constrained to emit JSON matching our schema.

## Prerequisites

Phase 1 complete (`schemas.ReceiptExtraction`). Ollama running locally with
`llama3.2-vision:11b` pulled (already done in this environment).

## Files to create / modify

- `receipt_ocr/extraction.py` (new)
- `tests/test_extraction.py` (new)

## Detailed spec

### `receipt_ocr/extraction.py`

```python
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

    content = response.message.content
    try:
        return ReceiptExtraction.model_validate_json(content)
    except ValidationError as exc:
        raise ExtractionError(
            f"Model returned data that did not match the schema: {exc}"
        ) from exc
```

Key points:
- `format=ReceiptExtraction.model_json_schema()` passes the JSON Schema dict; Ollama (>= 0.5,
  and our 0.24.0 is fine) constrains generation to it.
- `options={"temperature": 0}` makes extraction as deterministic as the model allows.
- The `ollama` import is lazy and inside the function so unit tests (which inject a fake client)
  don't require a running server.
- `response.message.content` is a JSON string; `model_validate_json` parses + validates in one
  step.

## Tests

### `tests/test_extraction.py`

No real server. Inject a fake client whose `.chat()` returns an object shaped like Ollama's
response (`.message.content` holds the JSON string).

```python
import types

import pytest

from receipt_ocr.extraction import ExtractionError, extract
from receipt_ocr.schemas import ReceiptExtraction


def _fake_response(content: str):
    message = types.SimpleNamespace(content=content)
    return types.SimpleNamespace(message=message)


class _FakeClient:
    def __init__(self, content: str):
        self._content = content
        self.last_kwargs = None

    def chat(self, **kwargs):
        self.last_kwargs = kwargs
        return _fake_response(self._content)


def test_extract_parses_valid_json(tmp_path):
    img = tmp_path / "r.jpg"
    img.write_bytes(b"x")
    payload = (
        '{"merchant":"Corner Cafe","purchased_at":"2026-05-20",'
        '"subtotal":18.0,"tax":1.5,"tip":3.0,"total":22.5,'
        '"line_items":[{"description":"Latte","quantity":2,'
        '"unit_price":5.0,"line_total":10.0}]}'
    )
    client = _FakeClient(payload)

    result = extract(img, client=client)

    assert isinstance(result, ReceiptExtraction)
    assert result.merchant == "Corner Cafe"
    assert result.total == 22.5
    assert len(result.line_items) == 1
    # The schema is passed to the model as `format`.
    assert client.last_kwargs["format"]["title"] == "ReceiptExtraction"
    assert client.last_kwargs["messages"][0]["images"] == [str(img)]


def test_extract_raises_on_bad_json(tmp_path):
    img = tmp_path / "r.jpg"
    img.write_bytes(b"x")
    client = _FakeClient('{"total": "not-a-number-and-missing-brace"')
    with pytest.raises(ExtractionError):
        extract(img, client=client)


@pytest.mark.integration
def test_extract_real_model(tmp_path):
    """Calls the real model. Run with: pytest -m integration

    Requires `ollama serve` and a real receipt image. Point SAMPLE at a fixture you add,
    e.g. tests/fixtures/receipt.jpg.
    """
    pytest.skip("Provide a real receipt fixture and remove this skip to run.")
```

## Edge cases & gotchas

- **Response shape:** the `ollama` package returns a `ChatResponse` object; `response.message.content`
  is the field we read. If a future version returns a dict, adapt to `response["message"]["content"]`.
- **`format` payload:** `model_json_schema()` returns a dict with a `title` of `"ReceiptExtraction"`;
  the test asserts on that to confirm the schema is wired through.
- **Model still fibs:** structured output guarantees *shape*, not *correctness*. Wrong numbers are
  caught downstream by reconciliation in Phase 4, not here.
- **Large images:** the client base64-encodes the file; phone photos are fine. If extraction is
  slow or OOMs, downscaling could be added later (out of scope for v1).

## Definition of Done

- `tests/test_extraction.py` passes the two unit tests (the integration test is skipped).
- `pytest` is green.
- (Optional manual check) With `ollama serve` running, calling `extract("some_receipt.jpg")`
  returns a populated `ReceiptExtraction`.

## Suggested commit

```
feat: add extraction stage calling Ollama vision model with structured output
```
