"""Ingestion stage: validate the image and hash it."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

# Common phone-camera formats. Extension check is a cheap sanity gate, not a
# guarantee the bytes are a valid image (the model call is the real test).
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tiff", ".bmp"}

# Formats Ollama's image decoder can't read. We transcode these to PNG before
# handing the file to the vision model. iPhones save photos as HEIC by default,
# so this is the common case for phone-camera receipts. (As a bonus, browsers
# can't display HEIC either, so storing the PNG makes the web viewer work too.)
CONVERT_TO_PNG_EXTENSIONS = {".heic", ".heif"}


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


def convert_to_png(path: Path) -> Path:
    """Transcode an image to PNG, writing the result next to the original.

    Used for formats the vision model's image decoder can't read (e.g. HEIC).
    The PNG is written alongside the source with the same stem and a ``.png``
    suffix; if it already exists it is reused, so repeat runs don't re-encode.

    Args:
        path: Path to the source image (already validated to exist).

    Returns:
        Path to the PNG version of the image.

    Raises:
        RuntimeError: If Pillow / pillow-heif are not installed, or the source
            bytes cannot be decoded into an image.
    """
    try:
        from PIL import Image, UnidentifiedImageError
        from pillow_heif import register_heif_opener
    except ImportError as exc:  # dependency missing -> clear, actionable message
        raise RuntimeError(
            f"Cannot convert '{path.name}' to PNG: install 'pillow' and "
            f"'pillow-heif' (pip install -r requirements.txt)."
        ) from exc

    # Teaches Pillow to open HEIC/HEIF files; safe to call repeatedly.
    register_heif_opener()

    dest = path.with_suffix(".png")
    if dest.exists():
        return dest
    try:
        with Image.open(path) as img:
            img.save(dest, format="PNG")
    except (UnidentifiedImageError, OSError) as exc:
        raise RuntimeError(f"Could not read image '{path.name}': {exc}") from exc
    return dest


def compute_sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of the file's bytes (read in chunks)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest(path: str | Path) -> IngestResult:
    """Validate, hash, and (if needed) transcode the image to a readable format.

    HEIC/HEIF images are converted to PNG so the downstream vision model can read
    them; the returned path then points at the PNG. The SHA-256 is always taken
    from the original source bytes so a photo's provenance stays stable across
    runs (and across Pillow versions, whose PNG encoding may differ).

    Args:
        path: Path to the receipt image.

    Returns:
        An IngestResult whose ``path`` is model-readable (the PNG for converted
        formats, otherwise the original) and whose ``sha256`` hashes the original.
    """
    validated = validate_image_path(path)
    sha256 = compute_sha256(validated)
    if validated.suffix.lower() in CONVERT_TO_PNG_EXTENSIONS:
        prepared = convert_to_png(validated)
    else:
        prepared = validated
    return IngestResult(path=prepared, sha256=sha256)
