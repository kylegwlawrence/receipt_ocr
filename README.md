# Receipt OCR

Read data from photos of receipts using a local vision model (via Ollama), structure it, and
store it in SQLite. Available as a command-line tool and a small web app.

## Requirements
- Python 3.13 (a `.venv` is included)
- Ollama running locally with a vision model pulled

## Setup
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage (CLI)
```bash
ollama serve                       # if it isn't already running
python -m app path/to/receipt.jpg
```
Options: `--db-path PATH` (default `data/receipts.db`), `--model NAME` (default `ministral-3:3b`), `--verbose`.

## Usage (web app)
A FastAPI app serves a browser viewer plus an upload form:
```bash
ollama serve                       # if it isn't already running
uvicorn app.web:app --reload       # or: python -m app.web
```
Then open http://127.0.0.1:8000. From the page you can:
- Upload a receipt photo and pick which installed vision model to extract with.
- Browse stored receipts, view their line items, and see the original photo.
- Delete a receipt (removes the database rows; the photo on disk is left in place).

Uploaded photos are saved under `images/` (gitignored). The database path defaults to
`data/receipts.db` and can be overridden with the `RECEIPTS_DB_PATH` environment variable.

### Web API
- `GET  /api/models` — installed vision-capable Ollama models + the configured default
- `GET  /api/receipts` — all receipt header rows (newest first)
- `GET  /api/receipts/{id}/items` — line items for one receipt
- `GET  /api/receipts/{id}/image` — the original receipt photo
- `POST /api/receipts` — upload a photo (multipart `file`, optional `model`) and run the pipeline
- `DELETE /api/receipts/{id}` — delete a receipt and its line items

## Inspecting the data
```bash
sqlite3 data/receipts.db "SELECT id, merchant, total, status, review_reason FROM receipt;"
sqlite3 data/receipts.db "SELECT receipt_id, description, line_total FROM lineitem;"
```
Receipts that are incomplete or whose totals don't add up are stored with status
`needs_review` and a reason. Re-running the same image is a no-op (deduped by image hash).

## Tests
```bash
pytest                  # unit tests (model is mocked; no Ollama needed)
pytest -m integration   # optional real-model test (needs Ollama + a sample image)
```

## How it works
Ingestion → Extraction → Parsing → Loading. The web app reuses the same pipeline; uploads run
it synchronously. See `CLAUDE.md` for the architecture and `GOALS.md` for the full intent
(both are project-local; `GOALS.md` is gitignored).
