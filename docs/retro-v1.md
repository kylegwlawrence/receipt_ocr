# Receipt OCR v1 — Retro

## What we built
A local, four-stage command-line pipeline that turns a receipt photo into structured rows in
SQLite: **Ingestion** (validate + SHA-256 dedupe) → **Extraction** (Ollama vision model with
schema-enforced JSON output) → **Parsing** (normalize values, reconcile totals, decide
`verified` vs `needs_review`) → **Loading** (insert receipt + line items, then read back to
verify the write). Each stage is an independently testable module; the suite mocks the model so
`pytest` runs without Ollama.

## What went well
- **Two schema layers paid off.** A permissive Pydantic `ReceiptExtraction` (what we ask the
  model for) kept separate from the SQLModel tables (what we persist) meant a partial/imperfect
  read still parses, and prompt changes never silently reshape the database.
- **Structured output via Ollama's `format` parameter** made extraction reliable in *shape* — we
  validate JSON in one step and push correctness checks downstream to reconciliation.
- **Always-write-with-status** (rather than reject) means nothing is lost; questionable receipts
  land as `needs_review` with a human-readable reason.
- **Dependency injection** (the `client` parameter on `extract`/`run_pipeline`) let the whole
  pipeline be tested end to end against a fake client with no server.
- **Code review caught real bugs before they shipped:** SQLite foreign-key enforcement was off by
  default, `created_at` lost its timezone on roundtrip, the session helper silently discarded
  writes without a commit, and totals reconciliation skipped any receipt without a tip. All fixed.

## What was awkward / what we'd change
- **Money as `float`.** Simple for v1 but invites rounding noise; the 0.01 reconcile tolerance
  papers over it. Integer cents would be cleaner.
- **US-first date parsing.** Ambiguous dates like `03/04/2026` are guessed month-first with no way
  to know the locale.
- **`from __future__ import annotations` fought SQLModel.** Stringized annotations broke
  SQLAlchemy's relationship resolution; we had to drop the import in `models.py`.
- **Single-image CLI only.** No batch mode, no web layer (both intentionally out of scope).

## Known limitations (carried forward)
- Ambiguous dates may parse to the wrong day.
- No image preprocessing — very blurry photos just land in `needs_review`.
- Re-encoded or resized copies of the same receipt are NOT deduped (the hash is over raw bytes).
- Reconciliation only fires when both `subtotal` and `total` are present (missing tax/tip count
  as 0); a receipt with only a total can't be arithmetic-checked.

## Ideas for v2 (not committed)
- FastAPI ingestion endpoint reusing `run_pipeline`.
- Integer-cents money storage.
- A simple review workflow for `needs_review` rows.
- Batch ingestion of a directory of images.
