"""main.py — orchestrate the receipt pipeline, then review pantry → shopping list.

Per receipt: OCR (Apple Vision) → classify + extract (gemma3) → de-dup against the
receipt index → either hold for human review (unreadable lines) or apply to the
pantry (groceries only) and record. One PDF is kept per receipt; re-uploads correct
the numbers via item deltas instead of double-counting.

Review (after draining, and daily): finalize any reviews you've marked ready,
process pantry checkboxes, rebuild expense reports + By-Store table from the index,
scan the journal, and refresh the shopping list (+ nudges).

Usage:
  uv run python main.py                 # drain Inbox + review (launchd entry point)
  uv run python main.py <file>          # process a single receipt + review
  uv run python main.py --review        # review only (finalize edits, refresh lists)
  uv run python main.py --watch [secs]  # poll the Inbox forever (default 30s)
"""
from __future__ import annotations

import datetime as dt
import fcntl
import re
import shutil
import sys
import time
from pathlib import Path

import expenses
import extract
import journal_scan
import ocr
import pantry
import receipts
import reminders_out
import review_flow
import sheets
import shopping
import store_breakdown
from config import ARCHIVE_DIR, FINISHED_THRESHOLD, GROCERY_TYPE, INBOX_DIR, PANTRY_PATH
from ollama import shutdown_ollama, wait_for_ollama

