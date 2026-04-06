"""
Unified Sheets interface for Jarvis.
Routes to google-drive-mcp if USE_GOOGLE_DRIVE_MCP=true; otherwise uses legacy client.
"""

import os
import logging
from typing import Any, List, Dict

from . import google_drive_mcp as gdrive_mcp
from . import sheets_legacy as legacy

logger = logging.getLogger(__name__)

USE_GOOGLE_DRIVE_MCP = str(os.getenv("USE_GOOGLE_DRIVE_MCP", "false")).strip().lower() == "true"


def get_values(spreadsheet_id: str, range_: str) -> List[List[Any]]:
    """Read a range from a sheet."""
    if USE_GOOGLE_DRIVE_MCP:
        return gdrive_mcp.get_values(spreadsheet_id, range_)
    else:
        return legacy.get_values(spreadsheet_id, range_)


def append_rows(spreadsheet_id: str, range_: str, rows: List[List[Any]], value_input_option: str = "RAW") -> Dict[str, Any]:
    """Append rows to a sheet."""
    if USE_GOOGLE_DRIVE_MCP:
        return gdrive_mcp.append_rows(spreadsheet_id, range_, rows, value_input_option)
    else:
        return legacy.append_rows(spreadsheet_id, range_, rows, value_input_option)


def update_values(spreadsheet_id: str, range_: str, values: List[List[Any]], value_input_option: str = "RAW") -> Dict[str, Any]:
    """Update a range in a sheet."""
    if USE_GOOGLE_DRIVE_MCP:
        return gdrive_mcp.update_values(spreadsheet_id, range_, values, value_input_option)
    else:
        return legacy.update_values(spreadsheet_id, range_, values, value_input_option)


def upsert_kv(spreadsheet_id: str, sheet_name: str, key: str, value: str) -> Dict[str, Any]:
    """Upsert a key-value pair in column A/B."""
    if USE_GOOGLE_DRIVE_MCP:
        return gdrive_mcp.upsert_kv(spreadsheet_id, sheet_name, key, value)
    else:
        return legacy.upsert_kv(spreadsheet_id, sheet_name, key, value)


def append_log(spreadsheet_id: str, sheet_name: str, rows: List[List[Any]]) -> Dict[str, Any]:
    """Append log rows."""
    if USE_GOOGLE_DRIVE_MCP:
        return gdrive_mcp.append_log(spreadsheet_id, sheet_name, rows)
    else:
        return legacy.append_rows(spreadsheet_id, f"'{sheet_name}'!A1", rows)


def read_memo_rows(spreadsheet_id: str, sheet_name: str) -> List[List[Any]]:
    """Read memo rows."""
    if USE_GOOGLE_DRIVE_MCP:
        return gdrive_mcp.read_memo_rows(spreadsheet_id, sheet_name)
    else:
        return legacy.get_values(spreadsheet_id, f"'{sheet_name}'!A:Z")


def write_memo_rows(spreadsheet_id: str, sheet_name: str, rows: List[List[Any]], start_row: int = 2) -> Dict[str, Any]:
    """Write memo rows."""
    if USE_GOOGLE_DRIVE_MCP:
        return gdrive_mcp.write_memo_rows(spreadsheet_id, sheet_name, rows, start_row)
    else:
        # Legacy: clear and write via update
        num_rows = len(rows)
        num_cols = max(len(r) for r in rows) if rows else 1
        range_write = f"'{sheet_name}'!R{start_row}C1:R{start_row + num_rows - 1}C{num_cols}"
        return legacy.update_values(spreadsheet_id, range_write, rows)


def test_connectivity() -> bool:
    """Test Sheets connectivity via the selected backend."""
    if USE_GOOGLE_DRIVE_MCP:
        return gdrive_mcp.test_connectivity()
    else:
        try:
            legacy._get_legacy_client()  # noqa: F841
            return True
        except Exception:
            return False
