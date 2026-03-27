from __future__ import annotations

from typing import Any, Awaitable, Callable


def prompt_cfg(
    sys_kv: Any,
    *,
    sys_kv_bool: Callable[[Any, str, bool], bool],
    safe_int: Callable[[Any, int], int],
) -> dict[str, Any]:
    enabled = sys_kv_bool(sys_kv, "memo.prompt.enabled", True)
    require_subject = sys_kv_bool(sys_kv, "memo.prompt.require_subject", True)
    require_group = sys_kv_bool(sys_kv, "memo.prompt.require_group", True)
    require_details = sys_kv_bool(sys_kv, "memo.prompt.require_details", True)
    min_chars = safe_int(sys_kv.get("memo.prompt.min_chars") if isinstance(sys_kv, dict) else None, 30)
    min_chars = max(0, min(500, int(min_chars)))
    return {
        "enabled": bool(enabled),
        "require_subject": bool(require_subject),
        "require_group": bool(require_group),
        "require_details": bool(require_details),
        "min_chars": min_chars,
    }


def needs_enrich(*, memo: str, subject: str, group: str, cfg: dict[str, Any]) -> dict[str, bool]:
    m = str(memo or "").strip()
    s = str(subject or "").strip()
    g = str(group or "").strip()
    need_subject = bool(cfg.get("require_subject")) and not s
    need_group = bool(cfg.get("require_group")) and not g
    need_details = bool(cfg.get("require_details")) and (len(m) < int(cfg.get("min_chars") or 0))
    return {"subject": need_subject, "group": need_group, "details": need_details}


async def enrich_prompt(
    ws: Any,
    *,
    ws_send_json: Callable[[Any, dict[str, Any]], Awaitable[None]],
    live_say: Callable[[Any, str], Awaitable[None]],
    instance_id: str,
) -> None:
    pending = getattr(ws.state, "pending_memo_enrich", None)
    if not isinstance(pending, dict):
        return
    need = pending.get("need") if isinstance(pending.get("need"), dict) else {}
    lang = str(getattr(ws.state, "user_lang", "") or "").strip().lower()

    prompt = ""
    if need.get("subject"):
        prompt = "หัวข้อเมโมคืออะไร?" if lang.startswith("th") else "What is the memo subject/title?"
    elif need.get("group"):
        prompt = (
            "เมโมนี้อยู่กลุ่มไหน? (เช่น ops/work/personal)"
            if lang.startswith("th")
            else "Which group/category is this memo? (e.g. ops/work/personal)"
        )
    elif need.get("details"):
        prompt = "เพิ่มรายละเอียดอีกนิดได้ไหม?" if lang.startswith("th") else "Can you add a bit more detail?"
    if not prompt:
        return

    try:
        await ws_send_json(ws, {"type": "text", "text": prompt, "instance_id": instance_id})
    except Exception:
        pass
    try:
        await live_say(ws, prompt)
    except Exception:
        pass


async def handle_followup(
    ws: Any,
    text: str,
    *,
    sys_kv_bool: Callable[[Any, str, bool], bool],
    memo_sheet_cfg_from_sys_kv: Callable[[dict[str, Any] | None], tuple[str, str]],
    sheet_name_to_a1: Callable[[str, str], str],
    sheet_get_header_row: Callable[..., Awaitable[list[Any]]],
    idx_from_header: Callable[[list[Any]], dict[str, int]],
    memo_ensure_header: Callable[..., Awaitable[None]],
    pick_sheets_tool_name: Callable[[str, str], str],
    mcp_tools_call: Callable[[str, dict[str, Any]], Awaitable[Any]],
    ws_send_json: Callable[[Any, dict[str, Any]], Awaitable[None]],
    live_say: Callable[[Any, str], Awaitable[None]],
    instance_id: str,
    now_dt_utc: Callable[[], str],
) -> bool:
    pending = getattr(ws.state, "pending_memo_enrich", None)
    if not isinstance(pending, dict):
        return False
    raw = str(text or "").strip()
    if not raw:
        return True

    need = pending.get("need") if isinstance(pending.get("need"), dict) else {}
    if need.get("subject"):
        pending["subject"] = raw
        need["subject"] = False
        pending["need"] = need
        await enrich_prompt(ws, ws_send_json=ws_send_json, live_say=live_say, instance_id=instance_id)
        return True
    if need.get("group"):
        pending["group"] = raw
        need["group"] = False
        pending["need"] = need
        await enrich_prompt(ws, ws_send_json=ws_send_json, live_say=live_say, instance_id=instance_id)
        return True
    if need.get("details"):
        pending["details"] = raw
        need["details"] = False
        pending["need"] = need

    if need.get("subject") or need.get("group") or need.get("details"):
        await enrich_prompt(ws, ws_send_json=ws_send_json, live_say=live_say, instance_id=instance_id)
        return True

    sys_kv = getattr(ws.state, "sys_kv", None)
    if not sys_kv_bool(sys_kv, "memo.enabled", False):
        return True

    spreadsheet_id, sheet_name = memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
    if not spreadsheet_id or not sheet_name:
        return True

    memo_base = str(pending.get("memo") or "").strip()
    subject = str(pending.get("subject") or "").strip()
    group = str(pending.get("group") or "").strip()
    details = str(pending.get("details") or "").strip()
    memo_final = memo_base
    if details:
        memo_final = (memo_final.rstrip() + "\n\nDetails: " + details).strip()

    sheet_a1 = sheet_name_to_a1(sheet_name, "memo")
    now_dt = now_dt_utc()

    header = []
    idx: dict[str, int] = {}
    try:
        header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
        idx = idx_from_header(header)
    except Exception:
        idx = {}
    if not idx:
        try:
            await memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1)
        except Exception:
            pass
        try:
            header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
            idx = idx_from_header(header)
        except Exception:
            idx = {}

    def _set(row: list[Any], col: str, value: Any) -> None:
        try:
            j = idx.get(str(col or "").strip().lower())
            if j is None:
                return
            while len(row) <= j:
                row.append("")
            row[j] = value
        except Exception:
            return

    def _as_bool_cell(v: Any) -> str:
        s = str(v or "").strip().lower()
        if s in {"true", "t", "1", "yes", "y", "on"}:
            return "TRUE"
        if s in {"false", "f", "0", "no", "n", "off"}:
            return "FALSE"
        return "TRUE" if bool(v) else "FALSE"

    # Canonical fixed-width row so Sheets "Table" formatting can't shift columns.
    # Note: memo_enrich followup doesn't allocate an id here; keep id blank.
    row_out: list[Any] = [
        "",  # id
        now_dt,
        _as_bool_cell(True),
        "new",
        group,
        subject,
        memo_final,
        "",
        now_dt,
        now_dt,
    ]

    tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
    try:
        await mcp_tools_call(
            tool_append,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_a1}!A:J",
                "values": [row_out],
                "value_input_option": "USER_ENTERED",
                "insert_data_option": "INSERT_ROWS",
            },
        )
    except Exception:
        pass

    try:
        ws.state.pending_memo_enrich = None
        ws.state.active_agent_id = None
        ws.state.active_agent_until_ts = 0
    except Exception:
        pass

    try:
        await ws_send_json(ws, {"type": "text", "text": "Memo updated.", "instance_id": instance_id})
    except Exception:
        pass
    return True
