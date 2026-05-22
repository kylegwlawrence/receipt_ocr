# Phase 6 — Pipeline orchestration & CLI

## Goal

Wire the four stages into one `run_pipeline(image_path)` function and expose it as a CLI:
`python -m receipt_ocr <image>`. This is the phase where the tool becomes usable end to end.

## Prerequisites

Phases 1–5 complete (`db`, `ingestion`, `extraction`, `parsing`, `loading`).

## Files to create / modify

- `receipt_ocr/pipeline.py` (new)
- `receipt_ocr/cli.py` (new)
- `receipt_ocr/__main__.py` (new)
- `tests/test_pipeline.py` (new)

## Detailed spec

### `receipt_ocr/pipeline.py`

```python
"""Pipeline orchestration: ingestion -> extraction -> parsing -> loading."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy.engine import Engine
from sqlmodel import Session

from receipt_ocr.config import settings
from receipt_ocr.db import init_db, make_engine
from receipt_ocr.extraction import ExtractionError, extract
from receipt_ocr.ingestion import ingest
from receipt_ocr.loading import LoadVerificationError, persist
from receipt_ocr.models import ReceiptStatus
from receipt_ocr.parsing import parse

logger = logging.getLogger("receipt_ocr")

Outcome = Literal["loaded", "skipped_duplicate", "error"]


@dataclass
class PipelineResult:
    """The result of running the pipeline on one image."""

    outcome: Outcome
    message: str
    receipt_id: int | None = None
    receipt_status: ReceiptStatus | None = None
    review_reason: str | None = None


def run_pipeline(
    image_path: str | Path,
    *,
    db_path: str | None = None,
    model: str | None = None,
    engine: Engine | None = None,
    client=None,
) -> PipelineResult:
    """Run the full pipeline on a single receipt image.

    Args:
        image_path: Path to the receipt image.
        db_path: SQLite path; defaults to settings.default_db_path. Ignored if `engine`
            is supplied.
        model: Ollama model override; defaults to settings.default_model.
        engine: Pre-built engine (used by tests). When None, one is created from db_path.
        client: Ollama-like client override (used by tests). Passed to extraction.

    Returns:
        A PipelineResult describing what happened.
    """
    engine = engine or make_engine(db_path or settings.default_db_path)
    init_db(engine)

    try:
        with Session(engine) as session:
            ingested = ingest(image_path, session)
            if ingested.is_duplicate:
                logger.info("Duplicate image; skipping (existing id=%s)", ingested.existing_id)
                return PipelineResult(
                    outcome="skipped_duplicate",
                    message=f"Already ingested as receipt {ingested.existing_id}",
                    receipt_id=ingested.existing_id,
                )

            extraction = extract(ingested.path, model=model, client=client)
            parsed = parse(extraction)
            receipt_id = persist(session, parsed, str(ingested.path), ingested.sha256)

            logger.info("Loaded receipt id=%s status=%s", receipt_id, parsed.status.value)
            return PipelineResult(
                outcome="loaded",
                message=f"Loaded receipt {receipt_id} ({parsed.status.value})",
                receipt_id=receipt_id,
                receipt_status=parsed.status,
                review_reason=parsed.review_reason,
            )
    except (ExtractionError, LoadVerificationError, FileNotFoundError, ValueError) as exc:
        logger.error("Pipeline failed: %s", exc)
        return PipelineResult(outcome="error", message=str(exc))
```

### `receipt_ocr/cli.py`

```python
"""Command-line entry point for the receipt OCR pipeline."""
from __future__ import annotations

import argparse
import logging
import sys

from receipt_ocr.config import settings
from receipt_ocr.pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="receipt_ocr",
        description="Read a receipt photo with a local vision model and store it in SQLite.",
    )
    parser.add_argument("image", help="Path to the receipt image.")
    parser.add_argument(
        "--db-path", default=settings.default_db_path,
        help=f"SQLite file path (default: {settings.default_db_path}).",
    )
    parser.add_argument(
        "--model", default=settings.default_model,
        help=f"Ollama vision model (default: {settings.default_model}).",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    result = run_pipeline(args.image, db_path=args.db_path, model=args.model)

    print(result.message)
    if result.outcome == "loaded" and result.review_reason:
        print(f"  needs review: {result.review_reason}")

    return 1 if result.outcome == "error" else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
```

