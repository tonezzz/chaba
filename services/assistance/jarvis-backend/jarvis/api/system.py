from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from jarvis.mcp.router import mcp_router

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/system/status")
async def get_system_status() -> dict[str, Any]:
    """Get system status"""
    try:
        mcp_health = await mcp_router.check_mcp_news_health()
        
        return {
            "ok": True,
            "timestamp": int(time.time()),
            "environment": os.getenv("JARVIS_ENV", "development"),
            "version": "0.1.0",
            "uptime_seconds": int(time.time() - int(os.getenv("PROCESS_START_TS", "0"))),
            "mcp_news": mcp_health
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system status: {str(e)}")


@router.get("/system/config")
async def get_system_config() -> dict[str, Any]:
    """Get system configuration (non-sensitive)"""
    try:
        config = {
            "JARVIS_ENV": os.getenv("JARVIS_ENV", "development"),
            "JARVIS_AGENTS_DIR": os.getenv("JARVIS_AGENTS_DIR", "/app/agents"),
            "JARVIS_SESSION_DB": os.getenv("JARVIS_SESSION_DB", "/data/jarvis_sessions.sqlite"),
            "WEAVIATE_URL": "configured" if os.getenv("WEAVIATE_URL") else "not_set",
            "REDIS_URL": "configured" if os.getenv("REDIS_URL") else "not_set",
            "MCP_BASE_URL": os.getenv("MCP_BASE_URL", "http://mcp-bundle-assistance:3050"),
        }
        return {"ok": True, "config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system config: {str(e)}")


@router.post("/system/reload")
async def reload_system() -> dict[str, Any]:
    """Reload system configuration"""
    try:
        # TODO: Implement system reload logic
        return {"ok": True, "message": "System reload - to be implemented"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload system: {str(e)}")


@router.get("/system/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint"""
    try:
        return {
            "status": "healthy",
            "timestamp": int(time.time()),
            "version": "0.1.0"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
