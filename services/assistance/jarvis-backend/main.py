import logging
import os
import time
import uuid
from typing import Any

from fastapi import Header, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware

# Import modular components
from jarvis.core.app import create_app
from jarvis.websocket.session import websocket_manager
from jarvis.agents.dispatch import agent_dispatcher
from jarvis.memory.cache import memory_cache

# Import API routers
from jarvis.api.oauth import router as oauth_router
from jarvis.api.logs import router as logs_router
from jarvis.api.sys_kv import router as sys_kv_router
from jarvis.api.dialog import router as dialog_router
from jarvis.api.system import router as system_router
from jarvis.api.sequential_tasks import router as sequential_tasks_router
from jarvis.api.gemini_admin import router as gemini_admin_router
from jarvis.api.config import router as config_router
from jarvis.api.news import router as news_router

# Import business logic modules

# Configuration
MCP_TOOL_MAP = os.getenv("MCP_TOOL_MAP", "{}")
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "").strip()
JARVIS_SESSION_DB = os.getenv("JARVIS_SESSION_DB", "/data/jarvis_sessions.sqlite").strip()

# Global variables for status endpoint
_PROCESS_START_TS = time.time()
INSTANCE_ID = str(uuid.uuid4())
_STARTUP_PREWARM_STATUS = {"ts": int(time.time()), "running": False, "ok": True, "memory_n": 0, "knowledge_n": 0, "error": ""}

def _weaviate_enabled() -> bool:
    """Check if Weaviate is enabled"""
    return bool(WEAVIATE_URL)

# Determine MCP base URL based on environment
MCP_ENV = os.getenv("JARVIS_ENV", "development")
if MCP_ENV == "test":
    MCP_BASE_URL = "http://mcp-bundle-assistance-test:3151"
else:
    MCP_BASE_URL = "http://mcp-bundle-assistance:3050"

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the FastAPI app
app = create_app()

# Initialize MCP router with environment-specific URL
from jarvis.mcp.router import MCPRouter
mcp_router = MCPRouter(base_url=MCP_BASE_URL)

# Include modular API routers
app.include_router(oauth_router, prefix="/jarvis/api", tags=["oauth"])
app.include_router(logs_router, tags=["logs"])
app.include_router(logs_router, prefix="/jarvis/api", tags=["logs"])
app.include_router(sys_kv_router, prefix="/jarvis/api", tags=["sys_kv"])
app.include_router(dialog_router, prefix="/jarvis/api", tags=["dialog"])
app.include_router(system_router, prefix="/jarvis/api", tags=["system"])
app.include_router(sequential_tasks_router, prefix="/jarvis/api", tags=["sequential_tasks"])
app.include_router(gemini_admin_router, tags=["gemini_admin"])
app.include_router(config_router, tags=["config"])
app.include_router(news_router, prefix="/jarvis/api", tags=["news"])


@app.websocket("/ws/live")
@app.websocket("/jarvis/ws/live")
async def ws_live(ws: WebSocket) -> None:
    """Main WebSocket endpoint - now uses modular session manager"""
    await websocket_manager.handle_connection(ws)


# Test MCP endpoint
@app.get("/jarvis/api/test-mcp")
async def test_mcp():
    """Test MCP connection"""
    try:
        # Test through the MCP router which handles session management
        tools = await mcp_router.list_tools()
        return {
            "status": "ok",
            "mcp_base_url": MCP_BASE_URL,
            "tools_count": len(tools),
            "tools": tools[:5]  # First 5 tools
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "mcp_base_url": MCP_BASE_URL
        }

@app.get("/status")
@app.get("/jarvis/status")
@app.get("/api/status")
@app.get("/jarvis/api/status")
async def status() -> dict[str, Any]:
    """Main status endpoint for Jarvis backend"""
    st = _STARTUP_PREWARM_STATUS if isinstance(_STARTUP_PREWARM_STATUS, dict) else {}
    try:
        uptime_s = max(0.0, float(time.time() - float(_PROCESS_START_TS)))
    except Exception:
        uptime_s = 0.0
    hostname = str(os.getenv("HOSTNAME") or "").strip() or None
    try:
        pid = int(os.getpid())
    except Exception:
        pid = None
    out: dict[str, Any] = {
        "ok": True,
        "service": "jarvis-backend",
        "instance_id": INSTANCE_ID,
        "hostname": hostname,
        "pid": pid,
        "uptime_s": uptime_s,
        "weaviate_enabled": _weaviate_enabled(),
        "startup_prewarm": {
            "ts": int(st.get("ts") or 0),
            "running": bool(st.get("running")),
            "ok": bool(st.get("ok")),
            "memory_n": int(st.get("memory_n") or 0),
            "knowledge_n": int(st.get("knowledge_n") or 0),
            "error": str(st.get("error") or "").strip(),
        },
        "mcp_news": {
            "status": "integrated",
            "endpoint": "/jarvis/api/current-news",
            "fallback_enabled": True
        }
    }

    # Best-effort: include container/module status rows when Portainer is configured.
    try:
        # Simplified container status - just check if we can reach key services
        from jarvis.mcp.router import mcp_router
        out["mcp_connection"] = "unknown"
        # Try a lightweight MCP connection test
        try:
            # This would be a lightweight check - for now just indicate it's configured
            out["mcp_connection"] = "configured"
        except Exception:
            out["mcp_connection"] = "error"
    except Exception as e:
        out["mcp_connection_error"] = str(e)

    return out


# Legacy endpoints (would be moved to appropriate modules)
@app.get("/jarvis/debug/status")
async def debug_status():
    """Debug status endpoint"""
    return {
        "ok": True,
        "mcp_cache_status": mcp_router.get_cache_status(),
        "memory_cache_status": memory_cache.get_cache_status(),
        "agents_count": len(agent_dispatcher.agents)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
