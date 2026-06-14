"""Pure-function tests for reminder label + markdown rendering."""
from __future__ import annotations

import reminders_out
from pantry import Item


def test_labels_out_before_low():
    low = [Item("Milk", 1, 1)]
    out = [Item("Olive oil", 0, 1)]
    assert reminders_out.labels(low, out) == ["Olive oil (out)", "Milk (low)"]


def test_render_groceries_markdown():
    md = reminders_out.render_groceries_markdown(["Olive oil (out)", "Milk (low)"])
    assert md.splitlines() == ["- [ ] 🛒 Olive oil (out)", "- [ ] 🛒 Milk (low)"]


def test_render_empty():
    assert reminders_out.render_groceries_markdown([]) == "_Nothing needed today._"
