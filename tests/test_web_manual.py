"""Tests for the manual receipt-entry endpoint in app.web.

These call :func:`app.web.create_manual_receipt` directly (no HTTP layer) against a
temporary database and a temporary images directory, so neither the real
``receipts.db`` nor the repo's ``images/`` folder is touched. ``RECEIPTS_DB_PATH``
is set to a temp file *before* importing app.web because that module builds its
engine and calls init_db() at import time.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
from datetime import date
from pathlib import Path

# Must run before importing app.web (it builds its engine at import time).
os.environ.setdefault(
    "RECEIPTS_DB_PATH", str(Path(tempfile.mkdtemp()) / "import_time.db")
)

import pytest
from fastapi import HTTPException
from sqlmodel import select
from starlette.datastructures import UploadFile

from app import web
from app.db import get_session, init_db, make_engine
from app.models import LineItem, Receipt, ReceiptStatus


def _setup(tmp_path: Path, monkeypatch) -> None:
    """Point app.web at a per-test temp database and temp images directory."""
    engine = make_engine(str(tmp_path / "t.db"))
    init_db(engine)
    monkeypatch.setattr(web, "engine", engine)
    # Keep uploaded files (and the relative_to() base) inside the tmp dir.
    monkeypatch.setattr(web, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(web, "IMAGES_DIR", tmp_path / "images")


def _upload(name: str = "receipt.png", data: bytes = b"fake-png-bytes") -> UploadFile:
    """Build an in-memory UploadFile. The bytes need not be a real image: the
    ingestion step only checks the extension and hashes the bytes for .png."""
    return UploadFile(filename=name, file=io.BytesIO(data))


def _call(**kwargs):
    """Run the async endpoint to completion and return its result dict."""
    return asyncio.run(web.create_manual_receipt(**kwargs))


def test_manual_entry_persists_verified_receipt(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    items = [
        {"description": "Latte", "value": "4.00"},
        {"description": "Muffin", "value": "3.50"},
        {"description": "", "value": ""},  # blank row -> dropped
    ]

    result = _call(
        file=_upload(),
        merchant="  Joe's Cafe  ",
        purchased_at="2026-06-01",
        total="12.50",
        tax="1.10",
        items=json.dumps(items),
    )

    assert result["outcome"] == "loaded"
    assert result["merchant"] == "Joe's Cafe"
    rid = result["receipt_id"]

    with get_session(web.engine) as session:
        receipt = session.get(Receipt, rid)
        assert receipt.merchant == "Joe's Cafe"
        assert receipt.status == ReceiptStatus.VERIFIED
        assert receipt.model == "manual-entry"
        assert receipt.purchased_at == date(2026, 6, 1)
        assert receipt.total == 12.5
        assert receipt.tax == 1.1
        assert receipt.subtotal is None and receipt.tip is None

        lines = session.exec(
            select(LineItem).where(LineItem.receipt_id == rid).order_by(LineItem.id)
        ).all()
        assert [(li.description, li.line_total) for li in lines] == [
            ("Latte", 4.0),
            ("Muffin", 3.5),
        ]
        assert all(li.status == ReceiptStatus.VERIFIED for li in lines)
        source_image_path = receipt.source_image_path

    # The uploaded photo was saved under the temp images dir and is referenced.
    saved = web._resolve(source_image_path)
    assert saved.is_file()
    assert saved.parent == tmp_path / "images"


def test_manual_entry_allows_blank_optional_fields(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    result = _call(
        file=_upload(),
        merchant="Corner Store",
        purchased_at="",
        total="",
        tax="",
        items=json.dumps([{"description": "Gum", "value": ""}]),
    )

    with get_session(web.engine) as session:
        receipt = session.get(Receipt, result["receipt_id"])
        assert receipt.purchased_at is None
        assert receipt.total is None and receipt.tax is None
        assert receipt.line_items[0].line_total is None


def test_manual_entry_rejects_unsupported_image(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        _call(
            file=_upload(name="notes.txt"),
            merchant="Store",
            purchased_at="",
            total="",
            tax="",
            items=json.dumps([{"description": "X", "value": "1"}]),
        )
    assert exc.value.status_code == 400


def test_manual_entry_rejects_blank_store_name(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        _call(
            file=_upload(),
            merchant="   ",
            purchased_at="",
            total="",
            tax="",
            items=json.dumps([{"description": "X", "value": "1"}]),
        )
    assert exc.value.status_code == 400


def test_manual_entry_persists_line_item_categories(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # A valid category, an explicit blank (no category), and a row that omits the
    # field entirely all coexist.
    items = [
        {"description": "Apples", "category": "fruits and vegetables", "value": "3.00"},
        {"description": "Mystery", "category": "", "value": "1.00"},
        {"description": "Bread", "value": "2.00"},  # category key absent
    ]

    result = _call(
        file=_upload(),
        merchant="Market",
        purchased_at="",
        total="",
        tax="",
        items=json.dumps(items),
    )

    with get_session(web.engine) as session:
        lines = session.exec(
            select(LineItem)
            .where(LineItem.receipt_id == result["receipt_id"])
            .order_by(LineItem.id)
        ).all()
        assert [(li.description, li.category) for li in lines] == [
            ("Apples", "fruits and vegetables"),
            ("Mystery", None),
            ("Bread", None),
        ]


def test_manual_entry_rejects_unknown_category(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        _call(
            file=_upload(),
            merchant="Store",
            purchased_at="",
            total="",
            tax="",
            items=json.dumps([{"description": "X", "category": "gadgets", "value": "1"}]),
        )
    assert exc.value.status_code == 400
    # The rejected request must not leave an orphaned file behind.
    images_dir = tmp_path / "images"
    assert not images_dir.exists() or not any(images_dir.iterdir())


def test_categories_endpoint_lists_configured_categories():
    from app.config import settings

    result = web.list_categories()
    assert result["categories"] == list(settings.item_categories)


def test_manual_entry_rejects_bad_number(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        _call(
            file=_upload(),
            merchant="Store",
            purchased_at="",
            total="abc",
            tax="",
            items=json.dumps([{"description": "X", "value": "1"}]),
        )
    assert exc.value.status_code == 400
    # A malformed request must not leave an orphaned file behind.
    images_dir = tmp_path / "images"
    assert not images_dir.exists() or not any(images_dir.iterdir())
