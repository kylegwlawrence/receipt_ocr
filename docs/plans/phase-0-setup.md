# Phase 0 — Setup & scaffolding

## Goal

Create the package skeleton, declare dependencies, and get `pytest` running, so every later
phase has a place to put code and tests. No pipeline logic yet.

## Prerequisites

None. This is the first phase. A Python 3.13 `.venv` already exists at the repo root with only
`pip` installed.

## Files to create / modify

- `requirements.txt` (new)
- `receipt_ocr/__init__.py` (new)
- `receipt_ocr/config.py` (new)
- `pytest.ini` (new)
- `tests/__init__.py` (new)
- `tests/test_smoke.py` (new, temporary sanity test — may be deleted in Phase 1)
- `.gitignore` (modify — append ignores)

## Detailed spec

### `requirements.txt`

```
ollama
pydantic
sqlmodel
pytest
```

Pin versions only if an install breaks; otherwise leave unpinned for v1 simplicity.

### `receipt_ocr/config.py`

Central place for tunable defaults so no magic values are scattered across modules. Use a frozen
dataclass instance (simple, importable, type-checked).

```python
"""Project-wide configuration defaults for the receipt OCR pipeline."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Default settings for the pipeline.

    Attributes:
        default_model: Ollama vision model used for extraction.
        default_db_path: SQLite file path used when none is supplied.
        reconcile_tolerance: Max allowed difference (in currency units) when
            checking that subtotal + tax + tip equals the total.
    """

    default_model: str = "llama3.2-vision:11b"
    default_db_path: str = "receipts.db"
    reconcile_tolerance: float = 0.01


settings = Settings()
```

### `receipt_ocr/__init__.py`

May expose a version string; otherwise leave effectively empty:

```python
"""Receipt OCR: read receipt photos with a local vision model and store them in SQLite."""

__version__ = "0.1.0"
```

### `pytest.ini`

```ini
[pytest]
testpaths = tests
markers =
    integration: tests that call the real Ollama model (deselected by default)
addopts = -m "not integration"
```

`addopts = -m "not integration"` makes a plain `pytest` skip the real-model tests; run them
explicitly with `pytest -m integration`.

### `tests/test_smoke.py`

A trivial test proving the harness and imports work:

```python
def test_imports():
    import ollama  # noqa: F401
    import pydantic  # noqa: F401
    import sqlmodel  # noqa: F401
    import receipt_ocr  # noqa: F401
```

### `.gitignore`

Append (don't overwrite — keep the existing entry, likely `.venv`):

```
__pycache__/
*.py[cod]
.pytest_cache/
*.db
*.sqlite3
data/
```

## Steps

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -c "import ollama, sqlmodel, pydantic; print('imports ok')"
pytest
```

## Edge cases & gotchas

- `sqlmodel` installs SQLAlchemy and Pydantic v2 transitively; that's expected.
- If `pip install` is slow or a wheel fails to build, it's almost certainly the SQLAlchemy
  build — usually resolves on retry; pin a known-good version only if needed.
- Don't commit `receipts.db` — the `.gitignore` entry above prevents it.

## Definition of Done

- `pip install -r requirements.txt` succeeds in `.venv`.
- `python -c "import ollama, sqlmodel, pydantic"` runs without error.
- `pytest` collects and passes (the smoke test).
- `receipt_ocr` is importable as a package.

## Suggested commit

```
chore: scaffold receipt_ocr package, deps, and pytest setup
```
