from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from jarvis.memory.cache import memory_cache
from jarvis.mcp.router import mcp_router

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/debug/status")
@router.get("/jarvis/debug/status")
@router.get("/api/debug/status")
@router.get("/jarvis/api/debug/status")
async def debug_status() -> dict[str, Any]:
    """Get debug status"""
    try:
        return {
            "ok": True,
            "mcp_cache_status": mcp_router.get_cache_status(),
            "memory_cache_status": memory_cache.get_cache_status(),
            "environment": os.getenv("JARVIS_ENV", "development")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug status error: {str(e)}")


@router.get("/verify/status")
@router.get("/jarvis/verify/status")
@router.get("/api/verify/status")
@router.get("/jarvis/api/verify/status")
async def verify_status() -> dict[str, Any]:
    """Verify system status"""
    try:
        cached = memory_cache.get_sheet_memory()
        return {
            "ok": True,
            "memory_cache_loaded": cached is not None,
            "timestamp": int(time.time())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verify status error: {str(e)}")


@router.get("/status")
@router.get("/jarvis/status")
@router.get("/api/status")
@router.get("/jarvis/api/status")
async def simple_status() -> dict[str, Any]:
    """Simple status endpoint for healthchecks"""
    return {"ok": True, "service": "jarvis-backend"}
