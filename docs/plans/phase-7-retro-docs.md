# Phase 7 — Retro & docs

## Goal

Close out v1: write a project README so anyone can set up and run the tool, update `CLAUDE.md`
to reflect the now-established commands and architecture (it currently says "greenfield" with no
tooling), and do a short retro per the project's working rules.

## Prerequisites

Phases 0–6 complete and the pipeline working end to end.

## Files to create / modify

- `README.md` (modify — currently empty)
- `CLAUDE.md` (modify — update status and "Commands" info)
- `docs/retro-v1.md` (new)

## Detailed spec

### `README.md`

Replace the empty file with a concise, practical guide. Suggested sections:

```markdown
# Receipt OCR

Read data from photos of receipts using a local vision model (via Ollama), structure it, and
store it in SQLite. Command-line tool; one image at a time.

## Requirements
- Python 3.13 (a `.venv` is included)
- Ollama running locally with a vision model pulled (default: `llama3.2-vision:11b`)

## Setup
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage
```bash
ollama serve                       # if it isn't already running
python -m receipt_ocr path/to/receipt.jpg
```
Options: `--db-path PATH` (default `receipts.db`), `--model NAME`, `--verbose`.

## Inspecting the data
```bash
sqlite3 receipts.db "SELECT id, merchant, total, status, review_reason FROM receipt;"
sqlite3 receipts.db "SELECT receipt_id, description, line_total FROM lineitem;"
```
Receipts that are incomplete or whose totals don't add up are stored with status
`needs_review` and a reason. Re-running the same image is a no-op (deduped by image hash).

## Tests
```bash
pytest                  # unit tests (model is mocked; no Ollama needed)
pytest -m integration   # optional real-model test (needs Ollama + a sample image)
```

## How it works
Ingestion → Extraction → Parsing → Loading. See `docs/plans/` for the full design.
```

### `CLAUDE.md` updates

Make these edits to the existing file:

1. **Status note** — replace the greenfield blockquote ("The repo currently has no source code
   and no commits…") with a short description of the now-real layout: a `receipt_ocr` package
   with a module per stage, tests under `tests/`, run via `python -m receipt_ocr`.
2. **Environment / tooling** — replace "No test, lint, or build tooling is configured yet" with
   the established commands:
   - Install: `pip install -r requirements.txt`
   - Test: `pytest` (and `pytest -m integration` for the real-model test)
   - Run: `python -m receipt_ocr <image>`
3. Note that dependencies live in `requirements.txt` and the DB defaults to `receipts.db`.

Keep the existing conventions section (Python-first, type hints, Google docstrings, comments,
small commits) — those still hold.

### `docs/retro-v1.md`

A short, honest retro. Suggested prompts to answer:

```markdown
# Receipt OCR v1 — Retro

## What we built
One-paragraph summary of the shipped pipeline.

## What went well
- ...

## What was awkward / what we'd change
- e.g. money as float, US-first date parsing, single-image CLI only.

## Known limitations (carried forward)
- Ambiguous dates may parse to the wrong day.
- No image preprocessing (very blurry photos just land in needs_review).
- Re-encoded copies of the same receipt are NOT deduped (hash is over raw bytes).

## Ideas for v2 (not committed)
- FastAPI ingestion endpoint reusing run_pipeline.
- Integer-cents money storage.
- A simple review workflow for needs_review rows.
```

## Edge cases & gotchas

- This phase changes **docs only** — no behavior changes, so there's nothing new to test. Just
  re-run `pytest` to confirm nothing regressed while editing.
- Double-check the README commands actually work by running them in a clean shell once.
- Keep `CLAUDE.md` accurate going forward — stale instructions are worse than none.

## Definition of Done

- `README.md` lets a new contributor install, run, and inspect results without asking questions.
- `CLAUDE.md` no longer says "greenfield"/"no tooling" and lists the real install/test/run
  commands.
- `docs/retro-v1.md` exists with the team's reflections.
- `pytest` still green.

## Suggested commit

```
docs: add README usage, update CLAUDE.md commands, and v1 retro
```
