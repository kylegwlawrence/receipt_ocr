"""Ingestion stage: validate the image and hash it."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

# Common phone-camera formats. Extension check is a cheap sanity gate, not a
# guarantee the bytes are a valid image (the model call is the real test).
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff", ".bmp"}


@dataclass
class IngestResult:
    """Outcome of ingesting one image.

    Attributes:
        path: The validated image path.
        sha256: Hex SHA-256 digest of the file bytes. Stored as provenance; no
            longer used for dedupe, but lets a photo's runs be grouped later.
    """

    path: Path
    sha256: str


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


def ingest(path: str | Path) -> IngestResult:
    """Validate and hash the image.

    Args:
        path: Path to the receipt image.

    Returns:
        An IngestResult with the validated path and its SHA-256 hash.
    """
    validated = validate_image_path(path)
    return IngestResult(path=validated, sha256=compute_sha256(validated))
