import hashlib

import pytest

from app.ingestion import (
    compute_sha256,
    ingest,
    validate_image_path,
)
from app.models import Receipt, ReceiptStatus


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
