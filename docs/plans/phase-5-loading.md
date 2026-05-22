# Phase 5 — Loading (persist + read-back verify)

## Goal

Write a `ParsedReceipt` (header + line items) to SQLite in one transaction, then **read it back**
to confirm the write actually landed — satisfying the goal's "Database writes data and checks it
writes successfully."

## Prerequisites

Phase 1 (`models`, `db`) and Phase 4 (`parsing.ParsedReceipt`).

## Files to create / modify

- `receipt_ocr/loading.py` (new)
- `tests/test_loading.py` (new)

## Detailed spec

### `receipt_ocr/loading.py`

```python
"""Loading stage: persist a parsed receipt and verify the write succeeded."""
from __future__ import annotations

from sqlmodel import Session

from receipt_ocr.models import LineItem, Receipt
from receipt_ocr.parsing import ParsedReceipt


class LoadVerificationError(RuntimeError):
    """Raised when a post-write read-back does not match what we tried to store."""


def to_models(
    parsed: ParsedReceipt, source_image_path: str, image_sha256: str
) -> Receipt:
    """Build a Receipt (with nested LineItems) from a ParsedReceipt.

    Args:
        parsed: The normalized receipt with its status already decided.
        source_image_path: Where the image came from (provenance).
        image_sha256: The image hash used for dedupe/uniqueness.

    Returns:
        An unsaved Receipt with its line_items relationship populated.
    """
    return Receipt(
        source_image_path=source_image_path,
        image_sha256=image_sha256,
        merchant=parsed.merchant,
        purchased_at=parsed.purchased_at,
        subtotal=parsed.subtotal,
        tax=parsed.tax,
        tip=parsed.tip,
        total=parsed.total,
        status=parsed.status,
        review_reason=parsed.review_reason,
        line_items=[
            LineItem(
                description=li.description,
                quantity=li.quantity,
                unit_price=li.unit_price,
                line_total=li.line_total,
            )
            for li in parsed.line_items
        ],
    )


def verify_write(session: Session, receipt_id: int, expected_line_items: int) -> bool:
    """Re-read the receipt and confirm it persisted with the right line-item count.

    Raises:
        LoadVerificationError: If the row is missing or the line-item count differs.
    """
    fetched = session.get(Receipt, receipt_id)
    if fetched is None:
        raise LoadVerificationError(f"Receipt {receipt_id} not found after commit")
    actual = len(fetched.line_items)
    if actual != expected_line_items:
        raise LoadVerificationError(
            f"Receipt {receipt_id}: expected {expected_line_items} line items, found {actual}"
        )
    return True


def persist(
    session: Session,
    parsed: ParsedReceipt,
    source_image_path: str,
    image_sha256: str,
) -> int:
    """Insert the receipt + line items, commit, and verify the write.

    Args:
        session: Active DB session.
        parsed: The normalized receipt to store.
        source_image_path: Provenance for the row.
        image_sha256: Image hash (unique per receipt).

    Returns:
        The new receipt's id.

    Raises:
        LoadVerificationError: If the read-back check fails.
    """
    receipt = to_models(parsed, source_image_path, image_sha256)
    session.add(receipt)
    session.commit()
    session.refresh(receipt)
    verify_write(session, receipt.id, len(parsed.line_items))
    return receipt.id
```

## Tests

### `tests/test_loading.py`

```python
import pytest

from receipt_ocr.loading import LoadVerificationError, persist, to_models, verify_write
from receipt_ocr.models import Receipt, ReceiptStatus
from receipt_ocr.parsing import ParsedLineItem, ParsedReceipt
from datetime import date


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
    rid = persist(session, _parsed(), "/tmp/r.jpg", "hash-1")
    assert isinstance(rid, int)

    row = session.get(Receipt, rid)
    assert row is not None
    assert row.merchant == "Corner Cafe"
    assert row.status == ReceiptStatus.VERIFIED
    assert len(row.line_items) == 2


def test_verify_write_raises_on_count_mismatch(session):
    rid = persist(session, _parsed(), "/tmp/r.jpg", "hash-2")
    with pytest.raises(LoadVerificationError):
        verify_write(session, rid, expected_line_items=99)


def test_verify_write_raises_when_missing(session):
    with pytest.raises(LoadVerificationError):
        verify_write(session, receipt_id=123456, expected_line_items=0)
```

## Edge cases & gotchas

- **Cascade:** assigning `line_items=[...]` on the `Receipt` and adding the receipt persists the
  children too (SQLModel/SQLAlchemy handles the FK on flush). No need to add line items
  separately.
- **Duplicate hash at insert:** `image_sha256` is `unique`, so inserting a second receipt with
  the same hash raises `sqlalchemy.exc.IntegrityError`. The pipeline's dedupe (Phase 2) prevents
  reaching here for known duplicates; this constraint is the backstop. Loading does not catch
  it — let it surface; the pipeline (Phase 6) decides how to report unexpected errors.
- **`session.refresh`** after commit populates `receipt.id`. Read-back uses `session.get`, which
  re-reads through the session.

## Definition of Done

- `tests/test_loading.py` passes: a parsed receipt persists with both line items, and
  `verify_write` raises on a count mismatch and on a missing id.
- `pytest` is green.

## Suggested commit

```
feat: add loading stage with insert and read-back verification
```
