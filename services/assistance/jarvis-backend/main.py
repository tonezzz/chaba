import asyncio
import logging
import os
import time
import uuid
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Import modular components
from jarvis.core.app import create_app
from jarvis.websocket.session import (
    websocket_manager,
    gemini_list_models,
    gemini_live_probe_and_cache,
    gemini_live_cache_status,
)
from jarvis.agents.dispatch import agent_dispatcher
from jarvis.memory.cache import memory_cache

# Import API routers
from jarvis.api.oauth import router as oauth_router
from jarvis.api.logs import router as logs_router
from jarvis.api.sys_kv import router as sys_kv_router
from jarvis.api.dialog import router as dialog_router
from jarvis.api.system import router as system_router

# Import business logic modules
from jarvis.gemini.client import gemini_client
from jarvis.utils.text import strip_html_tags, normalize_simple_cmd
from jarvis.utils.formatting import format_timestamp, format_duration_ms
from jarvis.mcp.mcp_client import mcp_text_json

from jarvis.feature_flags import feature_enabled
from jarvis import tools_router

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

# Helper functions
def _require_confirmation(require: bool, message: str, data: Any) -> None:
    """Helper function for requiring confirmation."""
    if require:
        logger.info(f"Confirmation required: {message}")
        # In a real implementation, this would prompt the user
        # For now, we'll just log it

def _current_news_router():
    """Create current news router"""
    from fastapi import APIRouter
    router = APIRouter()
    
    @router.get("/current-news")
    async def get_current_news():
        """Get current news"""
        import asyncio
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # Use the working MCP client functions
                from mcp_client import mcp_tools_call
                
                # Call MCP news_run tool
                result = await mcp_tools_call(MCP_BASE_URL, "news_1mcp_news_run", {
                    "start_at": "fetch", 
                    "stop_after": "render"
                })
                
                if "error" in result:
                    if attempt < max_retries - 1:
                        logger.warning(f"News fetch attempt {attempt + 1} failed, retrying in {retry_delay}s: {result['error']}")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        # Return fallback response on final attempt
                        return {
                            "status": "ok",
                            "brief": "📰 **News Brief** - Service Temporarily Unavailable\n\n• The news service is currently experiencing technical difficulties\n• Please try again in a few moments\n• Alternative: Check your preferred news source directly\n\n*We're working to restore full news functionality ASAP.*",
                            "full_result": {"fallback": True, "error": result['error']},
                            "fallback": True
                        }
                
                # Extract and return the brief
                brief = result.get("brief", "")
                if brief:
                    return {
                        "status": "ok",
                        "brief": brief,
                        "full_result": result
                    }
                else:
                    if attempt < max_retries - 1:
                        logger.warning(f"News fetch attempt {attempt + 1} returned empty brief, retrying...")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        return {
                            "status": "ok", 
                            "message": "News fetched but no brief generated",
                            "result": result,
                            "fallback": True
                        }
                        
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"News fetch attempt {attempt + 1} failed, retrying in {retry_delay}s: {str(e)}")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error in current news endpoint after {max_retries} attempts: {e}")
                    return {
                        "status": "ok",
                        "brief": "📰 **News Brief** - Service Unavailable\n\n• Unable to connect to news service at this time\n• This may be due to temporary server maintenance\n• Please try again shortly\n\n*Technical team has been notified.*",
                        "fallback": True
                    }
    
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
app.include_router(logs_router, prefix="/jarvis/api", tags=["logs"])
app.include_router(sys_kv_router, prefix="/jarvis/api", tags=["sys_kv"])
app.include_router(dialog_router, prefix="/jarvis/api", tags=["dialog"])
app.include_router(system_router, prefix="/jarvis/api", tags=["system"])

# Add missing sequential tasks endpoints
from pydantic import BaseModel, Field
from typing import Optional

class SequentialApplyRequest(BaseModel):
    notes: str = Field(default="")
    step_index: int = Field(ge=0)

class SequentialApplyResponse(BaseModel):
    ok: bool
    changed: bool
    notes: str

class SequentialApplyByTextRequest(BaseModel):
    notes: str = Field(default="")
    step_text: str = Field(default="")

class SequentialApplyByTextResponse(BaseModel):
    ok: bool
    changed: bool
    notes: str
    matched_step_index: Optional[int] = None

class SequentialApplyAllRequest(BaseModel):
    notes: str = Field(default="")

class SequentialApplyAllResponse(BaseModel):
    ok: bool
    changed: bool
    changed_count: int
    notes: str

class SequentialApplyAndSuggestRequest(BaseModel):
    mode: Optional[str] = Field(default="suggest")
    notes: str = Field(default="")
    step_index: Optional[int] = Field(default=None, ge=0)
    step_text: str = Field(default="")
    step_index_hint: Optional[int] = Field(default=None, ge=0)
    completed_tasks: Optional[list[dict[str, Any]]] = None

class SequentialSuggestRequest(BaseModel):
    task: dict[str, Any] = Field(default_factory=dict)
    completed_tasks: Optional[list[dict[str, Any]]] = None

