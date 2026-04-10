from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

import httpx
from fastapi import WebSocket

from jarvis.feature_flags import feature_enabled
from jarvis.providers.smart import get_smart_provider, SmartProvider
from jarvis.models import seed_all_models, get_model_registry_summary

logger = logging.getLogger(__name__)

INSTANCE_ID = str(uuid.uuid4())
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "").strip()
JARVIS_SESSION_DB = os.getenv("JARVIS_SESSION_DB", "/data/jarvis_sessions.sqlite").strip()
JARVIS_LEGACY_REMINDER_NOTIFICATIONS_ENABLED = str(os.getenv("JARVIS_LEGACY_REMINDER_NOTIFICATIONS_ENABLED", "false")).strip().lower() == "true"
JARVIS_AGENTS_DIR = os.getenv("JARVIS_AGENTS_DIR", "/app/agents").strip()
JARVIS_AGENT_CONTINUE_WINDOW_SECONDS = int(os.getenv("JARVIS_AGENT_CONTINUE_WINDOW_SECONDS", "120"))
JARVIS_MEMORY_CACHE_TTL_SECONDS = int(os.getenv("JARVIS_MEMORY_CACHE_TTL_SECONDS", "60"))
JARVIS_KNOWLEDGE_CACHE_TTL_SECONDS = int(os.getenv("JARVIS_KNOWLEDGE_CACHE_TTL_SECONDS", "120"))
JARVIS_GEMS_DRAFT_TTL_SECONDS = int(os.getenv("JARVIS_GEMS_DRAFT_TTL_SECONDS", "3600"))
JARVIS_GEMS_CACHE_TTL_SECONDS = int(os.getenv("JARVIS_GEMS_CACHE_TTL_SECONDS", "120"))
JARVIS_RECENT_DIALOG_TTL_HOURS = int(os.getenv("JARVIS_RECENT_DIALOG_TTL_HOURS", "24"))
JARVIS_RECENT_DIALOG_MAX_TURNS = int(os.getenv("JARVIS_RECENT_DIALOG_MAX_TURNS", "200"))
JARVIS_RECENT_DIALOG_MAX_TOKENS = int(os.getenv("JARVIS_RECENT_DIALOG_MAX_TOKENS", "8000"))

try:
    from google import genai
    from google.genai import types
    from google.genai import errors as genai_errors
except Exception:
    class _GenaiErrorsStub:
        class ClientError(Exception):
            pass

    class _GenaiStub:
        class Client:
            def __init__(self, *args: Any, **kwargs: Any):
                raise RuntimeError("google-genai is not installed")

    class _GenaiTypesStub:
        pass

    genai = _GenaiStub()
    types = _GenaiTypesStub()
    genai_errors = _GenaiErrorsStub()

try:
    import redis.asyncio as redis_async
except Exception:
    redis_async = None


