"""shopping.py — build the grocery shopping list from pantry state + history.

A candidate is something you've bought before and likely need now:
  - it's in ✅ Finished, or fully out, or at/below its `low` reorder point;
  - it's a near-empty staple (≤1 left) and it's been a while since you last shopped;
  - your journal says you're running out of it.

Pure `build_shopping_list` + a thin file writer, so the logic is unit-testable.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from config import PREVIEW_DAYS, SHOPPING_LIST_PATH, STALE_DAYS
from pantry import Item, days_since_last_shop


def build_shopping_list(
    stock: list[Item],
    finished: list[Item],
    journal_items: list[str] | None = None,
    today: dt.date | None = None,
    stale_days: int = STALE_DAYS,
) -> list[dict]:
    """Return ordered [{name, reason}] — highest-priority reason wins per item."""
    today = today or dt.date.today()
    journal_items = journal_items or []
    picks: dict[str, str] = {}      # normalized name → reason (first wins)
    _display: dict[str, str] = {}   # normalized name → original display name

    def add(name: str, reason: str) -> None:
        key = name.strip().lower()
        if key and key not in picks:
            picks[key] = reason
            _display[key] = name.strip()

    for it in finished:
        add(it.name, "finished")
    for it in stock:
        if it.is_out:
            add(it.name, "out")
    for it in stock:
        if it.is_low:
            add(it.name, "low")
    for name in journal_items:
        add(name, "mentioned in journal")

    days = days_since_last_shop(stock, finished, today)
    if days is not None and days >= stale_days:
        for it in stock:
            if it.qty <= 1:
                add(it.name, f"running low ({days} days since shopping)")

    return [{"name": _display[k], "reason": r} for k, r in picks.items()]


def build_upcoming(
    stock: list[Item],
    candidates: list[dict],
    today: dt.date | None = None,
    stale_days: int = STALE_DAYS,
    horizon: int = PREVIEW_DAYS,
) -> list[dict]:
    """Project items likely needed within the next `horizon` days.

    A near-empty staple (≤1 left) that isn't needed *yet* but whose last purchase
    will cross the staleness line within the horizon is surfaced as a heads-up,
    with the date it's expected to come due. Items already on the list are skipped.
    """
    today = today or dt.date.today()
    already = {c["name"].lower() for c in candidates}
    upcoming: list[dict] = []
    for it in stock:
        if it.qty > 1 or it.name.lower() in already or not it.last_bought:
            continue
        try:
            due = dt.date.fromisoformat(it.last_bought) + dt.timedelta(days=stale_days)
        except ValueError:
            continue
        if today < due <= today + dt.timedelta(days=horizon):
            upcoming.append({"name": it.name, "due": due.isoformat()})
    return sorted(upcoming, key=lambda u: u["due"])


def render_shopping_list(
    candidates: list[dict], today: dt.date, upcoming: list[dict] | None = None
) -> str:
    iso = today.isoformat()
    head = (
        "---\n"
        "type: shopping-list\n"
        f"updated: {iso}\n"
        "tags: [grocery, shopping]\n"
        "---\n"
        "# 🛒 Shopping List\n\n"
        f"> Auto-generated {iso}. Check items off as you buy them — scanning the "
        "receipt clears them automatically.\n\n"
    )
    if candidates:
        body = "\n".join(f"- [ ] {c['name']} — {c['reason']}" for c in candidates) + "\n"
    else:
        body = "- _Nothing needed right now 🎉_\n"

    horizon = (today + dt.timedelta(days=PREVIEW_DAYS)).isoformat()
    section = f"\n## 🔮 Coming up (by {horizon})\n\n"
    if upcoming:
        section += "\n".join(f"- {u['name']} — likely by {u['due']}" for u in upcoming) + "\n"
    else:
        section += "_Nothing projected to run low in the next two weeks._\n"
    return head + body + section


def write_shopping_list(
    candidates: list[dict],
    path: Path = SHOPPING_LIST_PATH,
    today: dt.date | None = None,
    upcoming: list[dict] | None = None,
) -> Path:
    today = today or dt.date.today()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_shopping_list(candidates, today, upcoming), encoding="utf-8")
    return path
