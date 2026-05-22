# Phase 1 — Data model & DB layer

## Goal

Define the two schema layers (what the model returns vs. what we store) and the SQLite helpers,
then prove a receipt + its line items can be written and read back.

## Prerequisites

Phase 0 complete (package skeleton, deps installed).

## Files to create / modify

- `receipt_ocr/schemas.py` (new) — Pydantic models the LLM returns.
- `receipt_ocr/models.py` (new) — SQLModel tables + status enum.
- `receipt_ocr/db.py` (new) — engine + init + session helpers.
- `tests/conftest.py` (new) — shared fixtures (in-memory engine/session, sample extraction).
- `tests/test_models.py` (new) — round-trip persistence test.
- Optionally delete `tests/test_smoke.py` once real tests exist.

## Detailed spec

### `receipt_ocr/schemas.py` — extraction schemas (Pydantic)

These define exactly what we ask the vision model to return. **Every field is optional** (except
a line item's description) so a partial or imperfect read still parses — the parsing stage, not
the schema, decides whether a receipt is good enough.

```python
"""Pydantic schemas describing the JSON the vision model must return.

These are intentionally permissive (mostly optional fields) so a partial read still
validates. The parsing stage decides whether the extracted data is complete enough.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LineItemExtraction(BaseModel):
    """A single line item as read from the receipt."""

    description: str
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None


class ReceiptExtraction(BaseModel):
    """The full receipt as read from the image."""

    merchant: str | None = None
    purchased_at: str | None = Field(
        default=None, description="Raw date/time string as printed on the receipt."
    )
    subtotal: float | None = None
    tax: float | None = None
    tip: float | None = None
    total: float | None = None
    line_items: list[LineItemExtraction] = Field(default_factory=list)
```

### `receipt_ocr/models.py` — persistence tables (SQLModel)

Normalized: one `Receipt` header row, many `LineItem` rows linked by foreign key.

```python
"""SQLModel tables for persisting receipts and their line items."""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from sqlmodel import Field, Relationship, SQLModel


class ReceiptStatus(str, Enum):
    """Whether an extracted receipt passed validation or needs a human look."""

    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"


class Receipt(SQLModel, table=True):
    """A receipt header row.

    image_sha256 is unique so the same photo is never ingested twice.
    """

    id: int | None = Field(default=None, primary_key=True)
    source_image_path: str
    image_sha256: str = Field(index=True, unique=True)
    merchant: str | None = None
    purchased_at: date | None = None
    subtotal: float | None = None
    tax: float | None = None
    tip: float | None = None
    total: float | None = None
    status: ReceiptStatus = Field(default=ReceiptStatus.NEEDS_REVIEW)
    review_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    line_items: list["LineItem"] = Relationship(back_populates="receipt")


class LineItem(SQLModel, table=True):
    """A single purchased item belonging to a receipt."""

    id: int | None = Field(default=None, primary_key=True)
    receipt_id: int | None = Field(default=None, foreign_key="receipt.id")
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None

    receipt: Receipt | None = Relationship(back_populates="line_items")
```

### `receipt_ocr/db.py` — engine + session helpers

```python
"""SQLite engine creation and session helpers (via SQLModel/SQLAlchemy)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.engine import Engine

# Importing models registers the tables on SQLModel.metadata before create_all().
from receipt_ocr import models  # noqa: F401


def make_engine(db_path: str) -> Engine:
    """Create a SQLite engine for the given file path."""
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db(engine: Engine) -> None:
    """Create all tables if they do not yet exist."""
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session(engine: Engine) -> Iterator[Session]:
    """Yield a session bound to the engine, closing it afterward."""
    with Session(engine) as session:
        yield session
```

> The `import receipt_ocr.models` inside `db.py` matters: `create_all` only creates tables that
> have been registered on `SQLModel.metadata`, which happens when the model classes are imported.

## Tests

### `tests/conftest.py`

Use an **in-memory SQLite** engine with `StaticPool` so the same connection (and thus the same
in-memory DB) is shared across the test's sessions.

```python
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
```

### `tests/test_models.py`

```python
from datetime import date

from receipt_ocr.models import LineItem, Receipt, ReceiptStatus


def test_receipt_roundtrip(session):
    receipt = Receipt(
        source_image_path="/tmp/r.jpg",
        image_sha256="abc123",
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

    fetched = session.get(Receipt, receipt.id)
    assert fetched is not None
    assert fetched.merchant == "Corner Cafe"
    assert fetched.status == ReceiptStatus.VERIFIED
    assert len(fetched.line_items) == 2
    assert {li.description for li in fetched.line_items} == {"Latte", "Muffin"}
```

## Edge cases & gotchas

- **In-memory DB sharing:** without `poolclass=StaticPool`, each connection gets a *fresh* empty
  in-memory database and tests fail mysteriously. Always use the fixture above for tests.
- **`datetime.utcnow` is deprecated** in 3.12+. Use `datetime.now(timezone.utc)` as shown.
- **Forward references:** `list["LineItem"]` / `Receipt | None` in `Relationship` fields are
  resolved by SQLModel; keep `from __future__ import annotations` at the top.
- **Enum storage:** because `ReceiptStatus(str, Enum)`, the string value (`"verified"`) is what
  lands in the column — convenient for `sqlite3` inspection.

## Definition of Done

- `tests/test_models.py` passes: a receipt with two line items is written, re-fetched, and the
  relationship + field values are intact.
- `pytest` is green.

## Suggested commit

```
feat: add receipt/line-item models, extraction schemas, and SQLite DB layer
```
