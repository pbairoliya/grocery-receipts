"""OCR smoke test: render a synthetic receipt, OCR it, check text round-trips."""
from __future__ import annotations

from pathlib import Path

import ocr
from receipt_fixture import render_receipt


def test_ocr_reads_items_and_prices_on_same_row(tmp_path: Path):
    img = render_receipt(tmp_path / "receipt.png")
    text = ocr.ocr_file(img)

    # Store + a few items survive recognition.
    assert "TRADER JOE" in text
    assert "BANANAS" in text
    assert "WHOLE MILK" in text

    # Row reconstruction keeps each item and its price on one line.
    milk_line = next(l for l in text.splitlines() if "WHOLE MILK" in l)
    assert "3.49" in milk_line
    banana_line = next(l for l in text.splitlines() if "BANANAS" in l)
    assert "1.29" in banana_line
