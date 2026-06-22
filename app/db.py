"""SQLite engine creation and session helpers (via SQLModel/SQLAlchemy)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# Importing models registers the tables on SQLModel.metadata before create_all().
from app import models  # noqa: F401

# Additive, idempotent migrations for columns introduced after a table first
# shipped. ``create_all`` only creates missing *tables*, never new columns on an
# existing one, so each entry here is applied with ``ALTER TABLE ... ADD COLUMN``
# when absent. Only safe for nullable columns with no default (existing rows get
# NULL). Keyed by table name -> {column: SQL type}.
_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "lineitem": {"category": "VARCHAR"},
}


def make_engine(db_path: str) -> Engine:
    """Create a SQLite engine for the given file path.

    Also enables SQLite foreign-key enforcement, which is OFF by default.
    Creates the parent directory if it does not exist.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_fk_pragma(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _apply_additive_migrations(engine: Engine) -> None:
    """Add any columns in ``_ADDITIVE_COLUMNS`` that an existing table is missing.

    Brings a database created before a column was introduced up to date without
    dropping data. A brand-new database created by ``create_all`` already has the
    columns, so this is a no-op there. Tables not present yet are skipped.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for column, sql_type in columns.items():
                if column not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))


def init_db(engine: Engine) -> None:
    """Create all tables if they do not yet exist, then apply additive migrations."""
    SQLModel.metadata.create_all(engine)
    _apply_additive_migrations(engine)


@contextmanager
def get_session(engine: Engine) -> Iterator[Session]:
    """Yield a session, committing on clean exit and rolling back on exception."""
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
