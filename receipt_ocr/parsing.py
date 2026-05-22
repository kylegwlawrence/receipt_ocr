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
