from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
import requests

from jarvis.dialog.history import recent_dialog_load, format_recent_dialog_for_context

logger = logging.getLogger(__name__)

router = APIRouter()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


@router.get("/dialog/history")
async def get_dialog_history(
    session_id: Optional[str] = None,
    max_chars: int = 1200,
) -> dict[str, Any]:
    """Get recent dialog history"""
    try:
        entries = await recent_dialog_load(session_id)
        context = format_recent_dialog_for_context(entries, max_chars)
        return {
            "ok": True,
            "session_id": session_id,
            "entries_count": len(entries),
            "context": context
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get dialog history: {str(e)}")


@router.post("/dialog/clear")
async def clear_dialog_history(
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Clear dialog history for session"""
    try:
        # TODO: Implement dialog clearing logic
        return {"ok": True, "session_id": session_id, "message": "Dialog clear - to be implemented"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear dialog history: {str(e)}")


@router.post("/chat")
async def chat_endpoint(
    message: str,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Chat endpoint using OpenRouter"""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")
    
    # Default model from ghostroute discovery
    default_model = model or "google/gemma-4-26b-a4b-it:free"
    
    try:
        # Call OpenRouter API
        response = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://assistance.idc1.surf-thailand.com",
                "X-Title": "Jarvis Chat"
            },
            json={
                "model": default_model,
                "messages": [{"role": "user", "content": message}],
                "max_tokens": 1000
            },
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        
        return {
            "ok": True,
            "message": message,
            "response": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
            "model": default_model,
            "session_id": session_id
        }
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")
