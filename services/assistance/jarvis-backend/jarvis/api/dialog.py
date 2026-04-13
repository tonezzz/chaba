from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from jarvis.dialog.history import recent_dialog_load, format_recent_dialog_for_context

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/dialog/history")
async def get_dialog_history(
    session_id: Optional[str] = None,
    max_chars: int = 1200,
) -> dict[str, Any]:
    """Get recent dialog history"""
    try:
        entries = await recent_dialog_load(session_id)
        context = format_recent_dialog_for_context(entries, max_chars)
        return {
            "ok": True,
            "session_id": session_id,
            "entries_count": len(entries),
            "context": context
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get dialog history: {str(e)}")


@router.post("/dialog/clear")
async def clear_dialog_history(
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Clear dialog history for session"""
    try:
        # TODO: Implement dialog clearing logic
        return {"ok": True, "session_id": session_id, "message": "Dialog clear - to be implemented"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear dialog history: {str(e)}")
