"""Tests for pantry tables, checkbox/qty reconcile, purchases, and round-trip."""
from __future__ import annotations

import datetime as dt

import pantry

# Old list format — exercises back-compat parsing (migrates to tables on write).
SAMPLE = """---
type: pantry
updated: 2026-06-01
tags: [grocery, pantry]
---
# Pantry

## 🥫 Stock
- [ ] Milk — qty 1 / low 1 · last 2026-06-01
- [x] Eggs — qty 12 / low 4 · last 2026-06-01
- [ ] Olive oil — qty 0 / low 1

## ✅ Finished
- [x] Butter — finished 2026-05-20
"""

TABLE = """## 🥫 Stock
| Have | Item | Qty | Low | Last bought | Store |
| :-: | --- | :-: | :-: | --- | --- |
| <input type="checkbox" checked/> | Garlic | 4 | 0 | 2026-06-14 | Trader Joe's |
| <input type="checkbox"/> | Milk | 2 | 1 | 2026-06-10 | Safeway |
| <input type="checkbox" checked/> | Eggs | 0 | 0 | 2026-06-10 | Safeway |
"""


def test_parse_table_checkbox_and_qty_semantics():
    items = {i.name: i for i in pantry.parse_stock(TABLE)}
    assert items["Garlic"].qty == 4 and items["Garlic"].store == "Trader Joe's"
    assert items["Garlic"].checked is False        # checked box = in stock
    assert items["Milk"].checked is True           # unchecked = used up
    assert items["Eggs"].checked is True           # qty 0 = used up


def test_parse_old_list_still_works():
    items = {i.name: i for i in pantry.parse_stock(SAMPLE)}
    assert items["Milk"].qty == 1 and items["Milk"].last_bought == "2026-06-01"
    assert items["Eggs"].checked is True           # [x] = used up


def test_render_stock_is_a_table_with_html_checkbox():
    it = pantry.Item("Garlic", qty=4, low=0, last_bought="2026-06-14", store="Trader Joe's")
    rows = pantry.render_stock([it])
    assert "| Have | Item | Qty | Low | Last bought | Store |" in rows
    assert any('<input type="checkbox" checked/>' in r and "| Garlic | 4 | 0 |" in r for r in rows)


def test_render_parse_table_roundtrip():
    it = pantry.Item("Garlic", qty=4, low=0, last_bought="2026-06-14", store="Trader Joe's")
    text = "## 🥫 Stock\n" + "\n".join(pantry.render_stock([it])) + "\n"
    back = pantry.parse_stock(text)[0]
    assert back.name == "Garlic" and back.qty == 4 and back.store == "Trader Joe's"
    assert back.last_bought == "2026-06-14" and back.checked is False


def test_reconcile_used_up_moves_to_finished():
    new_stock, new_finished = pantry.reconcile(pantry.parse_stock(TABLE), [], [], "2026-06-14")
    names_stock = {i.name for i in new_stock}
    assert names_stock == {"Garlic"}                       # Milk (unchecked) + Eggs (qty0) left
    assert {"Milk", "Eggs"} <= {i.name for i in new_finished}


def test_update_pantry_file_migrates_list_to_table(tmp_path):
    p = tmp_path / "Pantry.md"
    p.write_text(SAMPLE, encoding="utf-8")
    pantry.update_pantry_file(
        [{"item": "Milk", "qty": 1, "date": "2026-06-14", "store": "Safeway"}],
        path=p, today=dt.date(2026, 6, 14),
    )
    text = p.read_text(encoding="utf-8")
    assert "| Have | Item | Qty | Low | Last bought | Store |" in text
    assert '<input type="checkbox" checked/>' in text
    assert "| Milk | 2 | 1 |" in text                      # bought 1 more
    assert "| Eggs | 2026-06-14 |" in text                 # checked → Finished table
    assert "- [ ] Milk" not in text                        # old list format gone


def test_creates_file_when_missing(tmp_path):
    p = tmp_path / "sub" / "Pantry.md"
    pantry.update_pantry_file([{"item": "Rice", "qty": 1, "date": "2026-06-14", "store": "Costco"}],
                              path=p, today=dt.date(2026, 6, 14))
    text = p.read_text(encoding="utf-8")
    assert "type: pantry" in text
    assert "| Rice | 1 | 0 |" in text and "Costco" in text


def test_store_and_days_since():
    items = pantry.parse_stock(TABLE)
    assert pantry.days_since_last_shop(items, [], dt.date(2026, 6, 20)) == 6  # latest 06-14
