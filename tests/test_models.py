from datetime import date

from app.models import LineItem, Receipt, ReceiptStatus


def test_receipt_roundtrip(session):
    receipt = Receipt(
        source_image_path="/tmp/r.jpg",
        image_sha256="abc123",
        model="qwen2.5vl:3b",
        merchant="Corner Cafe",
        purchased_at=date(2026, 5, 20),
        subtotal=18.0, tax=1.5, tip=3.0, total=22.5,
        status=ReceiptStatus.VERIFIED,
        line_items=[
            LineItem(description="Latte", quantity=2, unit_price=5.0, line_total=10.0),
            LineItem(description="Muffin", quantity=1, unit_price=8.0, line_total=8.0),
        ],
    )
    session.add(receipt)
    session.commit()
    session.refresh(receipt)

    # expire_all forces SQLAlchemy to reload from DB rather than serving the identity-map cache.
    session.expire_all()
    fetched = session.get(Receipt, receipt.id)
    assert fetched is not None
    assert fetched.merchant == "Corner Cafe"
    assert fetched.status == ReceiptStatus.VERIFIED
    assert len(fetched.line_items) == 2
    assert {li.description for li in fetched.line_items} == {"Latte", "Muffin"}
