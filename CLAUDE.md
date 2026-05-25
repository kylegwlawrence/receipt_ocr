# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Receipt OCR: read data from photos of receipts using a local vision model, transform it into tabular form, and store it in a database (SQLite to start). Full intent and scope live in `GOALS.md` (note: `GOALS.md` is gitignored).

> **Status: v1 shipped.** The `app` package has one module per pipeline stage
> (`ingestion`, `extraction`, `parsing`, `loading`) wired together by `pipeline.py` and exposed
> as a CLI (`python -m app <image>`). Tests live under `tests/`. Keep this file updated as
> the architecture evolves.

## Intended pipeline architecture

A linear ingestion pipeline; each stage hands off to the next. Keep the stages as separate, simple components so each can be built and tested in isolation:

1. **Ingestion** — accept a receipt image (a phone-camera photo).
2. **Extraction** — send the image to a local vision model via Ollama to read its text.
3. **Parsing** — clean the extracted text and convert it to a tabular structure.
4. **Loading** — write the tabular data to the database and verify the write succeeded.

Out of scope for now: image submission via app/web page, an analytics dashboard, and RAG retrieval.

## Environment

- **Python 3.13** with a virtualenv at `.venv`. Activate with `source .venv/bin/activate`.
  Dependencies live in `requirements.txt` (managed with `pip`, no `pyproject.toml`).
- **Ollama** (local, `/usr/local/bin/ollama`) serves the vision model. Vision-capable models already pulled include `llama3.2-vision:11b` and `gemma3:12b`. Use `ollama list` to see what's available.
- **SQLite** is the database target; it defaults to `receipts.db` (override with `--db-path`).

### Commands
- Install: `pip install -r requirements.txt`
- Test: `pytest` (unit tests, model mocked); `pytest -m integration` for the real-model test
- Run: `python -m app <image>` (options: `--db-path`, `--model`, `--verbose`)

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
