"""review_flow.py — hold poorly-read receipts for human correction.

When OCR can't read an item name or price (faded ink), the receipt isn't silently
committed. Instead we write an editable note to Groceries/Review/: you fix the
rows, change `status: needs-review` → `status: ready` in the frontmatter, and the
next run finalizes it into the pantry + expenses. Render + parse are pure so the
round-trip is testable.
"""
from __future__ import annotations

import re
from pathlib import Path

from config import CATEGORIES, REVIEW_DIR
from extract import _to_float, _to_qty

STATUS_NEEDS = "needs-review"
STATUS_READY = "ready"


def _safe(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", text or "").strip()


def review_path(receipt: dict, review_dir: Path = REVIEW_DIR) -> Path:
    store = _safe(receipt.get("store", "")) or "Receipt"
    date = receipt.get("date", "") or "nodate"
    time = (receipt.get("time", "") or "").replace(":", "")
    name = f"{store} {date}" + (f" {time}" if time else "")
    return Path(review_dir) / f"{name}.md"


def render_review_note(receipt: dict, fp: str, ocr_text: str = "") -> str:
    reasons = receipt.get("review_reasons", [])
    lines = [
        "---", "type: receipt-review", f"status: {STATUS_NEEDS}", f"id: {fp}",
        f"store: {receipt.get('store','')}", f"date: {receipt.get('date','')}",
        f"time: {receipt.get('time','')}", f"receipt_type: {receipt.get('type','other')}",
        f"total: {receipt.get('total') if receipt.get('total') is not None else ''}",
        "---",
        f"# Review needed — {receipt.get('store','') or 'Receipt'} {receipt.get('date','')}", "",
        "⚠️ Some lines couldn't be read cleanly. Fix the rows below, then **tick the box**",
        "to add this receipt to your pantry (the next run intakes it for its date):", "",
        f"- [ ] ✅ Reviewed — add {receipt.get('store','') or 'this receipt'}"
        f" ({receipt.get('date','')}) to the pantry",
    ]
    if reasons:
        lines += ["", f"> Why this needs review: {'; '.join(reasons)}"]
    lines += ["", "## Items", "| Item | Category | Qty | Price |", "| --- | --- | --- | --- |"]
    for it in receipt.get("items", []):
        price = "" if it.get("price") is None else it["price"]
        lines.append(f"| {it.get('item','')} | {it.get('category','Other')} | {it.get('qty',1)} | {price} |")
    lines += ["", "## OCR text (reference)", "```", ocr_text.strip(), "```", ""]
    return "\n".join(lines)


def write_review_note(receipt: dict, fp: str, ocr_text: str = "", review_dir: Path = REVIEW_DIR) -> Path:
    path = review_path(receipt, review_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_review_note(receipt, fp, ocr_text), encoding="utf-8")
    return path


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    fm: dict = {}
    if m:
        for line in m.group(1).split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
    return fm


def _parse_items(text: str) -> list[dict]:
    valid = {c.lower(): c for c in CATEGORIES}
    items: list[dict] = []
    in_items = False
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("## Items"):
            in_items = True
            continue
        if in_items and s.startswith("## "):
            break
        if not (in_items and s.startswith("|")):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 4 or cells[0].lower() == "item" or set(s) <= set("|- "):
            continue
        name = cells[0]
        if not name:
            continue
        items.append({
            "item": name,
            "category": valid.get(cells[1].lower(), "Other"),
            "qty": _to_qty(cells[2]),
            "price": _to_float(cells[3]),
        })
    return items


def _is_approved(text: str) -> bool:
    """The user ticked the native '- [x] Reviewed' checkbox (persists on tap)."""
    return bool(re.search(r"^\s*-\s*\[x\]", text, re.IGNORECASE | re.MULTILINE))


def parse_review_note(text: str) -> dict:
    """Read an edited review note back into a receipt dict (+ status)."""
    fm = _frontmatter(text)
    items = _parse_items(text)
    for it in items:                       # stamp store/date so pantry gets them
        it["store"] = fm.get("store", "")
        it["date"] = fm.get("date", "")
    # Ticking the checkbox OR setting status: ready both finalize the receipt.
    approved = _is_approved(text) or fm.get("status") == STATUS_READY
    return {
        "id": fm.get("id", ""),
        "status": STATUS_READY if approved else STATUS_NEEDS,
        "store": fm.get("store", ""),
        "date": fm.get("date", ""),
        "time": fm.get("time", ""),
        "type": fm.get("receipt_type", "other"),
        "total": _to_float(fm.get("total")),
        "items": items,
    }


def ready_reviews(review_dir: Path = REVIEW_DIR) -> list[tuple[Path, dict]]:
    """Return (path, receipt) for every review note the user has marked ready."""
    review_dir = Path(review_dir)
    if not review_dir.exists():
        return []
    out: list[tuple[Path, dict]] = []
    for path in sorted(review_dir.glob("*.md")):
        receipt = parse_review_note(path.read_text(encoding="utf-8"))
        if receipt["status"] == STATUS_READY:
            out.append((path, receipt))
    return out
