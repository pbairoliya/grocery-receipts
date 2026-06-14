"""extract.py — OCR text → structured grocery line-items via local Ollama.

The model only *reads* the already-OCR'd text (Apple Vision handles the pixels),
so its job is the easy part: split items from prices, categorize, and skip the
subtotal/tax/total noise. Normalization is a pure function so it can be unit
tested without a running model.
"""
from __future__ import annotations

import datetime as dt
import re

from config import CATEGORIES, DEFAULT_MODEL, EXPENSE_TYPES, GROCERY_TYPE, REVIEW_TOTAL_TOLERANCE
from ollama import generate_json

# Lines that are receipt machinery, never pantry items — guard in case the
# model echoes one despite instructions.
_SUMMARY_WORDS = {
    "subtotal", "sub total", "total", "tax", "balance", "change", "cash",
    "credit", "debit", "visa", "mastercard", "amex", "tend", "tender",
    "payment", "savings", "you saved", "loyalty", "points",
}

# Placeholder names the model sometimes emits for unreadable lines — drop them.
_PLACEHOLDER_NAMES = {"unknown item", "unknown", "item", "n/a", ""}

SYSTEM_PROMPT = f"""You convert OCR text from a purchase receipt into structured JSON.
Receipts may be groceries, restaurants/bars, rent, utilities, transport, retail, etc.

Output STRICT JSON ONLY — one object, no markdown fences, no commentary:
{{
  "store": string,            // merchant/brand name, or "" if unclear
  "date": string,             // purchase date as YYYY-MM-DD, or "" if not found
  "time": string,             // time of purchase as HH:MM (24h), or "" if not found
  "type": string,             // EXACTLY one expense type from the list below
  "total": number,            // the printed grand TOTAL paid, or null if unreadable
  "items": [
    {{
      "item": string,         // clean, human product name (e.g. "Whole Milk")
      "category": string,     // EXACTLY one of the grocery categories below
      "qty": number,          // units bought (default 1 if not shown)
      "price": number         // line total in dollars (e.g. 3.49), null if unreadable
    }}
  ]
}}

For "type", pick the best expense category — classify by what was bought, not
just the store name. PREFER one of these common categories when it fits:
{", ".join(EXPENSE_TYPES)}
…but if NONE of them fit, invent a short, lowercase category of your own (one or
two words, e.g. "pharmacy", "haircut", "pet supplies", "hardware"). Never force a
bad fit into "other" when a clear category exists.
- "{GROCERY_TYPE}": a supermarket / grocery haul of ingredients (Trader Joe's,
  Safeway, Whole Foods, Costco food, etc.).
- "car": fuel/gas (look for "gallons", price/gal, a pump #), EV charging, parking,
  tolls, car wash, auto repair. A 7-Eleven/Costco/Wawa receipt that is FUEL → car.
- "dining": prepared food or drinks consumed out — restaurants, cafés, bars, fast
  food, coffee shops, takeout, delivery.
- "rent": apartment/housing. "utilities": power/water/internet/phone.
- "shopping": general retail (clothes, electronics, household goods).
- "health": pharmacy/medical. "entertainment": movies, events, games.
- "other": anything that doesn't clearly fit.
A convenience store (e.g. 7-Eleven) is "car" if the receipt is for gas, "dining"
if it's snacks/drinks, or "groceries" if it's grocery ingredients — decide from
the line items.

Grocery categories (for "category" on each item; fall back to "Other"):
{", ".join(CATEGORIES)}

Rules:
- Only itemize GROCERY receipts in detail. For non-grocery receipts (dining, rent,
  etc.) you may return an empty "items" array — "store", "date", "type", "total"
  are what matter there.
- ONE entry per purchased product line. Expand the OCR's abbreviations into a
  readable name ("WHL MILK 1GAL" -> "Whole Milk").
- NEVER include SUBTOTAL, TAX, TOTAL, payment, card, savings, store address, or
  any non-product line as an item.
- price is the line's dollar amount as a plain number (no "$").
- A line like "2 @ $1.89" is the unit breakdown of the PRODUCT ON THE LINE
  ABOVE it — set THAT item's qty to 2 and keep its line total (3.78). NEVER
  create a separate entry for an "@" line.
- If you CANNOT read an item's name, OMIT it entirely. NEVER output placeholder
  names like "Unknown Item", and never invent products not in the text.
- Do not duplicate an item. The number of entries should not exceed the receipt's
  stated item count if one is shown.
- If you cannot read a price, use null. Do not guess a price.
"""


def build_prompt(ocr_text: str) -> str:
    return f"Receipt OCR text:\n\n{ocr_text.strip()}\n\nReturn the JSON object."


