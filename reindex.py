"""reindex.py — rebuild index, pantry, and reports from the archived PDFs.

Re-OCRs every receipt under the archive and replays them through the pipeline, so
the receipt index and pantry are reconstructed from scratch. Use it to migrate
pre-index archives, or to recover if the index is ever lost. Pantry.md is backed
up to Pantry.md.bak first.

  uv run python reindex.py
"""
from __future__ import annotations

import datetime as dt

import expenses
import extract
import ocr
import pantry
import receipts
import review_flow
import store_breakdown
from config import ARCHIVE_DIR, GROCERY_TYPE, PANTRY_PATH, RECEIPTS_INDEX


def reindex() -> None:
    skip = {"Inbox", "Review"}
    pdfs = [
        p for p in ARCHIVE_DIR.rglob("*")
        if p.is_file() and ocr.is_supported(p) and not (skip & set(p.parts))
    ]
    if not pdfs:
        print(f"No archived receipts under {ARCHIVE_DIR}")
        return

    if PANTRY_PATH.exists():
        PANTRY_PATH.rename(PANTRY_PATH.with_suffix(".md.bak"))
        print(f"Backed up pantry → {PANTRY_PATH.name}.bak")
    RECEIPTS_INDEX.unlink(missing_ok=True)

    print(f"Re-OCRing {len(pdfs)} archived receipt(s)…")
    parsed = []
    for pdf in pdfs:
        receipt = extract.extract_receipt(ocr.ocr_file(pdf), fallback_date="")
        parsed.append((pdf, receipt))
    parsed.sort(key=lambda pr: (pr[1].get("date") or "", pr[1].get("time") or ""))

    now = dt.datetime.now().isoformat(timespec="seconds")
    index: list[dict] = []
    for pdf, receipt in parsed:
        receipt["date"] = receipt["date"] or dt.date.fromtimestamp(pdf.stat().st_mtime).isoformat()
        fp = receipts.fingerprint(receipt)
        if receipt["review_reasons"]:
            review_flow.write_review_note(receipt, fp, ocr_text="")
            status = "needs-review"
            print(f"  ⚠ {pdf.name}: needs review ({'; '.join(receipt['review_reasons'])})")
        else:
            if receipt["type"] == GROCERY_TYPE:
                deltas = receipts.item_deltas([], receipt["items"], receipt["store"], receipt["date"])
                if deltas:
                    pantry.update_pantry_file(deltas)
            status = "complete"
            print(f"  ✓ {pdf.name}: {receipt['type']} · {receipt['store']} · {receipt['date']} · {len(receipt['items'])} items")
        index = receipts.upsert(index, receipts.make_record(receipt, fp, pdf.name, status, now))

    receipts.save(index)
    store_breakdown.update_pantry_store_table()
    written = expenses.rebuild(index)
    print(f"Rebuilt index ({len(index)} receipts), pantry, and {len(written)} expense report(s).")


if __name__ == "__main__":
    reindex()
