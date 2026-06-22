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

import json
import logging
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import select

from app.config import settings
from app.db import get_session, init_db, make_engine
from app.ingestion import IMAGE_EXTENSIONS, ingest
from app.loading import persist
from app.models import LineItem, Receipt, ReceiptStatus
from app.parsing import ParsedLineItem, ParsedReceipt
from app.pipeline import run_pipeline

logger = logging.getLogger("app")

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


@app.get("/api/models")
def list_models() -> dict:
    """Return installed Ollama models that can read images (vision-capable).

    Each model's capabilities are read via the Ollama ``show`` API; only models
    whose capabilities include ``"vision"`` are returned, sorted by name. The
    configured default is reported separately so the UI can pre-select it.

    Returns:
        ``{"models": [name, ...], "default": <default model name>}``. On any Ollama
        error (server down, library missing) the list falls back to just the
        configured default so the selector is never empty.
    """
    default = settings.default_model
    try:
        import ollama  # imported lazily; the server may run without Ollama present

        vision: list[str] = []
        for entry in ollama.list().models:
            name = entry.model
            try:
                capabilities = ollama.show(name).capabilities or []
            except Exception:  # noqa: BLE001 - skip a model we can't introspect
                continue
            if "vision" in capabilities:
                vision.append(name)
        vision.sort()
        if not vision:
            vision = [default]
    except Exception as exc:  # noqa: BLE001 - any Ollama failure -> safe fallback
        logger.warning("Could not list Ollama models: %s", exc)
        vision = [default]

    return {"models": vision, "default": default}


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
                "model": r.model,
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
async def upload_receipt(
    file: UploadFile = File(...),
    model: str | None = Form(None),
) -> dict:
    """Accept a receipt photo, run the pipeline on it, and return the outcome.

    The uploaded file is saved into the ``images/`` folder under a collision-proof
    name, then handed to :func:`app.pipeline.run_pipeline` synchronously (the local
    vision model takes a few seconds). On an error the saved file is removed so
    ``images/`` only ever holds photos referenced by the database.

    Args:
        file: The multipart-uploaded image (jpg/png/webp/heic/...).
        model: Ollama model to extract with. Defaults to settings.default_model
            when omitted.

    Returns:
        A dict describing what happened: ``outcome``, ``message``, ``receipt_id``,
        the ``model`` used, and for loaded receipts ``status`` and ``review_reason``.

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
    result = run_pipeline(relative_path, engine=engine, model=model)

    if result.outcome != "loaded":
        # Nothing in the DB references this file, so don't leave it on disk.
        dest.unlink(missing_ok=True)
        # Ingestion transcodes HEIC/HEIF to a sibling PNG; remove that too so a
        # failed upload leaves nothing behind.
        png_sibling = dest.with_suffix(".png")
        if png_sibling != dest:
            png_sibling.unlink(missing_ok=True)

    if result.outcome == "error":
        raise HTTPException(status_code=500, detail=result.message)

    return {
        "outcome": result.outcome,
        "message": result.message,
        "receipt_id": result.receipt_id,
        "model": model or settings.default_model,
        "status": result.receipt_status.value if result.receipt_status else None,
        "review_reason": result.review_reason,
    }


def _parse_money(value: str | int | float | None) -> float | None:
    """Parse an optional money value into a rounded float (or None).

    Accepts both the form's string amounts (``total``/``tax``) and the JSON line
    items' values, which may arrive as strings or numbers.

    Args:
        value: The raw value (may be None, blank, a numeric string, or a number).

    Returns:
        ``None`` for a missing/blank value, otherwise the amount rounded to 2
        decimal places (matching the parsing stage's convention).

    Raises:
        HTTPException: 400 if the value is present but not a valid number.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return round(float(text), 2)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid number: '{value}'") from exc


def _parse_date(value: str | None) -> date | None:
    """Parse an optional ``YYYY-MM-DD`` string from a form into a date (or None).

    Raises:
        HTTPException: 400 if the value is present but not an ISO date.
    """
    if value is None or value.strip() == "":
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date: '{value}' (expected YYYY-MM-DD)",
        ) from exc