_DATE_PREFIX_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _fallback_date(path: Path) -> str:
    """Date for receipts whose printed date is unreadable: filename prefix, else mtime."""
    m = _DATE_PREFIX_RE.search(path.stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return dt.date.fromtimestamp(path.stat().st_mtime).isoformat()


def _safe_name(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|]', "", s)).strip()


def archived_name(store: str, date: str, suffix: str) -> str:
    """e.g. ('Trader Joe's', '2026-03-18', '.pdf') -> "Trader Joe's 2026-03-18.pdf"."""
    return f"{_safe_name(store) or 'Receipt'} {date or dt.date.today().isoformat()}{suffix}"


def _type_dir(rtype: str) -> Path:
    return ARCHIVE_DIR / (rtype or "other").title()   # Receipts/Car, Receipts/Groceries, …


def _archived_path(rtype: str, pdf_name: str) -> Path:
    return _type_dir(rtype) / pdf_name


def _archive(path: Path, store: str, date: str, rtype: str) -> Path:
    # File straight into a per-category folder: Receipts/Car/, Receipts/Groceries/…
    # A brand-new category just creates its own folder here.
    dest_dir = _type_dir(rtype)
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = archived_name(store, date, path.suffix)
    dest, n = dest_dir / base, 2
    while dest.exists():  # distinct receipt, same store+date → " (2)", " (3)", …
        dest = dest_dir / f"{base[: -len(path.suffix)]} ({n}){path.suffix}"
        n += 1
    shutil.move(str(path), str(dest))
    return dest


def _prev_applied_items(existing: dict | None) -> list[dict]:
    """Items already applied to the pantry for this fingerprint (for delta math)."""
    if existing and existing.get("status") == "complete" and existing.get("is_grocery"):
        return existing.get("items", [])
    return []


def _apply_to_pantry(receipt: dict, old_items: list[dict], today: dt.date) -> None:
    deltas = receipts.item_deltas(old_items, receipt["items"], receipt["store"], receipt["date"])
    if deltas:
        pantry.update_pantry_file(deltas, today=today)


def process_receipt(path: Path) -> dict:
    """OCR → classify → de-dup → apply or hold for review. Returns a summary dict."""
    path = Path(path)
    print(f"\n▶ Processing {path.name}")

    text = ocr.ocr_file(path)
    receipt = extract.extract_receipt(text, fallback_date=_fallback_date(path))
    receipt["date"] = receipt["date"] or _fallback_date(path)
    fp = receipts.fingerprint(receipt)

    index = receipts.load()
    existing = receipts.find(index, fp)
    total = expenses.receipt_total({"total": receipt["total"], "items": receipt["items"]})
    print(f"  {receipt['type']} · {receipt['store'] or 'unknown'} · {receipt['date']}"
          f"{(' ' + receipt['time']) if receipt['time'] else ''} · ${total:,.2f} · {len(receipt['items'])} items")

    # One PDF per receipt: keep the existing copy on a re-upload, else file this one.
    if existing and existing.get("pdf") and _archived_path(existing.get("type", ""), existing["pdf"]).exists():
        pdf_name, dup = existing["pdf"], True
        path.unlink(missing_ok=True)
        print(f"  ↺ duplicate of {pdf_name} — keeping one copy, updating numbers")
    else:
        pdf_name, dup = _archive(path, receipt["store"], receipt["date"], receipt["type"]).name, False

    # Unreadable lines → hold for human review, do NOT touch the pantry yet.
    if receipt["review_reasons"]:
        note = review_flow.write_review_note(receipt, fp, ocr_text=text)
        index = receipts.upsert(index, receipts.make_record(receipt, fp, pdf_name, "needs-review", _now()))
        receipts.save(index)
        print(f"  ⚠ needs review → {note.name} ({'; '.join(receipt['review_reasons'])})")
        return {"file": path.name, "status": "needs-review", "review_note": str(note)}

    # Clean → apply groceries to the pantry (delta vs whatever was applied before).
    if receipt["type"] == GROCERY_TYPE:
        _apply_to_pantry(receipt, _prev_applied_items(existing), dt.date.today())
    index = receipts.upsert(index, receipts.make_record(receipt, fp, pdf_name, "complete", _now()))
    receipts.save(index)
    if not dup and receipt["type"] == GROCERY_TYPE:
        sheets.append_line_items(receipt["items"])
    # A clean version supersedes any stale review note for the same receipt.
    stale = review_flow.review_path(receipt)
    if stale.exists():
        stale.unlink()

    print(f"  ✓ recorded ({'updated' if dup else 'new'}) · pdf: {pdf_name}")
    return {"file": path.name, "status": "complete", "type": receipt["type"], "total": round(total, 2)}


def _finalize_reviews(today: dt.date) -> list[dict]:
    """Apply review notes the user has marked `status: ready`, then delete them."""
    finalized: list[dict] = []
    for note_path, receipt in review_flow.ready_reviews():
        fp = receipt["id"] or receipts.fingerprint(receipt)
        index = receipts.load()
        existing = receipts.find(index, fp)
        if receipt["type"] == GROCERY_TYPE:
            _apply_to_pantry(receipt, _prev_applied_items(existing), today)
        pdf_name = existing.get("pdf", "") if existing else ""
        receipts.save(receipts.upsert(index, receipts.make_record(receipt, fp, pdf_name, "complete", _now())))
        note_path.unlink(missing_ok=True)
        finalized.append(receipt)
        print(f"  ✓ finalized review: {receipt['store']} {receipt['date']}")
    return finalized


def review(today: dt.date | None = None) -> dict:
    """Finalize edits, reconcile pantry, rebuild reports, refresh the shopping list."""
    today = today or dt.date.today()
    finalized = _finalize_reviews(today)

    state = pantry.update_pantry_file([], today=today)   # process ticked boxes
    store_breakdown.update_pantry_store_table()           # 🏪 By Store (from index)
    expenses.rebuild(receipts.load())                     # monthly expense reports

    journal_items = journal_scan.scan_journal(today)
    candidates = shopping.build_shopping_list(state["stock"], state["finished"], journal_items, today)
    upcoming = shopping.build_upcoming(state["stock"], candidates, today)
    shop_path = shopping.write_shopping_list(candidates, today=today, upcoming=upcoming)

    labels = [f"{c['name']} — {c['reason']}" for c in candidates]
    reminders_out.update_daily_note(labels, today)
    finished_n, out_n = len(state["finished"]), len(state["out"])
    triggered = finished_n >= FINISHED_THRESHOLD or bool(journal_items) or out_n > 0
    pushed = reminders_out.push_apple_reminders([c["name"] for c in candidates]) if (triggered and candidates) else False

    pending = sum(1 for r in receipts.load() if r.get("status") == "needs-review")
    print(
        f"  🛒 shopping list: {len(candidates)} item(s) → {shop_path.name} "
        f"(finished {finished_n}, journal {len(journal_items)}, out {out_n}; pushed: {pushed}); "
        f"reviews finalized: {len(finalized)}, pending: {pending}"
    )
    return {"candidates": candidates, "finalized": len(finalized), "pending_reviews": pending}


def rebuild_pantry_from_index(today: dt.date | None = None) -> None:
    """Rebuild Pantry.md purely from completed grocery records in the index.

    Unlike reindex.py (which re-OCRs the PDFs), this trusts the index — so any
    approved review edits are preserved — and is the way to reflect a receipt
    being removed from the index (e.g. a test scan). Resets the pantry first.
    """
    today = today or dt.date.today()
    PANTRY_PATH.unlink(missing_ok=True)
    groc = sorted(
        [r for r in receipts.load() if r.get("status") == "complete" and r.get("is_grocery")],
        key=lambda r: (r.get("date", ""), r.get("time", "")),
    )
    for r in groc:
        deltas = receipts.item_deltas([], r.get("items", []), r.get("store", ""), r.get("date", ""))
        if deltas:
            pantry.update_pantry_file(deltas, today=today)
    store_breakdown.update_pantry_store_table()
    expenses.rebuild(receipts.load())


def _pending(inbox: Path) -> list[Path]:
    if not inbox.exists():
        return []
    return sorted(p for p in inbox.iterdir() if p.is_file() and ocr.is_supported(p))


def drain_inbox() -> list[dict]:
    pending = _pending(INBOX_DIR)
    if not pending:
        print(f"Inbox empty: {INBOX_DIR}")
        return []
    print(f"Found {len(pending)} receipt(s) in {INBOX_DIR}")
    results = []
    for path in pending:
        try:
            results.append(process_receipt(path))
        except Exception as e:  # one bad receipt shouldn't stop the batch
            import traceback
            print(f"  ✗ Failed on {path.name}: {e}\n{traceback.format_exc()}")
            results.append({"file": path.name, "error": str(e)})
    return results


def watch(interval: int = 30) -> None:
    print(f"Watching {INBOX_DIR} every {interval}s (Ctrl-C to stop)…")
    while True:
        drain_inbox()
        review()
        time.sleep(interval)


_LOCK_PATH = Path(__file__).resolve().parent / ".pipeline.lock"


def main() -> None:
    args = sys.argv[1:]
    # Serialize runs: Apple Vision OCR deadlocks ("Resource deadlock avoided") if
    # two processes call it at once — e.g. the launchd watcher firing during a
    # manual run. A blocking file lock makes the second run wait its turn (and it
    # then drains any newly-arrived receipts), so nothing is lost or corrupted.
    lock_file = open(_LOCK_PATH, "w")
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    # Start Ollama on demand for this run, and always stop it afterward so it
    # isn't left resident eating RAM. A server the user started themselves is
    # detected and left untouched (see ollama.shutdown_ollama).
    wait_for_ollama()
    try:
        if args and args[0] == "--watch":
            watch(int(args[1]) if len(args) > 1 else 30)
        elif args and args[0] == "--review":
            review()
        elif args:
            process_receipt(Path(args[0]))
            review()
        else:
            drain_inbox()
            review()
    finally:
        shutdown_ollama()
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    main()
