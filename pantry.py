"""pantry.py — maintain the Obsidian pantry inventory markdown.

Pantry.md has two managed sections, both phone-editable in Obsidian:

    ## 🥫 Stock
    - [ ] Milk — qty 1 / low 1 · last 2026-03-18
    - [ ] Eggs — qty 12 / low 4 · last 2026-03-18

    ## ✅ Finished
    - [x] Olive oil — finished 2026-06-14

Checking a Stock item's box means "I finished this": on the next run it moves
into Finished (and becomes a shopping-list candidate). Buying it again moves it
back to Stock, bumps qty, and refreshes `last`. Parsing + reconciliation are
pure functions; only `update_pantry_file` touches disk.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from config import LOW_THRESHOLD, PANTRY_PATH
from note_io import extract_section

STOCK_HEADING = "🥫 Stock"
FINISHED_HEADING = "✅ Finished"
_LEGACY_LOW_HEADING = "🛒 Low / Out (auto — do not edit)"

# "- [ ] Milk — qty 1 / low 1 · last 2026-03-18 · Trader Joe's"
# (checkbox / low / last / store all optional; store is the trailing · field)
_STOCK_RE = re.compile(
    r"^-\s*(?:\[(?P<check>[ xX])\]\s*)?(?P<name>.+?)\s*[—–-]\s*qty\s+(?P<qty>\d+(?:\.\d+)?)"
    r"(?:\s*/\s*low\s+(?P<low>\d+(?:\.\d+)?))?"
    r"(?:\s*·\s*last\s+(?P<last>\d{4}-\d{2}-\d{2}))?"
    r"(?:\s*·\s*(?P<store>[^·]+?))?\s*$",
    re.IGNORECASE,
)
# "- [x] Olive oil — finished 2026-06-14"
_FINISHED_RE = re.compile(
    r"^-\s*(?:\[[ xX]\]\s*)?(?P<name>.+?)\s*[—–-]\s*finished\s+(?P<date>\d{4}-\d{2}-\d{2})\s*$",
    re.IGNORECASE,
)


@dataclass
class Item:
    name: str
    qty: float
    low: int = LOW_THRESHOLD
    last_bought: str | None = None
    store: str | None = None       # where it was last bought
    checked: bool = False          # checkbox state as parsed from Stock
    finished_date: str | None = None  # set when the item lives in Finished

    @property
    def is_out(self) -> bool:
        return self.qty <= 0

    @property
    def is_low(self) -> bool:
        return 0 < self.qty <= self.low


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


def _num(value: float) -> str:
    return str(int(value)) if float(value) == int(value) else str(value)


_CHECKED = '<input type="checkbox" checked/>'   # in stock (the user has it)
_UNCHECKED = '<input type="checkbox"/>'         # uncheck (or set Qty 0) = used up


def _table_cells(line: str) -> list[str] | None:
    """Cells of a markdown table DATA row, or None for non-rows/header/separator."""
    s = line.strip()
    if not s.startswith("|"):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    if cells and all(re.fullmatch(r":?-+:?", c) for c in cells if c):  # separator row
        return None
    return cells


def _cell(value: str) -> str | None:
    v = (value or "").strip()
    return v if v and v not in ("—", "-", "–") else None


def _parse_num(value: str, default: float) -> float:
    m = re.search(r"-?\d+(?:\.\d+)?", value or "")
    return float(m.group()) if m else default


def _esc(text: str) -> str:
    return (text or "").replace("|", "/")  # keep pipes out of table cells


def parse_stock(note_text: str) -> list[Item]:
    """Parse the Stock section — new table format, with the old list as fallback."""
    items: list[Item] = []
    for line in extract_section(note_text, STOCK_HEADING).split("\n"):
        cells = _table_cells(line)
        if cells and len(cells) >= 6:
            checkbox, name, qty_s, low_s, last_s, store_s = cells[:6]
            if not name or name.lower() == "item":
                continue
            checked = "checked" in checkbox.lower()
            qty = _parse_num(qty_s, 1.0)
            last = _cell(last_s)
            items.append(Item(
                name=name, qty=qty, low=int(_parse_num(low_s, LOW_THRESHOLD)),
                last_bought=last if last and re.match(r"\d{4}-\d{2}-\d{2}", last) else None,
                store=_cell(store_s),
                checked=(not checked) or qty <= 0,   # unchecked or empty = used up
            ))
            continue
        m = _STOCK_RE.match(line.strip())   # back-compat: old "- [ ] … qty …" list
        if m:
            items.append(Item(
                name=m.group("name").strip(), qty=float(m.group("qty")),
                low=int(float(m.group("low"))) if m.group("low") else LOW_THRESHOLD,
                last_bought=m.group("last"), store=(m.group("store") or "").strip() or None,
                checked=(m.group("check") or " ").lower() == "x",
            ))
    return items


def parse_finished(note_text: str) -> list[Item]:
    items: list[Item] = []
    for line in extract_section(note_text, FINISHED_HEADING).split("\n"):
        cells = _table_cells(line)
        if cells and len(cells) >= 2:
            name, date_s = cells[0], cells[1]
            if name and name.lower() != "item":
                store = _cell(cells[2]) if len(cells) >= 3 else None
                items.append(Item(name=name, qty=0, finished_date=_cell(date_s), store=store))
            continue
        m = _FINISHED_RE.match(line.strip())   # back-compat list
        if m:
            items.append(Item(name=m.group("name").strip(), qty=0, finished_date=m.group("date")))
    return items


def reconcile(
    stock: list[Item], finished: list[Item], purchases: list[dict], today: str
) -> tuple[list[Item], list[Item]]:
    """Apply checkbox state + purchases. Returns (new_stock, new_finished).

    - A checked Stock item → moved to Finished (qty 0, finished today).
    - A purchased item → (re)added to Stock, qty bumped, `last` set, unfinished.
    """
    new_stock: list[Item] = []
    finished_by = {_norm(it.name): it for it in finished}

    for it in stock:
        if it.checked:
            it.checked = False
            it.qty = 0
            it.finished_date = today
            finished_by[_norm(it.name)] = it
        else:
            new_stock.append(it)

    stock_by = {_norm(it.name): it for it in new_stock}
    for p in purchases:
        name = str(p.get("item", "")).strip()
        if not name:
            continue
        n = _norm(name)
        qty = float(p.get("qty", 1) or 1)
        date = p.get("date") or today
        store = (str(p.get("store", "")).strip() or None)
        if n not in stock_by and qty <= 0:
            continue  # a negative correction for an item we don't stock → no-op
        revived = finished_by.pop(n, None)  # repurchased → leaves Finished
        if n in stock_by:
            stock_by[n].qty += qty
            stock_by[n].last_bought = date
            stock_by[n].store = store or stock_by[n].store
        else:
            it = revived or Item(name=name, qty=0, low=LOW_THRESHOLD)
            it.qty += qty
            it.last_bought = date
            it.store = store or it.store
            it.finished_date = None
            new_stock.append(it)
            stock_by[n] = it

    return new_stock, list(finished_by.values())


def low_and_out(items: list[Item]) -> tuple[list[Item], list[Item]]:
    return ([it for it in items if it.is_low], [it for it in items if it.is_out])


def days_since_last_shop(stock: list[Item], finished: list[Item], today: dt.date) -> int | None:
    """Days since the most recent purchase across all items, or None if unknown."""
    dates = [it.last_bought for it in (*stock, *finished) if it.last_bought]
    if not dates:
        return None
    try:
        latest = max(dt.date.fromisoformat(d) for d in dates)
    except ValueError:
        return None
    return (today - latest).days


def render_stock(items: list[Item]) -> list[str]:
    """Render Stock as a table. Tip line first, then header + rows.

    Each row shows an HTML checkbox (checked = you have it). Obsidian doesn't
    save a *tap* on it, so the reliable "used it up" action is to set Qty to 0.
    """
    out = [
        "_Set an item's **Qty** to 0 (or uncheck it) when you finish it — "
        "it moves to ✅ Finished and onto the shopping list._",
        "",
        "| Have | Item | Qty | Low | Last bought | Store |",
        "| :-: | --- | :-: | :-: | --- | --- |",
    ]
    for it in sorted(items, key=lambda i: i.name.lower()):
        out.append(
            f"| {_CHECKED} | {_esc(it.name)} | {_num(it.qty)} | {it.low} | "
            f"{it.last_bought or ''} | {_esc(it.store or '')} |"
        )
    return out


def render_finished(items: list[Item]) -> list[str]:
    if not items:
        return ["_Nothing finished recently._"]
    ordered = sorted(items, key=lambda i: (i.finished_date or "", i.name.lower()), reverse=True)
    out = ["| Item | Finished | Store |", "| --- | --- | --- |"]
    out += [f"| {_esc(it.name)} | {it.finished_date or ''} | {_esc(it.store or '')} |" for it in ordered]
    return out


_EMPTY_PANTRY = (
    "---\n"
    "type: pantry\n"
    "updated: {date}\n"
    "tags: [grocery, pantry]\n"
    "---\n"
    "# Pantry\n\n"
    f"## {STOCK_HEADING}\n\n"
    f"## {FINISHED_HEADING}\n"
)


def _set_updated(note_text: str, date: str) -> str:
    if re.search(r"^updated:.*$", note_text, flags=re.MULTILINE):
        return re.sub(r"^updated:.*$", f"updated: {date}", note_text, count=1, flags=re.MULTILINE)
    return note_text


def _split_sections(text: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """Return (preamble, [(heading, body_lines), …]) split on '## ' headings."""
    lines = text.split("\n")
    first = next((i for i, l in enumerate(lines) if l.startswith("## ")), len(lines))
    preamble = "\n".join(lines[:first]).rstrip()
    sections: list[tuple[str, list[str]]] = []
    i = first
    while i < len(lines):
        head, body, j = lines[i][3:].strip(), [], i + 1
        while j < len(lines) and not lines[j].startswith("## "):
            body.append(lines[j])
            j += 1
        sections.append((head, [b for b in body]))
        i = j
    return preamble, sections


def update_pantry_file(
    purchases: list[dict], path: Path = PANTRY_PATH, today: dt.date | None = None
) -> dict:
    """Apply checkboxes + purchases to Pantry.md and re-render. Pure I/O wrapper.

    Returns {"stock", "finished", "low", "out"} (lists of Item) for the caller's
    shopping-list / reminder logic. Call with purchases=[] to just process any
    boxes you ticked on your phone.
    """
    today = today or dt.date.today()
    iso = today.isoformat()
    path = Path(path)
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = _EMPTY_PANTRY.format(date=iso)

    stock, finished = reconcile(parse_stock(text), parse_finished(text), purchases, iso)
    for it in stock:  # corrections can drive qty below zero — floor at out-of-stock
        it.qty = max(0.0, it.qty)
    low, out = low_and_out(stock)

    # Rebuild in a canonical order: Stock, Finished, then any other sections
    # (e.g. 🏪 By Store) preserved as-is. Self-heals a jumbled section order.
    preamble, sections = _split_sections(text)
    managed = {STOCK_HEADING, FINISHED_HEADING, _LEGACY_LOW_HEADING}
    others = [(h, b) for h, b in sections if h not in managed]

    parts = [preamble, ""]
    parts += [f"## {STOCK_HEADING}", "", *render_stock(stock), ""]
    parts += [f"## {FINISHED_HEADING}", "", *render_finished(finished), ""]
    for head, body in others:
        parts += [f"## {head}", "\n".join(body).strip(), ""]
    text = _set_updated("\n".join(parts), iso)

    path.write_text(text, encoding="utf-8")
    return {"stock": stock, "finished": finished, "low": low, "out": out}
