"""Command-line runner for the extraction eval harness.

Usage::

    python -m eval                       # run all cases with the default model
    python -m eval --model llava:7b      # try a different vision model
    python -m eval --cases-dir eval/cases

This calls the real Ollama model once per case, so it needs Ollama running and the
chosen model pulled. It prints a per-case grid and an aggregate summary, then exits
non-zero if any case errored (useful in CI/regression checks).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import settings
from app.extraction import ExtractionError, extract

from eval.harness import (
    MONEY_FIELDS,
    TEXT_FIELDS,
    CaseScore,
    aggregate,
    load_cases,
    score_case,
)

DEFAULT_CASES_DIR = Path(__file__).resolve().parent / "cases"


def _check(ok: bool) -> str:
    """Render a boolean as a compact pass/fail glyph."""
    return "✓" if ok else "✗"


def run(cases_dir: Path, model: str | None) -> list[CaseScore]:
    """Run the model over every case and score the results.

    Args:
        cases_dir: Directory of case files.
        model: Ollama model name, or None for the configured default.

    Returns:
        One :class:`CaseScore` per case, in case order.
    """
    cases = load_cases(cases_dir)
    if not cases:
        print(f"No case files (*.json) found in {cases_dir}.", file=sys.stderr)
        return []

    scores: list[CaseScore] = []
    for case in cases:
        if not case.image_path.is_file():
            scores.append(
                CaseScore(name=case.name, error=f"image not found: {case.image_path}")
            )
            continue
        try:
            got = extract(case.image_path, model=model)
        except ExtractionError as exc:
            scores.append(CaseScore(name=case.name, error=str(exc)))
            continue
        scores.append(score_case(case.name, case.expected, got))
    return scores


def _print_report(scores: list[CaseScore], model: str) -> None:
    """Print a per-case grid followed by the aggregate summary."""
    fields = TEXT_FIELDS + MONEY_FIELDS
    header = ["case", *fields, "items(R/P)"]
    print(f"\nModel: {model}\n")
    print("  ".join(header))
    print("-" * (len(header) * 12))

    for s in scores:
        if s.error:
            print(f"{s.name}  ERROR: {s.error}")
            continue
        cells = [s.name]
        for f in TEXT_FIELDS:
            cells.append(_check(s.text_correct[f]))
        for f in MONEY_FIELDS:
            cells.append(_check(s.money_correct[f]))
        cells.append(f"{s.item_recall:.2f}/{s.item_precision:.2f}")
        print("  ".join(cells))

    summary = aggregate(scores)
    print("\nAggregate (fraction correct across cases):")
    for metric, value in summary.items():
        print(f"  {metric:24s} {value:.2f}")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the harness, and return a process exit code.

    Returns:
        0 if every case scored without erroring, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description="Receipt extraction eval harness.")
    parser.add_argument(
        "--model",
        default=None,
        help=f"Ollama vision model (default: {settings.default_model}).",
    )
    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=DEFAULT_CASES_DIR,
        help="Directory of *.json case files.",
    )
    args = parser.parse_args(argv)

    scores = run(args.cases_dir, args.model)
    if not scores:
        return 1

    _print_report(scores, args.model or settings.default_model)
    return 1 if any(s.error for s in scores) else 0


if __name__ == "__main__":
    raise SystemExit(main())