class SequentialSuggestResponse(BaseModel):
    ok: bool = True
    next_step_text: Optional[str] = None
    next_step_index: Optional[int] = None
    template: Optional[list[str]] = None

class SequentialApplyAndSuggestResponse(BaseModel):
    ok: bool
    mode: str
    notes: str
    changed: bool
    changed_count: Optional[int] = None
    matched_step_index: Optional[int] = None
    next_step_text: Optional[str] = None
    next_step_index: Optional[int] = None
    template: Optional[list[str]] = None

@app.post("/tasks/sequential/apply", response_model=SequentialApplyResponse)
def tasks_sequential_apply(req: SequentialApplyRequest) -> SequentialApplyResponse:
    updated, changed = mark_checklist_step_done(req.notes, req.step_index)
    return SequentialApplyResponse(ok=True, changed=changed, notes=updated)

@app.post("/tasks/sequential/apply_by_text", response_model=SequentialApplyByTextResponse)
def tasks_sequential_apply_by_text(req: SequentialApplyByTextRequest) -> SequentialApplyByTextResponse:
    updated, changed, matched_idx = mark_checklist_step_done_by_text(req.notes, req.step_text)
    return SequentialApplyByTextResponse(ok=True, changed=changed, notes=updated, matched_step_index=matched_idx)

@app.post("/tasks/sequential/apply_all", response_model=SequentialApplyAllResponse)
def tasks_sequential_apply_all(req: SequentialApplyAllRequest) -> SequentialApplyAllResponse:
    updated, changed, changed_count = mark_all_checklist_steps_done(req.notes)
    return SequentialApplyAllResponse(ok=True, changed=changed, changed_count=changed_count, notes=updated)

@app.post("/tasks/sequential/suggest", response_model=SequentialSuggestResponse)
def tasks_sequential_suggest(req: SequentialSuggestRequest) -> SequentialSuggestResponse:
    task = req.task if isinstance(req.task, dict) else {}
    suggestion = suggest_next_step_from_task(task)
    
    template: Optional[list[str]] = None
    if req.completed_tasks is not None:
        template = suggest_template_from_completed_tasks(req.completed_tasks)
    
    return SequentialSuggestResponse(
        ok=True,
        next_step_text=suggestion.next_step_text,
        next_step_index=suggestion.next_step_index,
        template=template,
    )

@app.post("/tasks/sequential/apply_and_suggest", response_model=SequentialApplyAndSuggestResponse)
def tasks_sequential_apply_and_suggest(req: SequentialApplyAndSuggestRequest) -> SequentialApplyAndSuggestResponse:
    mode = str(req.mode or "suggest")
    notes_in = str(req.notes or "")

    updated_notes = notes_in
    changed = False
    changed_count: Optional[int] = None
    matched_step_index: Optional[int] = None

    if mode == "suggest":
        pass
    elif mode == "index":
        if req.step_index is None:
            raise HTTPException(status_code=400, detail="missing_step_index")
        updated_notes, changed = mark_checklist_step_done(updated_notes, int(req.step_index))
    elif mode == "text":
        step_text = str(req.step_text or "").strip()
        if not step_text:
            raise HTTPException(status_code=400, detail="missing_step_text")
        matches = find_checklist_step_indices_by_text(updated_notes, step_text)
        if len(matches) >= 2:
            hint = req.step_index_hint
            if hint is not None and int(hint) in matches:
                matched_step_index = int(hint)
                updated_notes, changed = mark_checklist_step_done(updated_notes, matched_step_index)
            else:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "ambiguous_step_text": True,
                        "step_text": step_text,
                        "match_indices": matches,
                    },
                )
        else:
            updated_notes, changed, matched_step_index = mark_checklist_step_done_by_text(updated_notes, step_text)
    elif mode == "all":
        updated_notes, changed, cnt = mark_all_checklist_steps_done(updated_notes)
        changed_count = cnt
    else:
        raise HTTPException(status_code=400, detail="invalid_mode")

    suggestion = suggest_next_step_from_task({"notes": updated_notes})
    template: Optional[list[str]] = None
    if req.completed_tasks is not None:
        template = suggest_template_from_completed_tasks(req.completed_tasks)

    return SequentialApplyAndSuggestResponse(
        ok=True,
        mode=mode,
        notes=updated_notes,
        changed=changed,
        changed_count=changed_count,
        matched_step_index=matched_step_index,
        next_step_text=suggestion.next_step_text,
        next_step_index=suggestion.next_step_index,
        template=template,
    )


@app.websocket("/ws/live")
@app.websocket("/jarvis/ws/live")
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


@app.get("/jarvis/api/gemini/models")
async def gemini_models() -> dict[str, Any]:
    models = gemini_list_models()
    return {"ok": True, "count": len(models), "models": models}


@app.get("/gemini/models")
async def gemini_models_unprefixed() -> dict[str, Any]:
    models = gemini_list_models()
    return {"ok": True, "count": len(models), "models": models}


