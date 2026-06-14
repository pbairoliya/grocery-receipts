"""Tests for shopping-list candidate logic and rendering."""
from __future__ import annotations

import datetime as dt

import shopping
from pantry import Item


def test_finished_out_low_and_journal():
    stock = [
        Item("Milk", qty=0, low=1, last_bought="2026-06-13"),   # out
        Item("Eggs", qty=2, low=4, last_bought="2026-06-13"),   # low
        Item("Rice", qty=5, low=0, last_bought="2026-06-13"),   # fine
    ]
    finished = [Item("Olive oil", qty=0, finished_date="2026-06-14", last_bought="2026-06-10")]
    out = shopping.build_shopping_list(
        stock, finished, journal_items=["Coffee"], today=dt.date(2026, 6, 14), stale_days=10
    )
    by = {c["name"]: c["reason"] for c in out}
    assert by["Olive oil"] == "finished"
    assert by["Milk"] == "out"
    assert by["Eggs"] == "low"
    assert by["Coffee"] == "mentioned in journal"
    assert "Rice" not in by


def test_stale_staple_rule():
    # One left, last shop 12 days ago → flagged "running low".
    stock = [Item("Ketchup", qty=1, low=0, last_bought="2026-06-02")]
    out = shopping.build_shopping_list(stock, [], today=dt.date(2026, 6, 14), stale_days=10)
    assert out and "running low" in out[0]["reason"]


def test_not_stale_keeps_staple_off():
    stock = [Item("Ketchup", qty=1, low=0, last_bought="2026-06-12")]
    out = shopping.build_shopping_list(stock, [], today=dt.date(2026, 6, 14), stale_days=10)
    assert out == []


def test_render_empty_and_populated():
    assert "Nothing needed" in shopping.render_shopping_list([], dt.date(2026, 6, 14))
    md = shopping.render_shopping_list([{"name": "Milk", "reason": "out"}], dt.date(2026, 6, 14))
    assert "- [ ] Milk — out" in md
    assert "type: shopping-list" in md


def test_build_upcoming_projects_within_horizon():
    # last bought 5 days ago, stale_days 10 → due in 5 days → inside a 14-day horizon.
    stock = [Item("Ketchup", qty=1, low=0, last_bought="2026-06-09")]
    up = shopping.build_upcoming(stock, [], today=dt.date(2026, 6, 14), stale_days=10, horizon=14)
    assert up == [{"name": "Ketchup", "due": "2026-06-19"}]


def test_upcoming_excludes_already_needed_and_well_stocked():
    stock = [
        Item("Ketchup", qty=1, low=0, last_bought="2026-06-09"),
        Item("Rice", qty=8, low=0, last_bought="2026-06-09"),       # plenty
    ]
    cands = [{"name": "Ketchup", "reason": "low"}]                  # already on list
    up = shopping.build_upcoming(stock, cands, today=dt.date(2026, 6, 14), stale_days=10, horizon=14)
    assert up == []


def test_upcoming_in_rendered_list():
    md = shopping.render_shopping_list(
        [], dt.date(2026, 6, 14), upcoming=[{"name": "Milk", "due": "2026-06-22"}]
    )
    assert "## 🔮 Coming up" in md
    assert "- Milk — likely by 2026-06-22" in md
