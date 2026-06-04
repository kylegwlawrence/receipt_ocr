"""Scoring logic and case loading for the extraction eval harness.

A *case* is a JSON file pairing a receipt image with its hand-checked correct
extraction (ground truth). The harness runs the model on each image and compares
the result to the ground truth, producing per-field scores and an aggregate report.

The scoring is deliberately simple and transparent:

* Text fields (``merchant``, ``purchased_at``) are compared after normalising
  case and whitespace — exact match only.
* Money fields (``subtotal``, ``tax``, ``tip``, ``total``) are compared as numbers
  within a small tolerance, and "both null" counts as correct (a receipt with no
  tip *should* read null).
* Line items are matched by normalised description; we report recall, precision,
  and the share of matched items whose ``line_total`` is also correct.

Everything here is pure given an extraction result, so the math is unit-testable
without touching Ollama.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.schemas import ReceiptExtraction

# Project root (the directory holding ``app`` and ``eval``). Image paths in case
# files are resolved against this so cases are portable across machines/CWDs.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Field groups, scored with different rules (see module docstring).
TEXT_FIELDS = ("merchant", "purchased_at")
MONEY_FIELDS = ("subtotal", "tax", "tip", "total")


@dataclass
class EvalCase:
    """One labelled example: an image plus its expected extraction.

    Attributes:
        name: Identifier for reporting (the case file's stem).
        image_path: Absolute path to the receipt image.
        expected: The hand-checked correct extraction.
    """

    name: str
    image_path: Path
    expected: ReceiptExtraction


@dataclass
class CaseScore:
    """The scored outcome of running one case.

    Attributes:
        name: The case name.
        error: Populated (and everything else left empty) if extraction failed.
        text_correct: Map of text field -> whether it matched.
        money_correct: Map of money field -> whether it matched.
        item_recall: Fraction of expected line items found in the prediction.
        item_precision: Fraction of predicted line items that were expected.
        item_total_accuracy: Among matched items, share with a correct line_total.
    """

    name: str
    error: str | None = None
    text_correct: dict[str, bool] = field(default_factory=dict)
    money_correct: dict[str, bool] = field(default_factory=dict)
    item_recall: float = 0.0
    item_precision: float = 0.0
    item_total_accuracy: float = 0.0


def _normalize_text(value: str | None) -> str | None:
    """Normalise text for comparison (None passes through).

    Lowercases, drops punctuation (so "Trader Joe's" == "Trader Joes"), and
    collapses all runs of whitespace to nothing — comparison is on alphanumerics
    only. This keeps merchant/description matching from failing on cosmetic
    differences in apostrophes, periods, or spacing.
    """
    if value is None:
        return None
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _text_equal(expected: str | None, got: str | None) -> bool:
    """Compare two text values after normalisation; both-null counts as equal."""
    return _normalize_text(expected) == _normalize_text(got)


def _money_equal(expected: float | None, got: float | None, tol: float) -> bool:
    """Compare two money values within ``tol``; both-null counts as equal."""
    if expected is None or got is None:
        return expected is None and got is None
    return abs(expected - got) <= tol


def score_case(
    name: str,
    expected: ReceiptExtraction,
    got: ReceiptExtraction,
    tol: float = settings.reconcile_tolerance,
) -> CaseScore:
    """Score one prediction against its ground truth.

    Args:
        name: Case name for the report.
        expected: The hand-checked correct extraction.
        got: The model's extraction.
        tol: Tolerance (currency units) for money comparisons.

    Returns:
        A populated :class:`CaseScore`.
    """
    score = CaseScore(name=name)

    for f in TEXT_FIELDS:
        score.text_correct[f] = _text_equal(getattr(expected, f), getattr(got, f))
    for f in MONEY_FIELDS:
        score.money_correct[f] = _money_equal(
            getattr(expected, f), getattr(got, f), tol
        )

    # Line-item matching: greedily pair predicted items to expected ones by
    # normalised description. Each expected item can be matched at most once.
    expected_items = list(expected.line_items)
    predicted_items = list(got.line_items)
    unmatched_expected = list(expected_items)
    matched_pairs: list[tuple] = []  # (expected_item, predicted_item)

    for pred in predicted_items:
        pred_desc = _normalize_text(pred.description)
        for exp in unmatched_expected:
            if _normalize_text(exp.description) == pred_desc:
                matched_pairs.append((exp, pred))
                unmatched_expected.remove(exp)
                break

    matched = len(matched_pairs)
    score.item_recall = matched / len(expected_items) if expected_items else 1.0
    score.item_precision = matched / len(predicted_items) if predicted_items else 1.0
    if matched:
        correct_totals = sum(
            _money_equal(exp.line_total, pred.line_total, tol)
            for exp, pred in matched_pairs
        )
        score.item_total_accuracy = correct_totals / matched
    else:
        # No matches: vacuously perfect only if there was nothing to match.
        score.item_total_accuracy = 1.0 if not expected_items else 0.0

    return score


def load_cases(cases_dir: Path) -> list[EvalCase]:
    """Load every ``*.json`` case file in ``cases_dir``.

    Each file must look like::

        {
          "image": "images/receipt1.jpg",
          "expected": { ...ReceiptExtraction fields... }
        }

    The ``expected`` block is validated against :class:`ReceiptExtraction`, so a
    malformed ground truth fails loudly here rather than skewing scores later.

    Args:
        cases_dir: Directory containing the case files.

    Returns:
        Cases sorted by name.

    Raises:
        FileNotFoundError: If ``cases_dir`` does not exist.
        ValueError: If a case file is missing required keys.
    """
    if not cases_dir.is_dir():
        raise FileNotFoundError(f"Cases directory not found: {cases_dir}")

    cases: list[EvalCase] = []
    for path in sorted(cases_dir.glob("*.json")):
        data = json.loads(path.read_text())
        if "image" not in data or "expected" not in data:
            raise ValueError(f"{path.name} must have 'image' and 'expected' keys")
        image = Path(data["image"]).expanduser()
        if not image.is_absolute():
            image = PROJECT_ROOT / image
        cases.append(
            EvalCase(
                name=path.stem,
                image_path=image,
                expected=ReceiptExtraction.model_validate(data["expected"]),
            )
        )
    return cases


def aggregate(scores: list[CaseScore]) -> dict[str, float]:
    """Summarise scored cases into headline accuracy numbers.

    Errored cases count as zero for every metric (a crash is not a pass), so the
    aggregate reflects real end-to-end reliability.

    Args:
        scores: Per-case scores.

    Returns:
        A dict of metric name -> value in ``[0, 1]``: one entry per field, plus
        ``line_item_recall``, ``line_item_precision``, ``line_item_total_accuracy``,
        and ``error_rate``.
    """
    n = len(scores)
    if n == 0:
        return {}

    def field_rate(group: tuple[str, ...], attr: str) -> dict[str, float]:
        out = {}
        for f in group:
            out[f] = sum(getattr(s, attr).get(f, False) for s in scores) / n
        return out

    summary: dict[str, float] = {}
    summary.update(field_rate(TEXT_FIELDS, "text_correct"))
    summary.update(field_rate(MONEY_FIELDS, "money_correct"))
    summary["line_item_recall"] = sum(s.item_recall for s in scores) / n
    summary["line_item_precision"] = sum(s.item_precision for s in scores) / n
    summary["line_item_total_accuracy"] = (
        sum(s.item_total_accuracy for s in scores) / n
    )
    summary["error_rate"] = sum(s.error is not None for s in scores) / n
    return summary
