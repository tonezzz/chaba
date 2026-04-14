from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

JARVIS_MEMORY_CACHE_TTL_SECONDS = int(os.getenv("JARVIS_MEMORY_CACHE_TTL_SECONDS", "60"))
JARVIS_KNOWLEDGE_CACHE_TTL_SECONDS = int(os.getenv("JARVIS_KNOWLEDGE_CACHE_TTL_SECONDS", "120"))
JARVIS_GEMS_DRAFT_TTL_SECONDS = int(os.getenv("JARVIS_GEMS_DRAFT_TTL_SECONDS", "3600"))
JARVIS_GEMS_CACHE_TTL_SECONDS = int(os.getenv("JARVIS_GEMS_CACHE_TTL_SECONDS", "120"))
JARVIS_GEMS_DRAFT_MAX_ENTRIES = int(os.getenv("JARVIS_GEMS_DRAFT_MAX_ENTRIES", "1000"))  # Prevent unbounded growth


# In-memory caches (these would be Redis in production)
_SHEET_MEMORY_CACHE: Dict[str, Any] = {
    "loaded_at": 0,
    "created_at": 0,
    "updated_at": 0,
    "sys_kv": None,
    "memory_items": None,
    "memory_sheet_name": None,
    "memory_context_text": "",
}

_SHEET_KNOWLEDGE_CACHE: Dict[str, Any] = {
    "loaded_at": 0,
    "created_at": 0,
    "updated_at": 0,
    "knowledge_items": None,
    "knowledge_sheet_name": None,
    "knowledge_context_text": "",
}

_SHEET_GEMS_CACHE: Dict[str, Any] = {
    "loaded_at": 0,
    "created_at": 0,
    "updated_at": 0,
    "gems": None,
    "gem_ids": None,
    "source": None,
}

_GEMS_DRAFTS: Dict[str, Dict[str, Any]] = {}


