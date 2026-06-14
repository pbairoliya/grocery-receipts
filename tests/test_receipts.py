"""Tests for the receipt index: fingerprinting, dedup, and item deltas."""
from __future__ import annotations

import receipts


def _r(store="Trader Joe's", date="2026-06-14", time="19:07", items=None, total=36.14, rtype="groceries"):
    return {"store": store, "date": date, "time": time, "type": rtype, "total": total,
            "items": items or [{"item": "Milk", "qty": 1, "price": 3.49}]}


def test_fingerprint_same_for_rescan_with_price_drift():
    # Same store/date/time → same id even if a price was OCR'd differently.
    a = _r(items=[{"item": "Milk", "qty": 1, "price": 3.49}])
    b = _r(items=[{"item": "Milk", "qty": 1, "price": 3.46}])  # OCR drift
    assert receipts.fingerprint(a) == receipts.fingerprint(b)


def test_fingerprint_uses_item_sig_when_no_time():
    a = _r(time="", items=[{"item": "Milk", "qty": 1, "price": 3.49}])
    b = _r(time="", items=[{"item": "Eggs", "qty": 1, "price": 4.19}])
    assert receipts.fingerprint(a) != receipts.fingerprint(b)


def test_fingerprint_distinguishes_different_times():
    assert receipts.fingerprint(_r(time="09:00")) != receipts.fingerprint(_r(time="19:07"))


def test_upsert_replaces_same_id(tmp_path):
    recs = []
    rec1 = receipts.make_record(_r(total=10.0), "fp1", "a.pdf", "complete", "t1")
    recs = receipts.upsert(recs, rec1)
    rec2 = receipts.make_record(_r(total=12.0), "fp1", "a.pdf", "complete", "t2")
    recs = receipts.upsert(recs, rec2)
    assert len(recs) == 1 and receipts.find(recs, "fp1")["total"] == 12.0


def test_item_deltas_new_receipt_all_positive():
    new = [{"item": "Milk", "qty": 2}, {"item": "Eggs", "qty": 1}]
    d = {x["item"]: x["qty"] for x in receipts.item_deltas([], new, "TJ", "2026-06-14")}
    assert d == {"Milk": 2.0, "Eggs": 1.0}


def test_item_deltas_correction_nets_out():
    old = [{"item": "Milk", "qty": 2}, {"item": "Eggs", "qty": 1}]
    new = [{"item": "Milk", "qty": 1}, {"item": "Bread", "qty": 1}]  # milk fixed 2→1, eggs gone, bread added
    d = {x["item"]: x["qty"] for x in receipts.item_deltas(old, new, "TJ", "2026-06-14")}
    assert d == {"Milk": -1.0, "Eggs": -1.0, "Bread": 1.0}


def test_load_save_roundtrip(tmp_path):
    path = tmp_path / ".receipts.jsonl"
    rec = receipts.make_record(_r(), "fp1", "a.pdf", "complete", "t1")
    receipts.save([rec], path)
    assert receipts.load(path)[0]["id"] == "fp1"
