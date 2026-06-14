"""Unit tests for the pure normalization logic in extract.py (no Ollama)."""
from __future__ import annotations

import extract


def test_normalize_receipt_basic():
    parsed = {
        "store": "Trader Joe's", "date": "06/14/2026", "time": "7:09 PM",
        "type": "groceries", "total": 4.78,
        "items": [
            {"item": "Whole Milk", "category": "Dairy", "qty": 1, "price": 3.49},
            {"item": "Bananas", "category": "Produce", "qty": "1", "price": "$1.29"},
        ],
    }
    r = extract.normalize_receipt(parsed, fallback_date="2026-01-01")
    assert r["store"] == "Trader Joe's" and r["date"] == "2026-06-14"
    assert r["time"] == "19:09" and r["type"] == "groceries" and r["total"] == 4.78
    assert [i["item"] for i in r["items"]] == ["Whole Milk", "Bananas"]
    assert r["review_reasons"] == []


def test_type_synonyms_and_open_categories():
    norm = lambda t: extract.normalize_receipt({"type": t, "items": []})["type"]
    assert norm("Gas") == "car" and norm("fuel") == "car"      # synonyms → canonical
    assert norm("Dining") == "dining" and norm("restaurant") == "dining"
    assert norm("haircut") == "haircut"                        # invented category kept
    assert norm("") == "other"


def test_summary_lines_dropped():
    parsed = {"type": "groceries", "items": [
        {"item": "SUBTOTAL", "price": 22.46},
        {"item": "Eggs", "category": "Dairy", "price": 4.19},
    ]}
    assert [i["item"] for i in extract.normalize_receipt(parsed)["items"]] == ["Eggs"]


def test_review_flag_on_missing_price():
    parsed = {"type": "groceries", "total": 5.0, "items": [
        {"item": "Spinach", "category": "Produce", "price": None},
        {"item": "Eggs", "category": "Dairy", "price": 4.19},
    ]}
    reasons = extract.normalize_receipt(parsed)["review_reasons"]
    assert any("unreadable price" in r and "Spinach" in r for r in reasons)


def test_review_flag_on_total_mismatch():
    parsed = {"type": "groceries", "total": 50.0, "items": [
        {"item": "Eggs", "category": "Dairy", "price": 4.19},
    ]}
    assert any("total" in r for r in extract.normalize_receipt(parsed)["review_reasons"])


def test_nongrocery_no_item_reconcile():
    # Dining receipt with no items + a total should NOT be flagged for review.
    parsed = {"type": "dining", "total": 42.0, "items": []}
    assert extract.normalize_receipt(parsed)["review_reasons"] == []


def test_bad_date_uses_fallback():
    assert extract.normalize_date("not a date", "2026-06-14") == "2026-06-14"
    assert extract.normalize_date("12/25/2025") == "2025-12-25"
