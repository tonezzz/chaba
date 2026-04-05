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
from jarvis.memory.cache import memory_cache

# Import API routers
from jarvis.api.oauth import router as oauth_router
from jarvis.api.debug import router as debug_router
from jarvis.api.logs import router as logs_router
from jarvis.api.memo import router as memo_router
from jarvis.api.sys_kv import router as sys_kv_router
from jarvis.api.memory import router as memory_router
from jarvis.api.imagen import router as imagen_router
from jarvis.api.reminders import router as reminders_router
from jarvis.api.sheets import router as sheets_router
from jarvis.api.dialog import router as dialog_router
from jarvis.api.system import router as system_router

# Import business logic modules
from jarvis.dialog.history import recent_dialog_load, format_recent_dialog_for_context
from jarvis.reminders.scheduler import reminder_scheduler
from jarvis.sheets.operations import load_sheet_table, load_sheet_kv5
from jarvis.gemini.client import gemini_client
from jarvis.utils.text import strip_html_tags, normalize_simple_cmd
from jarvis.utils.formatting import format_timestamp, format_duration_ms
from jarvis.mcp.mcp_client import mcp_text_json

# Import existing routers
from routes.google_tasks import create_router as _create_google_tasks_router
from routes.google_calendar import create_router as _create_google_calendar_router

# Import existing modules
import db_session
import google_common
from jarvis.feature_flags import feature_enabled
from jarvis import memo_sheet, memo_enrich, daily_brief, sheets_utils, current_news_skill, tools_router

# Import helper modules for Google Tasks
from tasks_sequential_v0 import suggest_next_step_from_task, suggest_template_from_completed_tasks
from checklist_v0 import next_actionable_step, parse_checklist_steps
from checklist_mutation_v0 import (
    find_checklist_step_indices_by_text,
    mark_all_checklist_steps_done,
    mark_checklist_step_done,
    mark_checklist_step_done_by_text,
)

# Configuration
MCP_TOOL_MAP = os.getenv("MCP_TOOL_MAP", "{}")
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "").strip()
JARVIS_SESSION_DB = os.getenv("JARVIS_SESSION_DB", "/data/jarvis_sessions.sqlite").strip()

# Determine MCP base URL based on environment
MCP_ENV = os.getenv("JARVIS_ENV", "development")
if MCP_ENV == "test":
    MCP_BASE_URL = "http://mcp-bundle-assistance-test:3151"
else:
    MCP_BASE_URL = "http://mcp-bundle-assistance:3050"

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Helper functions for Google Tasks integration
def _require_confirmation(require: bool, message: str, data: Any) -> None:
    """Helper function for requiring confirmation."""
    if require:
        logger.info(f"Confirmation required: {message}")
        # In a real implementation, this would prompt the user
        # For now, we'll just log it

def _resolve_google_tasks_tasklist(tasklist_id: Optional[str], tasklist_title: Optional[str]) -> tuple[Optional[str], str]:
    """Resolve Google Tasks tasklist ID and title."""
    if tasklist_id:
        return tasklist_id, tasklist_title or ""
    elif tasklist_title:
        # In a real implementation, this would look up the tasklist by title
        return None, tasklist_title
    else:
        return None, ""

def _google_tasks_fetch_task(tasklist_id: str, task_id: str) -> Optional[dict[str, Any]]:
    """Fetch a specific Google Task."""
    try:
        # This would call the MCP server to fetch the task
        # For now, return None as placeholder
        return None
    except Exception as e:
        logger.error(f"Failed to fetch task {task_id}: {e}")
        return None

def _google_tasks_undo_log(action: str, tasklist_id: Optional[str], task_id: Optional[str], before: Any, after: Any) -> str:
    """Log an undo action for Google Tasks."""
    import uuid
    undo_id = str(uuid.uuid4())
    # In a real implementation, this would store the undo log
    logger.info(f"Undo log: {action} - {undo_id}")
    return undo_id

def _undo_sheet_append(entry: dict[str, Any]) -> None:
    """Append entry to undo sheet."""
    # In a real implementation, this would append to the Google Sheet
    logger.info(f"Undo sheet append: {entry}")

def _google_tasks_undo_list(limit: int) -> list[dict[str, Any]]:
    """Get list of undo actions."""
    # In a real implementation, this would fetch from storage
    return []

def _google_tasks_undo_pop_last(limit: int) -> list[dict[str, Any]]:
    """Pop last undo actions."""
    # In a real implementation, this would remove from storage
    return []

def _current_news_router():
    """Create current news router"""
    from fastapi import APIRouter
    router = APIRouter()
    
    @router.get("/current-news")
    async def get_current_news():
        """Get current news endpoint."""
        return {"status": "ok", "message": "Current news endpoint placeholder"}
    
    return router

