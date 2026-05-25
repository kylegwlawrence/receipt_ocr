"""Ingestion stage: validate the image, hash it, and check for duplicates."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from app.models import Receipt

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
