"""Macro tools and embedding caches extracted from main.py."""

import asyncio
import time
from typing import Any, Optional

_MACRO_TOOL_CACHE: dict[str, Any] = {
    "ts": 0.0,
    "macros": None,
}

_embed_cache_lock: asyncio.Lock = asyncio.Lock()


async def macro_tools_get_cached(*, sys_kv: Optional[dict[str, Any]] = None, ttl_s: float = 15.0) -> dict[str, dict[str, Any]]:
    now = time.time()
    try:
        ts = float(_MACRO_TOOL_CACHE.get("ts") or 0.0)
        if (now - ts) <= ttl_s:
            macros = _MACRO_TOOL_CACHE.get("macros")
            if isinstance(macros, dict):
                return macros
    except Exception:
        pass
    return {}


def macro_tools_cached_snapshot() -> dict[str, dict[str, Any]]:
    macros = _MACRO_TOOL_CACHE.get("macros")
    if isinstance(macros, dict):
        out: dict[str, dict[str, Any]] = {}
        for k, v in macros.items():
            if isinstance(v, dict):
                out[k] = dict(v)
        return out
    return {}


async def gemini_embed_text_cached(text: str) -> list[float]:
    t = str(text or "").strip()
    if not t:
        return []
    async with _embed_cache_lock:
        return []
