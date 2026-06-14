"""config.py — paths and runtime settings (config.toml + env overrides).

Mirrors the pattern in ../daily-lookback/config.py: a committed
config.example.toml documents every key; the real config.toml (gitignored)
and environment variables override the hardcoded defaults below.
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.toml"

_VAULT = "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/pbrain"


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def _load_toml() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        import tomllib
    except ImportError:
        return {}
    with CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


_cfg = _load_toml()
_vault = _cfg.get("vault", {})
_ollama = _cfg.get("ollama", {})
_pantry = _cfg.get("pantry", {})
_sheets = _cfg.get("sheets", {})
_finance = _cfg.get("finance", {})

# --- Vault paths --------------------------------------------------------------
# All receipts (any expense type) live under one Receipts/ area; only the
# grocery-specific pantry/shopping notes stay in Groceries/.
_RECEIPTS = f"{_VAULT}/Receipts"
_DEFAULT_INBOX = f"{_RECEIPTS}/Inbox"
# Receipts file straight into a per-category folder under here (Receipts/Car, …).
_DEFAULT_ARCHIVE = _RECEIPTS
_DEFAULT_REVIEW = f"{_RECEIPTS}/Review"
_DEFAULT_INDEX = f"{_RECEIPTS}/.receipts.jsonl"
_DEFAULT_PANTRY = f"{_VAULT}/Groceries/Pantry.md"
_DEFAULT_SPENDING = f"{_VAULT}/Groceries/Spending"
_DEFAULT_SHOPPING = f"{_VAULT}/Groceries/Shopping List.md"
_DEFAULT_DAILY = f"{_VAULT}/Daily"
_DEFAULT_TEMPLATE = f"{_VAULT}/Templates/Daily Note.md"
_DEFAULT_BALANCE_SHEETS = f"{_VAULT}/Finance/Balance Sheets"
_DEFAULT_EXPENSES = f"{_VAULT}/Finance/Expenses"

INBOX_DIR: Path = _expand(
    os.environ.get("GROCERY_INBOX_DIR", _vault.get("inbox_dir", _DEFAULT_INBOX))
)
PANTRY_PATH: Path = _expand(
    os.environ.get("GROCERY_PANTRY_PATH", _vault.get("pantry_path", _DEFAULT_PANTRY))
)
ARCHIVE_DIR: Path = _expand(
    os.environ.get("GROCERY_ARCHIVE_DIR", _vault.get("archive_dir", _DEFAULT_ARCHIVE))
)
SPENDING_DIR: Path = _expand(
    os.environ.get("GROCERY_SPENDING_DIR", _vault.get("spending_dir", _DEFAULT_SPENDING))
)
SHOPPING_LIST_PATH: Path = _expand(
    os.environ.get("GROCERY_SHOPPING_LIST_PATH", _vault.get("shopping_list_path", _DEFAULT_SHOPPING))
)
DAILY_DIR: Path = _expand(
    os.environ.get("DAILY_VAULT_DIR", _vault.get("daily_dir", _DEFAULT_DAILY))
)
TEMPLATE_PATH: Path = _expand(
    os.environ.get("DAILY_TEMPLATE_PATH", _vault.get("template_path", _DEFAULT_TEMPLATE))
)
BALANCE_SHEETS_DIR: Path = _expand(
    os.environ.get(
        "GROCERY_BALANCE_SHEETS_DIR",
        _finance.get("balance_sheets_dir", _DEFAULT_BALANCE_SHEETS),
    )
)
EXPENSES_DIR: Path = _expand(
    os.environ.get("GROCERY_EXPENSES_DIR", _finance.get("expenses_dir", _DEFAULT_EXPENSES))
)
REVIEW_DIR: Path = _expand(
    os.environ.get("GROCERY_REVIEW_DIR", _vault.get("review_dir", _DEFAULT_REVIEW))
)
RECEIPTS_INDEX: Path = _expand(
    os.environ.get("GROCERY_RECEIPTS_INDEX", _vault.get("receipts_index", _DEFAULT_INDEX))
)

# --- Expense types ------------------------------------------------------------
# The receipt classifier picks exactly one. "groceries" is the only type that
# updates the pantry; all types are tracked in the monthly expense report.
GROCERY_TYPE: str = "groceries"
# Preferred categories (examples for the classifier) — NOT a hard list. The AI
# may invent a new short category when a receipt fits none of these, and a folder
# + expense line are created for it automatically.
EXPENSE_TYPES: list[str] = _cfg.get("expenses", {}).get(
    "types",
    ["groceries", "dining", "car", "rent", "utilities", "shopping",
     "health", "entertainment", "travel", "other"],
)

# Emoji per category for the expense report (unknown categories get the default).
EXPENSE_EMOJI: dict = {
    "groceries": "🛒", "dining": "🍽️", "car": "⛽", "rent": "🏠",
    "utilities": "💡", "shopping": "🛍️", "health": "💊", "entertainment": "🎬",
    "travel": "✈️", "transport": "🚌", "coffee": "☕", "pets": "🐾",
    "subscriptions": "🔁", "other": "🧾",
}
EXPENSE_EMOJI_DEFAULT: str = "🧾"
# A receipt is held for human review if parsed item prices miss the printed
# total by more than this fraction (poor-ink OCR), or any item price is unreadable.
REVIEW_TOTAL_TOLERANCE: float = float(
    os.environ.get("GROCERY_REVIEW_TOLERANCE", _cfg.get("expenses", {}).get("review_tolerance", 0.10))
)

# --- Reminders ----------------------------------------------------------------
# Name of the Apple Reminders list low-stock items are pushed to.
REMINDERS_LIST: str = os.environ.get(
    "GROCERY_REMINDERS_LIST", _vault.get("reminders_list", "Groceries")
)

# --- Pantry behaviour ---------------------------------------------------------
# Default reorder threshold for newly-seen items (flag when qty <= this). 0 means
# "only alert when fully out"; raise `low` per-item in Pantry.md for staples you
# want a buffer on (e.g. `- Eggs — qty 12 / low 4`). Avoids flagging everything
# the first time a fresh pantry is seeded from a single receipt.
LOW_THRESHOLD: int = int(
    os.environ.get("GROCERY_LOW_THRESHOLD", _pantry.get("low_threshold", 0))
)

# How many items in the ✅ Finished section before we actively nudge a shop run.
FINISHED_THRESHOLD: int = int(
    os.environ.get("GROCERY_FINISHED_THRESHOLD", _pantry.get("finished_threshold", 4))
)
# "Been a while since shopping": if the last receipt is >= this many days old,
# items with only one left are added to the shopping list. ~1-2 weeks.
STALE_DAYS: int = int(
    os.environ.get("GROCERY_STALE_DAYS", _pantry.get("stale_days", 10))
)
# How many recent daily notes to scan for "running out of X" mentions.
JOURNAL_SCAN_DAYS: int = int(
    os.environ.get("GROCERY_JOURNAL_SCAN_DAYS", _pantry.get("journal_scan_days", 3))
)
# Look-ahead window (days) for the shopping list's "coming up" preview.
PREVIEW_DAYS: int = int(
    os.environ.get("GROCERY_PREVIEW_DAYS", _pantry.get("preview_days", 14))
)

# --- Ollama -------------------------------------------------------------------
DEFAULT_MODEL: str = os.environ.get("OLLAMA_MODEL", _ollama.get("model", "gemma3:12b"))
OLLAMA_URL: str = os.environ.get(
    "OLLAMA_URL", _ollama.get("url", "http://localhost:11434/api/generate")
)
OLLAMA_TAGS_URL: str = os.environ.get(
    "OLLAMA_TAGS_URL", _ollama.get("tags_url", "http://localhost:11434/api/tags")
)
OLLAMA_MAX_RETRIES: int = int(
    os.environ.get("OLLAMA_MAX_RETRIES", _ollama.get("max_retries", 3))
)
OLLAMA_NUM_CTX: int = int(
    os.environ.get("OLLAMA_NUM_CTX", _ollama.get("num_ctx", 8192))
)
# How long to wait for a managed `ollama serve` to become ready before giving up.
OLLAMA_READY_TIMEOUT: int = int(
    os.environ.get("OLLAMA_READY_TIMEOUT", _ollama.get("ready_timeout", 120))
)

# --- Google Sheets ------------------------------------------------------------
# Spreadsheet ID + tab the line-item ledger is appended to. Empty = Sheets sink
# disabled (the rest of the pipeline still runs). Set during build.
SHEETS_SPREADSHEET_ID: str = os.environ.get(
    "GROCERY_SPREADSHEET_ID", _sheets.get("spreadsheet_id", "")
)
SHEETS_LEDGER_TAB: str = os.environ.get(
    "GROCERY_LEDGER_TAB", _sheets.get("ledger_tab", "Groceries")
)

# Canonical spend categories — the model is constrained to these for clean
# roll-ups. Override with [pantry] categories in config.toml if desired.
CATEGORIES: list[str] = _pantry.get(
    "categories",
    [
        "Produce", "Dairy", "Meat & Seafood", "Bakery", "Pantry",
        "Frozen", "Beverages", "Snacks", "Household", "Personal Care", "Other",
    ],
)
