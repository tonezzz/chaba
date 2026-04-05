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
        """Initialize the session"""
        # Store session_id on WebSocket state
        self.ws.state.session_id = self.session_id
        
        # Initialize Redis if available
        self._redis_client = await self._get_redis_client()
        
        # Initialize Gemini client
        self.client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY", ""),
            http_options={"api_version": "v1alpha"}
        )
        
        # Configure session
        self.config = types.LiveConnectConfig(
            temperature=0.7,
        )
        
        # Start Gemini session
        try:
            # Try a different model that might be more compatible
            model_name = "gemini-2.0-flash-exp"
            # Remove "models/" prefix if present
            if model_name.startswith("models/"):
                model_name = model_name[7:]
            
            print(f"Using model: {model_name}")
            print(f"Config: {self.config}")
            
            self.session = self.client.aio.live.connect(
                model=model_name,
                config=self.config,
            )
            print("Gemini Live session connected successfully")
        except Exception as e:
            print(f"Failed to connect to Gemini Live API: {e}")
            print("Using fallback echo mode")
            self.session = None
        
        # Load session state
        await self._load_session_state()
        
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
        return """
You are Jarvis, a helpful AI assistant. You have access to various tools and capabilities.
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
            # Session is automatically closed by async context manager in _handle_gemini_session
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
        
        # Handle WebSocket communication with proper session management
        await self._handle_gemini_session(session)
    
    async def _emit_session_resume(self, session: WebSocketSession) -> None:
        """Emit session resume data"""
        # Implementation would load recent dialog and send to client
        pass
    
    async def _handle_gemini_session(self, session: WebSocketSession) -> None:
        """Handle Gemini session and WebSocket communication"""
        if session.session is None:
            # Fallback echo mode
            await self._handle_echo_mode(session)
            return
            
        try:
            async with session.session as gemini_session:
                # Create tasks for concurrent communication
                ws_to_gemini_task = asyncio.create_task(
                    self._ws_to_gemini_with_session(session, gemini_session)
                )
                gemini_to_ws_task = asyncio.create_task(
                    self._gemini_to_ws_with_session(session, gemini_session)
                )
                
                # Wait for either task to complete (error or disconnect)
                done, pending = await asyncio.wait(
                    [ws_to_gemini_task, gemini_to_ws_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                        
        except Exception as e:
            logger.error(f"Gemini session error: {e}")
    
    async def _handle_echo_mode(self, session: WebSocketSession) -> None:
        """Fallback echo mode when Gemini Live API is not available"""
        try:
            logger.info("Using echo mode - WebSocket connected but Gemini Live API unavailable")
            
            while True:
                data = await session.ws.receive_text()
                message = json.loads(data)
                
                # Echo back the message
                await session.send_json({
                    "type": "echo",
                    "text": f"Echo: {message.get('text', 'No text')}",
                    "instance_id": INSTANCE_ID,
                    "mode": "echo"
                })
                
        except Exception as e:
            logger.error(f"Echo mode error: {e}")
    
    async def _ws_to_gemini_with_session(self, session: WebSocketSession, gemini_session) -> None:
        """Forward WebSocket messages to Gemini with active session"""
        try:
            while True:
                data = await session.ws.receive_text()
                message = json.loads(data)
                
                # Handle different message types
                if message.get("type") == "text":
                    await gemini_session.send(message.get("text", ""))
                elif message.get("type") == "audio":
                    # Handle audio data
                    pass
                    
        except Exception as e:
            logger.error(f"ws_to_gemini error: {e}")
    
    async def _gemini_to_ws_with_session(self, session: WebSocketSession, gemini_session) -> None:
        """Forward Gemini responses to WebSocket with active session"""
        try:
            async for response in gemini_session.receive():
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
