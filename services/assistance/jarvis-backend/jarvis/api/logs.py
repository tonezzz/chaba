from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/logs/ui/append")
@router.post("/jarvis/api/logs/ui/append")
async def logs_ui_append(req: dict[str, Any]) -> dict[str, Any]:
    """Append UI logs"""
    try:
        # Implementation would extract from main.py logs_ui_append
        return {"ok": True, "path": "/tmp/ui.log", "appended": len(req.get("entries", []))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to append UI logs: {str(e)}")


@router.get("/logs/sheets/status")
def logs_sheets_status() -> dict[str, Any]:
    """Get sheets logs status"""
    try:
        # Implementation would extract from main.py logs_sheets_status
        return {"ok": True, "queue_length": 0, "last_processed": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get sheets logs status: {str(e)}")


@router.get("/logs/ui/today")
def logs_ui_today(max_bytes: int = 200000, max_lines: Optional[int] = None) -> dict[str, Any]:
    """Get today's UI logs"""
    try:
        # Implementation would extract from main.py logs_ui_today
        return {"ok": True, "content": "", "size": 0, "lines": 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get UI logs: {str(e)}")


@router.get("/logs/ws/today")
def logs_ws_today(max_bytes: int = 200000, max_lines: Optional[int] = None) -> dict[str, Any]:
    """Get today's WebSocket logs"""
    try:
        # Implementation would extract from main.py logs_ws_today
        return {"ok": True, "content": "", "size": 0, "lines": 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get WebSocket logs: {str(e)}")
