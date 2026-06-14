"""Unit tests for journal-scan cleaning (LLM call covered by a live check)."""
from __future__ import annotations

import journal_scan


def test_clean_dedupes_and_strips():
    assert journal_scan._clean(["Coffee", "- milk ", "coffee", "•Eggs"]) == ["Coffee", "milk", "Eggs"]


def test_clean_handles_empty():
    assert journal_scan._clean(None) == []
    assert journal_scan._clean([" ", ""]) == []


def test_grocery_like_filter_drops_finance_terms():
    assert journal_scan._is_grocery_like("coffee")       # not caught by "fee"
    assert journal_scan._is_grocery_like("cashews")      # not caught by "cash"
    assert journal_scan._is_grocery_like("paper towels")
    assert not journal_scan._is_grocery_like("credit card")
    assert not journal_scan._is_grocery_like("bank account")
    assert not journal_scan._is_grocery_like("rent")
    assert not journal_scan._is_grocery_like("gym membership")
    assert not journal_scan._is_grocery_like("flight ticket")
