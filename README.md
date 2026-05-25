# Receipt OCR

Read data from photos of receipts using a local vision model (via Ollama), structure it, and
store it in SQLite. Command-line tool; one image at a time.

## Requirements
- Python 3.13 (a `.venv` is included)
- Ollama running locally with a vision model pulled

## Setup
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage
```bash
ollama serve                       # if it isn't already running
python -m app path/to/receipt.jpg
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
