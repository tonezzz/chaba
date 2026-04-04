from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

RECENT_DIALOG_TTL_SECONDS = int(os.getenv("JARVIS_RECENT_DIALOG_TTL_SECONDS") or "21600")
RECENT_DIALOG_MAX_TURNS = int(os.getenv("JARVIS_RECENT_DIALOG_MAX_TURNS") or "40")
RECENT_DIALOG_MAX_CHARS = int(os.getenv("JARVIS_RECENT_DIALOG_MAX_CHARS") or "4000")

_RECENT_DIALOG_MEM: dict[str, list[dict[str, Any]]] = {}


def recent_dialog_redis_key(session_id: str) -> str:
    """Generate Redis key for recent dialog"""
    sid = str(session_id or "").strip()
    return f"jarvis:recent_dialog:v1:{sid}"


def recent_dialog_should_store(role: str, text: str) -> bool:
    """Check if dialog should be stored"""
    r = str(role or "").strip().lower()
    if r not in {"user", "model"}:
        return False
    
    t = str(text or "").strip()
    if not t:
        return False
    
    # Filter out very short or system-only messages
    if len(t) < 3:
        return False
    
    # Filter out debug/system messages
    low = t.lower()
    if low.startswith("debug:") or low.startswith("system:") or low.startswith("trace:"):
        return False
    
    return True


def clamp_text(s: Any, limit: int) -> str:
    """Clamp text to specified limit"""
    try:
        t = str(s or "")
    except Exception:
        return ""
    
    t = t.strip()
    if not t:
        return ""
    if len(t) > limit:
        return t[:limit].rstrip() + "…"
    return t


async def recent_dialog_append(session_id: str | None, role: str, text: str, *, trace_id: str | None = None) -> None:
    """Append dialog to recent history"""
    sid = str(session_id or "").strip()
    if not sid:
        return
    
    if not recent_dialog_should_store(role, text):
        return
    
    entry = {
        "role": str(role or "").strip().lower(),
        "text": clamp_text(text, RECENT_DIALOG_MAX_CHARS),
        "ts": int(time.time()),
        "trace_id": str(trace_id or "").strip() or None,
    }
    
    if sid not in _RECENT_DIALOG_MEM:
        _RECENT_DIALOG_MEM[sid] = []
    
    mem = _RECENT_DIALOG_MEM[sid]
    mem.append(entry)
    
    # Keep only recent turns
    if len(mem) > RECENT_DIALOG_MAX_TURNS:
        _RECENT_DIALOG_MEM[sid] = mem[-RECENT_DIALOG_MAX_TURNS:]
    
    # TODO: Store in Redis if available


async def recent_dialog_load(session_id: str | None) -> list[dict[str, Any]]:
    """Load recent dialog history"""
    sid = str(session_id or "").strip()
    if not sid:
        return []
    
    # TODO: Load from Redis if available
    return _RECENT_DIALOG_MEM.get(sid, [])


async def recent_dialog_prune() -> None:
    """Prune old dialog entries"""
    now = int(time.time())
    cutoff = now - RECENT_DIALOG_TTL_SECONDS
    
    for sid, entries in list(_RECENT_DIALOG_MEM.items()):
        # Filter out old entries
        filtered = [e for e in entries if e.get("ts", 0) > cutoff]
        if filtered:
            _RECENT_DIALOG_MEM[sid] = filtered
        else:
            _RECENT_DIALOG_MEM.pop(sid, None)


def format_recent_dialog_for_context(entries: list[dict[str, Any]], max_chars: int = 1200) -> str:
    """Format recent dialog for context"""
    if not entries:
        return ""
    
    lines = []
    total_chars = 0
    
    for entry in entries[-10:]:  # Last 10 entries
        role = entry.get("role", "unknown")
        text = entry.get("text", "")
        if not text:
            continue
        
        line = f"{role.title()}: {text}"
        if total_chars + len(line) > max_chars:
            break
        
        lines.append(line)
        total_chars += len(line)
    
    return "\n".join(lines)
