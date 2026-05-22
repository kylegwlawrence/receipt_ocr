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


def test_needs_review_when_totals_mismatch_without_tip():
    # No tip (common for retail/grocery) must still reconcile: tip is treated as 0.
    ext = _good()
    ext.tip = None
    ext.total = 99.99  # subtotal+tax = 19.50
    parsed = parse(ext)
    assert parsed.status == ReceiptStatus.NEEDS_REVIEW
    assert "!=" in parsed.review_reason


def test_verified_without_tip_when_totals_match():
    ext = _good()
    ext.tip = None
    ext.total = 19.5  # subtotal(18.0) + tax(1.5)
    parsed = parse(ext)
    assert parsed.status == ReceiptStatus.VERIFIED
    assert parsed.review_reason is None


def test_empty_line_items_flagged_for_review():
    # Blank descriptions are rejected by the schema validator, so this tests
    # the empty-list code path directly.
    ext = _good()
    ext.line_items = []
    parsed = parse(ext)
    assert parsed.line_items == []
    assert "no line items" in parsed.review_reason
