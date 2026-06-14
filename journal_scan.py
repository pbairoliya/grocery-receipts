"""journal_scan.py — read recent daily-note journals for "running out of X" mentions.

Best-effort and local: if Ollama is down or there's nothing to read, it returns
an empty list and the pipeline carries on. Only the journal/free-text sections
are scanned — not tasks or auto-generated blocks.
"""
from __future__ import annotations

import datetime as dt
import re

from config import DEFAULT_MODEL, JOURNAL_SCAN_DAYS
from note_io import extract_section, note_path_for
from ollama import generate_json, ollama_up

# Free-text sections worth scanning in a daily note.
_SCAN_HEADINGS = ("📓 Journal", "🧠 Learnings", "🪞 Looking back")

SYSTEM_PROMPT = """You read short personal journal entries and pull out GROCERY,
FOOD, or HOUSEHOLD-CONSUMABLE items the writer indicates they are LOW ON, OUT OF,
FINISHED, or NEED TO BUY (e.g. coffee, milk, dish soap, paper towels).

Output STRICT JSON ONLY: {"items": [string, ...]} — clean product names. Include
an item ONLY if the text clearly implies the writer needs to RESTOCK it.

NEVER include things that are not physical groceries you'd buy at a supermarket:
no money, bills, credit/debit cards, rent, loans, subscriptions, taxes, work,
meetings, people, places, emotions, or tasks. If nothing qualifies, return
{"items": []}. Never invent items, and never include food merely eaten or cooked.
"""

# Belt-and-suspenders filter: drop anything that smells non-grocery even if the
# model slips it through (e.g. "credit card" from a finance journal entry).
_STOP_TERMS = (
    # money / finance — the journal is finance-heavy, so guard hard here
    "card", "credit", "debit", "bill", "rent", "mortgage", "loan", "payment",
    "invoice", "subscription", "money", "cash", "venmo", "paypal", "tax",
    "insurance", "salary", "paycheck", "account", "bank", "savings", "checking",
    "deposit", "withdraw", "transfer", "fund", "invest", "stock", "crypto",
    "budget", "debt", "fee", "balance", "statement", "interest",
    # admin / life, never groceries
    "gym", "meeting", "email", "appointment", "flight", "ticket", "reservation",
)


_STOP_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in _STOP_TERMS) + r")\b", re.IGNORECASE)


def _is_grocery_like(name: str) -> bool:
    # Whole-word match only, so "coffee" isn't caught by "fee" nor "cashews" by "cash".
    return not _STOP_RE.search(name)


def collect_journal_text(today: dt.date, days: int = JOURNAL_SCAN_DAYS) -> str:
    """Concatenate the free-text sections of the last `days` daily notes."""
    chunks: list[str] = []
    for back in range(days):
        path = note_path_for(today - dt.timedelta(days=back))
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for heading in _SCAN_HEADINGS:
            body = extract_section(text, heading).strip()
            if body:
                chunks.append(body)
    return "\n\n".join(chunks).strip()


def _clean(items) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for it in items or []:
        name = str(it).strip().strip("-•").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def scan_journal(
    today: dt.date | None = None, days: int = JOURNAL_SCAN_DAYS, *, model: str = DEFAULT_MODEL
) -> list[str]:
    """Return grocery items the recent journal implies the user needs."""
    today = today or dt.date.today()
    text = collect_journal_text(today, days)
    if not text or not ollama_up():
        return []
    try:
        parsed = generate_json(
            f"Journal entries:\n\n{text}\n\nReturn the JSON object.",
            SYSTEM_PROMPT,
            model=model,
        )
    except RuntimeError as e:
        print(f"Journal scan skipped (Ollama): {e}")
        return []
    return [n for n in _clean(parsed.get("items")) if _is_grocery_like(n)]


if __name__ == "__main__":
    print(scan_journal())
