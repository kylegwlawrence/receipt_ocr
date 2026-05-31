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
