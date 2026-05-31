import types

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Receipt
from app.pipeline import run_pipeline


def _engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    return eng


def _client(content: str):
    class _C:
        def chat(self, **kwargs):
            return types.SimpleNamespace(message=types.SimpleNamespace(content=content))
    return _C()


GOOD_JSON = (
    '{"merchant":"Corner Cafe","purchased_at":"2026-05-20","subtotal":18.0,'
    '"tax":1.5,"tip":3.0,"total":22.5,"line_items":[{"description":"Latte",'
    '"quantity":2,"unit_price":5.0,"line_total":10.0}]}'
)


def test_pipeline_loads_same_image_each_run(tmp_path):
    # With dedupe removed, re-running the same image creates a distinct new row
    # (this is what lets one receipt be compared across models).
    img = tmp_path / "r.jpg"
    img.write_bytes(b"img-bytes")
    engine = _engine()

    first = run_pipeline(img, engine=engine, client=_client(GOOD_JSON))
    second = run_pipeline(img, engine=engine, client=_client(GOOD_JSON))

    assert first.outcome == "loaded"
    assert second.outcome == "loaded"
    assert first.receipt_id is not None
    assert second.receipt_id != first.receipt_id


def test_pipeline_records_model_per_run(tmp_path):
    # Two models on the same image produce two rows with different model values.
    img = tmp_path / "r.jpg"
    img.write_bytes(b"img-bytes")
    engine = _engine()

    run_pipeline(img, engine=engine, client=_client(GOOD_JSON), model="model-a")
    run_pipeline(img, engine=engine, client=_client(GOOD_JSON), model="model-b")

    with Session(engine) as s:
        models = sorted(r.model for r in s.exec(select(Receipt)).all())
    assert models == ["model-a", "model-b"]


def test_pipeline_error_on_bad_extraction(tmp_path):
    img = tmp_path / "r.jpg"
    img.write_bytes(b"img-bytes")
    result = run_pipeline(img, engine=_engine(), client=_client('{"total":'))
    assert result.outcome == "error"


def test_pipeline_error_on_client_failure(tmp_path):
    img = tmp_path / "r.jpg"
    img.write_bytes(b"img-bytes")

    class _BoomClient:
        def chat(self, **kwargs):
            raise ConnectionError("ollama server not reachable")

    result = run_pipeline(img, engine=_engine(), client=_BoomClient())
    assert result.outcome == "error"
    assert "failed" in result.message.lower()


def test_pipeline_needs_review_flagged(tmp_path):
    img = tmp_path / "r.jpg"
    img.write_bytes(b"img-bytes")
    bad_total = GOOD_JSON.replace('"total":22.5', '"total":99.99')
    result = run_pipeline(img, engine=_engine(), client=_client(bad_total))
    assert result.outcome == "loaded"
    assert result.review_reason is not None
