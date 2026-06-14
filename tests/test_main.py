"""Tests for archive naming and fallback-date derivation."""
from __future__ import annotations

from pathlib import Path

import main


def test_archived_name_store_and_date():
    assert main.archived_name("Trader Joe's", "2026-03-18", ".pdf") == "Trader Joe's 2026-03-18.pdf"


def test_archived_name_sanitizes_and_defaults():
    assert main.archived_name("A/B:Mart", "2026-03-18", ".jpg") == "ABMart 2026-03-18.jpg"
    assert main.archived_name("", "2026-03-18", ".pdf") == "Receipt 2026-03-18.pdf"


def test_fallback_date_from_filename_prefix():
    assert main._fallback_date(Path("/x/2026-06-14-173200.png")) == "2026-06-14"