# Note trigger functions
def _extract_note_text(text: str) -> Optional[str]:
    """Extract note text from trigger phrase."""
    import re
    raw = str(text or "").strip()
    if not raw:
        return None
    s = " ".join(raw.split())
    lower = s.lower()

    eng_triggers = ("make a note",)
    thai_triggers = ("สร้างบันทึก", "จดบันทึก")
    # Speech-to-text frequently inserts spaces between Thai words, e.g. "จด บันทึก".
    # Also accept common Thai "note" variants.
    thai_note_patterns = (
        r"^(?:ช่วย\s*)?(?:จด\s*บันทึก|สร้าง\s*บันทึก)\s*[:\-]?\s*(.*)$",
        r"^(?:ช่วย\s*)?(?:จด\s*โน้ต|สร้าง\s*โน้ต)\s*[:\-]?\s*(.*)$",
        r"^(?:ช่วย\s*)?สร้าง\s*เป็น\s*โน้ต\s*[:\-]?\s*(.*)$",
    )

    for trig in eng_triggers:
        if lower.startswith(trig):
            rest = s[len(trig) :].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    for pat in thai_note_patterns:
        m = re.search(pat, s)
        if m:
            rest = str(m.group(1) or "").strip()
            return rest or None

    for trig in thai_triggers:
        if s.startswith(trig):
            rest = s[len(trig) :].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    for trig in eng_triggers:
        idx = lower.find(trig)
        if idx >= 0:
            rest = s[idx + len(trig) :].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    for trig in thai_triggers:
        idx = s.find(trig)
        if idx >= 0:
            rest = s[idx + len(trig) :].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    return None


def _is_note_trigger(text: str) -> bool:
    """Check if text is a note trigger."""
    import re
    raw = str(text or "").strip()
    if not raw:
        return False
    s = " ".join(raw.split())
    lower = s.lower()

    if lower.startswith("make a note") or "make a note" in lower:
        return True

    # Keep in sync with _extract_note_text.
    thai_note_patterns = (
        r"^(?:ช่วย\s*)?(?:จด\s*บันทึก|สร้าง\s*บันทึก)\s*(?:[:\-]\s*)?(.*)$",
        r"^(?:ช่วย\s*)?(?:จด\s*โน้ต|สร้าง\s*โน้ต)\s*(?:[:\-]\s*)?(.*)$",
        r"^(?:ช่วย\s*)?สร้าง\s*เป็น\s*โน้ต\s*(?:[:\-]\s*)?(.*)$",
    )
    for pat in thai_note_patterns:
        if re.search(pat, s):
            return True

    thai_triggers = ("สร้างบันทึก", "จดบันทึก")
    for trig in thai_triggers:
        if trig in s:
            return True
    return False

# Create the FastAPI app
app = create_app()

# Initialize MCP router with environment-specific URL
from jarvis.mcp.router import MCPRouter
mcp_router = MCPRouter(base_url=MCP_BASE_URL)

# Include modular API routers
app.include_router(oauth_router, prefix="/jarvis/api", tags=["oauth"])
app.include_router(debug_router, prefix="/jarvis/api", tags=["debug"])
app.include_router(logs_router, prefix="/jarvis/api", tags=["logs"])
app.include_router(memo_router, prefix="/jarvis/api", tags=["memo"])
app.include_router(sys_kv_router, prefix="/jarvis/api", tags=["sys_kv"])
app.include_router(memory_router, prefix="/jarvis/api", tags=["memory"])
app.include_router(imagen_router, prefix="/jarvis/api", tags=["imagen"])
app.include_router(reminders_router, prefix="/jarvis/api", tags=["reminders"])
app.include_router(sheets_router, prefix="/jarvis/api", tags=["sheets"])
app.include_router(dialog_router, prefix="/jarvis/api", tags=["dialog"])
app.include_router(system_router, prefix="/jarvis/api", tags=["system"])

# Include existing routers
app.include_router(
    _create_google_tasks_router(
        mcp_tool_map=MCP_TOOL_MAP,
        mcp_tools_call=lambda name, arguments: mcp_router.call_tool(name, arguments),
        mcp_tools_call_with_progress=lambda ws, name, arguments, trace_id: mcp_router.call_tool_with_progress(ws, name, arguments, trace_id),
        mcp_text_json=mcp_text_json,
        require_confirmation=_require_confirmation,
        resolve_tasklist=lambda tasklist_id, tasklist_title: _resolve_google_tasks_tasklist(
            tasklist_id=tasklist_id, tasklist_title=tasklist_title
        ),
        fetch_task=lambda tasklist_id, task_id: _google_tasks_fetch_task(tasklist_id=tasklist_id, task_id=task_id),
        undo_log=_google_tasks_undo_log,
        undo_sheet_append=lambda entry: _undo_sheet_append(entry),
        undo_list=_google_tasks_undo_list,
        undo_pop_last=_google_tasks_undo_pop_last,
        parse_checklist_steps=parse_checklist_steps,
        next_actionable_step=next_actionable_step,
        suggest_template_from_completed_tasks=suggest_template_from_completed_tasks,
    ),
    prefix="/jarvis/api",
    tags=["google-tasks"]
)

app.include_router(
    _create_google_calendar_router(
        mcp_tool_map=MCP_TOOL_MAP,
        mcp_tools_call=lambda name, arguments: mcp_router.call_tool(name, arguments),
        mcp_tools_call_with_progress=lambda ws, name, arguments, trace_id: mcp_router.call_tool_with_progress(ws, name, arguments, trace_id),
        mcp_text_json=mcp_text_json,
        require_confirmation=_require_confirmation,
        undo_sheet_append=lambda entry: _undo_sheet_append(entry),
        undo_list=_google_tasks_undo_list,
        undo_pop_last=_google_tasks_undo_pop_last,
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