### `receipt_ocr/__main__.py`

```python
"""Enables `python -m receipt_ocr <image>`."""
import sys

from receipt_ocr.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

## Tests

### `tests/test_pipeline.py`

Drive the whole pipeline with a fake Ollama client and an in-memory engine, so no server or
real image is needed.

```python
import types

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from receipt_ocr.pipeline import run_pipeline


def _engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    return eng


def _client(content: str):
    class _C:
        def chat(self, **kwargs):
            return types.SimpleNamespace(message=types.SimpleNamespace(content=content))
    return _C()


GOOD_JSON = (
    '{"merchant":"Corner Cafe","purchased_at":"2026-05-20","subtotal":18.0,'
    '"tax":1.5,"tip":3.0,"total":22.5,"line_items":[{"description":"Latte",'
    '"quantity":2,"unit_price":5.0,"line_total":10.0}]}'
)


def test_pipeline_loads_then_skips_duplicate(tmp_path):
    img = tmp_path / "r.jpg"
    img.write_bytes(b"img-bytes")
    engine = _engine()

    first = run_pipeline(img, engine=engine, client=_client(GOOD_JSON))
    assert first.outcome == "loaded"
    assert first.receipt_id is not None

    second = run_pipeline(img, engine=engine, client=_client(GOOD_JSON))
    assert second.outcome == "skipped_duplicate"
    assert second.receipt_id == first.receipt_id


def test_pipeline_error_on_bad_extraction(tmp_path):
    img = tmp_path / "r.jpg"
    img.write_bytes(b"img-bytes")
    result = run_pipeline(img, engine=_engine(), client=_client('{"total":'))
    assert result.outcome == "error"


def test_pipeline_needs_review_flagged(tmp_path):
    img = tmp_path / "r.jpg"
    img.write_bytes(b"img-bytes")
    bad_total = GOOD_JSON.replace('"total":22.5', '"total":99.99')
    result = run_pipeline(img, engine=_engine(), client=_client(bad_total))
    assert result.outcome == "loaded"
    assert result.review_reason is not None
```

## Manual end-to-end check (real model)

```bash
source .venv/bin/activate
ollama serve                      # if not already running
python -m receipt_ocr path/to/receipt.jpg
sqlite3 receipts.db "SELECT id, merchant, total, status, review_reason FROM receipt;"
sqlite3 receipts.db "SELECT receipt_id, description, line_total FROM lineitem;"
python -m receipt_ocr path/to/receipt.jpg   # second run -> 'Already ingested...'
```

## Edge cases & gotchas

- **Error catch list:** `run_pipeline` catches the known stage errors and returns an `error`
  result instead of crashing. An unexpected exception (e.g. `IntegrityError` from a dedupe race)
  will propagate — that's intentional for v1 so genuine bugs are visible.
- **`init_db` every run** is cheap and idempotent (`create_all` only creates missing tables); it
  keeps the CLI usable on a fresh machine with no setup step.
- **Exit codes:** `0` for loaded/skipped, `1` for error — useful if the CLI is ever scripted.
- The `client` parameter exists purely for tests; real runs leave it `None` and use `ollama`.

## Definition of Done

- `tests/test_pipeline.py` passes (load, skip-duplicate, error, needs-review).
- `python -m receipt_ocr <image>` runs end to end against the real model and writes both tables;
  a second run on the same image prints the duplicate message.
- `pytest` is green.

## Suggested commit

```
feat: add pipeline orchestration and CLI entry point
```
