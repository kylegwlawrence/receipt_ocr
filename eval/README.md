# Extraction eval harness

A small, manually-run harness that scores the **real** vision model against a set
of labelled receipts. Use it to tell whether a prompt, schema, or model change
actually helped — instead of eyeballing one receipt at a time.

This is separate from `pytest`: the unit tests mock the model, this harness calls
Ollama for real.

## Run it
```bash
ollama serve                    # if it isn't already running
python -m eval                  # all cases, default model
python -m eval --model llava:7b # try another vision model
```
Exit code is non-zero if any case errored, so it can gate a regression check.

## Add a case
Each case is a JSON file in `eval/cases/` pairing an image with its hand-checked
correct extraction (see `example.json`):

```json
{
  "image": "images/receipt1.jpg",
  "expected": { "merchant": "...", "total": 19.99, "line_items": [ ... ] }
}
```
- `image` is resolved relative to the project root.
- `expected` is validated against `app.schemas.ReceiptExtraction`, so a malformed
  ground truth fails loudly.
- Use `null` for fields the receipt genuinely doesn't show (e.g. no tip).

Aim for ~10 cases covering the tricky bits: multiple TOTAL lines, missing
tip/tax, comma thousands separators, faint/blurry photos.

## How scoring works
- **Text** (`merchant`, `purchased_at`): exact match after lower/space normalising.
- **Money** (`subtotal`, `tax`, `tip`, `total`): numeric match within
  `settings.reconcile_tolerance`; "both null" counts as correct.
- **Line items**: matched by normalised description, reported as recall / precision,
  plus the share of matched items with a correct `line_total`.

The aggregate prints the fraction of cases correct per field. Errored cases count
as zero (a crash is not a pass).

## Note on images
`images/` is gitignored, so case files are committed but their photos are not —
add your own receipts under `images/` and point each case's `image` field at them.
The scoring logic in `harness.py` is pure and unit-testable without Ollama.
