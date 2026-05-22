"""Enables `python -m receipt_ocr <image>`."""
import sys

from receipt_ocr.cli import main

if __name__ == "__main__":
    sys.exit(main())
