"""Parsing stage: normalize extracted values and decide a verification status.

Pure functions only — no I/O. Given a ReceiptExtraction, produce a ParsedReceipt with
cleaned values, a status (verified / needs_review), and a human-readable reason when the
data looks incomplete or inconsistent. Each line item is reconciled the same way
(quantity x unit_price vs line_total) and a flagged item rolls up to flag its receipt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.config import settings
from app.models import ReceiptStatus
from app.schemas import LineItemExtraction, ReceiptExtraction

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
    # Optional grocery category; only set by manual entry (see app.config.ITEM_CATEGORIES).
    category: str | None = None
    status: ReceiptStatus = ReceiptStatus.NEEDS_REVIEW
    review_reason: str | None = None


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


def reconcile_line_item(item: ParsedLineItem) -> tuple[ReceiptStatus, str | None]:
    """Decide a per-item status by checking the line's arithmetic.

    Flags an item when quantity x unit_price does not match its printed line_total,
    or when line_total is non-positive. The arithmetic check only runs when unit_price
    and line_total are both present; a missing quantity is treated as 1 (the common
    single-unit case), mirroring how the receipt-level check treats missing tax/tip as 0.

    Args:
        item: A cleaned line item whose monetary fields are already rounded.

    Returns:
        (status, review_reason). review_reason is None when verified.
    """
    reasons: list[str] = []
    tol = settings.reconcile_tolerance

    if item.line_total is not None and item.line_total <= 0:
        reasons.append("non-positive line total")

    # Use `is not None` (not truthiness) so a 0 unit_price/quantity is still checked.
    if item.unit_price is not None and item.line_total is not None:
        quantity = item.quantity if item.quantity is not None else 1
        expected = quantity * item.unit_price
        if abs(expected - item.line_total) > tol:
            reasons.append(
                f"qty*unit_price ({expected:.2f}) != line_total ({item.line_total:.2f})"
            )

    if reasons:
        return ReceiptStatus.NEEDS_REVIEW, "; ".join(reasons)
    return ReceiptStatus.VERIFIED, None


def _clean_line_items(items: list[LineItemExtraction]) -> list[ParsedLineItem]:
    """Drop blank-description items, round monetary fields, and flag bad arithmetic."""
    cleaned: list[ParsedLineItem] = []
    for it in items:
        desc = (it.description or "").strip()
        if not desc:
            continue
        item = ParsedLineItem(
            description=desc,
            quantity=it.quantity,
            unit_price=round_money(it.unit_price),
            line_total=round_money(it.line_total),
        )
        item.status, item.review_reason = reconcile_line_item(item)
        cleaned.append(item)
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

    # Totals consistency: checkable whenever subtotal and total are present.
    # Missing tax/tip are treated as 0 so the check still runs for receipts
    # without a tip (e.g. retail/grocery), which is the common case.
    if parsed.total is not None and parsed.subtotal is not None:
        expected = parsed.subtotal + (parsed.tax or 0.0) + (parsed.tip or 0.0)
        if abs(expected - parsed.total) > tol:
            reasons.append(
                f"subtotal+tax+tip ({expected:.2f}) != total ({parsed.total:.2f})"
            )

    # Roll up per-item flags so a verified receipt never hides a bad line item.
    flagged = [it for it in parsed.line_items if it.status is ReceiptStatus.NEEDS_REVIEW]
    if flagged:
        reasons.append(f"{len(flagged)} line item(s) need review")

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
