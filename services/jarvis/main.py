from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

APP_NAME = "jarvis-api"
APP_VERSION = "0.1.0"
DEFAULT_PORT = int(os.environ.get("PORT", os.environ.get("JARVIS_PORT", "8070")))


def build_debug_status() -> Dict[str, Any]:
    """Build the debug-status payload.

    Dependency checks are best-effort: any failure is reflected in the
    ``ok`` flag and the ``deps`` list rather than raising an HTTP error,
    so the endpoint never returns 5xx even when dependencies are down.
    """
    deps: List[Dict[str, Any]] = [
        # Add real dependency probes here as the service grows.
        # Example shape: {"name": "database", "ok": True, "detail": "connected"}
    ]
    overall_ok: bool = all(d.get("ok", False) for d in deps) if deps else True
    return {"ok": overall_ok, "deps": deps, "version": APP_VERSION}


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/jarvis/api/debug/status")
async def debug_status() -> Dict[str, Any]:
    """Return structured health/dependency status for the Jarvis UI."""
    return build_debug_status()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=DEFAULT_PORT, reload=False)
