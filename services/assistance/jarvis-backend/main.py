from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_NAME = "jarvis-backend"
APP_VERSION = "0.1.0"

logging.basicConfig(level=os.getenv("JARVIS_LOG_LEVEL", "INFO"))
logger = logging.getLogger(APP_NAME)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

MACROS_FILE = os.getenv("JARVIS_MACROS_FILE", "/data/macros.json").strip()
PORT = int(os.getenv("PORT", "8018"))
CORS_ORIGINS: List[str] = [
    o.strip()
    for o in (os.getenv("JARVIS_CORS_ORIGINS") or "*").split(",")
    if o.strip()
]


# ---------------------------------------------------------------------------
# Macro data model
# ---------------------------------------------------------------------------

class Macro(BaseModel):
    id: str
    name: str
    content: str
    tags: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# In-memory macro store
# ---------------------------------------------------------------------------

_macros: List[Macro] = []
_macros_loaded_at: Optional[float] = None


def _load_macros_from_file(path: str) -> List[Macro]:
    """Load macros from a JSON file.  Returns an empty list on any error."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, list):
            logger.warning("macros file is not a JSON array: %s", path)
            return []
        result: List[Macro] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                result.append(Macro(**item))
            except Exception as exc:
                logger.warning("skipping invalid macro entry: %s", exc)
        return result
    except FileNotFoundError:
        logger.info("macros file not found (%s); starting with empty set", path)
        return []
    except Exception as exc:
        logger.error("failed to load macros from %s: %s", path, exc)
        return []


def _reload_all() -> Dict[str, Any]:
    """Reload all macros from disk and update the in-memory store."""
    global _macros, _macros_loaded_at
    before = len(_macros)
    _macros = _load_macros_from_file(MACROS_FILE)
    _macros_loaded_at = time.time()
    after = len(_macros)
    logger.info("system_reload_macros(mode=all): loaded %d macros (was %d)", after, before)
    return {
        "ok": True,
        "mode": "all",
        "loaded": after,
        "previous": before,
    }


def _reload_by_id(macro_id: str) -> Dict[str, Any]:
    """Reload a single macro by id from the on-disk source."""
    global _macros
    fresh = _load_macros_from_file(MACROS_FILE)
    match = next((m for m in fresh if m.id == macro_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"macro id '{macro_id}' not found in source")
    # Replace or append
    idx = next((i for i, m in enumerate(_macros) if m.id == macro_id), None)
    if idx is not None:
        _macros[idx] = match
        action = "updated"
    else:
        _macros.append(match)
        action = "added"
    logger.info("system_reload_macros(mode=by_id, id=%s): %s", macro_id, action)
    return {
        "ok": True,
        "mode": "by_id",
        "id": macro_id,
        "action": action,
        "macro": match.model_dump(),
    }


def _reload_by_name(name: str) -> Dict[str, Any]:
    """Reload a single macro by name from the on-disk source."""
    global _macros
    fresh = _load_macros_from_file(MACROS_FILE)
    match = next((m for m in fresh if m.name == name), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"macro name '{name}' not found in source")
    idx = next((i for i, m in enumerate(_macros) if m.name == name), None)
    if idx is not None:
        _macros[idx] = match
        action = "updated"
    else:
        _macros.append(match)
        action = "added"
    logger.info("system_reload_macros(mode=by_name, name=%s): %s", name, action)
    return {
        "ok": True,
        "mode": "by_name",
        "name": name,
        "action": action,
        "macro": match.model_dump(),
    }


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Warm the macro store on startup
_macros = _load_macros_from_file(MACROS_FILE)
_macros_loaded_at = time.time()


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class InvokeRequest(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _get_str_arg(arguments: Dict[str, Any], key: str) -> str:
    """Extract and strip a string argument, returning empty string if absent."""
    return str(arguments.get(key) or "").strip()


def _tool_system_reload_macros(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Primary implementation of system_reload_macros."""
    mode: str = _get_str_arg(arguments, "mode") or "all"
    if mode == "all":
        return _reload_all()
    if mode == "by_id":
        macro_id = _get_str_arg(arguments, "id")
        if not macro_id:
            raise HTTPException(status_code=422, detail="'id' is required for mode=by_id")
        return _reload_by_id(macro_id)
    if mode == "by_name":
        name = _get_str_arg(arguments, "name")
        if not name:
            raise HTTPException(status_code=422, detail="'name' is required for mode=by_name")
        return _reload_by_name(name)
    raise HTTPException(status_code=422, detail=f"Unknown mode '{mode}'. Use 'all', 'by_id', or 'by_name'.")


