import asyncio
import logging
import os
import uuid
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# Import modular components
from jarvis.core.app import create_app
from jarvis.websocket.session import websocket_manager
from jarvis.agents.dispatch import agent_dispatcher
from jarvis.skills.news import news_skill
from jarvis.mcp.router import mcp_router
from jarvis.memory.cache import memory_cache

# Import existing routers
from routes.google_tasks import create_router as _create_google_tasks_router
from routes.google_calendar import create_router as _create_google_calendar_router

# Import existing modules
import db_session
import google_common
from jarvis.feature_flags import feature_enabled
from jarvis import memo_sheet, memo_enrich, daily_brief, sheets_utils, current_news_skill, tools_router

# Configuration
MCP_TOOL_MAP = os.getenv("MCP_TOOL_MAP", "{}")
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "").strip()
JARVIS_SESSION_DB = os.getenv("JARVIS_SESSION_DB", "/data/jarvis_sessions.sqlite").strip()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the FastAPI app
app = create_app()

# Include existing routers
app.include_router(
    _create_google_tasks_router(
        mcp_tool_map=MCP_TOOL_MAP,
        mcp_tools_call=lambda name, arguments: mcp_router.call_tool(name, arguments),
        mcp_tools_call_with_progress=lambda ws, name, arguments, trace_id: mcp_router.call_tool_with_progress(ws, name, arguments, trace_id),
    ),
    prefix="/jarvis/api",
    tags=["google-tasks"]
)

app.include_router(
    _create_google_calendar_router(
        mcp_tool_map=MCP_TOOL_MAP,
        mcp_tools_call=lambda name, arguments: mcp_router.call_tool(name, arguments),
        mcp_tools_call_with_progress=lambda ws, name, arguments, trace_id: mcp_router.call_tool_with_progress(ws, name, arguments, trace_id),
    ),
    prefix="/jarvis/api",
    tags=["google-calendar"]
)

# Include current news router
app.include_router(_current_news_router(), prefix="/jarvis/api", tags=["current-news"])


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    """Main WebSocket endpoint - now uses modular session manager"""
    await websocket_manager.handle_connection(ws)


# MCP tool declarations (simplified)
def _mcp_tool_declarations() -> list[dict[str, Any]]:
    """Get MCP tool declarations"""
    try:
        tools = mcp_router.list_tools()
        return tools
    except Exception as e:
        logger.error(f"Failed to get MCP tool declarations: {e}")
        return []


# Agent handlers (would be expanded)
async def _handle_agent_news(ws: WebSocket, text: str, trace_id: str) -> bool:
    """Handle news agent dispatch"""
    return await news_skill.handle_current_news(ws, text, trace_id)


async def _handle_agent_follow_news(ws: WebSocket, text: str, trace_id: str) -> bool:
    """Handle follow news agent dispatch"""
    return await news_skill.handle_follow_news(ws, text, trace_id)


# Tool calling functions
async def _mcp_tools_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call MCP tool"""
    return await mcp_router.call_tool(name, arguments)


async def _mcp_tools_call_with_progress(ws: WebSocket, name: str, arguments: dict[str, Any], trace_id: str) -> dict[str, Any]:
    """Call MCP tool with progress"""
    return await mcp_router.call_tool_with_progress(ws, name, arguments, trace_id)


# Current news router (simplified placeholder)
def _current_news_router():
    """Create current news router"""
    from fastapi import APIRouter
    router = APIRouter()
    
    @router.get("/current-news")
    async def get_current_news():
        """Get current news"""
        return {"ok": True, "message": "Current news endpoint - to be implemented"}
    
    return router


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