def _to_float(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if m:
            return float(m.group())
    return None


def _to_qty(value) -> float:
    f = _to_float(value)
    if f is None or f <= 0:
        return 1.0
    # Keep whole numbers as ints for clean display (2 not 2.0).
    return int(f) if f == int(f) else f


def normalize_date(value: str, fallback: str = "") -> str:
    """Return an ISO YYYY-MM-DD date from common receipt formats, else fallback."""
    value = (value or "").strip()
    if not value:
        return fallback
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    # Already-ISO-ish prefix (e.g. "2026-06-14T..").
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return m.group(0)
    return fallback


def _is_summary(name: str) -> bool:
    low = name.lower().strip()
    return any(low == w or low.startswith(w) for w in _SUMMARY_WORDS)


def normalize_items(parsed: dict, store: str, date: str) -> list[dict]:
    """Coerce a raw model object's items into validated line-item rows."""
    valid_categories = {c.lower(): c for c in CATEGORIES}
    rows: list[dict] = []
    for raw in parsed.get("items", []) or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("item", "") or "").strip()
        if not name or _is_summary(name) or name.lower() in _PLACEHOLDER_NAMES:
            continue
        price = _to_float(raw.get("price"))
        category = valid_categories.get(str(raw.get("category", "")).lower().strip(), "Other")
        rows.append(
            {
                "store": store,
                "date": date,
                "item": name,
                "category": category,
                "qty": _to_qty(raw.get("qty")),
                "price": round(price, 2) if price is not None else None,
            }
        )
    return rows


# Map common phrasings onto canonical category names so folders/labels stay tidy,
# while still allowing brand-new categories the model invents.
_TYPE_SYNONYMS = {
    "gas": "car", "fuel": "car", "gasoline": "car", "auto": "car", "automotive": "car",
    "food": "dining", "restaurant": "dining", "restaurants": "dining", "eating out": "dining",
    "takeout": "dining", "fast food": "dining", "bar": "dining", "cafe": "dining",
    "grocery": "groceries", "supermarket": "groceries", "market": "groceries",
    "utility": "utilities", "pharmacy": "health", "medical": "health",
    "clothing": "shopping", "retail": "shopping", "pet": "pets", "subscription": "subscriptions",
}


def _normalize_type(value: str) -> str:
    """Open category: tidy the model's label, map synonyms, but allow new ones."""
    v = re.sub(r"[^a-z0-9 &/+-]", "", str(value or "").strip().lower()).strip()
    v = re.sub(r"\s+", " ", v)
    v = _TYPE_SYNONYMS.get(v, v)
    return v[:30] or "other"


def _normalize_time(value: str) -> str:
    m = re.search(r"(\d{1,2}):([0-5]\d)\s*([AaPp][Mm])?", str(value or ""))
    if not m:
        return ""
    hour, minute, ap = int(m.group(1)), m.group(2), (m.group(3) or "").lower()
    if ap == "pm" and hour < 12:
        hour += 12
    elif ap == "am" and hour == 12:
        hour = 0
    return f"{hour % 24:02d}:{minute}"


def review_reasons(items: list[dict], total: float | None, rtype: str) -> list[str]:
    """Why a receipt needs human review (poor-ink OCR). Empty list = clean."""
    reasons: list[str] = []
    missing = [it["item"] for it in items if it.get("price") is None]
    if missing:
        reasons.append(f"unreadable price for: {', '.join(missing)}")
    # Only reconcile item sums against the printed total for itemized (grocery) receipts.
    if rtype == GROCERY_TYPE and total and items:
        summed = sum(it["price"] or 0 for it in items)
        if total > 0 and abs(summed - total) / total > REVIEW_TOTAL_TOLERANCE:
            reasons.append(f"items sum to ${summed:,.2f} but receipt total is ${total:,.2f}")
    return reasons


def normalize_receipt(parsed: dict, fallback_date: str = "") -> dict:
    """Raw model object → validated receipt dict (pure, testable)."""
    store = str(parsed.get("store", "") or "").strip()
    date = normalize_date(str(parsed.get("date", "") or ""), fallback_date)
    rtype = _normalize_type(parsed.get("type"))
    total = _to_float(parsed.get("total"))
    items = normalize_items(parsed, store, date)
    return {
        "store": store,
        "date": date,
        "time": _normalize_time(parsed.get("time")),
        "type": rtype,
        "total": round(total, 2) if total is not None else None,
        "items": items,
        "review_reasons": review_reasons(items, total, rtype),
    }


def extract_receipt(ocr_text: str, fallback_date: str = "", *, model: str = DEFAULT_MODEL) -> dict:
    """OCR text → validated receipt dict {store,date,time,type,total,items,review_reasons}."""
    parsed = generate_json(build_prompt(ocr_text), SYSTEM_PROMPT, model=model)
    return normalize_receipt(parsed, fallback_date)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    from ocr import ocr_file

    if len(sys.argv) != 2:
        raise SystemExit("usage: uv run python extract.py <receipt.jpg|receipt.pdf>")
    receipt = extract_receipt(ocr_file(Path(sys.argv[1])), fallback_date=dt.date.today().isoformat())
    print(json.dumps(receipt, indent=2))