def _tool_system_macros_reload(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Deprecated alias for system_reload_macros.  Kept for backward compatibility."""
    # Preserve backward-compatible default: always mode=all
    if "mode" not in arguments:
        arguments = {**arguments, "mode": "all"}
    return _tool_system_reload_macros(arguments)


def _tool_system_reload(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Reload the system.  Reloads all macros by default unless bypass_macros=true."""
    bypass_macros: bool = bool(arguments.get("bypass_macros", False))
    result: Dict[str, Any] = {"ok": True, "components": {}}
    if not bypass_macros:
        result["components"]["macros"] = _tool_system_reload_macros({"mode": "all"})
    return result


_tool_registry: Dict[str, Any] = {
    "system_reload_macros": _tool_system_reload_macros,
    "system_macros_reload": _tool_system_macros_reload,
    "system_reload": _tool_system_reload,
}

_tool_schemas: List[Dict[str, Any]] = [
    {
        "name": "system_reload_macros",
        "description": (
            "Reload assistant macros from the configured source. "
            "Use mode='all' to reload everything, mode='by_id' + id=<id> to reload one macro by its id, "
            "or mode='by_name' + name=<name> to reload one macro by its name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["all", "by_id", "by_name"],
                    "description": "Reload scope.  Defaults to 'all'.",
                },
                "id": {
                    "type": "string",
                    "description": "Macro id to reload.  Required when mode='by_id'.",
                },
                "name": {
                    "type": "string",
                    "description": "Macro name to reload.  Required when mode='by_name'.",
                },
            },
        },
    },
    {
        "name": "system_macros_reload",
        "description": (
            "[Deprecated — use system_reload_macros instead] "
            "Reload all assistant macros from the configured source.  "
            "Kept for backward compatibility; delegates to system_reload_macros with mode='all'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["all", "by_id", "by_name"],
                    "description": "Reload scope.  Defaults to 'all'.",
                },
                "id": {"type": "string"},
                "name": {"type": "string"},
            },
        },
    },
    {
        "name": "system_reload",
        "description": (
            "Reload the Jarvis system.  Calls system_reload_macros(mode=all) by default. "
            "Pass bypass_macros=true to skip macro reloading."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bypass_macros": {
                    "type": "boolean",
                    "description": "If true, skip reloading macros.  Default false.",
                },
            },
        },
    },
]


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "macros_count": len(_macros),
        "macros_loaded_at": _macros_loaded_at,
    }


@app.get("/jarvis/api/debug/status")
async def debug_status() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "dependencies": {
            "macros": {
                "ok": True,
                "count": len(_macros),
                "loaded_at": _macros_loaded_at,
                "source": MACROS_FILE,
            },
        },
    }


@app.get("/macros")
async def list_macros() -> Dict[str, Any]:
    return {"macros": [m.model_dump() for m in _macros]}


@app.post("/invoke")
async def invoke(request: InvokeRequest) -> Any:
    handler = _tool_registry.get(request.tool)
    if not handler:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{request.tool}'")
    return handler(request.arguments)


@app.get("/.well-known/mcp.json")
async def manifest() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "Jarvis assistant backend — manages prompt macros and system reload operations.",
        "capabilities": {
            "tools": _tool_schemas,
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
