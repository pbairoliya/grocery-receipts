"""store_breakdown.py — "where did my money go" table for Pantry.md.

Aggregates the receipt index by store (trips, items, spent, last trip) and
injects a read-only `## 🏪 By Store` table into Pantry.md. Sourced from the
index so it stays consistent with the de-duplicated expense reports.
"""
from __future__ import annotations

from pathlib import Path

import receipts
from config import PANTRY_PATH, RECEIPTS_INDEX
from expenses import receipt_total
from note_io import inject_section

BY_STORE_HEADING = "🏪 By Store"


def _nicer_casing(candidate: str, current: str) -> bool:
    """Prefer the variant with more lowercase letters ('Trader Joe's' > 'TRADER JOE'S')."""
    lc = lambda s: sum(c.islower() for c in s)
    return lc(candidate) > lc(current)


def aggregate(records: list[dict]) -> list[dict]:
    """Sum completed GROCERY receipts by store. (Gas/dining aren't grocery stores.)"""
    by_store: dict[str, dict] = {}
    for r in records:
        if r.get("status") != "complete" or not r.get("is_grocery"):
            continue
        store = r.get("store") or "Unknown"
        key = store.casefold()
        s = by_store.setdefault(
            key, {"store": store, "trips": 0, "items": 0, "spent": 0.0, "last": ""}
        )
        if _nicer_casing(store, s["store"]):
            s["store"] = store
        s["trips"] += 1
        s["items"] += len(r.get("items", []))
        s["spent"] += receipt_total(r)
        s["last"] = max(s["last"], r.get("date", ""))
    return sorted(by_store.values(), key=lambda r: r["spent"], reverse=True)


def render_table(rows: list[dict]) -> str:
    if not rows:
        return "_No receipts recorded yet._"
    out = ["| Store | Trips | Items | Spent | Last trip |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        out.append(f"| {r['store']} | {r['trips']} | {r['items']} | ${r['spent']:,.2f} | {r['last']} |")
    return "\n".join(out)


def update_pantry_store_table(
    pantry_path: Path = PANTRY_PATH, index_path: Path = RECEIPTS_INDEX
) -> Path:
    """Inject/refresh the 🏪 By Store table in Pantry.md from the receipt index."""
    pantry_path = Path(pantry_path)
    if not pantry_path.exists():
        return pantry_path
    rows = aggregate(receipts.load(index_path))
    text = inject_section(pantry_path.read_text(encoding="utf-8"), BY_STORE_HEADING, render_table(rows))
    pantry_path.write_text(text, encoding="utf-8")
    return pantry_path
