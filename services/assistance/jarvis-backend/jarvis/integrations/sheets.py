"""
Unified Sheets interface for Jarvis.
Routes to google-drive-mcp via MCP-over-HTTP (streamable HTTP).
"""

import os
import logging
import json
from typing import Any, List, Dict
import httpx

logger = logging.getLogger(__name__)

# Force MCP mode; legacy removed
GOOGLE_DRIVE_MCP_BASE_URL = os.getenv("GOOGLE_DRIVE_MCP_BASE_URL", "http://google-drive-mcp:8032")

# Session state for MCP-over-HTTP
_mcp_session_id: str | None = None

# Default timeout for MCP calls (seconds)
MCP_TIMEOUT = 15


class SheetsError(Exception):
    """Raised when Sheets operation fails."""


def _extract_first_sse_json(text: str) -> Dict[str, Any]:
    """Parse the first JSON object from an SSE response body."""
    # SSE format is lines like: "event: message" and "data: {...json...}"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:") :].strip()
        if not data_str:
            continue
        return json.loads(data_str)
    raise SheetsError("Invalid MCP SSE response: missing data")


def _ensure_mcp_session():
    """Initialize google-drive-mcp streamable HTTP session if not already done."""
    global _mcp_session_id
    if _mcp_session_id:
        return
    url = f"{GOOGLE_DRIVE_MCP_BASE_URL}/mcp"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "jarvis-backend", "version": "1.0.0"}
        }
    }
    try:
        with httpx.Client(timeout=MCP_TIMEOUT) as client:
            resp = client.post(
                url,
                json=payload,
                headers={"accept": "application/json, text/event-stream"},
            )
            resp.raise_for_status()
            # Session id is provided as a response header.
            session_id = resp.headers.get("mcp-session-id")
            if not session_id:
                raise SheetsError("MCP initialize missing mcp-session-id header")
            _mcp_session_id = session_id

            # Best-effort: verify body is valid SSE w/ JSON payload
            _ = _extract_first_sse_json(resp.text)
    except Exception as e:
        logger.error(f"Failed to initialize MCP session: {e}")
        raise SheetsError("MCP session initialization failed")


def _mcp_call(tool: str, arguments: Dict[str, Any]) -> Any:
    """
    Call a Sheets tool via google-drive-mcp MCP-over-HTTP.
    Sends MCP JSON-RPC call to /mcp endpoint.
    """
    _ensure_mcp_session()
    url = f"{GOOGLE_DRIVE_MCP_BASE_URL}/mcp"
    headers = {
        "accept": "application/json, text/event-stream",
        "mcp-session-id": str(_mcp_session_id),
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": arguments
        }
    }
    try:
        with httpx.Client(timeout=MCP_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            # google-drive-mcp returns SSE
            data = _extract_first_sse_json(resp.text)
            if "error" in data:
                raise SheetsError(data["error"].get("message", "Unknown MCP error"))
            if "result" in data:
                return data["result"]
            return data
    except httpx.HTTPStatusError as e:
        logger.error(f"Sheets MCP HTTP error calling {tool}: {e}")
        raise SheetsError(f"HTTP error {e.response.status_code}")
    except Exception as e:
        logger.error(f"Sheets MCP call failed for {tool}: {e}")
        raise SheetsError(str(e))


# ----------------------------------------------------------------------
# Adapter functions mirroring the legacy Sheets client interface
# ----------------------------------------------------------------------
def get_values(spreadsheet_id: str, range_: str) -> List[List[Any]]:
    """Read a range from a sheet via MCP."""
    result = _mcp_call("getGoogleSheetContent", {"spreadsheetId": spreadsheet_id, "range": range_})
    return result.get("values", [])


def append_rows(spreadsheet_id: str, range_: str, rows: List[List[Any]], value_input_option: str = "RAW") -> Dict[str, Any]:
    """Append rows to a sheet via MCP."""
    result = _mcp_call("appendSpreadsheetRows", {
        "spreadsheetId": spreadsheet_id,
        "range": range_,
        "values": rows,
        "valueInputOption": value_input_option,
    })
    return result


def update_values(spreadsheet_id: str, range_: str, values: List[List[Any]], value_input_option: str = "RAW") -> Dict[str, Any]:
    """Update a range in a sheet via MCP."""
    result = _mcp_call("updateGoogleSheet", {
        "spreadsheetId": spreadsheet_id,
        "range": range_,
        "data": values,
        "valueInputOption": value_input_option,
    })
    return result


def upsert_kv(spreadsheet_id: str, sheet_name: str, key: str, value: str) -> Dict[str, Any]:
    """Upsert a key-value pair in column A/B via MCP."""
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
    """Append log rows via MCP."""
    return append_rows(spreadsheet_id, f"'{sheet_name}'!A1", rows)


def read_memo_rows(spreadsheet_id: str, sheet_name: str) -> List[List[Any]]:
    """Read memo rows via MCP."""
    return get_values(spreadsheet_id, f"'{sheet_name}'!A:Z")


def write_memo_rows(spreadsheet_id: str, sheet_name: str, rows: List[List[Any]], start_row: int = 2) -> Dict[str, Any]:
    """Write memo rows via MCP."""
    num_rows = len(rows)
    num_cols = max(len(r) for r in rows) if rows else 1
    range_write = f"'{sheet_name}'!R{start_row}C1:R{start_row + num_rows - 1}C{num_cols}"
    return update_values(spreadsheet_id, range_write, rows)


def test_connectivity() -> bool:
    """Test Sheets connectivity via MCP."""
    try:
        # Use a dummy sheet ID; any 404/403 means connectivity is fine
        get_values("dummy_spreadsheet_id", "Sheet1!A1:A1")
    except SheetsError as e:
        if "404" in str(e) or "403" in str(e) or "Not found" in str(e):
            return True
        logger.error(f"Sheets MCP connectivity test failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Sheets MCP connectivity test error: {e}")
        return False
    return True
