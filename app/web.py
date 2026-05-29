"""A minimal web UI for browsing stored receipts and their line items.

This is a read-only viewer over the SQLite database produced by the pipeline.
It serves a single HTML page plus a small JSON API:

* ``GET /``                          -> the viewer page
* ``GET /api/receipts``              -> all receipt header rows
* ``GET /api/receipts/{id}/items``   -> line items for one receipt
* ``GET /api/receipts/{id}/image``   -> the original receipt photo

Run it with::

    uvicorn app.web:app --reload

The database path defaults to :data:`app.config.settings.default_db_path` and can
be overridden with the ``RECEIPTS_DB_PATH`` environment variable.
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import select

from app.config import settings
from app.db import get_session, init_db, make_engine
from app.ingestion import IMAGE_EXTENSIONS
from app.models import LineItem, Receipt
from app.pipeline import run_pipeline

# Project root (the directory that holds the ``app`` package). Relative paths in
# the database (e.g. "images/receipt1.jpg") and the configured DB path are
# resolved against this so the server works regardless of the caller's CWD.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
# Uploaded photos are written here (gitignored) so the viewer's image endpoint
# can serve them later, just like images ingested via the CLI.
IMAGES_DIR = PROJECT_ROOT / "images"


def _resolve(path_str: str) -> Path:
    """Resolve a possibly-relative path against the project root."""
    p = Path(path_str).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def _db_path() -> str:
    """Return the configured database path (env override wins)."""
    return os.environ.get("RECEIPTS_DB_PATH", settings.default_db_path)


# A single shared engine for the app's lifetime. init_db is a no-op when the
# tables already exist, so this is safe even for an empty/new database.
engine = make_engine(str(_resolve(_db_path())))
init_db(engine)

app = FastAPI(title="Receipt OCR Viewer")


@app.get("/api/receipts")
def list_receipts() -> list[dict]:
    """Return every receipt header row, newest first.

    Returns:
        A list of receipt dicts with the columns shown in the table. Dates and
        timestamps are rendered as ISO strings (or None) for easy display.
    """
    with get_session(engine) as session:
        receipts = session.exec(
            select(Receipt).order_by(Receipt.created_at.desc())
        ).all()
        return [
            {
                "id": r.id,
                "merchant": r.merchant,
                "purchased_at": r.purchased_at.isoformat() if r.purchased_at else None,
                "subtotal": r.subtotal,
                "tax": r.tax,
                "tip": r.tip,
                "total": r.total,
                "status": r.status.value,
                "review_reason": r.review_reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in receipts
        ]


@app.get("/api/receipts/{receipt_id}/items")
def list_items(receipt_id: int) -> list[dict]:
    """Return the line items belonging to one receipt.

    Args:
        receipt_id: Primary key of the receipt.

    Returns:
        A list of line-item dicts ordered by their insertion id.

    Raises:
        HTTPException: 404 if no receipt with that id exists.
    """
    with get_session(engine) as session:
        if session.get(Receipt, receipt_id) is None:
            raise HTTPException(status_code=404, detail="Receipt not found")
        items = session.exec(
            select(LineItem)
            .where(LineItem.receipt_id == receipt_id)
            .order_by(LineItem.id)
        ).all()
        return [
            {
                "id": i.id,
                "description": i.description,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "line_total": i.line_total,
            }
            for i in items
        ]


@app.get("/api/receipts/{receipt_id}/image")
def get_image(receipt_id: int) -> FileResponse:
    """Serve the original photo for one receipt.

    Args:
        receipt_id: Primary key of the receipt.

    Returns:
        The image file as an HTTP response.

    Raises:
        HTTPException: 404 if the receipt or its image file is missing.
    """
    with get_session(engine) as session:
        receipt = session.get(Receipt, receipt_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="Receipt not found")
        image_path = _resolve(receipt.source_image_path)

    if not image_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Image file not found: {receipt.source_image_path}",
        )
    return FileResponse(image_path)


@app.post("/api/receipts", status_code=201)
async def upload_receipt(file: UploadFile = File(...)) -> dict:
    """Accept a receipt photo, run the pipeline on it, and return the outcome.

    The uploaded file is saved into the ``images/`` folder under a collision-proof
    name, then handed to :func:`app.pipeline.run_pipeline` synchronously (the local
    vision model takes a few seconds). On a duplicate or error the saved file is
    removed so ``images/`` only ever holds photos referenced by the database.

    Args:
        file: The multipart-uploaded image (jpg/png/webp/heic/...).

    Returns:
        A dict describing what happened: ``outcome`` (loaded/skipped_duplicate),
        ``message``, ``receipt_id``, and for loaded receipts ``status`` and
        ``review_reason``.

    Raises:
        HTTPException: 400 for an unsupported/missing extension, 500 if the
            pipeline reports an error.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported image type '{suffix or file.filename}'. "
                f"Expected one of: {sorted(IMAGE_EXTENSIONS)}"
            ),
        )

    # Save under "<original-stem>_<short-uuid><suffix>" so two uploads with the
    # same filename never overwrite each other. Duplicate *content* is caught by
    # the pipeline's SHA-256 check, not by the filename.
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(file.filename or "receipt").stem
    dest = IMAGES_DIR / f"{stem}_{uuid4().hex[:8]}{suffix}"
    dest.write_bytes(await file.read())

    # Store a path relative to the project root so the DB stays portable and the
    # image endpoint's _resolve() can find it again.
    relative_path = dest.relative_to(PROJECT_ROOT)
    result = run_pipeline(relative_path, engine=engine)

    if result.outcome != "loaded":
        # Nothing in the DB references this file, so don't leave it on disk.
        dest.unlink(missing_ok=True)

    if result.outcome == "error":
        raise HTTPException(status_code=500, detail=result.message)

    return {
        "outcome": result.outcome,
        "message": result.message,
        "receipt_id": result.receipt_id,
        "status": result.receipt_status.value if result.receipt_status else None,
        "review_reason": result.review_reason,
    }


# Mount the static viewer last so the API routes above take precedence. html=True
# makes "/" serve index.html.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main() -> None:  # pragma: no cover - convenience runner
    """Run the dev server via ``python -m app.web``."""
    import uvicorn

    uvicorn.run("app.web:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":  # pragma: no cover
    main()
