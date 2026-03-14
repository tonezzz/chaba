from typing import Any, Optional, Callable, Awaitable

from fastapi import HTTPException


async def resolve_google_tasks_tasklist(
    *,
    tasklist_id: Optional[str],
    tasklist_title: Optional[str],
    mcp_tool_map: dict[str, dict[str, Any]],
    mcp_tools_call: Callable[[str, dict[str, Any]], Awaitable[Any]],
    mcp_text_json: Callable[[Any], Any],
) -> tuple[Optional[str], str]:
    chosen_tasklist_id = str(tasklist_id or "").strip() or None
    desired_title = str(tasklist_title or "").strip()
    if not desired_title:
        return chosen_tasklist_id, ""

    list_tasklists_meta = mcp_tool_map.get("google_tasks_list_tasklists") if isinstance(mcp_tool_map, dict) else None
    if not isinstance(list_tasklists_meta, dict):
        raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")
    list_tasklists_tool = str(list_tasklists_meta.get("mcp_name") or "").strip()
    if not list_tasklists_tool:
        raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")

    tl_res = await mcp_tools_call(list_tasklists_tool, {})
    tl_parsed = mcp_text_json(tl_res)
    if isinstance(tl_parsed, dict) and isinstance(tl_parsed.get("data"), dict):
        tl_parsed = tl_parsed["data"]

    tasklists = tl_parsed.get("items") if isinstance(tl_parsed, dict) else None
    if not isinstance(tasklists, list) or not tasklists:
        raise HTTPException(status_code=404, detail="google_tasks_no_tasklists")

    wanted = desired_title.casefold()
    for tl in tasklists:
        if not isinstance(tl, dict):
            continue
        title = str(tl.get("title") or "").strip()
        if title.casefold() == wanted:
            tid = str(tl.get("id") or "").strip() or None
            if not tid:
                raise HTTPException(status_code=502, detail="google_tasks_tasklist_missing_id")
            return tid, title

    raise HTTPException(status_code=404, detail="google_tasks_tasklist_title_not_found")


async def google_tasks_fetch_task(
    *,
    tasklist_id: str,
    task_id: str,
    mcp_tool_map: dict[str, dict[str, Any]],
    mcp_tools_call: Callable[[str, dict[str, Any]], Awaitable[Any]],
    mcp_text_json: Callable[[Any], Any],
) -> Optional[dict[str, Any]]:
    list_tasks_meta = mcp_tool_map.get("google_tasks_list_tasks") if isinstance(mcp_tool_map, dict) else None
    if not isinstance(list_tasks_meta, dict):
        return None
    list_tasks_tool = str(list_tasks_meta.get("mcp_name") or "").strip()
    if not list_tasks_tool:
        return None

    page_token: Optional[str] = None
    for _ in range(0, 5):
        args: dict[str, Any] = {
            "tasklist_id": tasklist_id,
            "max_results": 100,
            "show_completed": True,
            "show_hidden": True,
        }
        if page_token:
            args["page_token"] = page_token
        res = await mcp_tools_call(list_tasks_tool, args)
        parsed = mcp_text_json(res)
        if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict):
            parsed = parsed["data"]
        items = parsed.get("items") if isinstance(parsed, dict) else None
        if isinstance(items, list):
            for t in items:
                if not isinstance(t, dict):
                    continue
                if str(t.get("id") or "").strip() == task_id:
                    return t
        page_token = str(parsed.get("nextPageToken") or "").strip() if isinstance(parsed, dict) else ""
        if not page_token:
            break
    return None


async def google_calendar_fetch_event(
    *,
    event_id: str,
    mcp_tool_map: dict[str, dict[str, Any]],
    mcp_tools_call: Callable[[str, dict[str, Any]], Awaitable[Any]],
    mcp_text_json: Callable[[Any], Any],
) -> Optional[dict[str, Any]]:
    eid = str(event_id or "").strip()
    if not eid:
        return None

    meta = mcp_tool_map.get("google_calendar_list_events") if isinstance(mcp_tool_map, dict) else None
    if not isinstance(meta, dict):
        return None
    list_events_tool = str(meta.get("mcp_name") or "").strip()
    if not list_events_tool:
        return None

    res = await mcp_tools_call(list_events_tool, {"max_results": 250, "single_events": True, "order_by": "updated"})
    parsed = mcp_text_json(res)
    if not isinstance(parsed, dict):
        return None
    data = parsed.get("data")
    if not isinstance(data, dict):
        return None
    items = data.get("items")
    if not isinstance(items, list):
        return None
    for it in items:
        if isinstance(it, dict) and str(it.get("id") or "").strip() == eid:
            return it
    return None
