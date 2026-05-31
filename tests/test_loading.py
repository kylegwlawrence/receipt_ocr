from datetime import date

import pytest

from app.loading import LoadVerificationError, persist, verify_write
from app.models import Receipt, ReceiptStatus
from app.parsing import ParsedLineItem, ParsedReceipt


def _parsed() -> ParsedReceipt:
    return ParsedReceipt(
        merchant="Corner Cafe", purchased_at=date(2026, 5, 20),
        subtotal=18.0, tax=1.5, tip=3.0, total=22.5,
        line_items=[
            ParsedLineItem("Latte", 2, 5.0, 10.0),
            ParsedLineItem("Muffin", 1, 8.0, 8.0),
        ],
        status=ReceiptStatus.VERIFIED,
        review_reason=None,
    )


def test_persist_writes_and_verifies(session):
    rid = persist(session, _parsed(), "/tmp/r.jpg", "hash-1", "qwen2.5vl:3b")
    assert isinstance(rid, int)

    row = session.get(Receipt, rid)
    assert row is not None
    assert row.merchant == "Corner Cafe"
    assert row.model == "qwen2.5vl:3b"
    assert row.status == ReceiptStatus.VERIFIED
    assert len(row.line_items) == 2


def test_verify_write_raises_on_count_mismatch(session):
    rid = persist(session, _parsed(), "/tmp/r.jpg", "hash-2", "qwen2.5vl:3b")
    with pytest.raises(LoadVerificationError):
        verify_write(session, rid, expected_line_items=99)


def test_verify_write_raises_when_missing(session):
    with pytest.raises(LoadVerificationError):
        verify_write(session, receipt_id=123456, expected_line_items=0)


def test_persist_round_trips_line_item_status(session):
    # Per-item status and reason must survive the write and read back unchanged.
    parsed = _parsed()
    parsed.line_items[0].status = ReceiptStatus.NEEDS_REVIEW
    parsed.line_items[0].review_reason = "qty*unit_price (10.00) != line_total (99.00)"
    rid = persist(session, parsed, "/tmp/r.jpg", "hash-status", "qwen2.5vl:3b")

    row = session.get(Receipt, rid)
    flagged = next(i for i in row.line_items if i.description == "Latte")
    assert flagged.status == ReceiptStatus.NEEDS_REVIEW
    assert "!=" in flagged.review_reason
