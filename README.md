# Receipt OCR

Read data from photos of receipts using a local vision model (via Ollama), structure it, and
store it in SQLite. Available as a command-line tool and a small web app.

## Requirements
- Python 3.12 or newer
- Ollama running locally with a vision model pulled (only needed for model
  extraction; the manual-entry flow works without it)

## Setup
```bash
python3 -m venv .venv         # first time only
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
uvicorn app.web:app --port 8005 --reload   # or: python -m app.web
```
Then open http://127.0.0.1:8005. From the page you can:
- Upload a receipt photo and pick which installed vision model to extract with.
- Browse stored receipts, view their line items, and see the original photo.
- Delete a receipt (removes the database rows; the photo on disk is left in place).

There's also a manual-entry page at `/entry.html` for hand-typing a receipt's
fields alongside its photo, skipping the model entirely (records are stored as
`verified` and tagged `model="manual-entry"`).

Uploaded photos are saved under `images/` (gitignored). The database path defaults to
`data/receipts.db` and can be overridden with the `RECEIPTS_DB_PATH` environment variable.

## Serving on the Tailscale network

To run the app on this machine and reach it from other devices on the tailnet
(e.g. `pi6` / `100.117.77.103`), use the helper scripts:

```bash
./serve.sh            # start the server in a detached tmux session
./serve.sh attach     # attach to the session (Ctrl-b d to detach)
./serve.sh status     # check whether it's running
./serve.sh stop       # stop it and kill the session
```

Then open `http://pi6:8005` (or `http://100.117.77.103:8005`) from any tailnet device.

By default the server binds **only** the Tailscale IP, so it's reachable over
Tailscale but not exposed on the local LAN/Wi-Fi. Override the host/port with
environment variables (read by `python -m app.web`):

- `RECEIPTS_HOST` — interface to bind (default: localhost for `python -m app.web`;
  `run_server.sh` sets it to this machine's Tailscale IP). Use `0.0.0.0` to bind
  every interface.
- `RECEIPTS_PORT` — port (default `8005`).
- `RECEIPTS_RELOAD` — set to `1` to enable auto-reload (development only).

`run_server.sh` launches the foreground server (resolving the Tailscale IP via
`tailscale ip -4`); `serve.sh` wraps it in tmux. There is no authentication, so
keep it on the tailnet rather than binding `0.0.0.0` on an untrusted network.

### Web API
- `GET  /api/models` — installed vision-capable Ollama models + the configured default
- `GET  /api/receipts` — all receipt header rows (newest first)
- `GET  /api/receipts/{id}/items` — line items for one receipt
- `GET  /api/receipts/{id}/image` — the original receipt photo
- `POST /api/receipts` — upload a photo (multipart `file`, optional `model`) and run the pipeline
- `POST /api/receipts/manual` — save a photo plus hand-typed fields, skipping the model
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
