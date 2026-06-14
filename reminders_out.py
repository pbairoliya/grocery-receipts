"""reminders_out.py — surface low-stock groceries to the user.

Two independent sinks:
  1. Apple Reminders — a "Groceries" list on the iPhone's daily agenda/widgets,
     written via osascript. (New code: daily-lookback never wrote Reminders.)
  2. The Obsidian daily note's "## 🛒 Groceries" section — a written record,
     deliberately separate from daily-lookback's "🔔 Reminders" section so the
     two tools never overwrite each other.

Both degrade gracefully: a failure in one sink prints a warning and returns
False rather than breaking the pipeline.
"""
from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

from config import REMINDERS_LIST
from note_io import (
    GROCERIES_HEADING,
    inject_section,
    note_path_for,
    render_template,
)


def labels(low, out) -> list[str]:
    """Build display labels like 'Olive oil (out)', 'Milk (low)' — out first."""
    return [f"{it.name} (out)" for it in out] + [f"{it.name} (low)" for it in low]


# --- Sink 1: Apple Reminders --------------------------------------------------

def _applescript(list_name: str) -> str:
    # List name is interpolated (we control it); item names arrive as argv, so
    # AppleScript handles their quoting — no string-injection risk.
    safe = list_name.replace('"', '\\"')
    return f'''
on run argv
    tell application "Reminders"
        if not (exists list "{safe}") then
            make new list with properties {{name:"{safe}"}}
        end if
        set theList to list "{safe}"
        set existingNames to name of (reminders of theList whose completed is false)
        repeat with rawName in argv
            set nm to rawName as text
            if existingNames does not contain nm then
                make new reminder at end of theList with properties {{name:nm}}
            end if
        end repeat
    end tell
end run
'''


def push_apple_reminders(item_labels: list[str], list_name: str = REMINDERS_LIST) -> bool:
    """Add labels to the Apple Reminders list, skipping ones already pending."""
    if not item_labels:
        return True
    try:
        proc = subprocess.run(
            ["osascript", "-e", _applescript(list_name), *item_labels],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"Apple Reminders push failed: {e}")
        return False
    if proc.returncode != 0:
        print(f"Apple Reminders push failed: {proc.stderr.strip()}")
        return False
    return True


# --- Sink 2: Obsidian daily note ----------------------------------------------

def render_groceries_markdown(item_labels: list[str]) -> str:
    if not item_labels:
        return "_Nothing needed today._"
    return "\n".join(f"- [ ] 🛒 {label}" for label in item_labels)


def update_daily_note(
    item_labels: list[str], date: dt.date | None = None, *, dry_run: bool = False
) -> Path | None:
    """Write the 🛒 Groceries section into today's daily note.

    Creates the note from the daily template if it doesn't exist yet. Returns
    the note path (or None if writing was skipped/failed).
    """
    date = date or dt.date.today()
    path = note_path_for(date)
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8")
        else:
            text = render_template(date)
        text = inject_section(text, GROCERIES_HEADING, render_groceries_markdown(item_labels))
        if dry_run:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path
    except OSError as e:
        print(f"Daily-note update failed: {e}")
        return None


def notify_low_stock(low, out, date: dt.date | None = None) -> dict:
    """Fan low/out items out to both sinks. Returns a small status dict."""
    item_labels = labels(low, out)
    return {
        "labels": item_labels,
        "apple_reminders": push_apple_reminders(item_labels),
        "daily_note": str(update_daily_note(item_labels, date) or ""),
    }
