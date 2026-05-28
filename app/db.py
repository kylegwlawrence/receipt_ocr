"""SQLite engine creation and session helpers (via SQLModel/SQLAlchemy)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# Importing models registers the tables on SQLModel.metadata before create_all().
from app import models  # noqa: F401


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


def init_db(engine: Engine) -> None:
    """Create all tables if they do not yet exist."""
    SQLModel.metadata.create_all(engine)


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