class WebSocketSession:
    """Manages a WebSocket session with Jarvis"""
    
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.session_id = self._extract_session_id()
        self.client = None
        self.config = None
        self.session = None
        self._redis_client = None
        
    def _extract_session_id(self) -> str:
        """Extract session_id from query params"""
        try:
            session_id = self.ws.query_params.get("session_id", "")
            if not session_id:
                session_id = str(uuid.uuid4())
            return str(session_id).strip()
        except Exception:
            return str(uuid.uuid4())
    
    async def initialize(self) -> None:
        """Initialize the session with smart model selection."""
        # Store session_id on WebSocket state
        self.ws.state.session_id = self.session_id
        
        # Initialize Redis if available
        self._redis_client = await self._get_redis_client()
        
        # Get smart provider for model selection
        self.smart_provider = get_smart_provider()
        
        # Initialize Gemini client
        self.client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY", ""),
            http_options={"api_version": "v1alpha"}
        )
        
        # Configure session
        self.config = {
            "generation_config": {
                "response_modalities": ["AUDIO", "TEXT"],
                "speech_config": {
                    "voice_config": {"prebuilt_voice_id": "Puck"},
                },
                "temperature": 0.7,
            },
            "system_instruction": {
                "parts": [{"text": self._get_system_instruction()}],
            },
        }
        
        # Select model based on default chat task (can be re-selected later)
        model_id, provider, task = self.smart_provider.select_model(
            "Hello",  # Default greeting to classify as chat
            has_attachment=False,
        )
        
        # Map to Gemini model (for now, only Gemini Live is supported)
        # Future: route to different providers based on selection
        gemini_model = self._map_to_gemini_model(model_id)
        
        logger.info(
            "Session %s: selected model=%s (task=%s, provider=%s)",
            self.session_id[:8],
            model_id,
            task.primary_type.value,
            provider
        )
        
        # Start Gemini session
        self.session = self.client.aio.live.connect(
            model=gemini_model,
            config=self.config,
        )
        
        # Store selected model info
        self.selected_model = model_id
        self.selected_provider = provider
        
        # Load session state
        await self._load_session_state()
    
    def _map_to_gemini_model(self, model_id: str) -> str:
        """Map selected model to Gemini Live-compatible model."""
        # For now, we only support Gemini Live models
        # Future: route to OpenRouter/Anthropic via HTTP mode
        
        gemini_models = {
            "gemini-2.5-flash": "models/gemini-2.5-flash-preview-tts",
            "gemini-2.5-flash-lite-preview": "models/gemini-2.5-flash-lite-preview",
            "gemini-2.0-flash-exp": "models/gemini-2.0-flash-exp",
        }
        
        # Default to flash-exp for Live API compatibility
        return gemini_models.get(model_id, "models/gemini-2.0-flash-exp")
        
    async def _get_redis_client(self) -> Any:
        """Get Redis client if available"""
        if redis_async is None:
            return None
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            return await redis_async.from_url(redis_url, decode_responses=True)
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}")
            return None
    
    def _get_system_instruction(self) -> str:
        """Get system instruction for Gemini"""
        # Get available models for reference
        models_summary = get_model_registry_summary()
        free_models = [m for m in models_summary if m["cost_input"] == "0"]
        
        return f"""\
You are Jarvis, a helpful AI assistant.

Available AI providers: Gemini, OpenRouter (free models), Anthropic, OpenAI.
Free models available: {len(free_models)} (Claude 3.5 Sonnet, Gemini 2.0 Flash, Llama 3.3, etc.)

Be concise, helpful, and accurate. If you're unsure about something, admit it.
        """.strip()
    
    async def _load_session_state(self) -> None:
        """Load session state from cache/storage"""
        # Apply cached memory if available
        cached = self._get_cached_sheet_memory()
        if cached:
            self._apply_cached_sheet_memory_to_ws(cached)
    
    def _get_cached_sheet_memory(self) -> Optional[dict[str, Any]]:
        """Get cached sheet memory (placeholder)"""
        # This would be implemented in memory module
        return None
    
    def _apply_cached_sheet_memory_to_ws(self, cached: dict[str, Any]) -> None:
        """Apply cached memory to WebSocket state"""
        try:
            self.ws.state.sys_kv = cached.get("sys_kv")
            self.ws.state.memory_items = cached.get("memory_items")
            self.ws.state.memory_sheet_name = cached.get("memory_sheet_name")
            self.ws.state.memory_context_text = cached.get("memory_context_text")
        except Exception as e:
            logger.warning(f"Failed to apply cached memory: {e}")
    
    async def send_json(self, data: dict[str, Any], trace_id: Optional[str] = None) -> None:
        """Send JSON message to WebSocket"""
        try:
            message = json.dumps(data)
            await self.ws.send_text(message)
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {e}")
    
    async def send_progress(self, message: str, phase: str = "progress", **kwargs) -> None:
        """Send progress message"""
        await self.send_json({
            "type": "progress",
            "text": message,
            "phase": phase,
            "instance_id": INSTANCE_ID,
            **kwargs
        })
    
    async def close(self) -> None:
        """Close the session"""
        try:
            if self.session:
                await self.session.close()
            if self._redis_client:
                await self._redis_client.close()
        except Exception as e:
            logger.warning(f"Error closing WebSocket session: {e}")


class WebSocketManager:
    """Manages multiple WebSocket sessions"""
    
    def __init__(self):
        self.active_sessions: dict[str, WebSocketSession] = {}
        
    async def handle_connection(self, ws: WebSocket) -> None:
        """Handle new WebSocket connection"""
        session = WebSocketSession(ws)
        
        try:
            await session.initialize()
            self.active_sessions[session.session_id] = session
            
            # Handle the WebSocket communication
            await self._handle_websocket_loop(session)
            
        except Exception as e:
            logger.error(f"WebSocket session error: {e}")
        finally:
            await session.close()
            self.active_sessions.pop(session.session_id, None)
    
    async def _handle_websocket_loop(self, session: WebSocketSession) -> None:
        """Main WebSocket communication loop"""
        await session.ws.accept()
        
        # Send session resume data
        await self._emit_session_resume(session)
        
        # Start concurrent loops
        await asyncio.gather(
            self._ws_to_gemini(session),
            self._gemini_to_ws(session),
            return_exceptions=True
        )
    
    async def _emit_session_resume(self, session: WebSocketSession) -> None:
        """Emit session resume data"""
        # Implementation would load recent dialog and send to client
        pass
    
    async def _ws_to_gemini(self, session: WebSocketSession) -> None:
        """Forward WebSocket messages to Gemini"""
        try:
            while True:
                data = await session.ws.receive_text()
                message = json.loads(data)
                
                # Handle different message types
                if message.get("type") == "text":
                    await session.session.send(message.get("text", ""))
                elif message.get("type") == "audio":
                    # Handle audio data
                    pass
                    
        except Exception as e:
            logger.error(f"ws_to_gemini error: {e}")
    
    async def _gemini_to_ws(self, session: WebSocketSession) -> None:
        """Forward Gemini responses to WebSocket"""
        try:
            async for response in session.session.receive():
                if response.text:
                    await session.send_json({
                        "type": "text",
                        "text": response.text,
                        "instance_id": INSTANCE_ID
                    })
                elif response.data:
                    # Handle audio/data responses
                    pass
                    
        except Exception as e:
            logger.error(f"gemini_to_ws error: {e}")
    
    async def broadcast_to_all(self, message: dict[str, Any]) -> None:
        """Broadcast message to all active sessions"""
        for session in self.active_sessions.values():
            try:
                await session.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to broadcast to session {session.session_id}: {e}")


# Global manager instance
websocket_manager = WebSocketManager()