@app.get("/jarvis/api/gemini/live/cache")
async def gemini_live_cache() -> dict[str, Any]:
    return {"ok": True, **gemini_live_cache_status()}


@app.get("/gemini/live/cache")
async def gemini_live_cache_unprefixed() -> dict[str, Any]:
    return {"ok": True, **gemini_live_cache_status()}


@app.post("/jarvis/api/gemini/live/probe")
async def gemini_live_probe() -> dict[str, Any]:
    result = await gemini_live_probe_and_cache()
    return result


@app.post("/gemini/live/probe")
async def gemini_live_probe_unprefixed() -> dict[str, Any]:
    result = await gemini_live_probe_and_cache()
    return result


@app.get("/jarvis/api/gemini/live/recommend")
async def gemini_live_recommend() -> dict[str, Any]:
    models = gemini_list_models()
    # Recommend models based on list output (keep deterministic ordering)
    ranked = [
        m for m in models
        if any(k in m.lower() for k in ["live", "realtime", "native-audio"]) or "bidi" in m.lower()
    ]
    return {"ok": True, "count": len(ranked), "models": ranked}


@app.get("/gemini/live/recommend")
async def gemini_live_recommend_unprefixed() -> dict[str, Any]:
    models = gemini_list_models()
    ranked = [
        m for m in models
        if any(k in m.lower() for k in ["live", "realtime", "native-audio"]) or "bidi" in m.lower()
    ]
    return {"ok": True, "count": len(ranked), "models": ranked}


def _parse_bool_cell(v: Any) -> bool:
    """Parse boolean value from cell"""
    s = str(v or "").strip().lower()
    return s in {"1", "true", "t", "yes", "y", "on", "enabled"}


def _split_phrases(value: Any) -> list[str]:
    """Split phrases from comma-separated value"""
    raw = str(value or "").strip()
    if not raw:
        return []
    parts: list[str] = []
    for line in raw.replace("\r", "\n").split("\n"):
        try:
            line = str(line or "")
            if "#" in line:
                line = line.split("#", 1)[0]
        except Exception:
            pass
        for p in str(line or "").split(","):
            s = str(p or "").strip()
            if s:
                parts.append(s)
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        k = p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def _sys_kv_snapshot() -> dict[str, str]:
    """Get system key-value snapshot (simplified version)"""
    # For now, return empty dict - this would be populated from system sheet
    return {}


def _voice_command_config_from_sys_kv(sys_kv: dict[str, str]) -> dict[str, Any]:
    """Get voice command configuration from system key-value"""
    def _get(k: str, default: str = "") -> str:
        v = str(sys_kv.get(k) or "").strip()
        return v if v else default

    enabled = True
    raw_enabled = _get("voice_cmd.enabled", "")
    if raw_enabled:
        try:
            enabled = _parse_bool_cell(raw_enabled)
        except Exception:
            enabled = True

    try:
        debounce_ms = int(float(_get("voice_cmd.debounce_ms", "10000")))
        debounce_ms = max(0, min(debounce_ms, 120_000))
    except Exception:
        debounce_ms = 10_000

    return {
        "enabled": enabled,
        "debounce_ms": debounce_ms,
        "recent_activity": {
            "enabled": _parse_bool_cell(_get("voice_cmd.recent_activity.enabled", "true")),
            "phrases": _split_phrases(
                _get(
                    "voice_cmd.recent_activity.phrases",
                    "recent tasks,recent task,recent activity,what was i doing,what were you doing,เมื่อกี้ทำอะไร,เมื่อกี้ทำอะไรอยู่,ทำอะไรล่าสุด,งานล่าสุด,ล่าสุดทำอะไร",
                )
            ),
        },
        "reload": {
            "enabled": _parse_bool_cell(_get("voice_cmd.reload.enabled", "true")),
            "phrases": _split_phrases(_get("voice_cmd.reload.phrases", "")),
            "mode_keywords": {
                "gems": _split_phrases(_get("voice_cmd.reload.keywords.gems", "gems,gem,models,model,เจม,โมเดล")),
                "knowledge": _split_phrases(_get("voice_cmd.reload.keywords.knowledge", "knowledge,kb,know,ความรู้")),
                "memory": _split_phrases(_get("voice_cmd.reload.keywords.memory", "memory,mem,เมม,เมมโม")),
            },
        },
        "reminders_add": {
            "enabled": _parse_bool_cell(_get("voice_cmd.reminders_add.enabled", "true")),
            "phrases": _split_phrases(_get("voice_cmd.reminders_add.phrases", "")),
        },
        "gems_list": {
            "enabled": _parse_bool_cell(_get("voice_cmd.gems_list.enabled", "true")),
            "phrases": _split_phrases(_get("voice_cmd.gems_list.phrases", "")),
        },
    }


@app.get("/config/voice_commands")
@app.get("/jarvis/config/voice_commands")
def config_voice_commands() -> dict[str, Any]:
    """Get voice commands configuration"""
    sys_kv = _sys_kv_snapshot()
    cfg = _voice_command_config_from_sys_kv(sys_kv)
    return {"ok": True, "config": cfg}


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
