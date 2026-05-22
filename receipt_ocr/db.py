"""SQLite engine creation and session helpers (via SQLModel/SQLAlchemy)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

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
