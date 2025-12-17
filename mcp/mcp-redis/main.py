from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import redis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_NAME = "mcp-redis"
APP_VERSION = "0.1.0"

REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
REDIS_DEFAULT_DB = int(os.getenv("REDIS_DB", "0"))


def _redis_client() -> redis.Redis:
    if not REDIS_URL:
        raise HTTPException(status_code=503, detail="redis_unconfigured")
    try:
        return redis.from_url(
            REDIS_URL,
            db=REDIS_DEFAULT_DB,
            decode_responses=True,
            socket_connect_timeout=float(os.getenv("REDIS_CONNECT_TIMEOUT", "2")),
            socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT", "5")),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"redis_client_error:{exc}") from exc


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "redis_ping",
            "description": "Ping Redis and return a simple status.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "redis_get",
            "description": "Get a string value by key.",
            "input_schema": {
                "type": "object",
                "required": ["key"],
                "properties": {"key": {"type": "string"}},
            },
        },
        {
            "name": "redis_set",
            "description": "Set a string value by key. Optional TTL in seconds.",
            "input_schema": {
                "type": "object",
                "required": ["key", "value"],
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "ttl_seconds": {"type": "integer", "minimum": 1},
                },
            },
        },
        {
            "name": "redis_del",
            "description": "Delete one or more keys.",
            "input_schema": {
                "type": "object",
                "required": ["keys"],
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}, "minItems": 1}
                },
            },
        },
        {
            "name": "redis_scan",
            "description": "Scan keys with an optional pattern and count hint.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "match": {"type": "string"},
                    "count": {"type": "integer", "minimum": 1},
                },
            },
        },
    ]


class InvokePayload(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


def redis_ready() -> bool:
    return bool(REDIS_URL)


@app.get("/health")
async def health() -> Dict[str, Any]:
    status = "ok" if redis_ready() else "degraded"
    detail: Any = None
    if redis_ready():
        try:
            pong = _redis_client().ping()
            detail = {"ping": pong}
            if not pong:
                status = "error"
        except HTTPException as exc:
            status = "error"
            detail = exc.detail
    return {
        "status": status,
        "redisReady": redis_ready(),
        "redisUrlConfigured": bool(REDIS_URL),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
    }


@app.get("/.well-known/mcp.json")
async def manifest() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "Redis utility MCP provider",
        "capabilities": {"tools": tool_definitions()},
    }


@app.post("/invoke")
async def invoke(payload: InvokePayload) -> Dict[str, Any]:
    tool = payload.tool
    args = payload.arguments or {}
    client = _redis_client()

    if tool == "redis_ping":
        return {"pong": bool(client.ping())}

    if tool == "redis_get":
        key = str(args.get("key") or "").strip()
        if not key:
            raise HTTPException(status_code=400, detail="key is required")
        return {"key": key, "value": client.get(key)}

    if tool == "redis_set":
        key = str(args.get("key") or "").strip()
        value = str(args.get("value") or "").strip()
        if not key:
            raise HTTPException(status_code=400, detail="key is required")
        ttl = args.get("ttl_seconds")
        if ttl is not None:
            try:
                ttl_int = int(ttl)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="ttl_seconds must be numeric")
            if ttl_int < 1:
                raise HTTPException(status_code=400, detail="ttl_seconds must be >= 1")
            ok = client.set(name=key, value=value, ex=ttl_int)
        else:
            ok = client.set(name=key, value=value)
        return {"ok": bool(ok), "key": key}

    if tool == "redis_del":
        keys = args.get("keys")
        if not isinstance(keys, list) or not keys:
            raise HTTPException(status_code=400, detail="keys must be a non-empty list")
        keys_norm = [str(k).strip() for k in keys if k is not None and str(k).strip()]
        if not keys_norm:
            raise HTTPException(status_code=400, detail="keys must be a non-empty list")
        deleted = int(client.delete(*keys_norm))
        return {"deleted": deleted, "keys": keys_norm}

    if tool == "redis_scan":
        match = args.get("match")
        count = args.get("count")
        scan_kwargs: Dict[str, Any] = {}
        if isinstance(match, str) and match.strip():
            scan_kwargs["match"] = match.strip()
        if count is not None:
            try:
                count_int = int(count)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="count must be numeric")
            if count_int < 1:
                raise HTTPException(status_code=400, detail="count must be >= 1")
            scan_kwargs["count"] = count_int

        cursor = 0
        keys_out: List[str] = []
        max_rounds = int(os.getenv("REDIS_SCAN_MAX_ROUNDS", "10"))
        rounds = 0
        while True:
            cursor, batch = client.scan(cursor=cursor, **scan_kwargs)
            keys_out.extend(batch)
            rounds += 1
            if cursor == 0 or rounds >= max_rounds:
                break
        return {"keys": keys_out, "count": len(keys_out), "rounds": rounds, "truncated": cursor != 0}

    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


@app.get("/")
async def root() -> Dict[str, Any]:
    return {"service": APP_NAME, "version": APP_VERSION, "status": "ok"}
