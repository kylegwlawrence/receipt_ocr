"""Tests for the additive column migration in app.db.

A database created before the ``lineitem.category`` column existed must gain that
column (without losing data) the next time ``init_db`` runs, and re-running the
migration must be a harmless no-op.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.db import init_db, make_engine


def _lineitem_columns(engine) -> set[str]:
    """Return the set of column names on the ``lineitem`` table."""
    return {col["name"] for col in inspect(engine).get_columns("lineitem")}


def test_migration_adds_missing_category_column(tmp_path: Path) -> None:
    engine = make_engine(str(tmp_path / "old.db"))

    # Simulate a pre-category schema: a lineitem table without the new column,
    # holding one existing row.
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE lineitem ("
                "id INTEGER PRIMARY KEY, receipt_id INTEGER, description VARCHAR,"
                "quantity FLOAT, unit_price FLOAT, line_total FLOAT,"
                "status VARCHAR, review_reason VARCHAR)"
            )
        )
        conn.execute(
            text("INSERT INTO lineitem (id, description) VALUES (1, 'Pre-existing')")
        )

    assert "category" not in _lineitem_columns(engine)

    init_db(engine)

    # The column now exists and the pre-existing row survived with a NULL category.
    assert "category" in _lineitem_columns(engine)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT description, category FROM lineitem WHERE id = 1")
        ).one()
    assert row == ("Pre-existing", None)


def test_migration_is_idempotent(tmp_path: Path) -> None:
    engine = make_engine(str(tmp_path / "fresh.db"))
    # A fresh database already has the column via create_all; running again must
    # not raise (no duplicate ALTER).
    init_db(engine)
    init_db(engine)
    assert "category" in _lineitem_columns(engine)
