from datetime import date

from app.models import ReceiptStatus
from app.parsing import parse, parse_date, round_money
from app.schemas import LineItemExtraction, ReceiptExtraction


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


def test_line_item_flagged_when_qty_price_mismatch():
    # The header reconciles, so the only receipt reason is the bad line rolling up.
    ext = _good()
    ext.line_items = [
        LineItemExtraction(description="Latte", quantity=2, unit_price=5.0, line_total=10.0),
        LineItemExtraction(description="Muffin", quantity=1, unit_price=8.0, line_total=99.0),
    ]
    parsed = parse(ext)
    assert parsed.line_items[0].status == ReceiptStatus.VERIFIED
    assert parsed.line_items[0].review_reason is None
    assert parsed.line_items[1].status == ReceiptStatus.NEEDS_REVIEW
    assert "!=" in parsed.line_items[1].review_reason
    # The flagged item rolls up to flag the receipt.
    assert parsed.status == ReceiptStatus.NEEDS_REVIEW
    assert "line item" in parsed.review_reason


def test_line_items_verified_when_arithmetic_matches():
    ext = _good()
    ext.line_items = [
        LineItemExtraction(description="Latte", quantity=2, unit_price=5.0, line_total=10.0),
    ]
    parsed = parse(ext)
    assert parsed.line_items[0].status == ReceiptStatus.VERIFIED
    assert parsed.status == ReceiptStatus.VERIFIED


def test_missing_quantity_treated_as_one():
    # A single-unit line often omits quantity: unit_price should equal line_total.
    ext = _good()
    ext.line_items = [LineItemExtraction(description="Latte", unit_price=10.0, line_total=10.0)]
    assert parse(ext).line_items[0].status == ReceiptStatus.VERIFIED

    ext.line_items = [LineItemExtraction(description="Latte", unit_price=10.0, line_total=12.0)]
    flagged = parse(ext).line_items[0]
    assert flagged.status == ReceiptStatus.NEEDS_REVIEW
    assert "!=" in flagged.review_reason


def test_line_item_not_flagged_when_unit_price_missing():
    # Without a unit price the arithmetic is unverifiable, so the item is not flagged.
    ext = _good()  # its single item has only a line_total
    parsed = parse(ext)
    assert parsed.line_items[0].status == ReceiptStatus.VERIFIED
    assert parsed.status == ReceiptStatus.VERIFIED


def test_non_positive_line_total_flagged():
    ext = _good()
    ext.line_items = [LineItemExtraction(description="Latte", unit_price=0.0, line_total=0.0)]
    item = parse(ext).line_items[0]
    assert item.status == ReceiptStatus.NEEDS_REVIEW
    assert "non-positive" in item.review_reason
