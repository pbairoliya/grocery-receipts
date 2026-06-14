"""Tests for the Google Sheets row mapping."""
from __future__ import annotations

import sheets


def test_item_to_row():
    item = {"date": "2026-06-14", "store": "TJ", "item": "Milk",
            "category": "Dairy", "qty": 1, "price": 3.49}
    assert sheets.item_to_row(item) == ["2026-06-14", "TJ", "Milk", "Dairy", 1, 3.49]


def test_item_to_row_handles_none_price():
    assert sheets.item_to_row({"item": "X"})[-1] == ""
