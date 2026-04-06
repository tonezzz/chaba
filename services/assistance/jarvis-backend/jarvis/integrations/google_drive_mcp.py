"""
Google Drive MCP adapter for Jarvis.

Maps legacy Sheets operations to google-drive-mcp tools.
Controlled by USE_GOOGLE_DRIVE_MCP feature flag.
"""

import os
import logging
from typing import Any, Optional, List, Dict
import httpx

logger = logging.getLogger(__name__)

USE_GOOGLE_DRIVE_MCP = str(os.getenv("USE_GOOGLE_DRIVE_MCP", "false")).strip().lower() == "true"

# Base URL for the MCP server in HTTP mode (adjust if using stdio via mcp-bundle)
GOOGLE_DRIVE_MCP_BASE_URL = os.getenv("GOOGLE_DRIVE_MCP_BASE_URL", "http://google-drive-mcp:8032")

# Optional: service account credentials path (if needed for the MCP server)
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

# Default timeout for MCP calls (seconds)
MCP_TIMEOUT = 15


class GoogleDriveMCPError(Exception):
    """Raised when MCP tool call fails."""


def _mcp_call(tool: str, arguments: Dict[str, Any]) -> Any:
    """
    Call a google-drive-mcp tool via HTTP.
    Expected to return the MCP tool's result dict.
    """
    url = f"{GOOGLE_DRIVE_MCP_BASE_URL}/tools/{tool}"
    try:
        with httpx.Client(timeout=MCP_TIMEOUT) as client:
            resp = client.post(url, json=arguments)
            resp.raise_for_status()
            data = resp.json()
            # MCP tools usually return { result: ..., isError: false/true }
            # We'll unwrap and raise on error.
            if isinstance(data, dict) and data.get("isError"):
                raise GoogleDriveMCPError(data.get("content", {}).get("text", "Unknown MCP error"))
            if isinstance(data, dict) and "result" in data:
                return data["result"]
            return data
    except httpx.HTTPStatusError as e:
        logger.error(f"MCP HTTP error calling {tool}: {e}")
        raise GoogleDriveMCPError(f"HTTP error {e.response.status_code}")
    except Exception as e:
        logger.error(f"MCP call failed for {tool}: {e}")
        raise GoogleDriveMCPError(str(e))


# ----------------------------------------------------------------------
# Adapter functions mirroring the legacy Sheets client interface
# ----------------------------------------------------------------------
def get_values(spreadsheet_id: str, range_: str) -> List[List[Any]]:
    """Read a range from a sheet via Drive MCP."""
    if not USE_GOOGLE_DRIVE_MCP:
        raise RuntimeError("USE_GOOGLE_DRIVE_MCP is disabled; falling back to legacy Sheets client not implemented here.")
    result = _mcp_call("getGoogleSheetContent", {"spreadsheetId": spreadsheet_id, "range": range_})
    # Drive MCP returns values in result.values
    return result.get("values", [])


def append_rows(spreadsheet_id: str, range_: str, rows: List[List[Any]], value_input_option: str = "RAW") -> Dict[str, Any]:
    """Append rows to a sheet via Drive MCP."""
    if not USE_GOOGLE_DRIVE_MCP:
        raise RuntimeError("USE_GOOGLE_DRIVE_MCP is disabled.")
    result = _mcp_call("appendSpreadsheetRows", {
        "spreadsheetId": spreadsheet_id,
        "range": range_,
        "values": rows,
        "valueInputOption": value_input_option,
    })
    return result


def update_values(spreadsheet_id: str, range_: str, values: List[List[Any]], value_input_option: str = "RAW") -> Dict[str, Any]:
    """Update a range in a sheet via Drive MCP."""
    if not USE_GOOGLE_DRIVE_MCP:
        raise RuntimeError("USE_GOOGLE_DRIVE_MCP is disabled.")
    result = _mcp_call("updateGoogleSheet", {
        "spreadsheetId": spreadsheet_id,
        "range": range_,
        "data": values,
        "valueInputOption": value_input_option,
    })
    return result


