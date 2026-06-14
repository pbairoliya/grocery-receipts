"""note_io.py — Obsidian markdown section helpers.

Slim copy of the section-upsert helpers from ../daily-lookback/note_io.py,
dropping the task/rules-specific machinery. These are the pieces reused for the
pantry file and the daily-note grocery section.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from config import DAILY_DIR, TEMPLATE_PATH

# Grocery low-stock lands under its OWN daily-note heading — deliberately NOT
# "🔔 Reminders", which daily-lookback regenerates wholesale each morning.
GROCERIES_HEADING = "🛒 Groceries"


def note_path_for(date: dt.date) -> Path:
    return DAILY_DIR / f"{date.isoformat()}.md"


def render_template(date: dt.date) -> str:
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    long_form = f"{date.strftime('%A, %B')} {date.day}, {date.year}"
    text = text.replace("{{date:YYYY-MM-DD}}", date.isoformat())
    text = text.replace("{{date:dddd, MMMM D, YYYY}}", long_form)
    return text


def extract_section(text: str, heading: str) -> str:
    lines = text.split("\n")
    start = end = None
    for i, line in enumerate(lines):
        if start is None:
            if line.startswith("## " + heading):
                start = i + 1
        elif line.startswith("## "):
            end = i
            break
    if start is None:
        return ""
    return "\n".join(lines[start : end if end is not None else len(lines)])


def _section_bounds(lines: list[str], heading: str) -> tuple[int, int] | None:
    header = f"## {heading}"
    for i, line in enumerate(lines):
        if line.startswith(header):
            end = len(lines)
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("## "):
                    end = j
                    break
            return i, end
    return None


def inject_section(note_text: str, heading: str, section_body: str) -> str:
    """Idempotent upsert: replace the heading's block if present, else insert."""
    lines = note_text.split("\n")
    new_block = [f"## {heading}", "", section_body.strip(), ""]

    bounds = _section_bounds(lines, heading)
    if bounds is not None:
        start, end = bounds
        return "\n".join(lines[:start] + new_block + lines[end:])

    for i, line in enumerate(lines):
        if line.startswith("# ") and not line.startswith("## "):
            return "\n".join(lines[: i + 1] + [""] + new_block + lines[i + 1 :])

    return note_text.rstrip() + "\n\n" + "\n".join(new_block)


def remove_section(note_text: str, heading: str) -> str:
    """Drop a whole `## heading` block (heading + body) if present."""
    lines = note_text.split("\n")
    bounds = _section_bounds(lines, heading)
    if bounds is None:
        return note_text
    start, end = bounds
    return "\n".join(lines[:start] + lines[end:])


def is_section_empty(note_text: str, heading: str) -> bool:
    body = extract_section(note_text, heading)
    for line in body.split("\n"):
        s = line.strip()
        if not s or s.startswith(">") or s in ("-", "- "):
            continue
        return False
    return True


def replace_section_body(note_text: str, heading: str, new_body_lines: list[str]) -> str:
    """Replace a section's body, preserving any leading `>` callout hint lines."""
    if not new_body_lines:
        return note_text
    lines = note_text.split("\n")
    bounds = _section_bounds(lines, heading)
    if bounds is None:
        return note_text
    start, end = bounds

    hints: list[str] = []
    i = start + 1
    while i < end:
        s = lines[i].strip()
        if s.startswith(">"):
            hints.append(lines[i])
            i += 1
        elif not s and not hints:
            i += 1
        else:
            break

    replacement = [lines[start]] + hints + list(new_body_lines) + [""]
    return "\n".join(lines[:start] + replacement + lines[end:])
