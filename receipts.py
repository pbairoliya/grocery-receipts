"""receipts.py — the receipt index: source of truth for dedup + idempotency.

Every processed receipt is stored as one JSON line keyed by a fingerprint
(store + date + time, falling back to an item/price signature). Re-uploading the
same receipt resolves to the same fingerprint, so we keep ONE PDF and recompute
the *delta* into the pantry instead of double-counting. Expense reports and the
By-Store table are rebuilt from this index, making the whole pipeline idempotent.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from config import GROCERY_TYPE, RECEIPTS_INDEX


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "unknown"


def _item_signature(items: list[dict]) -> str:
    """Stable 8-char hash of the (item, price) multiset — distinguishes receipts."""
    parts = sorted(f"{_slug(it.get('item',''))}:{it.get('price')}" for it in items)
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:8]


def fingerprint(receipt: dict) -> str:
    """Identity for a receipt: store + date + (time or item-signature).

    A re-scan of the same purchase shares store, date and printed time, so it maps
    to the same id even if a price or two were OCR'd differently. When no time is
    legible, the item/price signature stands in (two separate same-day trips are
    very unlikely to share an identical itemisation)."""
    store, date = _slug(receipt.get("store", "")), receipt.get("date", "") or "nodate"
    time = receipt.get("time", "")
    tail = time or _item_signature(receipt.get("items", []))
    return f"{store}|{date}|{tail}"


def load(path: Path = RECEIPTS_INDEX) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def save(records: list[dict], path: Path = RECEIPTS_INDEX) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")


def find(records: list[dict], fp: str) -> dict | None:
    return next((r for r in records if r.get("id") == fp), None)


def upsert(records: list[dict], record: dict) -> list[dict]:
    """Insert or replace the record with the same id. Returns the new list."""
    out = [r for r in records if r.get("id") != record["id"]]
    out.append(record)
    return out


def item_deltas(old_items: list[dict], new_items: list[dict], store: str, date: str) -> list[dict]:
    """Signed qty changes to turn `old_items` into `new_items` (for pantry apply).

    A brand-new receipt has old_items=[] → all positive. A correction yields the
    difference per item (can be negative or zero), so the pantry nets out as if
    the receipt had been processed once with the corrected numbers.
    """
    def by_name(items):
        agg: dict[str, dict] = {}
        for it in items:
            key = _slug(it.get("item", ""))
            if not key:
                continue
            cur = agg.setdefault(key, {"item": it.get("item", ""), "qty": 0.0})
            cur["qty"] += float(it.get("qty", 1) or 1)
        return agg

    old, new = by_name(old_items), by_name(new_items)
    deltas: list[dict] = []
    for key in set(old) | set(new):
        d = new.get(key, {}).get("qty", 0.0) - old.get(key, {}).get("qty", 0.0)
        if d != 0:
            name = (new.get(key) or old.get(key))["item"]
            deltas.append({"item": name, "qty": d, "store": store, "date": date})
    return deltas


def make_record(receipt: dict, fp: str, pdf_name: str, status: str, now_iso: str) -> dict:
    return {
        "id": fp,
        "store": receipt.get("store", ""),
        "date": receipt.get("date", ""),
        "time": receipt.get("time", ""),
        "type": receipt.get("type", "other"),
        "total": receipt.get("total"),
        "items": receipt.get("items", []),
        "pdf": pdf_name,
        "status": status,           # "complete" | "needs-review"
        "is_grocery": receipt.get("type") == GROCERY_TYPE,
        "updated": now_iso,
    }
