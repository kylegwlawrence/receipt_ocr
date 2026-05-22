# Receipt OCR — v1 Implementation Plan

This folder is the implementation plan for Receipt OCR v1, broken into phases. Each phase is a
self-contained spec that one agent (or person) can implement and commit on its own. Work the
phases **in order** — each builds on the previous one.

## What we're building

A simple, local, four-stage ingestion pipeline that reads a photo of a receipt, extracts its
data with a local vision model (via Ollama), structures it, and stores it in SQLite — checking
that the write succeeded. v1 is a command-line tool that takes one image path. No web layer, no
dashboard, no RAG (those are explicitly out of scope per `GOALS.md`).

Pipeline: **Ingestion → Extraction → Parsing → Loading.**

## Locked decisions

These were settled up front; implement to them, don't relitigate.

| Area | Decision |
|------|----------|
| Extraction | Vision model returns **structured JSON directly**, enforced by a Pydantic schema via Ollama's `format` parameter. Parsing validates/cleans the JSON — it does **not** parse free text. |
| Vision model | `llama3.2-vision:11b` (default; configurable via CLI/`config.py`). |
| Interface (v1) | CLI on one image path. No web layer. |
| Database | SQLModel over SQLite. |
| Dependencies | `requirements.txt` + the existing `pip` in `.venv`. No uv/poetry/pyproject. |
| Ollama client | Official `ollama` Python package. |
| Test tooling | `pytest` only. No lint/format/type-check tooling yet. |
| Schema | Normalized: `receipts` + `line_items`. Capture merchant, date, total, **subtotal, tax, tip**, and line items (description, qty, unit price, line total). |
| Failure handling | **Always write**; flag incomplete/non-reconciling rows as `needs_review` with a reason. |
| Duplicates | **Skip by image SHA-256**: store the hash, skip re-ingesting the same photo. |
| Money | `float` rounded to 2 dp for v1. (Revisit integer cents / `Numeric` later if precision matters.) |

## Stack & dependencies

`requirements.txt`:

```
ollama
pydantic
sqlmodel
pytest
```

`sqlmodel` pulls in SQLAlchemy and Pydantic; `pydantic` is listed explicitly because the
extraction schemas depend on it directly. No Pillow — the `ollama` client accepts an image path
directly, and hashing uses the stdlib `hashlib`.

Environment (already present): Python 3.13 in `.venv`, Ollama 0.24.0 with `llama3.2-vision:11b`
pulled.

## Project layout (flat package)

```
receipt_ocr/
  __init__.py
  __main__.py      # `python -m receipt_ocr <image>` -> cli.main()
  config.py        # DEFAULT_MODEL, DEFAULT_DB_PATH, RECONCILE_TOLERANCE
  schemas.py       # Pydantic models the LLM must return (ReceiptExtraction, LineItemExtraction)
  models.py        # SQLModel tables (Receipt, LineItem) + ReceiptStatus enum
  db.py            # make_engine(), init_db(), get_session()
  ingestion.py     # validate path, read bytes, sha256, dedupe lookup
  extraction.py    # call Ollama vision model -> ReceiptExtraction
  parsing.py       # normalize + reconcile + decide status (pure functions)
  loading.py       # map to tables, insert, read-back verify
  pipeline.py      # run_pipeline(image_path) orchestrating the four stages
  cli.py           # argparse -> pipeline
tests/
  __init__.py
  conftest.py
  test_models.py test_ingestion.py test_extraction.py
  test_parsing.py test_loading.py test_pipeline.py
requirements.txt
pytest.ini
README.md          # project-level (written in Phase 7)
```

**Why two schema layers:** `schemas.py` is *what we ask the model for* (loose, all-optional, so
a partial read still parses). `models.py` is *what we persist* (the database tables). The parsing
stage maps the first onto the second and decides the row's status. Keeping them separate means a
change to the prompt/model output never silently reshapes the database.

## Data flow in one picture

```
image path
  │  ingestion.py    validate, sha256, dedupe check ─── duplicate? ──> stop (skipped_duplicate)
  ▼
ReceiptExtraction   extraction.py   Ollama vision model, JSON enforced by schema
  │
  ▼
ParsedReceipt       parsing.py      normalize values, reconcile totals, set status + reason
  │
  ▼
Receipt + LineItems loading.py      insert in one transaction, then read back to verify
  │
  ▼
PipelineResult      pipeline.py     outcome = loaded | skipped_duplicate | error
```

## Conventions (apply to every phase)

- **Type hints** on every function and field.
- **Google-style docstrings** and explanatory comments. (This project explicitly wants comments —
  it overrides the usual "comment sparingly" default.)
- **Keep it simple** — no abstractions beyond what the phase needs.
- **One small, focused commit per phase**, with a self-review of the diff before committing. Each
  phase doc ends with a suggested commit message.
- Run `pytest` before each commit; it must be green.
- A retro is done at the end (Phase 7).

## Phases

| # | Doc | What it delivers |
|---|-----|------------------|
| 0 | [phase-0-setup.md](phase-0-setup.md) | Package skeleton, `requirements.txt`, `pytest` setup, `config.py`, `.gitignore`. |
| 1 | [phase-1-data-model-db.md](phase-1-data-model-db.md) | `schemas.py`, `models.py`, `db.py`; a round-trip persistence test. |
| 2 | [phase-2-ingestion.md](phase-2-ingestion.md) | Image validation, SHA-256 hashing, duplicate lookup. |
| 3 | [phase-3-extraction.md](phase-3-extraction.md) | Ollama vision call with structured (schema-enforced) JSON output. |
| 4 | [phase-4-parsing.md](phase-4-parsing.md) | Normalize values, reconcile totals, decide `verified` vs `needs_review`. |
| 5 | [phase-5-loading.md](phase-5-loading.md) | Insert receipt + line items, then read back to verify the write. |
| 6 | [phase-6-pipeline-cli.md](phase-6-pipeline-cli.md) | Orchestrate the four stages; the `python -m receipt_ocr` CLI. |
| 7 | [phase-7-retro-docs.md](phase-7-retro-docs.md) | Project README, update `CLAUDE.md` commands, v1 retro. |

## End-to-end verification (after Phase 6)

```bash
source .venv/bin/activate
ollama serve                       # if it isn't already running
python -m receipt_ocr path/to/receipt.jpg
sqlite3 receipts.db "SELECT id, merchant, total, status, review_reason FROM receipt;"
sqlite3 receipts.db "SELECT * FROM lineitem;"
```

Expected:
- A clear receipt writes a row to both tables and reads back with status `verified`.
- A blurry/partial receipt still writes, with status `needs_review` and a populated
  `review_reason`.
- Re-running the same image prints `skipped_duplicate` and does not write again.

Automated tests: `pytest` runs the unit suite (the model is mocked, so no Ollama needed).
`pytest -m integration` runs the optional real-model check (needs `ollama serve` and a sample
image; skipped by default).
