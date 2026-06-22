"""Tests for the store-list and category-totals endpoints in app.web.

These call the endpoint functions directly (no HTTP layer) against a per-test temp
database. ``RECEIPTS_DB_PATH`` is set before importing app.web because that module
builds its engine and calls init_db() at import time.
"""
from __future__ import annotations

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

from app import web
from app.db import get_session, init_db, make_engine
from app.models import LineItem, Receipt, ReceiptStatus


def _seed(tmp_path: Path, monkeypatch) -> None:
    """Point app.web at a temp DB seeded with two receipts across two stores."""
    engine = make_engine(str(tmp_path / "t.db"))
    init_db(engine)
    monkeypatch.setattr(web, "engine", engine)

    with get_session(engine) as session:
        # QFC on 2026-06-04: dairy 10.00, fruits and vegetables 5.00, uncategorized 2.00
        session.add(
            Receipt(
                source_image_path="a.png", image_sha256="h1", model="manual-entry",
                merchant="QFC", purchased_at=date(2026, 6, 4),
                status=ReceiptStatus.VERIFIED,
                line_items=[
                    LineItem(description="Milk", category="dairy", line_total=10.0),
                    LineItem(description="Apples", category="fruits and vegetables", line_total=5.0),
                    LineItem(description="Mystery", category=None, line_total=2.0),
                ],
            )
        )
        # Safeway on 2026-06-10: dairy 3.00, snacks 4.00, and a null line_total (counts, adds 0)
        session.add(
            Receipt(
                source_image_path="b.png", image_sha256="h2", model="manual-entry",
                merchant="Safeway", purchased_at=date(2026, 6, 10),
                status=ReceiptStatus.VERIFIED,
                line_items=[
                    LineItem(description="Cheese", category="dairy", line_total=3.0),
                    LineItem(description="Chips", category="snacks", line_total=4.0),
                    LineItem(description="Freebie", category="snacks", line_total=None),
                ],
            )
        )


def _by_cat(result: dict) -> dict[str, float]:
    return {r["category"]: r["total"] for r in result["rows"]}


def test_list_stores_returns_sorted_distinct(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert web.list_stores() == {"stores": ["QFC", "Safeway"]}


def test_summary_unfiltered_totals_all_categories(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    result = web.summary_by_category()

    assert _by_cat(result) == {
        "dairy": 13.0,
        "fruits and vegetables": 5.0,
        "snacks": 4.0,
        "(uncategorized)": 2.0,
    }
    assert result["grand_total"] == 24.0
    assert result["item_count"] == 6  # the null line_total item is still counted
    # Rows are sorted by total, largest first.
    assert [r["category"] for r in result["rows"]][0] == "dairy"


def test_summary_filtered_by_store(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    result = web.summary_by_category(store="Safeway")
    assert _by_cat(result) == {"snacks": 4.0, "dairy": 3.0}
    assert result["grand_total"] == 7.0


def test_summary_filtered_by_category(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    result = web.summary_by_category(category="dairy")
    assert _by_cat(result) == {"dairy": 13.0}
    assert result["item_count"] == 2


def test_summary_filtered_by_date_range(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    # Only the QFC receipt (2026-06-04) falls in this window.
    result = web.summary_by_category(date_from="2026-06-01", date_to="2026-06-05")
    assert _by_cat(result) == {
        "dairy": 10.0,
        "fruits and vegetables": 5.0,
        "(uncategorized)": 2.0,
    }
    assert result["grand_total"] == 17.0


def test_summary_combined_filters(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    result = web.summary_by_category(store="QFC", category="dairy")
    assert _by_cat(result) == {"dairy": 10.0}


def test_summary_rejects_bad_date(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        web.summary_by_category(date_from="nonsense")
    assert exc.value.status_code == 400
