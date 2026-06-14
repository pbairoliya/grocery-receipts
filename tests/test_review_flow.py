"""Tests for the review-note render/parse round-trip and checkbox approval."""
from __future__ import annotations

import review_flow as rf

RECEIPT = {
    "store": "Trader Joe's", "date": "2026-03-18", "time": "19:07",
    "type": "groceries", "total": 36.14,
    "items": [
        {"item": "Palak Paneer", "category": "Pantry", "qty": 1, "price": 3.99},
        {"item": "Baby Spinach", "category": "Produce", "qty": 1, "price": None},  # unreadable
    ],
    "review_reasons": ["unreadable price for: Baby Spinach"],
}


def test_render_has_approve_checkbox_and_table():
    md = rf.render_review_note(RECEIPT, "fp1", ocr_text="RAW OCR")
    assert "- [ ] ✅ Reviewed — add Trader Joe's (2026-03-18) to the pantry" in md
    assert "| Palak Paneer | Pantry | 1 | 3.99 |" in md
    assert "| Baby Spinach | Produce | 1 |  |" in md   # blank price to fill
    assert "RAW OCR" in md


def test_unticked_note_is_not_ready():
    md = rf.render_review_note(RECEIPT, "fp1", "RAW")
    assert rf.parse_review_note(md)["status"] == "needs-review"


def test_ticking_checkbox_finalizes_with_user_fix():
    md = rf.render_review_note(RECEIPT, "fp1", "RAW")
    md = md.replace("- [ ] ✅ Reviewed", "- [x] ✅ Reviewed")               # tick the box
    md = md.replace("| Baby Spinach | Produce | 1 |  |", "| Baby Spinach | Produce | 1 | 2.49 |")
    parsed = rf.parse_review_note(md)
    assert parsed["status"] == "ready" and parsed["id"] == "fp1"
    assert parsed["total"] == 36.14
    spinach = next(i for i in parsed["items"] if i["item"] == "Baby Spinach")
    assert spinach["price"] == 2.49 and spinach["store"] == "Trader Joe's"


def test_status_ready_frontmatter_still_works():
    md = rf.render_review_note(RECEIPT, "fp1", "RAW").replace("status: needs-review", "status: ready")
    assert rf.parse_review_note(md)["status"] == "ready"


def test_ready_reviews_filters_by_tick(tmp_path):
    rf.write_review_note(RECEIPT, "fp1", "RAW", review_dir=tmp_path)             # not ticked
    p = rf.write_review_note({**RECEIPT, "store": "Safeway"}, "fp2", "RAW", review_dir=tmp_path)
    p.write_text(p.read_text().replace("- [ ] ✅ Reviewed", "- [x] ✅ Reviewed"), encoding="utf-8")
    found = rf.ready_reviews(tmp_path)
    assert [r["id"] for _, r in found] == ["fp2"]
