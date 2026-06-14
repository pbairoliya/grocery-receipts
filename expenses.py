"""expenses.py — monthly expense reports, rebuilt from the receipt index.

Because the report is *derived* from the index (not appended to), reprocessing or
de-duplicating a receipt can never double-count: we just rewrite the month from
the current set of records. Groceries get their own subtotal and a category
sub-breakdown; every other expense type is summed alongside.
"""
from __future__ import annotations

from pathlib import Path

from config import EXPENSE_EMOJI, EXPENSE_EMOJI_DEFAULT, EXPENSES_DIR, GROCERY_TYPE


def label_for(category: str) -> str:
    """Emoji + Title-cased category, e.g. 'car' -> '⛽ Car'."""
    return f"{EXPENSE_EMOJI.get(category, EXPENSE_EMOJI_DEFAULT)} {category.title()}"


def _money(v: float) -> str:
    return f"${v:,.2f}"


def receipt_total(rec: dict) -> float:
    if rec.get("total") is not None:
        return float(rec["total"])
    return sum(float(it.get("price") or 0) for it in rec.get("items", []))


def _complete(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("status") == "complete"]


def months_in(records: list[dict]) -> list[str]:
    return sorted({(r.get("date") or "")[:7] for r in _complete(records) if r.get("date")})


def month_report_text(records: list[dict], month: str) -> str:
    recs = sorted(
        [r for r in _complete(records) if (r.get("date") or "").startswith(month)],
        key=lambda r: (r.get("date", ""), r.get("time", "")),
    )

    by_type: dict[str, float] = {}
    grocery_by_cat: dict[str, float] = {}
    for r in recs:
        by_type[r.get("type", "other")] = by_type.get(r.get("type", "other"), 0.0) + receipt_total(r)
        if r.get("type") == GROCERY_TYPE:
            for it in r.get("items", []):
                cat = it.get("category", "Other") or "Other"
                grocery_by_cat[cat] = grocery_by_cat.get(cat, 0.0) + float(it.get("price") or 0)

    grand = sum(by_type.values())
    out = [
        "---", "type: expense-report", f"month: {month}", "tags: [finance, expenses]", "---",
        f"# Expenses — {month}", "",
        "> Rebuilt from scanned receipts each run; de-duplicated, so totals stay accurate.", "",
        "## Total", f"**{_money(grand)}**", "",
        "## By type",
    ]
    for t, amt in sorted(by_type.items(), key=lambda kv: -kv[1]):
        out.append(f"- {label_for(t)}: {_money(amt)}")

    if grocery_by_cat:
        out += ["", f"### {label_for(GROCERY_TYPE)} by category"]
        for c, amt in sorted(grocery_by_cat.items(), key=lambda kv: -kv[1]):
            out.append(f"- {c}: {_money(amt)}")

    out += ["", "## Receipts", "| Date | Store | Type | Total |", "| --- | --- | --- | --- |"]
    for r in recs:
        out.append(
            f"| {r.get('date','')} | {r.get('store','') or 'Unknown'} | "
            f"{r.get('type','other')} | {_money(receipt_total(r))} |"
        )
    return "\n".join(out) + "\n"


def rebuild(records: list[dict], expenses_dir: Path = EXPENSES_DIR) -> list[Path]:
    """Rewrite a monthly expense note for every month present in the index."""
    expenses_dir = Path(expenses_dir)
    written: list[Path] = []
    months = months_in(records)
    if months:
        expenses_dir.mkdir(parents=True, exist_ok=True)
    for month in months:
        path = expenses_dir / f"{month}.md"
        path.write_text(month_report_text(records, month), encoding="utf-8")
        written.append(path)
    return written
