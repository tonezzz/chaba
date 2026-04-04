from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Header

from jarvis.utils.validation import require_api_token_if_configured

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/memory/set")
@router.post("/jarvis/memory/set")
async def memory_set(
    req: dict[str, Any],
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Set memory value"""
    require_api_token_if_configured(x_api_token)
    try:
        # Implementation would extract from main.py memory_set
        key = req.get("key", "")
        value = req.get("value", "")
        return {"ok": True, "key": key, "value": value, "scope": "global", "priority": 0, "enabled": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set memory: {str(e)}")
