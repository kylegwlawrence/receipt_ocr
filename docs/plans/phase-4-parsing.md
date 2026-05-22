# Phase 4 — Parsing (normalize, reconcile, status)

## Goal

Turn a raw `ReceiptExtraction` into clean, typed values and decide whether the receipt is
trustworthy (`verified`) or needs a human look (`needs_review`) with a reason. These are **pure
functions** — no database, no model, no I/O — which makes them fast and easy to test.

## Prerequisites

Phase 1 (`schemas.ReceiptExtraction`, `models.ReceiptStatus`) and Phase 0 (`config.settings`).

## Files to create / modify

- `receipt_ocr/parsing.py` (new)
- `tests/test_parsing.py` (new)

## Detailed spec

### `receipt_ocr/parsing.py`

```python
"""Parsing stage: normalize extracted values and decide a verification status.

Pure functions only — no I/O. Given a ReceiptExtraction, produce a ParsedReceipt with
cleaned values, a status (verified / needs_review), and a human-readable reason when the
data looks incomplete or inconsistent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from receipt_ocr.config import settings
from receipt_ocr.models import ReceiptStatus
from receipt_ocr.schemas import LineItemExtraction, ReceiptExtraction

# Date formats we attempt, in order, after trying ISO.
_DATE_FORMATS = (
    "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y",
    "%Y/%m/%d", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y",
)


@dataclass
class ParsedLineItem:
    description: str
    quantity: float | None
    unit_price: float | None
    line_total: float | None


@dataclass
class ParsedReceipt:
    merchant: str | None
    purchased_at: date | None
    subtotal: float | None
    tax: float | None
    tip: float | None
    total: float | None
    line_items: list[ParsedLineItem] = field(default_factory=list)
    status: ReceiptStatus = ReceiptStatus.NEEDS_REVIEW
    review_reason: str | None = None


def parse_date(raw: str | None) -> date | None:
    """Best-effort parse of a printed date string into a date. Returns None on failure."""
    if not raw:
        return None
    text = raw.strip()
    try:
        return date.fromisoformat(text[:10])  # handles 'YYYY-MM-DD' and 'YYYY-MM-DDTHH:MM'
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def round_money(value: float | None) -> float | None:
    """Round a monetary amount to 2 decimal places, preserving None."""
    return None if value is None else round(value, 2)


def _clean_line_items(items: list[LineItemExtraction]) -> list[ParsedLineItem]:
    """Drop blank-description items and round monetary fields."""
    cleaned: list[ParsedLineItem] = []
    for it in items:
        desc = (it.description or "").strip()
        if not desc:
            continue
        cleaned.append(
            ParsedLineItem(
                description=desc,
                quantity=it.quantity,
                unit_price=round_money(it.unit_price),
                line_total=round_money(it.line_total),
            )
        )
    return cleaned


def reconcile(parsed: ParsedReceipt) -> tuple[ReceiptStatus, str | None]:
    """Decide a status by checking completeness and arithmetic consistency.

    Returns:
        (status, review_reason). review_reason is None when verified.
    """
    reasons: list[str] = []
    tol = settings.reconcile_tolerance

    if not parsed.merchant:
        reasons.append("missing merchant")
    if parsed.purchased_at is None:
        reasons.append("missing or unparseable date")
    if parsed.total is None or parsed.total <= 0:
        reasons.append("missing or non-positive total")
    if not parsed.line_items:
        reasons.append("no line items")

    # Totals consistency: only checkable when the parts and the total are all present.
    if (
        parsed.total is not None
        and parsed.subtotal is not None
        and parsed.tax is not None
        and parsed.tip is not None
    ):
        expected = parsed.subtotal + parsed.tax + parsed.tip
        if abs(expected - parsed.total) > tol:
            reasons.append(
                f"subtotal+tax+tip ({expected:.2f}) != total ({parsed.total:.2f})"
            )

    if reasons:
        return ReceiptStatus.NEEDS_REVIEW, "; ".join(reasons)
    return ReceiptStatus.VERIFIED, None


def parse(extraction: ReceiptExtraction) -> ParsedReceipt:
    """Normalize an extraction and attach a verification status."""
    parsed = ParsedReceipt(
        merchant=(extraction.merchant or "").strip() or None,
        purchased_at=parse_date(extraction.purchased_at),
        subtotal=round_money(extraction.subtotal),
        tax=round_money(extraction.tax),
        tip=round_money(extraction.tip),
        total=round_money(extraction.total),
        line_items=_clean_line_items(extraction.line_items),
    )
    parsed.status, parsed.review_reason = reconcile(parsed)
    return parsed
```

## Tests

### `tests/test_parsing.py`

```python
from datetime import date

from receipt_ocr.models import ReceiptStatus
from receipt_ocr.parsing import parse, parse_date, round_money
from receipt_ocr.schemas import LineItemExtraction, ReceiptExtraction


def _good() -> ReceiptExtraction:
    return ReceiptExtraction(
        merchant="Corner Cafe", purchased_at="2026-05-20",
        subtotal=18.0, tax=1.5, tip=3.0, total=22.5,
        line_items=[LineItemExtraction(description="Latte", line_total=10.0)],
    )


def test_parse_date_iso_and_slash():
    assert parse_date("2026-05-20") == date(2026, 5, 20)
    assert parse_date("05/20/2026") == date(2026, 5, 20)
    assert parse_date("May 20, 2026") == date(2026, 5, 20)
    assert parse_date("garbage") is None
    assert parse_date(None) is None


def test_round_money():
    assert round_money(1.239) == 1.24
    assert round_money(None) is None


def test_verified_when_complete_and_consistent():
    parsed = parse(_good())
    assert parsed.status == ReceiptStatus.VERIFIED
    assert parsed.review_reason is None
    assert parsed.purchased_at == date(2026, 5, 20)


def test_needs_review_when_total_missing():
    ext = _good()
    ext.total = None
    parsed = parse(ext)
    assert parsed.status == ReceiptStatus.NEEDS_REVIEW
    assert "total" in parsed.review_reason


def test_needs_review_when_totals_do_not_reconcile():
    ext = _good()
    ext.total = 99.99  # subtotal+tax+tip = 22.50
    parsed = parse(ext)
    assert parsed.status == ReceiptStatus.NEEDS_REVIEW
    assert "!=" in parsed.review_reason


def test_blank_line_items_dropped_and_flagged():
    ext = _good()
    ext.line_items = [LineItemExtraction(description="   ")]
    parsed = parse(ext)
    assert parsed.line_items == []
    assert "no line items" in parsed.review_reason
```

## Edge cases & gotchas

- **Ambiguous dates** (`03/04/2026`) can't be disambiguated without locale info. We try
  US-style (`%m/%d/%Y`) before day-first; document this and accept it for v1. A wrong-but-valid
  date won't trigger review — that's a known limitation.
- **Partial totals:** the reconciliation check only fires when subtotal, tax, tip, *and* total
  are all present. A receipt with only a total is still `verified` if merchant/date/line items
  are present — we can't reconcile what we don't have.
- **Floating point:** comparisons use `settings.reconcile_tolerance` (0.01) so 1-cent rounding
  noise doesn't trip the check.
- Keep this module **I/O-free** — it's what makes the suite fast and deterministic.

## Definition of Done

- `tests/test_parsing.py` passes, covering: verified path, missing-total, totals mismatch,
  blank line items, and date parsing variants.
- `pytest` is green.

## Suggested commit

```
feat: add parsing stage with normalization and reconciliation/status logic
```
