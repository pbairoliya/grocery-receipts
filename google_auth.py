"""google_auth.py — one-time OAuth for Google Sheets, then silent refresh.

Adapted from ../daily-lookback/google_auth.py. This project needs WRITE access
to Sheets, so it uses its OWN credentials.json/token.json (a different scope set
would invalidate daily-lookback's read-only token if shared).

Setup (one-time):
  1. Google Cloud console → enable Google Sheets API.
  2. OAuth client ID → Desktop app → download JSON as `credentials.json` here.
  3. Run:  uv run python google_auth.py     (opens browser, click Allow)
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent
CREDS = HERE / "credentials.json"
TOKEN = HERE / "token.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = (
        Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        if TOKEN.exists()
        else None
    )
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not CREDS.exists():
            raise SystemExit(
                f"Missing {CREDS.name}. Download an OAuth 'Desktop app' client from "
                "Google Cloud console (with the Sheets API enabled) and save it here."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
        creds = flow.run_local_server(port=0)
    TOKEN.write_text(creds.to_json())
    return creds


def sheets_client():
    from googleapiclient.discovery import build

    return build("sheets", "v4", credentials=_creds(), cache_discovery=False)


def is_configured() -> bool:
    return CREDS.exists()


if __name__ == "__main__":
    sheets_client()
    print("Authenticated. token.json written — Sheets writes are now hands-free.")
