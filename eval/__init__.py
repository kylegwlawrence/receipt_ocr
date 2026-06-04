"""A small evaluation harness for the receipt extraction stage.

Unlike the unit tests under ``tests/`` (which mock the vision model), this harness
runs the *real* model against a set of labelled receipts and scores the output
field-by-field. It exists so that prompt/schema/model changes can be compared
objectively instead of by eyeballing one receipt at a time.

See ``eval/README.md`` for usage and the case-file format.
"""
