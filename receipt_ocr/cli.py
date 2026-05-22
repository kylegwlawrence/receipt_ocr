"""Command-line entry point for the receipt OCR pipeline."""
from __future__ import annotations

import argparse
import logging
import sys

from receipt_ocr.config import settings
from receipt_ocr.pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="receipt_ocr",
        description="Read a receipt photo with a local vision model and store it in SQLite.",
    )
    parser.add_argument("image", help="Path to the receipt image.")
    parser.add_argument(
        "--db-path", default=settings.default_db_path,
        help=f"SQLite file path (default: {settings.default_db_path}).",
    )
    parser.add_argument(
        "--model", default=settings.default_model,
        help=f"Ollama vision model (default: {settings.default_model}).",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    result = run_pipeline(args.image, db_path=args.db_path, model=args.model)

    print(result.message)
    if result.outcome == "loaded" and result.review_reason:
        print(f"  needs review: {result.review_reason}")

    return 1 if result.outcome == "error" else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
