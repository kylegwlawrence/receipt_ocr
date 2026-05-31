"""Tests for the delete endpoint in app.web.

These call :func:`app.web.delete_receipt` directly (no HTTP layer) against a
temporary database, so the real receipts.db is never touched. ``RECEIPTS_DB_PATH``
is set to a temp file *before* importing app.web because that module builds its
engine and calls init_db() at import time.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Must run before importing app.web: that module builds its engine and calls
# init_db() at import time, and we don't want that to touch the real DB.
os.environ.setdefault(
    "RECEIPTS_DB_PATH", str(Path(tempfile.mkdtemp()) / "import_time.db")
)

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app import web
from app.db import get_session, init_db, make_engine
from app.models import LineItem, Receipt, ReceiptStatus


def _setup(tmp_path: Path, monkeypatch) -> None:
    """Point app.web at a per-test temporary database."""
    engine = make_engine(str(tmp_path / "t.db"))
    init_db(engine)
    monkeypatch.setattr(web, "engine", engine)


def _make_receipt(image_path: str, sha: str) -> int:
    """Insert a receipt with two line items; return its id."""
    with get_session(web.engine) as session:
        receipt = Receipt(
            merchant="Joe's Cafe",
            source_image_path=image_path,
            image_sha256=sha,
            status=ReceiptStatus.VERIFIED,
        )
        receipt.line_items = [
            LineItem(description="Latte"),
            LineItem(description="Muffin"),
        ]
        session.add(receipt)
        session.flush()
        return receipt.id


def test_delete_missing_raises_404(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        web.delete_receipt(999)
    assert exc.value.status_code == 404


def test_delete_removes_receipt_and_cascades_line_items(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    rid = _make_receipt("images/r.jpg", "sha-1")

    assert web.delete_receipt(rid) == {"deleted": rid}

    # The row is gone and its line items were removed by the cascade.
    with get_session(web.engine) as session:
        assert session.get(Receipt, rid) is None
        items = session.exec(
            select(LineItem).where(LineItem.receipt_id == rid)
        ).all()
        assert items == []


def test_delete_leaves_image_file_on_disk(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"img")
    rid = _make_receipt(str(image), "sha-2")

    web.delete_receipt(rid)

    # Deletion is DB-only: the photo must remain on disk.
    assert image.exists()