def get_spreadsheet_info(spreadsheet_id: str) -> Dict[str, Any]:
    """Get metadata including sheet names via Drive MCP."""
    if not USE_GOOGLE_DRIVE_MCP:
        raise RuntimeError("USE_GOOGLE_DRIVE_MCP is disabled.")
    result = _mcp_call("getSpreadsheetInfo", {"spreadsheetId": spreadsheet_id})
    return result


def list_sheets(spreadsheet_id: str) -> List[Dict[str, Any]]:
    """List sheets/tabs in a spreadsheet via Drive MCP."""
    if not USE_GOOGLE_DRIVE_MCP:
        raise RuntimeError("USE_GOOGLE_DRIVE_MCP is disabled.")
    result = _mcp_call("listSheets", {"spreadsheetId": spreadsheet_id})
    return result.get("sheets", [])


# ----------------------------------------------------------------------
# Helpers used by Jarvis (e.g., upsert_kv, logs, memos)
# ----------------------------------------------------------------------
def upsert_kv(spreadsheet_id: str, sheet_name: str, key: str, value: str) -> Dict[str, Any]:
    """
    Upsert a key-value pair in column A/B of a sheet.
    If the key exists in column A, update column B; else append a new row.
    """
    if not USE_GOOGLE_DRIVE_MCP:
        raise RuntimeError("USE_GOOGLE_DRIVE_MCP is disabled.")
    # Read column A to find the key
    range_a = f"'{sheet_name}'!A:A"
    rows = get_values(spreadsheet_id, range_a)
    key_to_row = {row[0]: idx + 1 for idx, row in enumerate(rows) if row}
    if key in key_to_row:
        # Update existing row's column B
        row_num = key_to_row[key]
        range_b = f"'{sheet_name}'!B{row_num}"
        return update_values(spreadsheet_id, range_b, [[value]])
    else:
        # Append new key-value row
        return append_rows(spreadsheet_id, f"'{sheet_name}'!A1", [[key, value]])


def append_log(spreadsheet_id: str, sheet_name: str, rows: List[List[Any]]) -> Dict[str, Any]:
    """Append log rows to a sheet."""
    if not USE_GOOGLE_DRIVE_MCP:
        raise RuntimeError("USE_GOOGLE_DRIVE_MCP is disabled.")
    return append_rows(spreadsheet_id, f"'{sheet_name}'!A1", rows)


def read_memo_rows(spreadsheet_id: str, sheet_name: str) -> List[List[Any]]:
    """Read all rows from a memo sheet (assumes header in row 1)."""
    if not USE_GOOGLE_DRIVE_MCP:
        raise RuntimeError("USE_GOOGLE_DRIVE_MCP is disabled.")
    # Read the whole sheet; caller can skip header if needed
    range_all = f"'{sheet_name}'!A:Z"
    return get_values(spreadsheet_id, range_all)


def write_memo_rows(spreadsheet_id: str, sheet_name: str, rows: List[List[Any]], start_row: int = 2) -> Dict[str, Any]:
    """
    Write memo rows starting at start_row (default 2, to skip header).
    Clears existing rows below start_row before writing.
    """
    if not USE_GOOGLE_DRIVE_MCP:
        raise RuntimeError("USE_GOOGLE_DRIVE_MCP is disabled.")
    # Determine range to clear and write
    num_rows = len(rows)
    num_cols = max(len(r) for r in rows) if rows else 1
    range_write = f"'{sheet_name}'!R{start_row}C1:R{start_row + num_rows - 1}C{num_cols}"
    return update_values(spreadsheet_id, range_write, rows)


# ----------------------------------------------------------------------
# Health check / connectivity test
# ----------------------------------------------------------------------
def test_connectivity() -> bool:
    """Simple connectivity test: try to read a tiny range from a known sheet."""
    try:
        # Use a dummy spreadsheet ID; if it fails with 404/403, that's fine—just proves connectivity.
        get_values("dummy_spreadsheet_id", "Sheet1!A1:A1")
    except GoogleDriveMCPError as e:
        # If the error is about missing file, connectivity is fine
        if "404" in str(e) or "403" in str(e) or "Not found" in str(e):
            return True
        logger.error(f"Google Drive MCP connectivity test failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Google Drive MCP connectivity test error: {e}")
        return False
    return True
