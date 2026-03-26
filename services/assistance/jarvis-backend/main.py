from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.responses import JSONResponse

APP_NAME = "jarvis-backend"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8018"))

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()

app = FastAPI(title=APP_NAME, version=APP_VERSION)


def _check_deps() -> List[Dict[str, Any]]:
    deps: List[Dict[str, Any]] = []

    gemini_ok = bool(GEMINI_API_KEY)
    deps.append(
        {
            "name": "gemini",
            "ok": gemini_ok,
            "detail": "api key configured" if gemini_ok else "GEMINI_API_KEY not set",
        }
    )

    return deps


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": APP_NAME, "version": APP_VERSION}


def _debug_status_response() -> JSONResponse:
    deps = _check_deps()
    overall_ok = all(d["ok"] for d in deps)
    return JSONResponse(
        status_code=200,
        content={"ok": overall_ok, "deps": deps},
    )


@app.get("/debug/status")
def debug_status() -> JSONResponse:
    return _debug_status_response()


@app.get("/jarvis/api/debug/status")
def jarvis_api_debug_status() -> JSONResponse:
    return _debug_status_response()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
