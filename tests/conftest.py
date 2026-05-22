import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from receipt_ocr import models  # noqa: F401  (register tables)
from receipt_ocr.schemas import LineItemExtraction, ReceiptExtraction


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def sample_extraction() -> ReceiptExtraction:
    return ReceiptExtraction(
        merchant="Corner Cafe",
        purchased_at="2026-05-20",
        subtotal=18.00,
        tax=1.50,
        tip=3.00,
        total=22.50,
        line_items=[
            LineItemExtraction(description="Latte", quantity=2, unit_price=5.00, line_total=10.00),
            LineItemExtraction(description="Muffin", quantity=1, unit_price=8.00, line_total=8.00),
        ],
    )
