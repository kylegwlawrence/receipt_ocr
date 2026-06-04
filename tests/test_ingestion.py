import hashlib

import pytest

from app.ingestion import (
    compute_sha256,
    ingest,
    validate_image_path,
)


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


def test_ingest_returns_path_and_hash(tmp_path):
    # Ingestion no longer checks for duplicates; it just validates and hashes.
    p = _write_image(tmp_path)
    result = ingest(p)
    assert result.path == p
    assert result.sha256 == hashlib.sha256(b"fake-image-bytes").hexdigest()


def test_ingest_converts_heic_to_png(tmp_path):
    # HEIC can't be read by the vision model, so ingestion transcodes it to a
    # PNG sibling and returns that path; the hash still tracks the original.
    pytest.importorskip("pillow_heif")
    from PIL import Image
    from pillow_heif import register_heif_opener

    register_heif_opener()
    src = tmp_path / "receipt.heic"
    Image.new("RGB", (8, 8), "white").save(src, format="HEIF")

    result = ingest(src)

    assert result.path == src.with_suffix(".png")
    assert result.path.is_file()
    # Provenance hash is of the original HEIC bytes, not the generated PNG.
    assert result.sha256 == compute_sha256(src)
