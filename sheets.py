"""sheets.py — append grocery line-items to the Google Sheets ledger.

Each item becomes one row: [date, store, item, category, qty, price]. The sheet
itself owns running totals (a SUM column / pivot), which keeps this code a dumb,
append-only writer. Disabled (no-op) until a spreadsheet_id is configured.
"""
from __future__ import annotations

from config import SHEETS_LEDGER_TAB, SHEETS_SPREADSHEET_ID

HEADER = ["Date", "Store", "Item", "Category", "Qty", "Price"]


def is_enabled() -> bool:
    return bool(SHEETS_SPREADSHEET_ID)


def item_to_row(item: dict) -> list:
    return [
        item.get("date", ""),
        item.get("store", ""),
        item.get("item", ""),
        item.get("category", ""),
        item.get("qty", ""),
        item.get("price") if item.get("price") is not None else "",
    ]


def _ensure_header(client) -> None:
    """Write the header row once if the first row is empty."""
    rng = f"{SHEETS_LEDGER_TAB}!A1:F1"
    resp = (
        client.spreadsheets()
        .values()
        .get(spreadsheetId=SHEETS_SPREADSHEET_ID, range=rng)
        .execute()
    )
    if not resp.get("values"):
        client.spreadsheets().values().update(
            spreadsheetId=SHEETS_SPREADSHEET_ID,
            range=rng,
            valueInputOption="RAW",
            body={"values": [HEADER]},
        ).execute()


def append_line_items(items: list[dict]) -> int:
    """Append items to the ledger tab. Returns rows written (0 if disabled)."""
    if not is_enabled() or not items:
        if not is_enabled():
            print("Sheets sink disabled (no spreadsheet_id configured) — skipping.")
        return 0

    from google_auth import sheets_client

    client = sheets_client()
    _ensure_header(client)
    rows = [item_to_row(it) for it in items]
    client.spreadsheets().values().append(
        spreadsheetId=SHEETS_SPREADSHEET_ID,
        range=f"{SHEETS_LEDGER_TAB}!A:F",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()
    return len(rows)
