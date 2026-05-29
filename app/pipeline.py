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
from app.models import Receipt, ReceiptStatus
from app.parsing import parse

logger = logging.getLogger("app")

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
    force: bool = False,
) -> PipelineResult:
    """Run the full pipeline on a single receipt image.

    Args:
        image_path: Path to the receipt image.
        db_path: SQLite path; defaults to settings.default_db_path. Ignored if `engine`
            is supplied.
        model: Ollama model override; defaults to settings.default_model.
        engine: Pre-built engine (used by tests). When None, one is created from db_path.
        client: Ollama-like client override (used by tests). Passed to extraction.
        force: When True, delete any existing receipt for this image and re-process it.

    Returns:
        A PipelineResult describing what happened.
    """
    engine = engine or make_engine(db_path or settings.default_db_path)
    init_db(engine)

    try:
        with get_session(engine) as session:
            ingested = ingest(image_path, session)
            if ingested.is_duplicate:
                if not force:
                    logger.info("Duplicate image; skipping (existing id=%s)", ingested.existing_id)
                    return PipelineResult(
                        outcome="skipped_duplicate",
                        message=f"Already ingested as receipt {ingested.existing_id}",
                        receipt_id=ingested.existing_id,
                    )
                existing = session.get(Receipt, ingested.existing_id)
                if existing:
                    logger.info("Force re-processing; deleting existing receipt id=%s", existing.id)
                    session.delete(existing)
                    session.flush()

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
    except Exception as exc:
        # Catch everything (SQLAlchemy OperationalError/IntegrityError, unexpected
        # runtime errors, etc.) so the pipeline always returns a clean result
        # rather than crashing the caller with a raw traceback.
        logger.error("Pipeline failed: %s", exc)
        return PipelineResult(outcome="error", message=str(exc))