class MemoryCache:
    """Manages memory caching for Jarvis"""
    
    @staticmethod
    def get_sheet_memory() -> Optional[Dict[str, Any]]:
        """Get cached sheet memory"""
        now = int(time.time())
        loaded_at = int(_SHEET_MEMORY_CACHE.get("loaded_at") or 0)
        if loaded_at <= 0:
            return None
        
        ttl = JARVIS_MEMORY_CACHE_TTL_SECONDS
        if (now - loaded_at) > ttl:
            return None
        
        return dict(_SHEET_MEMORY_CACHE)
    
    @staticmethod
    def set_sheet_memory(payload: Dict[str, Any]) -> None:
        """Set cached sheet memory"""
        now = int(time.time())
        try:
            if int(_SHEET_MEMORY_CACHE.get("created_at") or 0) <= 0:
                _SHEET_MEMORY_CACHE["created_at"] = now
            _SHEET_MEMORY_CACHE["loaded_at"] = now
            _SHEET_MEMORY_CACHE["updated_at"] = now
            _SHEET_MEMORY_CACHE["sys_kv"] = payload.get("sys_kv")
            _SHEET_MEMORY_CACHE["memory_items"] = payload.get("memory_items")
            _SHEET_MEMORY_CACHE["memory_sheet_name"] = payload.get("memory_sheet_name")
            _SHEET_MEMORY_CACHE["memory_context_text"] = str(payload.get("memory_context_text") or "")
        except Exception as e:
            logger.error(f"Failed to set sheet memory cache: {e}")
    
    @staticmethod
    def clear_sheet_memory() -> None:
        """Clear sheet memory cache"""
        try:
            _SHEET_MEMORY_CACHE["loaded_at"] = 0
            _SHEET_MEMORY_CACHE["created_at"] = 0
            _SHEET_MEMORY_CACHE["updated_at"] = 0
            _SHEET_MEMORY_CACHE["sys_kv"] = None
            _SHEET_MEMORY_CACHE["memory_items"] = None
            _SHEET_MEMORY_CACHE["memory_sheet_name"] = None
            _SHEET_MEMORY_CACHE["memory_context_text"] = ""
        except Exception as e:
            logger.error(f"Failed to clear sheet memory cache: {e}")
    
    @staticmethod
    def get_sheet_knowledge() -> Optional[Dict[str, Any]]:
        """Get cached sheet knowledge"""
        now = int(time.time())
        loaded_at = int(_SHEET_KNOWLEDGE_CACHE.get("loaded_at") or 0)
        if loaded_at <= 0:
            return None
        
        ttl = JARVIS_KNOWLEDGE_CACHE_TTL_SECONDS
        if (now - loaded_at) > ttl:
            return None
        
        return dict(_SHEET_KNOWLEDGE_CACHE)
    
    @staticmethod
    def set_sheet_knowledge(payload: Dict[str, Any]) -> None:
        """Set cached sheet knowledge"""
        now = int(time.time())
        try:
            if int(_SHEET_KNOWLEDGE_CACHE.get("created_at") or 0) <= 0:
                _SHEET_KNOWLEDGE_CACHE["created_at"] = now
            _SHEET_KNOWLEDGE_CACHE["loaded_at"] = now
            _SHEET_KNOWLEDGE_CACHE["updated_at"] = now
            _SHEET_KNOWLEDGE_CACHE["knowledge_items"] = payload.get("knowledge_items")
            _SHEET_KNOWLEDGE_CACHE["knowledge_sheet_name"] = payload.get("knowledge_sheet_name")
            _SHEET_KNOWLEDGE_CACHE["knowledge_context_text"] = str(payload.get("knowledge_context_text") or "")
        except Exception as e:
            logger.error(f"Failed to set sheet knowledge cache: {e}")
    
    @staticmethod
    def get_sheet_gems() -> Optional[Dict[str, Any]]:
        """Get cached sheet gems"""
        now = int(time.time())
        loaded_at = int(_SHEET_GEMS_CACHE.get("loaded_at") or 0)
        if loaded_at <= 0:
            return None
        
        ttl = JARVIS_GEMS_CACHE_TTL_SECONDS
        if (now - loaded_at) > ttl:
            return None
        
        return dict(_SHEET_GEMS_CACHE)
    
    @staticmethod
    def set_sheet_gems(payload: Dict[str, Any]) -> None:
        """Set cached sheet gems"""
        _SHEET_GEMS_CACHE["loaded_at"] = int(time.time())
        _SHEET_GEMS_CACHE["gems"] = payload.get("gems")
        _SHEET_GEMS_CACHE["gem_ids"] = payload.get("gem_ids")
        _SHEET_GEMS_CACHE["source"] = payload.get("source")
    
    @staticmethod
    def set_gems_draft(draft_id: str, draft_data: Dict[str, Any]) -> None:
        """Set gems draft with LRU eviction if over max entries"""
        try:
            # Enforce max entries limit with LRU eviction
            max_entries = JARVIS_GEMS_DRAFT_MAX_ENTRIES
            if len(_GEMS_DRAFTS) >= max_entries:
                # Find and remove oldest entry
                oldest_key = None
                oldest_time = float('inf')
                for key, draft in _GEMS_DRAFTS.items():
                    updated = int(draft.get("updated_at") or 0)
                    if updated < oldest_time:
                        oldest_time = updated
                        oldest_key = key
                if oldest_key:
                    del _GEMS_DRAFTS[oldest_key]
                    logger.info(f"Evicted oldest gems draft: {oldest_key}")
            
            draft_data["updated_at"] = int(time.time())
            _GEMS_DRAFTS[draft_id] = draft_data
        except Exception as e:
            logger.error(f"Failed to set gems draft: {e}")
    
    @staticmethod
    def get_gems_draft(draft_id: str) -> Optional[Dict[str, Any]]:
        """Get gems draft"""
        draft = _GEMS_DRAFTS.get(draft_id)
        if not draft:
            return None
        
        # Check TTL
        now = int(time.time())
        updated_at = int(draft.get("updated_at") or 0)
        ttl = JARVIS_GEMS_DRAFT_TTL_SECONDS
        if (now - updated_at) > ttl:
            _GEMS_DRAFTS.pop(draft_id, None)
            return None
        
        return dict(draft)
    
    @staticmethod
    def prune_gems_drafts() -> None:
        """Prune expired gems drafts"""
        try:
            ttl = JARVIS_GEMS_DRAFT_TTL_SECONDS
            now = int(time.time())
            expired_keys = []
            
            for key, draft in _GEMS_DRAFTS.items():
                updated_at = int(draft.get("updated_at") or 0)
                if (now - updated_at) > ttl:
                    expired_keys.append(key)
            
            for key in expired_keys:
                _GEMS_DRAFTS.pop(key, None)
                
        except Exception as e:
            logger.error(f"Failed to prune gems drafts: {e}")
    
    @staticmethod
    def apply_cached_memory_to_ws_state(ws_state: Any, cached: Dict[str, Any]) -> None:
        """Apply cached memory to WebSocket state"""
        try:
            ws_state.sys_kv = cached.get("sys_kv")
            ws_state.memory_items = cached.get("memory_items")
            ws_state.memory_sheet_name = cached.get("memory_sheet_name")
            ws_state.memory_context_text = cached.get("memory_context_text")
        except Exception as e:
            logger.error(f"Failed to apply cached memory to WS state: {e}")
    
    @staticmethod
    def apply_cached_knowledge_to_ws_state(ws_state: Any, cached: Dict[str, Any]) -> None:
        """Apply cached knowledge to WebSocket state"""
        try:
            ws_state.knowledge_items = cached.get("knowledge_items")
            ws_state.knowledge_sheet_name = cached.get("knowledge_sheet_name")
            ws_state.knowledge_context_text = cached.get("knowledge_context_text")
        except Exception as e:
            logger.error(f"Failed to apply cached knowledge to WS state: {e}")
    
    @staticmethod
    def get_cache_status() -> Dict[str, Any]:
        """Get status of all caches"""
        now = int(time.time())
        
        sheet_memory_age = now - int(_SHEET_MEMORY_CACHE.get("loaded_at") or 0)
        sheet_knowledge_age = now - int(_SHEET_KNOWLEDGE_CACHE.get("loaded_at") or 0)
        sheet_gems_age = now - int(_SHEET_GEMS_CACHE.get("loaded_at") or 0)
        
        return {
            "sheet_memory": {
                "loaded": _SHEET_MEMORY_CACHE.get("loaded_at") > 0,
                "age_seconds": sheet_memory_age,
                "ttl_seconds": JARVIS_MEMORY_CACHE_TTL_SECONDS,
                "expired": sheet_memory_age > JARVIS_MEMORY_CACHE_TTL_SECONDS
            },
            "sheet_knowledge": {
                "loaded": _SHEET_KNOWLEDGE_CACHE.get("loaded_at") > 0,
                "age_seconds": sheet_knowledge_age,
                "ttl_seconds": JARVIS_KNOWLEDGE_CACHE_TTL_SECONDS,
                "expired": sheet_knowledge_age > JARVIS_KNOWLEDGE_CACHE_TTL_SECONDS
            },
            "sheet_gems": {
                "loaded": _SHEET_GEMS_CACHE.get("loaded_at") > 0,
                "age_seconds": sheet_gems_age,
                "ttl_seconds": JARVIS_GEMS_CACHE_TTL_SECONDS,
                "expired": sheet_gems_age > JARVIS_GEMS_CACHE_TTL_SECONDS
            },
            "gems_drafts": {
                "count": len(_GEMS_DRAFTS),
                "ttl_seconds": JARVIS_GEMS_DRAFT_TTL_SECONDS
            }
        }


# Global cache instance
memory_cache = MemoryCache()
