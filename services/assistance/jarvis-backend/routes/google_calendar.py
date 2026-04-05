from __future__ import annotations

from typing import Any, Callable, Awaitable, Optional

from fastapi import APIRouter, HTTPException

from google_schemas import (
    GoogleCalendarUndoItem,
    GoogleCalendarUndoLastRequest,
    GoogleCalendarUndoListResponse,
    GoogleCalendarUndoResponse,
)


def create_router(
    *,
    mcp_tool_map: dict[str, dict[str, Any]],
    mcp_tools_call: Callable[[str, dict[str, Any]], Awaitable[Any]],
    mcp_tools_call_with_progress: Optional[Callable[[Any, str, dict[str, Any], str], Awaitable[Any]]] = None,
    mcp_text_json: Callable[[Any], Any],
    require_confirmation: Callable[[bool, str, Any], None],
    undo_sheet_append: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
    undo_list: Callable[[int], list[dict[str, Any]]],
    undo_pop_last: Callable[[int], list[dict[str, Any]]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/google-calendar/auth/status")
    async def google_calendar_auth_status() -> dict[str, Any]:
        auth_meta = mcp_tool_map.get("google_calendar_auth_status") if isinstance(mcp_tool_map, dict) else None
        if not isinstance(auth_meta, dict):
            raise HTTPException(status_code=500, detail="google_calendar_tools_not_configured")
        auth_tool = str(auth_meta.get("mcp_name") or "").strip()
        if not auth_tool:
            raise HTTPException(status_code=500, detail="google_calendar_tools_not_configured")

        try:
            res = await mcp_tools_call(auth_tool, {})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail={"google_calendar_auth_status_failed": str(e)})

        parsed = mcp_text_json(res)
        if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict):
            return {"ok": True, "data": parsed.get("data")}
        if isinstance(parsed, dict):
            return parsed
        return {"ok": True, "raw": parsed}

    @router.get("/google-calendar/undo/list", response_model=GoogleCalendarUndoListResponse)
    async def google_calendar_undo_list(limit: int = 10) -> GoogleCalendarUndoListResponse:
        items = undo_list(limit)
        return GoogleCalendarUndoListResponse(ok=True, items=[GoogleCalendarUndoItem(**i) for i in items])

    @router.post("/google-calendar/undo/last", response_model=GoogleCalendarUndoResponse)
    async def google_calendar_undo_last(req: GoogleCalendarUndoLastRequest) -> GoogleCalendarUndoResponse:
        n = max(1, min(int(req.n or 1), 50))
        action = "google_calendar_undo_last"
        require_confirmation(bool(req.confirm), action, {"n": n})

        popped = undo_pop_last(n)
        results: list[dict[str, Any]] = []

        for item in popped:
            orig_action = str(item.get("action") or "")
            event_id = str(item.get("event_id") or "").strip() or None
            before = item.get("before")
            undo_id = item.get("undo_id")

            if orig_action == "google_calendar_create_event" and event_id:
                meta = mcp_tool_map.get("google_calendar_delete_event") if isinstance(mcp_tool_map, dict) else None
                mcp_name = str(meta.get("mcp_name") or "").strip() if isinstance(meta, dict) else ""
                if not mcp_name:
                    raise HTTPException(status_code=500, detail="google_calendar_tools_not_configured")
                res = await mcp_tools_call(mcp_name, {"event_id": event_id})
                result_obj = {"undo_id": undo_id, "undone": "delete_created_event", "result": mcp_text_json(res)}
                results.append(result_obj)
                if undo_sheet_append is not None:
                    try:
                        await undo_sheet_append(
                            {
                                "event": "executed",
                                "undo_id": undo_id,
                                "scope": "google_calendar",
                                "action": orig_action,
                                "event_id": event_id,
                                "status": "ok",
                                "result": result_obj,
                            }
                        )
                    except Exception:
                        pass
                continue

            if orig_action == "google_calendar_update_event" and event_id and isinstance(before, dict):
                meta = mcp_tool_map.get("google_calendar_update_event") if isinstance(mcp_tool_map, dict) else None
                mcp_name = str(meta.get("mcp_name") or "").strip() if isinstance(meta, dict) else ""
                if not mcp_name:
                    raise HTTPException(status_code=500, detail="google_calendar_tools_not_configured")
                payload: dict[str, Any] = {"event_id": event_id}
                for k_src, k_dst in (("summary", "summary"), ("description", "description")):
                    if k_src in before:
                        payload[k_dst] = before.get(k_src)
                if isinstance(before.get("start"), dict) and before["start"].get("dateTime"):
                    payload["start"] = before["start"].get("dateTime")
                elif isinstance(before.get("start"), dict) and before["start"].get("date"):
                    payload["start"] = before["start"].get("date")
                if isinstance(before.get("end"), dict) and before["end"].get("dateTime"):
                    payload["end"] = before["end"].get("dateTime")
                elif isinstance(before.get("end"), dict) and before["end"].get("date"):
                    payload["end"] = before["end"].get("date")
                tz = None
                if isinstance(before.get("start"), dict):
                    tz = before["start"].get("timeZone")
                if tz:
                    payload["timezone"] = tz
                res = await mcp_tools_call(mcp_name, {k: v for k, v in payload.items() if v is not None})
                result_obj = {"undo_id": undo_id, "undone": "revert_event", "result": mcp_text_json(res)}
                results.append(result_obj)
                if undo_sheet_append is not None:
                    try:
                        await undo_sheet_append(
                            {
                                "event": "executed",
                                "undo_id": undo_id,
                                "scope": "google_calendar",
                                "action": orig_action,
                                "event_id": event_id,
                                "status": "ok",
                                "result": result_obj,
                            }
                        )
                    except Exception:
                        pass
                continue

            if orig_action == "google_calendar_delete_event" and isinstance(before, dict):
                meta = mcp_tool_map.get("google_calendar_create_event") if isinstance(mcp_tool_map, dict) else None
                mcp_name = str(meta.get("mcp_name") or "").strip() if isinstance(meta, dict) else ""
                if not mcp_name:
                    raise HTTPException(status_code=500, detail="google_calendar_tools_not_configured")
                payload2: dict[str, Any] = {
                    "summary": str(before.get("summary") or ""),
                    "description": str(before.get("description") or ""),
                }
                if isinstance(before.get("start"), dict) and before["start"].get("dateTime"):
                    payload2["start"] = before["start"].get("dateTime")
                elif isinstance(before.get("start"), dict) and before["start"].get("date"):
                    payload2["start"] = before["start"].get("date")
                if isinstance(before.get("end"), dict) and before["end"].get("dateTime"):
                    payload2["end"] = before["end"].get("dateTime")
                elif isinstance(before.get("end"), dict) and before["end"].get("date"):
                    payload2["end"] = before["end"].get("date")
                tz2 = None
                if isinstance(before.get("start"), dict):
                    tz2 = before["start"].get("timeZone")
                if tz2:
                    payload2["timezone"] = tz2
                res = await mcp_tools_call(
                    mcp_name,
                    {k: v for k, v in payload2.items() if v is not None and str(v) != ""},
                )
                result_obj = {
                    "undo_id": undo_id,
                    "undone": "recreate_deleted_event",
                    "result": mcp_text_json(res),
                    "note": "recreated_event_has_new_id",
                }
                results.append(result_obj)
                if undo_sheet_append is not None:
                    try:
                        await undo_sheet_append(
                            {
                                "event": "executed",
                                "undo_id": undo_id,
                                "scope": "google_calendar",
                                "action": orig_action,
                                "event_id": event_id,
                                "status": "ok",
                                "result": result_obj,
                            }
                        )
                    except Exception:
                        pass
                continue

            result_obj = {"undo_id": undo_id, "skipped": True, "reason": "insufficient_undo_data", "action": orig_action}
            results.append(result_obj)
            if undo_sheet_append is not None:
                try:
                    await undo_sheet_append(
                        {
                            "event": "executed",
                            "undo_id": undo_id,
                            "scope": "google_calendar",
                            "action": orig_action,
                            "event_id": event_id,
                            "status": "skipped",
                            "result": result_obj,
                        }
                    )
                except Exception:
                    pass

        return GoogleCalendarUndoResponse(ok=True, undone=len(results), results=results)

    return router
