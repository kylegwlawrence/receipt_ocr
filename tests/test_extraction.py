import types

import pytest

from app.extraction import ExtractionError, extract
from app.schemas import ReceiptExtraction


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


def test_extract_wraps_client_failure(tmp_path):
    """A failing chat call (e.g. Ollama down) surfaces as ExtractionError."""
    img = tmp_path / "r.jpg"
    img.write_bytes(b"x")

    class _BoomClient:
        def chat(self, **kwargs):
            raise ConnectionError("ollama server not reachable")

    with pytest.raises(ExtractionError):
        extract(img, client=_BoomClient())


@pytest.mark.integration
def test_extract_real_model(tmp_path):
    """Calls the real model. Run with: pytest -m integration

    Requires `ollama serve` and a real receipt image. Point SAMPLE at a fixture you add,
    e.g. tests/fixtures/receipt.jpg.
    """
    pytest.skip("Provide a real receipt fixture and remove this skip to run.")
