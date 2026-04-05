from __future__ import annotations

from typing import Any, Callable, Awaitable, Optional

from fastapi import APIRouter, HTTPException


def create_router(
    *,
    mcp_tool_map: dict[str, dict[str, Any]],
    mcp_tools_call: Callable[[str, dict[str, Any]], Awaitable[Any]],
    mcp_text_json: Callable[[Any], Any],
    require_confirmation: Callable[[bool, str, Any], None],
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
            return {"ok": True, "raw": parsed}

    return router
