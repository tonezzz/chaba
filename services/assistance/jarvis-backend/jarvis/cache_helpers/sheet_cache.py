"""Sheet memory/knowledge/gems cache helpers extracted from main.py."""

import os
import time
from typing import Any, Optional

from fastapi import WebSocket


_SHEET_MEMORY_CACHE: dict[str, Any] = {
    "loaded_at": 0,
    "created_at": 0,
    "updated_at": 0,
    "sys_kv": None,
    "memory_items": None,
    "memory_sheet_name": None,
    "memory_context_text": "",
}

_SHEET_KNOWLEDGE_CACHE: dict[str, Any] = {
    "loaded_at": 0,
    "created_at": 0,
    "updated_at": 0,
    "knowledge_items": None,
    "knowledge_sheet_name": None,
    "knowledge_context_text": "",
}

_SHEET_GEMS_CACHE: dict[str, Any] = {
    "loaded_at": 0,
    "created_at": 0,
    "updated_at": 0,
    "gems": None,
    "gem_ids": None,
    "gems_context_text": "",
}


def memory_cache_ttl_seconds() -> int:
    try:
        return max(5, int(os.getenv("JARVIS_MEMORY_CACHE_TTL_SECONDS") or "60"))
    except Exception:
        return 60


def knowledge_cache_ttl_seconds() -> int:
    try:
        return max(5, int(os.getenv("JARVIS_KNOWLEDGE_CACHE_TTL_SECONDS") or "120"))
    except Exception:
        return 120


def gems_cache_ttl_seconds() -> int:
    try:
        v = int(str(os.getenv("JARVIS_GEMS_CACHE_TTL_SECONDS") or "120").strip())
        return v if v > 0 else 120
    except Exception:
        return 120


def get_cached_sheet_memory() -> Optional[dict[str, Any]]:
    now = int(time.time())
    loaded_at = int(_SHEET_MEMORY_CACHE.get("loaded_at") or 0)
    if loaded_at <= 0:
        return None
    ttl = memory_cache_ttl_seconds()
    if (now - loaded_at) > ttl:
        return None
    return dict(_SHEET_MEMORY_CACHE)


def set_cached_sheet_memory(payload: dict[str, Any]) -> None:
    now = int(time.time())
    try:
        if int(_SHEET_MEMORY_CACHE.get("created_at") or 0) <= 0:
            _SHEET_MEMORY_CACHE["created_at"] = now
            _SHEET_MEMORY_CACHE["loaded_at"] = now
    except Exception:
        _SHEET_MEMORY_CACHE["created_at"] = now
        _SHEET_MEMORY_CACHE["loaded_at"] = now
    _SHEET_MEMORY_CACHE["loaded_at"] = now
    _SHEET_MEMORY_CACHE["updated_at"] = now
    _SHEET_MEMORY_CACHE["sys_kv"] = payload.get("sys_kv")
    _SHEET_MEMORY_CACHE["memory_items"] = payload.get("memory_items")
    _SHEET_MEMORY_CACHE["memory_sheet_name"] = payload.get("memory_sheet_name")
    _SHEET_MEMORY_CACHE["memory_context_text"] = str(payload.get("memory_context_text") or "")


def clear_sheet_caches() -> None:
    try:
        _SHEET_MEMORY_CACHE["loaded_at"] = 0
        _SHEET_MEMORY_CACHE["created_at"] = 0
        _SHEET_MEMORY_CACHE["updated_at"] = 0
        _SHEET_MEMORY_CACHE["sys_kv"] = None
        _SHEET_MEMORY_CACHE["memory_items"] = None
        _SHEET_MEMORY_CACHE["memory_sheet_name"] = None
        _SHEET_MEMORY_CACHE["memory_context_text"] = ""
    except Exception:
        pass
    try:
        _SHEET_KNOWLEDGE_CACHE["loaded_at"] = 0
        _SHEET_KNOWLEDGE_CACHE["created_at"] = 0
        _SHEET_KNOWLEDGE_CACHE["updated_at"] = 0
        _SHEET_KNOWLEDGE_CACHE["knowledge_items"] = None
        _SHEET_KNOWLEDGE_CACHE["knowledge_sheet_name"] = None
        _SHEET_KNOWLEDGE_CACHE["knowledge_context_text"] = ""
    except Exception:
        pass
    try:
        _SHEET_GEMS_CACHE["loaded_at"] = 0
        _SHEET_GEMS_CACHE["created_at"] = 0
        _SHEET_GEMS_CACHE["updated_at"] = 0
        _SHEET_GEMS_CACHE["gems"] = None
        _SHEET_GEMS_CACHE["gem_ids"] = None
        _SHEET_GEMS_CACHE["gems_context_text"] = ""
    except Exception:
        pass