@app.post("/api/receipts/manual", status_code=201)
async def create_manual_receipt(
    file: UploadFile = File(...),
    merchant: str = Form(...),
    purchased_at: str | None = Form(None),
    total: str | None = Form(None),
    tax: str | None = Form(None),
    items: str = Form("[]"),
) -> dict:
    """Persist a hand-entered receipt (photo + typed fields), skipping the model.

    This is the manual-annotation counterpart to :func:`upload_receipt`. Instead
    of running the vision pipeline, it builds a :class:`~app.parsing.ParsedReceipt`
    directly from the submitted form and stores it as VERIFIED ground truth tagged
    with the model name ``"manual-entry"`` (so manual records are distinguishable
    from model extractions). The photo is saved and, if HEIC/HEIF, transcoded to
    PNG via :func:`app.ingestion.ingest` — just like the pipeline — so the viewer's
    image endpoint can display it.

    Args:
        file: The required receipt photo.
        merchant: Store name (required, non-blank).
        purchased_at: Purchase date as ``YYYY-MM-DD`` (optional).
        total: Receipt total as a money string (optional).
        tax: Tax amount as a money string (optional).
        items: A JSON array of ``{"description": str, "value": str}`` line items.
            Rows with a blank description are dropped.

    Returns:
        A dict: ``{"outcome": "loaded", "receipt_id": int, "merchant": str}``.

    Raises:
        HTTPException: 400 for an unsupported image, a blank store name, malformed
            numbers/date, or invalid items JSON; 500 if the write fails.
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

    if not merchant.strip():
        raise HTTPException(status_code=400, detail="Store name is required.")

    # Decode and validate the form payload up front so a malformed request fails
    # before we write anything to disk.
    try:
        raw_items = json.loads(items)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid items JSON: {exc}") from exc
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=400, detail="items must be a JSON array.")

    line_items = [
        ParsedLineItem(
            description=str(row.get("description", "")).strip(),
            quantity=None,
            unit_price=None,
            line_total=_parse_money(row.get("value")),
            status=ReceiptStatus.VERIFIED,
        )
        for row in raw_items
        if isinstance(row, dict) and str(row.get("description", "")).strip()
    ]

    parsed = ParsedReceipt(
        merchant=merchant.strip(),
        purchased_at=_parse_date(purchased_at),
        subtotal=None,
        tax=_parse_money(tax),
        tip=None,
        total=_parse_money(total),
        line_items=line_items,
        status=ReceiptStatus.VERIFIED,
        review_reason=None,
    )

    # Save the photo under a collision-proof name (same scheme as upload_receipt),
    # then ingest it to hash and, for HEIC/HEIF, transcode to a viewer-readable PNG.
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(file.filename or "receipt").stem
    dest = IMAGES_DIR / f"{stem}_{uuid4().hex[:8]}{suffix}"
    dest.write_bytes(await file.read())
    try:
        ingested = ingest(dest)
        relative_path = ingested.path.relative_to(PROJECT_ROOT)
        with get_session(engine) as session:
            receipt_id = persist(
                session, parsed, str(relative_path), ingested.sha256, model="manual-entry"
            )
    except HTTPException:
        dest.unlink(missing_ok=True)
        dest.with_suffix(".png").unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 - clean up the orphaned file on any failure
        dest.unlink(missing_ok=True)
        dest.with_suffix(".png").unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Could not save receipt: {exc}") from exc

    return {"outcome": "loaded", "receipt_id": receipt_id, "merchant": merchant.strip()}


@app.delete("/api/receipts/{receipt_id}")
def delete_receipt(receipt_id: int) -> dict:
    """Delete a receipt and its line items from the database.

    The line items are removed automatically by the ORM cascade configured on
    ``Receipt.line_items``. The original photo on disk is intentionally left in
    place — deletion only affects the database, so no image files are ever
    removed here.

    Args:
        receipt_id: Primary key of the receipt to delete.

    Returns:
        A dict echoing the deleted id, e.g. ``{"deleted": 3}``.

    Raises:
        HTTPException: 404 if no receipt with that id exists.
    """
    with get_session(engine) as session:
        receipt = session.get(Receipt, receipt_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="Receipt not found")
        # The session context manager commits the delete (and its line-item
        # cascade) on clean exit.
        session.delete(receipt)

    return {"deleted": receipt_id}


# Mount the static viewer last so the API routes above take precedence. html=True
# makes "/" serve index.html.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main() -> None:  # pragma: no cover - convenience runner
    """Run the dev server via ``python -m app.web``."""
    import uvicorn

    uvicorn.run("app.web:app", host="127.0.0.1", port=8005, reload=True)


if __name__ == "__main__":  # pragma: no cover
    main()
