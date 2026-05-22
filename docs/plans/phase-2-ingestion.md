# Phase 2 — Ingestion (validate, hash, dedupe)

## Goal

Turn an image path into a validated `Path` plus a SHA-256 hash, and detect whether that exact
image has already been ingested. This is the cheap gate that runs *before* the expensive model
call, so duplicates never reach the vision model.

## Prerequisites

Phase 1 complete (`models.Receipt` exists with a unique `image_sha256` column; `db.py` session
helper available).

## Files to create / modify

- `receipt_ocr/ingestion.py` (new)
- `tests/test_ingestion.py` (new)

## Detailed spec

### `receipt_ocr/ingestion.py`

```python
"""Ingestion stage: validate the image, hash it, and check for duplicates."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from receipt_ocr.models import Receipt

# Common phone-camera formats. Extension check is a cheap sanity gate, not a
# guarantee the bytes are a valid image (the model call is the real test).
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff", ".bmp"}


@dataclass
class IngestResult:
    """Outcome of ingesting one image.

    Attributes:
        path: The validated image path.
        sha256: Hex SHA-256 digest of the file bytes.
        is_duplicate: True if a receipt with this hash already exists.
        existing_id: The id of the existing receipt when is_duplicate is True.
    """

    path: Path
    sha256: str
    is_duplicate: bool
    existing_id: int | None


def validate_image_path(path: str | Path) -> Path:
    """Validate that the path exists, is a file, and has an image extension.

    Args:
        path: Path to the receipt image.

    Returns:
        The resolved Path.

    Raises:
        FileNotFoundError: If the path does not exist or is not a file.
        ValueError: If the extension is not a recognized image type.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"No such image file: {p}")
    if p.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(
            f"Unsupported image extension '{p.suffix}'. "
            f"Expected one of: {sorted(IMAGE_EXTENSIONS)}"
        )
    return p


def compute_sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of the file's bytes (read in chunks)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_existing(session: Session, image_sha256: str) -> Receipt | None:
    """Return the existing receipt with this image hash, if any."""
    statement = select(Receipt).where(Receipt.image_sha256 == image_sha256)
    return session.exec(statement).first()


def ingest(path: str | Path, session: Session) -> IngestResult:
    """Validate and hash the image, then check the DB for a duplicate.

    Args:
        path: Path to the receipt image.
        session: Active DB session for the duplicate lookup.

    Returns:
        An IngestResult describing the image and whether it's a duplicate.
    """
    validated = validate_image_path(path)
    digest = compute_sha256(validated)
    existing = find_existing(session, digest)
    return IngestResult(
        path=validated,
        sha256=digest,
        is_duplicate=existing is not None,
        existing_id=existing.id if existing else None,
    )
```

## Tests

### `tests/test_ingestion.py`

Use `tmp_path` (a pytest builtin) to create real files. Verify the hash against Python's own
`hashlib` so the test is self-checking.

```python
import hashlib

import pytest

from receipt_ocr.ingestion import (
    compute_sha256,
    ingest,
    validate_image_path,
)
from receipt_ocr.models import Receipt, ReceiptStatus


def _write_image(tmp_path, name="r.jpg", data=b"fake-image-bytes"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_validate_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_image_path(tmp_path / "nope.jpg")


def test_validate_rejects_bad_extension(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hi")
    with pytest.raises(ValueError):
        validate_image_path(p)


def test_compute_sha256_matches_hashlib(tmp_path):
    data = b"some-bytes"
    p = _write_image(tmp_path, data=data)
    assert compute_sha256(p) == hashlib.sha256(data).hexdigest()


def test_ingest_flags_new_image(tmp_path, session):
    p = _write_image(tmp_path)
    result = ingest(p, session)
    assert result.is_duplicate is False
    assert result.existing_id is None
    assert result.sha256 == hashlib.sha256(b"fake-image-bytes").hexdigest()


def test_ingest_detects_duplicate(tmp_path, session):
    p = _write_image(tmp_path)
    digest = hashlib.sha256(b"fake-image-bytes").hexdigest()
    session.add(
        Receipt(
            source_image_path=str(p),
            image_sha256=digest,
            status=ReceiptStatus.VERIFIED,
        )
    )
    session.commit()

    result = ingest(p, session)
    assert result.is_duplicate is True
    assert result.existing_id is not None
```

## Edge cases & gotchas

- The extension check is deliberately lenient — it filters obvious non-images (`.txt`, `.pdf`)
  but does not decode the file. A corrupt JPEG is caught later when the model call fails.
- Hash the **file bytes**, not a normalized image, so a re-encode/resize of the same photo is a
  *different* hash. That's acceptable for v1; content-based dedupe was explicitly not chosen.
- `Receipt.image_sha256` is `unique` at the DB level too, so even a race that bypasses
  `find_existing` is caught at insert time (see Phase 5).

## Definition of Done

- All tests in `tests/test_ingestion.py` pass.
- `pytest` is green.

## Suggested commit

```
feat: add ingestion stage with image validation and SHA-256 dedupe
```
