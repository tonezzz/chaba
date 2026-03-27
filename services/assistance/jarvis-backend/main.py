"""
jarvis-backend — Gemini Live + Skills Sheet SSOT routing.

Key features
------------
* GET  /health                         — liveness probe
* GET  /jarvis/api/debug/status        — dependency status
* GET  /config/voice_commands          — voice command config (backward compat)
* POST /config/voice_commands          — update voice command config
* GET  /jarvis/api/sys_kv/{key}        — read a sys_kv entry
* POST /jarvis/api/sys_kv/{key}        — write a sys_kv entry
* POST /jarvis/api/skills/reload       — reload skills sheet from JARVIS_SKILLS_JSON
* POST /jarvis/api/dispatch            — dispatch a text message through the skill router
* WS   /jarvis/ws/session              — Gemini Live bidirectional session

Skills routing gate
-------------------
sys_kv key ``system.skills.routing.enabled`` (default ``false``).

When ``true`` the sheet-first dispatcher runs before the legacy
``_dispatch_sub_agents`` fallback.  When ``false`` behaviour is unchanged.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from skills_router import SkillParseError, SkillRow, match_skill, parse_skill_rows

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="jarvis-backend", version="1.0.0")
logger = logging.getLogger("jarvis-backend")

# ---------------------------------------------------------------------------
# Build-time metadata
# ---------------------------------------------------------------------------

_GIT_SHA = os.getenv("GIT_SHA", "unknown")
_SERVICE = "jarvis-backend"
_VERSION = "1.0.0"


def _utc_ts() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# sys_kv  –  in-memory key/value store for runtime configuration
# ---------------------------------------------------------------------------

_sys_kv: Dict[str, str] = {}

# Seed defaults
_sys_kv.setdefault("system.skills.routing.enabled", "false")
_sys_kv.setdefault("system.skills.sheet_name", os.getenv("JARVIS_SKILLS_SHEET_NAME", "skills"))


def _kv_get(key: str, default: str = "") -> str:
    return _sys_kv.get(key, default)


def _kv_set(key: str, value: str) -> None:
    _sys_kv[key] = value


def _routing_enabled() -> bool:
    return _kv_get("system.skills.routing.enabled", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
    )


# ---------------------------------------------------------------------------
# Skills sheet  –  in-memory loaded rows
# ---------------------------------------------------------------------------

_skills: List[SkillRow] = []


def _load_skills_from_env() -> List[SkillRow]:
    """Load skills from JARVIS_SKILLS_JSON env var (JSON array of row dicts).

    Returns an empty list if the env var is absent or unparseable.
    """
    raw = os.getenv("JARVIS_SKILLS_JSON", "").strip()
    if not raw:
        return []
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list):
            logger.warning("JARVIS_SKILLS_JSON is not a JSON array; ignoring")
            return []
        return parse_skill_rows(rows)
    except SkillParseError as exc:
        logger.error("Skills parse error in JARVIS_SKILLS_JSON: %s", exc)
        return []
    except (ValueError, TypeError) as exc:
        logger.error("Failed to parse JARVIS_SKILLS_JSON: %s", exc)
        return []


# Eager load at startup
_skills = _load_skills_from_env()


# ---------------------------------------------------------------------------
# Voice commands  –  backward-compatible config store
# ---------------------------------------------------------------------------

_voice_commands: List[Dict[str, Any]] = []


def _default_voice_commands() -> List[Dict[str, Any]]:
    raw = os.getenv("JARVIS_VOICE_COMMANDS_JSON", "").strip()
    if not raw:
        return []
    try:
        cmds = json.loads(raw)
        if isinstance(cmds, list):
            return cmds
    except (ValueError, TypeError):
        pass
    return []


_voice_commands = _default_voice_commands()


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------


def _dispatch_sub_agents(text: str, **kw: Any) -> Dict[str, Any]:
    """Legacy/fallback sub-agent dispatcher stub.

    In a full deployment this would fan out to Gemini / tool calls.
    For the purposes of the routing feature it is the fallback that runs
    when no skill row matches (or when routing is disabled).
    """
    return {"dispatched_by": "sub_agents", "text": text, **kw}


def _dispatch_with_sheet(text: str, lang: str = "any") -> Dict[str, Any]:
    """Sheet-first dispatcher.

    1. If routing gate is disabled → legacy fallback immediately.
    2. Try to match *text* against loaded skill rows.
    3. On match → return routed result; on no match → legacy fallback.
    """
    if not _routing_enabled():
        return _dispatch_sub_agents(text)

    matched = match_skill(text, _skills, lang=lang)
    if matched is None:
        return _dispatch_sub_agents(text)

    return {
        "dispatched_by": "skills_sheet",
        "skill_id": matched.skill_id,
        "handler": matched.handler,
        "arg_json": matched.arg_json,
        "text": text,
    }


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class SysKvBody(BaseModel):
    value: str


class SkillsReloadBody(BaseModel):
    rows: Optional[List[Dict[str, Any]]] = None


class DispatchBody(BaseModel):
    text: str
    lang: str = "any"


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": _SERVICE,
        "version": _VERSION,
        "git_sha": _GIT_SHA,
        "ts": _utc_ts(),
    }


@app.get("/jarvis/api/debug/status")
def debug_status() -> Dict[str, Any]:
    routing_enabled = _routing_enabled()
    return {
        "ok": True,
        "service": _SERVICE,
        "version": _VERSION,
        "git_sha": _GIT_SHA,
        "ts": _utc_ts(),
        "skills_routing_enabled": routing_enabled,
        "skills_loaded": len(_skills),
        "voice_commands_loaded": len(_voice_commands),
        "sys_kv_keys": sorted(_sys_kv.keys()),
    }


# ---------------------------------------------------------------------------
# sys_kv endpoints
# ---------------------------------------------------------------------------


@app.get("/jarvis/api/sys_kv/{key:path}")
def sys_kv_get(key: str) -> Dict[str, Any]:
    if key not in _sys_kv:
        raise HTTPException(status_code=404, detail="key_not_found")
    return {"ok": True, "key": key, "value": _sys_kv[key]}


@app.post("/jarvis/api/sys_kv/{key:path}")
def sys_kv_set(key: str, body: SysKvBody) -> Dict[str, Any]:
    _kv_set(key, body.value)
    return {"ok": True, "key": key, "value": body.value}


# ---------------------------------------------------------------------------
# Voice commands endpoints  (backward compatibility)
# ---------------------------------------------------------------------------


@app.get("/config/voice_commands")
def get_voice_commands() -> Dict[str, Any]:
    return {"ok": True, "commands": _voice_commands}


@app.post("/config/voice_commands")
def set_voice_commands(body: Dict[str, Any]) -> Dict[str, Any]:
    global _voice_commands
    cmds = body.get("commands")
    if not isinstance(cmds, list):
        raise HTTPException(status_code=400, detail="commands must be a list")
    _voice_commands = cmds
    return {"ok": True, "commands": _voice_commands}


# ---------------------------------------------------------------------------
# Skills sheet endpoints
# ---------------------------------------------------------------------------


@app.get("/jarvis/api/skills")
def skills_list() -> Dict[str, Any]:
    return {
        "ok": True,
        "skills": [
            {
                "skill_id": s.skill_id,
                "enabled": s.enabled,
                "priority": s.priority,
                "match_type": s.match_type,
                "pattern": s.pattern,
                "lang": s.lang,
                "handler": s.handler,
                "arg_json": s.arg_json,
            }
            for s in _skills
        ],
    }


@app.post("/jarvis/api/skills/reload")
def skills_reload(body: Optional[SkillsReloadBody] = None) -> Dict[str, Any]:
    """Reload the skills sheet.

    If ``body.rows`` is provided, use those rows directly.
    Otherwise, re-read JARVIS_SKILLS_JSON from the environment.
    """
    global _skills
    rows_override = body.rows if body else None
    if rows_override is not None:
        try:
            _skills = parse_skill_rows(rows_override)
        except SkillParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        _skills = _load_skills_from_env()
    return {"ok": True, "skills_loaded": len(_skills)}


# ---------------------------------------------------------------------------
# Dispatch endpoint
# ---------------------------------------------------------------------------


@app.post("/jarvis/api/dispatch")
def dispatch(body: DispatchBody) -> Dict[str, Any]:
    result = _dispatch_with_sheet(body.text, lang=body.lang)
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# WebSocket session  –  Gemini Live proxy stub
# ---------------------------------------------------------------------------


@app.websocket("/jarvis/ws/session")
async def ws_session(ws: WebSocket) -> None:  # pragma: no cover
    """Bidirectional WebSocket session bridging the browser to Gemini Live.

    Protocol shapes are kept stable (no changes to existing message types).
    The skills routing layer is invoked on ``transcript`` messages before
    forwarding to Gemini or the legacy sub-agent dispatcher.
    """
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                await ws.send_text(
                    json.dumps({"type": "error", "detail": "invalid_json"})
                )
                continue

            msg_type = str(msg.get("type") or "")

            if msg_type == "transcript":
                text = str(msg.get("text") or "").strip()
                lang = str(msg.get("lang") or "any").strip()
                if text:
                    dispatch_result = _dispatch_with_sheet(text, lang=lang)
                    await ws.send_text(
                        json.dumps({"type": "dispatch_result", **dispatch_result})
                    )
            elif msg_type == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
            else:
                await ws.send_text(
                    json.dumps({"type": "echo", "original": msg})
                )
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    port = int(os.getenv("PORT", "8018"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
