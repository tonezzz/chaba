from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter()

_OAUTH_CALLBACK_LAST: dict[str, Any] = {}


@router.get("/oauth/callback")
@router.get("/jarvis/oauth/callback")
@router.get("/api/oauth/callback")
@router.get("/jarvis/api/oauth/callback")
async def oauth_callback_capture(request: Request) -> Response:
    """Capture OAuth callback"""
    try:
        # Implementation would extract from main.py oauth_callback_capture
        return Response(content="OAuth callback captured", media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OAuth callback error: {str(e)}")


@router.get("/oauth/callback/last")
@router.get("/jarvis/oauth/callback/last")
@router.get("/api/oauth/callback/last")
@router.get("/jarvis/api/oauth/callback/last")
def oauth_callback_last() -> dict[str, Any]:
    """Get last OAuth callback"""
    return {"ok": True, "last": dict(_OAUTH_CALLBACK_LAST)}
