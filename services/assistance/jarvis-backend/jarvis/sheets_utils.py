from __future__ import annotations

import re
from typing import Any, Awaitable, Callable


def sheet_name_to_a1(sheet_name: str, default: str = "Sheet1") -> str:
    s = str(sheet_name or "").strip() or default
    if re.match(r"^[A-Za-z0-9_]+$", s):
        return s
    return "'" + s.replace("'", "''") + "'"


def idx_from_header(header: list[Any]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for i, c in enumerate(header):
        name = str(c or "").strip().lower()
        if name and name not in idx:
            idx[name] = i
    return idx


async def sheet_get_header_row(
    *,
    spreadsheet_id: str,
    sheet_a1: str,
    max_cols: str,
    mcp_tools_call: Callable[[str, dict[str, Any]], Awaitable[Any]],
    pick_sheets_tool_name: Callable[[str, str], str],
    mcp_text_json: Callable[[Any], Any],
) -> list[Any]:
    tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
    res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!A1:{max_cols}1"})
    parsed = mcp_text_json(res)
    vals = parsed.get("values") if isinstance(parsed, dict) else None
    if not isinstance(vals, list) or not vals:
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if isinstance(data, dict):
            vals = data.get("values")
    header = vals[0] if isinstance(vals, list) and vals and isinstance(vals[0], list) else []
    return list(header) if isinstance(header, list) else []
