"""
Legacy Google Sheets client wrapper for Jarvis.
Kept for comparison and fallback during migration to google-drive-mcp.
"""

import os
import logging
from typing import Any, List, Dict

logger = logging.getLogger(__name__)

# Legacy env vars (will be removed after migration)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN", "")


def _get_legacy_client():
    """Return the legacy Sheets API client if credentials are present."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError

        if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN):
            raise RuntimeError("Missing Google OAuth credentials for legacy Sheets client")

        creds = Credentials(
            token=None,
            refresh_token=GOOGLE_REFRESH_TOKEN,
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
        )
        # Refresh token to ensure valid access token
        creds.refresh(None)
        service = build("sheets", "v4", credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Failed to initialize legacy Sheets client: {e}")
        raise


def get_values(spreadsheet_id: str, range_: str) -> List[List[Any]]:
    """Legacy Sheets get_values."""
    service = _get_legacy_client()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_).execute()
    return result.get("values", [])


def append_rows(spreadsheet_id: str, range_: str, rows: List[List[Any]], value_input_option: str = "RAW") -> Dict[str, Any]:
    """Legacy Sheets append."""
    service = _get_legacy_client()
    sheet = service.spreadsheets()
    body = {"values": rows}
    result = sheet.values().append(
        spreadsheetId=spreadsheet_id,
        range=range_,
        valueInputOption=value_input_option,
        body=body,
    ).execute()
    return result


def update_values(spreadsheet_id: str, range_: str, values: List[List[Any]], value_input_option: str = "RAW") -> Dict[str, Any]:
    """Legacy Sheets update."""
    service = _get_legacy_client()
    sheet = service.spreadsheets()
    body = {"values": values}
    result = sheet.values().update(
        spreadsheetId=spreadsheet_id,
        range=range_,
        valueInputOption=value_input_option,
        body=body,
    ).execute()
    return result


def upsert_kv(spreadsheet_id: str, sheet_name: str, key: str, value: str) -> Dict[str, Any]:
    """Legacy upsert key-value in column A/B."""
    range_a = f"'{sheet_name}'!A:A"
    rows = get_values(spreadsheet_id, range_a)
    key_to_row = {row[0]: idx + 1 for idx, row in enumerate(rows) if row}
    if key in key_to_row:
        row_num = key_to_row[key]
        range_b = f"'{sheet_name}'!B{row_num}"
        return update_values(spreadsheet_id, range_b, [[value]])
    else:
        return append_rows(spreadsheet_id, f"'{sheet_name}'!A1", [[key, value]])
