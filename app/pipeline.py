"""Pipeline orchestration: ingestion -> extraction -> parsing -> loading."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy.engine import Engine

from app.config import settings
from app.db import get_session, init_db, make_engine
from app.extraction import ExtractionError, extract
from app.ingestion import ingest
from app.loading import LoadVerificationError, persist
from app.models import ReceiptStatus
from app.parsing import parse

logger = logging.getLogger("app")

Outcome = Literal["loaded", "error"]


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

    Every call inserts a new receipt row; the same image may be processed any number
    of times (e.g. once per model for comparison).

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
    resolved_model = model or settings.default_model

    try:
        with get_session(engine) as session:
            ingested = ingest(image_path)
            extraction = extract(ingested.path, model=resolved_model, client=client)
            parsed = parse(extraction)
            receipt_id = persist(
                session, parsed, str(ingested.path), ingested.sha256, resolved_model
            )

            logger.info(
                "Loaded receipt id=%s model=%s status=%s",
                receipt_id, resolved_model, parsed.status.value,
            )
            return PipelineResult(
                outcome="loaded",
                message=f"Loaded receipt {receipt_id} ({parsed.status.value})",
                receipt_id=receipt_id,
                receipt_status=parsed.status,
                review_reason=parsed.review_reason,
            )
    except Exception as exc:
        # Catch everything (SQLAlchemy OperationalError/IntegrityError, unexpected
        # runtime errors, etc.) so the pipeline always returns a clean result
        # rather than crashing the caller with a raw traceback.
        logger.error("Pipeline failed: %s", exc)
        return PipelineResult(outcome="error", message=str(exc))
