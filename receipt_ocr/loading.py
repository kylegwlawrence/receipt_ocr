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
