# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Receipt OCR: read data from photos of receipts using a local vision model, transform it into tabular form, and store it in a database (SQLite to start). Full intent and scope live in `GOALS.md` (note: `GOALS.md` is gitignored).

> **Status: v1 shipped.** The `app` package contains the four pipeline stage modules
> (`ingestion`, `extraction`, `parsing`, `loading`), plus supporting modules: `pipeline.py`
> (orchestration), `cli.py` (CLI entry point), `config.py` (default settings), `db.py`
> (SQLite engine/session helpers), `models.py` (SQLModel ORM tables), and `schemas.py`
> (Pydantic extraction schemas). Exposed as a CLI via `python -m app <image>` and as a FastAPI
> web app (`web.py` + `static/index.html` viewer + `static/entry.html` manual-entry page) for
> uploading, browsing, and hand-annotating receipts. Tests live under `tests/`. Keep this file
> updated as the architecture evolves.

## Intended pipeline architecture

A linear ingestion pipeline; each stage hands off to the next. Keep the stages as separate, simple components so each can be built and tested in isolation:

1. **Ingestion** — accept a receipt image (a phone-camera photo).
2. **Extraction** — send the image to a local vision model via Ollama to read its text.
3. **Parsing** — clean the extracted text and convert it to a tabular structure.
4. **Loading** — write the tabular data to the database and verify the write succeeded.

The web app (`app/web.py`) is a thin FastAPI layer over this pipeline: it reuses `run_pipeline`
for uploads, serves a read-only viewer (`app/static/index.html`), and serves a manual
receipt-entry page (`app/static/entry.html`) for hand-annotating receipts. Endpoints:
`GET /api/models` (installed vision-capable Ollama models + default), `GET /api/receipts`,
`GET /api/receipts/{id}/items`, `GET /api/receipts/{id}/image`, `POST /api/receipts`
(upload + run pipeline), `POST /api/receipts/manual` (save a photo + hand-typed fields,
skipping the model; reuses `loading.persist`, stored as `verified` and tagged
`model="manual-entry"`), `DELETE /api/receipts/{id}` (delete DB rows; the photo on disk is
kept). Uploaded photos are saved to `images/` (gitignored).

Out of scope for now: an analytics dashboard and RAG retrieval. (An earlier draft listed web
ingestion as out of scope; that's now implemented via the web app above.)

## Environment

- **Python 3.13** with a virtualenv at `.venv`. Activate with `source .venv/bin/activate`.
  Dependencies live in `requirements.txt` (managed with `pip`, no `pyproject.toml`): `ollama`,
  `pillow`, `pillow-heif`, `pydantic`, `sqlmodel`, `fastapi`, `uvicorn`, `python-multipart`,
  `pytest`. (`pillow`/`pillow-heif` let ingestion transcode HEIC/HEIF photos to PNG, since the
  Ollama vision model can't decode HEIC.)
- **Ollama** (local, `/usr/local/bin/ollama`) serves the vision model. The current default model is `ministral-3:3b` (see `app/config.py`). Use `ollama list` to see what's available locally.
- **SQLite** is the database target; it defaults to `data/receipts.db` (override with `--db-path`,
  or the `RECEIPTS_DB_PATH` env var for the web app).

### Commands
- Install: `pip install -r requirements.txt`
- Test: `pytest` (unit tests, model mocked); `pytest -m integration` for the real-model test
- Run (CLI): `python -m app <image>` (options: `--db-path`, `--model`, `--verbose`)
- Run (web): `uvicorn app.web:app --port 8005 --reload` (or `python -m app.web`), then open http://127.0.0.1:8005
- Serve on the tailnet: `./serve.sh` runs the app in a detached tmux session named `receipt_ocr` (subcommands: `attach`/`stop`/`status`). It calls `run_server.sh`, which binds this machine's Tailscale IP only (resolved via `tailscale ip -4`, fallback `100.117.77.103`). `python -m app.web` reads `RECEIPTS_HOST` (default `127.0.0.1`), `RECEIPTS_PORT` (default `8005`), and `RECEIPTS_RELOAD` (default off). No auth — keep it on the tailnet, not `0.0.0.0` on untrusted networks.

No lint or build tooling is configured yet.

## Conventions (from GOALS.md)

- Python first — prefer Python for all components.
- Web framework: use **FastAPI** if/when a web layer is needed (e.g., an HTTP ingestion endpoint). Not installed yet.
- Use type hints throughout.
- Write Google-style docstrings and comment the code. (This overrides the usual sparse-comment default — this project explicitly wants docstrings and comments.)
- Keep the architecture simple; avoid premature complexity.
- Keep commits small and focused; do a code review before each commit.
- Do a retro at the end of major phases.
- Explain things plainly: concise and descriptive, with minimal jargon.
