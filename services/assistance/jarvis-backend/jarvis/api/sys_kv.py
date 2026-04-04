from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Header

from jarvis.utils.validation import require_api_token_if_configured

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/sys_kv/reload")
@router.post("/jarvis/sys_kv/reload")
async def sys_kv_reload(x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token")) -> dict[str, Any]:
    """Reload system key-value store"""
    require_api_token_if_configured(x_api_token)
    try:
        # Implementation would extract from main.py sys_kv_reload
        return {"ok": True, "keys": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload sys_kv: {str(e)}")


@router.get("/sys_kv/snapshot")
@router.get("/jarvis/sys_kv/snapshot")
def sys_kv_snapshot_http(x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token")) -> dict[str, Any]:
    """Get system key-value snapshot"""
    require_api_token_if_configured(x_api_token)
    try:
        # Implementation would extract from main.py sys_kv_snapshot_http
        return {"ok": True, "sys_kv": {}, "google_gates": {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get sys_kv snapshot: {str(e)}")


@router.post("/sys_kv/bootstrap/google_gates")
@router.post("/jarvis/sys_kv/bootstrap/google_gates")
async def sys_kv_bootstrap_google_gates(
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Bootstrap Google gates"""
    require_api_token_if_configured(x_api_token)
    try:
        # Implementation would extract from main.py sys_kv_bootstrap_google_gates
        return {"ok": True, "message": "sys_kv_bootstrap_google_gates - to be implemented"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to bootstrap Google gates: {str(e)}")
