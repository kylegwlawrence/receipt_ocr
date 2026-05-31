"""Tests for the model-listing endpoint and per-upload model selection in app.web.

These call the endpoint functions directly (no HTTP layer), matching the style of
``test_web_delete.py``. ``RECEIPTS_DB_PATH`` is set to a temp file *before* importing
app.web because that module builds its engine and calls init_db() at import time.
Ollama is faked via ``sys.modules`` so no server is needed.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import types
from pathlib import Path

# Must run before importing app.web (it builds an engine at import time).
os.environ.setdefault(
    "RECEIPTS_DB_PATH", str(Path(tempfile.mkdtemp()) / "import_time.db")
)

from fastapi import UploadFile

from app import web
from app.config import settings


def _fake_ollama(capabilities_by_model: dict[str, list[str]]):
    """Build a stand-in ollama module exposing list() and show()."""
    models = [types.SimpleNamespace(model=name) for name in capabilities_by_model]

    def show(name):
        return types.SimpleNamespace(capabilities=capabilities_by_model[name])

    return types.SimpleNamespace(
        list=lambda: types.SimpleNamespace(models=models),
        show=show,
    )


def test_list_models_keeps_only_vision(monkeypatch):
    fake = _fake_ollama(
        {
            "qwen2.5vl:3b": ["completion", "vision"],
            "llama3.1:8b": ["completion", "tools"],
            "ministral-3:3b": ["completion", "vision", "tools"],
        }
    )
    monkeypatch.setitem(sys.modules, "ollama", fake)

    out = web.list_models()
    assert out["models"] == ["ministral-3:3b", "qwen2.5vl:3b"]  # sorted, vision-only
    assert out["default"] == settings.default_model


def test_list_models_falls_back_when_ollama_unavailable(monkeypatch):
    boom = types.SimpleNamespace(
        list=lambda: (_ for _ in ()).throw(ConnectionError("down")),
    )
    monkeypatch.setitem(sys.modules, "ollama", boom)

    out = web.list_models()
    assert out["models"] == [settings.default_model]
    assert out["default"] == settings.default_model


def test_upload_passes_selected_model_to_pipeline(tmp_path, monkeypatch):
    captured = {}

    def fake_run_pipeline(path, *, engine=None, model=None):
        captured["model"] = model
        return types.SimpleNamespace(
            outcome="loaded",
            message="ok",
            receipt_id=1,
            receipt_status=None,
            review_reason=None,
        )

    # Stub the pipeline and point the save location inside a temp project root so
    # dest.relative_to(PROJECT_ROOT) resolves.
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(web, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(web, "IMAGES_DIR", tmp_path / "images")

    upload = UploadFile(filename="r.jpg", file=io.BytesIO(b"img-bytes"))
    out = asyncio.run(web.upload_receipt(file=upload, model="qwen2.5vl:3b"))

    assert captured["model"] == "qwen2.5vl:3b"
    assert out["model"] == "qwen2.5vl:3b"
    assert out["outcome"] == "loaded"


def test_upload_without_model_defaults_to_settings(tmp_path, monkeypatch):
    captured = {}

    def fake_run_pipeline(path, *, engine=None, model=None):
        captured["model"] = model
        return types.SimpleNamespace(
            outcome="loaded",
            message="ok",
            receipt_id=2,
            receipt_status=None,
            review_reason=None,
        )

    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(web, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(web, "IMAGES_DIR", tmp_path / "images")

    upload = UploadFile(filename="r.jpg", file=io.BytesIO(b"img-bytes"))
    out = asyncio.run(web.upload_receipt(file=upload, model=None))

    # The pipeline receives None (it resolves the default internally), but the API
    # response reports the concrete default model name for the UI.
    assert captured["model"] is None
    assert out["model"] == settings.default_model
