# grocery-receipts

Scan **any** receipt on your iPhone → it classifies the expense (groceries,
dining, rent, …), updates an Obsidian **pantry** for groceries, builds a
**shopping list**, and tracks **all spending** in monthly expense reports. Re-scans
are de-duplicated (one PDF, corrected numbers — never double-counted), and
poorly-read receipts are held for a quick human review. All on-device: **Apple
Vision** OCR + **Ollama `gemma3:12b`**. No cloud OCR, no model downloads.

## How it flows

```
iPhone scan ──iCloud──▶ Receipts/Inbox/*.pdf|png|jpg   (launchd watches the folder)
        │
   ocr.py (Apple Vision) ──▶ extract.py (gemma3 → store/date/time/type/total/items)
        │
   receipts.py  ── fingerprint (store+date+time) → de-dup, keep ONE pdf ──▶ .receipts.jsonl  (source of truth)
        │                                                                         │
   poor ink? → Groceries/Review/<note>.md (you fix → status: ready)         (derived each run)
        │                                                          ┌──────────────┼───────────────┐
   groceries → pantry.py (Pantry.md qty±, By-Store table)    expenses.py     shopping.py     reminders_out.py
                                                          Finance/Expenses/  Shopping List.md  Apple Reminders
                                                          YYYY-MM.md         + 🔮 2-wk preview  + daily note 🛒
                                          filed → Receipts/<Category>/
```

## Run it

```bash
uv sync                          # one-time: install deps
uv run python main.py            # drain the Inbox + review
uv run python main.py path.jpg   # process a single receipt + review
uv run python main.py --review   # review only (finalize edits, refresh lists)
uv run python main.py --watch    # poll the Inbox every 30s
uv run python reindex.py         # rebuild index + pantry + reports from archived PDFs
uv run pytest                    # tests
```

The defaults target the `pbrain` iCloud vault. Override anything via
`config.toml` (copy `config.example.toml`) or env vars — see `config.py`.

## Capture (iPhone → Inbox)

Scan **any** receipt — groceries, gas, restaurants, anything — into
`iCloud Drive/Obsidian/pbrain/Receipts/Inbox/` via **Files app → ⋯ → Scan
Documents**, or a one-tap **"Scan Receipt" Shortcut** (Scan Document → Set Name to
a timestamp → Save File to that folder, *Ask Where to Save = off*). The document
scanner deskews/de-glares, which lifts OCR accuracy. **PDF, PNG, and JPEG all
work.** Each receipt is classified and filed under `Receipts/<Category>/`
(Groceries, Car, Dining, …). The classifier prefers common categories but will
**invent a new one** (and create its folder + expense line) when nothing fits.

## Automate (folder-watch)

```bash
cp com.pbairol.grocery-receipts.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.pbairol.grocery-receipts.plist
```

Now any receipt dropped into the Inbox is processed within seconds. Logs →
`watcher.log`.

## Google Sheets (optional, off until configured)

1. Google Cloud console → enable the **Sheets API** → OAuth **Desktop** client →
   save as `credentials.json` here.
2. `uv run python google_auth.py` (browser consent once → `token.json`).
3. Put the spreadsheet ID + tab in `config.toml`:
   ```toml
   [sheets]
   spreadsheet_id = "<from the sheet URL>"
   ledger_tab = "Groceries"
   ```
   Until set, the Sheets step no-ops and the rest of the pipeline still runs.

## The pantry file

`Groceries/Pantry.md`, phone-editable in Obsidian. Receipts bump `qty`; you lower
it as you use things. An item alerts when `qty <= low`:

```
## 🥫 Stock
- Milk — qty 1 / low 1     # buffered staple: reorder at 1
- Eggs — qty 12 / low 4
- Rice — qty 2 / low 0     # default: only alerts when fully out
```

New items default to `low 0` (alert only when out); raise `low` for staples. Tick
a box to mark something **finished** — it moves to `## ✅ Finished` and onto the
shopping list. Each line records its store and last-bought date.

## Reviewing a poorly-read receipt

If the ink is too faint to read a price (item sums don't match the printed
total), the receipt is held in `Groceries/Review/<store date>.md` instead of
committing wrong numbers. Open it, fix the rows, change `status: needs-review` →
`status: ready` in the frontmatter, and the next run finalizes it into the pantry
and expenses.

## All expenses

Every receipt is classified (`groceries · dining · rent · utilities · …`).
`Finance/Expenses/YYYY-MM.md` is **rebuilt from the receipt index each run** — so
totals are always de-duplicated — with a per-type breakdown, a 🛒 Groceries
subtotal + category detail, and a receipts table. Only grocery receipts touch the
pantry.

## How dedup works

Each receipt's identity is `store + date + time` (falling back to an item/price
signature). Re-uploading or re-scanning the same receipt resolves to the same id,
so the pantry is corrected by the *delta* and **one PDF** is kept — never
double-counted. The index lives at `Groceries/.receipts.jsonl` (hidden) and is the
source of truth; `reindex.py` rebuilds everything from the archived PDFs.

## Notes

- Low-stock / shopping items write to their own `## 🛒 Groceries` daily-note
  section, so they never collide with daily-lookback's `## 🔔 Reminders`.
- The journal scan ignores money/admin terms (rent, bank, credit card…) so a
  finance-heavy journal doesn't pollute the grocery list.
