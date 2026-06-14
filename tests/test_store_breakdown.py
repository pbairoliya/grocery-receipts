"""Tests for By-Store aggregation from the receipt index."""
from __future__ import annotations

import store_breakdown as sb


def _rec(store, date, total, n_items, status="complete", is_grocery=True):
    return {"store": store, "date": date, "total": total, "status": status,
            "is_grocery": is_grocery, "items": [{"item": f"x{i}"} for i in range(n_items)]}


def test_aggregate_merges_case_and_sums():
    records = [
        _rec("Trader Joe's", "2026-03-18", 33.29, 11),
        _rec("TRADER JOE'S", "2026-06-14", 52.58, 17),   # different casing → merged
        _rec("Safeway", "2026-06-14", 51.60, 12),
    ]
    rows = sb.aggregate(records)
    by = {r["store"]: r for r in rows}
    assert by["Trader Joe's"]["trips"] == 2
    assert by["Trader Joe's"]["items"] == 28
    assert round(by["Trader Joe's"]["spent"], 2) == 85.87
    assert by["Trader Joe's"]["last"] == "2026-06-14"
    assert rows[0]["store"] == "Trader Joe's"  # sorted by spend desc


def test_excludes_needs_review():
    records = [_rec("Safeway", "2026-06-14", 51.60, 12, status="needs-review")]
    assert sb.aggregate(records) == []


def test_excludes_non_grocery():
    # A 7-Eleven gas (car) receipt is NOT a grocery store → not in By Store.
    records = [_rec("7-Eleven", "2026-06-14", 43.00, 0, is_grocery=False)]
    assert sb.aggregate(records) == []


def test_render_table():
    md = sb.render_table(sb.aggregate([_rec("Safeway", "2026-06-14", 51.60, 12)]))
    assert "| Safeway | 1 | 12 | $51.60 | 2026-06-14 |" in md
    assert "No receipts" in sb.render_table([])