def apply_cached_sheet_memory_to_ws(ws: WebSocket, cached: dict[str, Any]) -> None:
    try:
        ws.state.sys_kv = cached.get("sys_kv")
        ws.state.memory_items = cached.get("memory_items")
        ws.state.memory_sheet_name = cached.get("memory_sheet_name")
        ws.state.memory_context_text = cached.get("memory_context_text")
    except Exception:
        pass


def set_cached_sys_kv_only(sys_kv: dict[str, str]) -> None:
    try:
        now = int(time.time())
        if _SHEET_MEMORY_CACHE.get("created_at", 0) <= 0:
            _SHEET_MEMORY_CACHE["created_at"] = now
            _SHEET_MEMORY_CACHE["loaded_at"] = now
        _SHEET_MEMORY_CACHE["loaded_at"] = now
        _SHEET_MEMORY_CACHE["updated_at"] = now
        _SHEET_MEMORY_CACHE["sys_kv"] = sys_kv
    except Exception:
        pass


def get_cached_sheet_knowledge() -> Optional[dict[str, Any]]:
    now = int(time.time())
    loaded_at = int(_SHEET_KNOWLEDGE_CACHE.get("loaded_at") or 0)
    if loaded_at <= 0:
        return None
    ttl = knowledge_cache_ttl_seconds()
    if (now - loaded_at) > ttl:
        return None
    return dict(_SHEET_KNOWLEDGE_CACHE)


def set_cached_sheet_knowledge(payload: dict[str, Any]) -> None:
    now = int(time.time())
    try:
        if int(_SHEET_KNOWLEDGE_CACHE.get("created_at") or 0) <= 0:
            _SHEET_KNOWLEDGE_CACHE["created_at"] = now
            _SHEET_KNOWLEDGE_CACHE["loaded_at"] = now
    except Exception:
        _SHEET_KNOWLEDGE_CACHE["created_at"] = now
        _SHEET_KNOWLEDGE_CACHE["loaded_at"] = now
    _SHEET_KNOWLEDGE_CACHE["loaded_at"] = now
    _SHEET_KNOWLEDGE_CACHE["updated_at"] = now
    _SHEET_KNOWLEDGE_CACHE["knowledge_items"] = payload.get("knowledge_items")
    _SHEET_KNOWLEDGE_CACHE["knowledge_sheet_name"] = payload.get("knowledge_sheet_name")
    _SHEET_KNOWLEDGE_CACHE["knowledge_context_text"] = str(payload.get("knowledge_context_text") or "")


def apply_cached_sheet_knowledge_to_ws(ws: WebSocket, cached: dict[str, Any]) -> None:
    try:
        ws.state.knowledge_items = cached.get("knowledge_items")
        ws.state.knowledge_sheet_name = cached.get("knowledge_sheet_name")
        ws.state.knowledge_context_text = cached.get("knowledge_context_text")
    except Exception:
        pass


def get_cached_sheet_gems() -> Optional[dict[str, Any]]:
    now = int(time.time())
    loaded_at = int(_SHEET_GEMS_CACHE.get("loaded_at") or 0)
    if loaded_at <= 0:
        return None
    ttl = gems_cache_ttl_seconds()
    if (now - loaded_at) > ttl:
        return None
    gems = _SHEET_GEMS_CACHE.get("gems")
    gem_ids = _SHEET_GEMS_CACHE.get("gem_ids")
    if not gems and not gem_ids:
        return None
    return dict(_SHEET_GEMS_CACHE)


def set_cached_sheet_gems(payload: dict[str, Any]) -> None:
    _SHEET_GEMS_CACHE["loaded_at"] = int(time.time())
    _SHEET_GEMS_CACHE["gems"] = payload.get("gems")
    _SHEET_GEMS_CACHE["gem_ids"] = payload.get("gem_ids")
    _SHEET_GEMS_CACHE["gems_context_text"] = str(payload.get("gems_context_text") or "")
