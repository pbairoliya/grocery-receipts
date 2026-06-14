"""Tests for index-derived monthly expense reports."""
from __future__ import annotations

import expenses


def _rec(store, date, rtype, total, items=None, status="complete"):
    return {"store": store, "date": date, "type": rtype, "total": total,
            "status": status, "items": items or []}


RECORDS = [
    _rec("Trader Joe's", "2026-06-14", "groceries", 52.58, [
        {"item": "Milk", "category": "Dairy", "price": 3.49},
        {"item": "Bananas", "category": "Produce", "price": 1.29},
    ]),
    _rec("Chipotle", "2026-06-13", "dining", 14.20),
    _rec("Greystar", "2026-06-01", "rent", 1500.00),
    _rec("Old", "2026-05-02", "dining", 9.99),                     # different month
    _rec("Pending", "2026-06-10", "groceries", 99.0, status="needs-review"),  # excluded
]


def test_month_report_totals_and_grocery_subtotal():
    text = expenses.month_report_text(RECORDS, "2026-06")
    assert "**$1,566.78**" in text                 # 52.58 + 14.20 + 1500 (pending excluded)
    assert "- 🛒 Groceries: $52.58" in text
    assert "- 🏠 Rent: $1,500.00" in text
    assert "- 🍽️ Dining: $14.20" in text
    # Grocery category sub-breakdown present.
    assert "### 🛒 Groceries by category" in text
    assert "- Dairy: $3.49" in text


def test_label_for_known_and_unknown():
    assert expenses.label_for("car") == "⛽ Car"
    assert expenses.label_for("groceries") == "🛒 Groceries"
    assert expenses.label_for("haircut") == "🧾 Haircut"   # invented category → default emoji


def test_receipts_table_excludes_other_months_and_pending():
    text = expenses.month_report_text(RECORDS, "2026-06")
    assert "| 2026-06-14 | Trader Joe's | groceries | $52.58 |" in text
    assert "Old" not in text and "Pending" not in text


def test_rebuild_writes_one_file_per_month(tmp_path):
    paths = expenses.rebuild(RECORDS, tmp_path)
    names = sorted(p.name for p in paths)
    assert names == ["2026-05.md", "2026-06.md"]
    assert (tmp_path / "2026-06.md").read_text().startswith("---")
