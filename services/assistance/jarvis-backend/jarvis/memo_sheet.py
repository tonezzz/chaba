from __future__ import annotations

from typing import Any, Awaitable, Callable


async def ensure_header(
    *,
    spreadsheet_id: str,
    sheet_a1: str,
    force: bool,
    sheet_get_header_row: Callable[..., Awaitable[list[Any]]],
    mcp_tools_call: Callable[[str, dict[str, Any]], Awaitable[Any]],
    pick_sheets_tool_name: Callable[[str, str], str],
) -> None:
    tool_update = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")

    try:
        got_header = await sheet_get_header_row(
            spreadsheet_id=spreadsheet_id,
            sheet_a1=sheet_a1,
            max_cols="J",
        )
        if got_header and any(str(x or "").strip() for x in got_header) and not force:
            lowered = [str(x or "").strip().lower() for x in got_header if str(x or "").strip()]
            has_dupes = len(set(lowered)) != len(lowered)
            required = {
                "id",
                "active",
                "group",
                "subject",
                "memo",
                "status",
                "result",
                "date_time",
                "_created",
                "_updated",
            }
            missing_required = any(k not in set(lowered) for k in required)
            if not has_dupes and not missing_required:
                return
    except Exception:
        pass

    header = [
        "id",
        "active",
        "group",
        "memo",
        "status",
        "subject",
        "result",
        "date_time",
        "_created",
        "_updated",
    ]

    res_u = await mcp_tools_call(
        tool_update,
        {
            "spreadsheet_id": spreadsheet_id,
            "range": f"{sheet_a1}!A1:J1",
            "values": [header],
            "value_input_option": "RAW",
        },
    )

    try:
        await mcp_tools_call(
            tool_update,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_a1}!K1:K1",
                "values": [[""]],
                "value_input_option": "RAW",
            },
        )
    except Exception:
        pass

    try:
        await mcp_tools_call(
            tool_update,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_a1}!L1:Z1",
                "values": [[""] * 15],
                "value_input_option": "RAW",
            },
        )
    except Exception:
        pass

    try:
        got_header2 = await sheet_get_header_row(
            spreadsheet_id=spreadsheet_id,
            sheet_a1=sheet_a1,
            max_cols="J",
        )
        if got_header2 and any(str(x or "").strip() for x in got_header2):
            return
    except Exception:
        pass

    raise RuntimeError(f"memo_header_ensure_failed: values_update={res_u}")
