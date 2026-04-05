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
from starlette.websockets import WebSocketDisconnect

from jarvis.feature_flags import feature_enabled

# Conditional import for Gemini API
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    GENAI_AVAILABLE = False

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
            # Try models that are known to support Live API
            models_to_try = [
                "gemini-2.5-flash-native-audio-preview-12-2025",  # Original audio model
                "gemini-2.0-flash-exp",                          # Experimental model
                "gemini-1.5-pro",                                # Pro model
                "gemini-1.5-flash",                              # Flash model
                "gemini-2.5-flash",                              # Latest flash
                "gemini-2.0-flash",                              # Previous version
                "gemini-2.5-pro",                                # Latest pro
                "gemini-2.5-flash-exp",                          # Experimental flash
                "gemini-2.0-flash-exp",                          # Experimental flash 2.0
            ]
            
            # Try different configurations
            configs_to_try = [
                # Config 1: Text only
                types.LiveConnectConfig(
                    temperature=0.7,
                    response_modalities=["TEXT"],
                    generation_config=types.GenerationConfig(
                        max_output_tokens=1024,
                        temperature=0.7,
                    )
                ),
                # Config 2: Minimal config
                types.LiveConnectConfig(
                    temperature=0.7,
                ),
                # Config 3: With audio (if supported)
                types.LiveConnectConfig(
                    temperature=0.7,
                    response_modalities=["AUDIO", "TEXT"],
                    generation_config=types.GenerationConfig(
                        max_output_tokens=1024,
                        temperature=0.7,
                    )
                )
            ]
            
            for model_name in models_to_try:
                for config_idx, config in enumerate(configs_to_try):
                    try:
                        # Remove "models/" prefix if present
                        clean_model_name = model_name
                        if clean_model_name.startswith("models/"):
                            clean_model_name = clean_model_name[7:]
                        
                        logger.info(f"Trying model: {clean_model_name} with config {config_idx + 1}")
                        
                        self.config = config
                        
                        self.session = self.client.aio.live.connect(
                            model=clean_model_name,
                            config=self.config,
                        )
                        
                        logger.info(f"✅ Gemini Live session connected successfully with model: {clean_model_name}, config {config_idx + 1}")
                        break
                        
                    except Exception as model_error:
                        logger.warning(f"❌ Model {clean_model_name} with config {config_idx + 1} failed: {model_error}")
                        if model_name == models_to_try[-1] and config_idx == len(configs_to_try) - 1:
                            # Last model and last config tried
                            raise model_error
                        continue
                
                if self.session is not None:
                    break  # Found working configuration
            
        except Exception as e:
            logger.error(f"Failed to connect to Gemini Live API: {e}")
            # Try to get more specific error information
            if "1008" in str(e):
                logger.info("Model not found error - trying to list available models")
                try:
                    models = self.client.models.list()
                    available_models = [model.name for model in models]
                    logger.info(f"Available models: {available_models}")
                    
                    # Try to find models that might support Live API
                    live_candidates = [m for m in available_models if any(keyword in m.lower() for keyword in ['flash', 'pro', 'exp', 'audio', 'live'])]
                    if live_candidates:
                        logger.info(f"Potential Live API models: {live_candidates}")
                except Exception as list_error:
                    logger.error(f"Could not list models: {list_error}")
            elif "invalid argument" in str(e).lower():
                logger.info("Invalid argument error - trying different configuration")
            else:
                logger.error(f"Unexpected Gemini Live API error: {e}")
                
            logger.info("Using fallback smart mode")
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
    """Manages single WebSocket session per user"""
    
    def __init__(self):
        self.active_session: Optional[WebSocketSession] = None
        self.active_session_id: Optional[str] = None
        
    async def handle_connection(self, ws: WebSocket) -> None:
        """Handle new WebSocket connection with single-session constraint"""
        session = WebSocketSession(ws)
        
        try:
            await session.initialize()
            
            # Check if there's an existing session for the same user
            # Extract user identifier from session or client parameters
            user_id = self._extract_user_id(session)
            
            logger.info(f"Connection attempt for user {user_id}, current active session: {self.active_session_id}")
            
            # If there's an existing session for this user, disconnect it
            if self.active_session and self.active_session_id == user_id:
                logger.info(f"Disconnecting existing session for user {user_id}")
                await self._disconnect_existing_session()
            else:
                logger.info(f"No existing session for user {user_id} or different user")
            
            # Set this as the active session
            self.active_session = session
            self.active_session_id = user_id
            
            logger.info(f"New session established for user {user_id}: {session.session_id}")
            
            # Handle the WebSocket communication
            await self._handle_websocket_loop(session)
            
        except Exception as e:
            logger.error(f"WebSocket session error: {e}")
        finally:
            await session.close()
            # Clear active session if this was the active one
            if self.active_session and self.active_session.session_id == session.session_id:
                self.active_session = None
                self.active_session_id = None
                logger.info(f"Session cleared for user: {user_id}")
    
    def _extract_user_id(self, session: WebSocketSession) -> str:
        """Extract user identifier from session parameters"""
        # For now, use session_id as user identifier, but this could be enhanced
        # to use actual user authentication tokens or client IDs
        try:
            # Try to get client_id from query params
            client_id = session.ws.query_params.get("client_id", "")
            if client_id:
                return str(client_id)
        except Exception:
            pass
        
        # Fallback to session_id if no client_id
        return session.session_id
    
    async def _disconnect_existing_session(self) -> None:
        """Disconnect the existing active session"""
        if self.active_session:
            try:
                # Send a session takeover message
                await self.active_session.send_json({
                    "type": "system",
                    "text": "Session connected from another device",
                    "instance_id": INSTANCE_ID
                })
                
                # Close the existing WebSocket with a specific code
                await self.active_session.ws.close(code=4000, reason="session_taken_over")
                logger.info(f"Disconnected existing session: {self.active_session.session_id}")
                
            except Exception as e:
                logger.warning(f"Error disconnecting existing session: {e}")
            finally:
                self.active_session = None
                self.active_session_id = None
    
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
            # Try smart fallback with regular Gemini API
            await self._handle_smart_fallback_mode(session)
            return
            
        try:
            # session.session is the async context manager from live.connect()
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
            # Fall back to smart mode if Live API fails during session
            await self._handle_smart_fallback_mode(session)
    
    async def _handle_smart_fallback_mode(self, session: WebSocketSession) -> None:
        """Smart fallback mode using regular Gemini API for intelligent responses"""
        try:
            logger.info("Using smart fallback mode - Regular Gemini API for intelligent responses")
            
            # Initialize regular Gemini client
            api_key = os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                logger.warning("No GEMINI_API_KEY found, falling back to echo mode")
                await self._handle_echo_mode(session)
                return
            
            # Send welcome message
            await session.send_json({
                "type": "text",
                "text": "Jarvis here! I'm ready to help you with intelligent responses. What can I do for you?",
                "instance_id": INSTANCE_ID,
                "mode": "smart_fallback"
            })
            
            # Handle messages with intelligent responses
            while True:
                try:
                    data = await asyncio.wait_for(session.ws.receive_text(), timeout=30.0)
                    message = json.loads(data)
                    
                    if message.get("type") == "text":
                        user_text = message.get("text", "").strip()
                        if not user_text:
                            continue
                        
                        logger.info(f"Processing message with Gemini: {user_text[:50]}...")
                        
                        # Get intelligent response from Gemini via HTTP API
                        try:
                            response_text = await self._get_gemini_response(user_text, api_key)
                            
                            await session.send_json({
                                "type": "text",
                                "text": response_text,
                                "instance_id": INSTANCE_ID,
                                "mode": "smart_fallback"
                            })
                            
                            logger.info(f"Sent intelligent response: {response_text[:50]}...")
                            
                        except Exception as gemini_error:
                            logger.error(f"Gemini API error: {gemini_error}")
                            await session.send_json({
                                "type": "text",
                                "text": "I'm having trouble thinking right now. Could you try again?",
                                "instance_id": INSTANCE_ID,
                                "mode": "smart_fallback"
                            })
                    
                except asyncio.TimeoutError:
                    # Send periodic ping
                    await session.send_json({
                        "type": "text",
                        "text": "Still here and ready to help! Send me a message.",
                        "instance_id": INSTANCE_ID,
                        "mode": "smart_fallback"
                    })
                    
                except WebSocketDisconnect:
                    logger.info("WebSocket disconnected in smart fallback mode")
                    break
                    
                except Exception as e:
                    logger.error(f"Error in smart fallback mode: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"Failed to initialize smart fallback mode: {e}")
            # Final fallback to echo mode
            await self._handle_echo_mode(session)
    
    async def _get_gemini_response(self, user_text: str, api_key: str) -> str:
        """Get response from Gemini API via HTTP"""
        try:
            # Use the Gemini Pro API via HTTP
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": api_key
            }
            
            payload = {
                "contents": [{
                    "parts": [{
                        "text": user_text
                    }]
                }],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 1024
                }
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                
                result = response.json()
                if "candidates" in result and len(result["candidates"]) > 0:
                    return result["candidates"][0]["content"]["parts"][0]["text"]
                else:
                    return "I'm not sure how to respond to that. Could you try asking differently?"
                    
        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}")
            return "I'm having trouble connecting to my brain right now. Please try again in a moment."
    
    async def _handle_echo_mode(self, session: WebSocketSession) -> None:
        """Fallback echo mode when Gemini Live API is not available"""
        try:
            logger.info("Using echo mode - WebSocket connected but Gemini Live API unavailable")
            
            # Send a welcome message to confirm the connection is working
            await session.send_json({
                "type": "text",
                "text": "Echo mode active! Send me a message and I'll echo it back.",
                "instance_id": INSTANCE_ID,
                "mode": "echo"
            })
            logger.info("Welcome message sent")
            
            while True:
                try:
                    # Add timeout to prevent hanging
                    data = await asyncio.wait_for(session.ws.receive_text(), timeout=30.0)
                    logger.info(f"Received WebSocket message: {data}")
                    
                    try:
                        message = json.loads(data)
                        logger.info(f"Parsed message: {message}")
                        
                        # Echo back the message
                        echo_response = {
                            "type": "text",
                            "text": f"Echo: {message.get('text', 'No text')}",
                            "instance_id": INSTANCE_ID,
                            "mode": "echo"
                        }
                        logger.info(f"Sending echo response: {echo_response}")
                        
                        await session.send_json(echo_response)
                        logger.info("Echo response sent successfully")
                        
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON message: {e}")
                        # Send error response
                        await session.send_json({
                            "type": "text",
                            "text": f"Invalid JSON: {str(e)}",
                            "instance_id": INSTANCE_ID,
                            "mode": "echo"
                        })
                        
                except asyncio.TimeoutError:
                    logger.info("No message received for 30 seconds, sending ping")
                    await session.send_json({
                        "type": "text",
                        "text": "Still here! Send me a message.",
                        "instance_id": INSTANCE_ID,
                        "mode": "echo"
                    })
                    
        except WebSocketDisconnect as e:
            logger.info(f"WebSocket disconnected gracefully: {e}")
        except Exception as e:
            logger.error(f"Echo mode error: {e}")
            logger.error(f"Echo mode error type: {type(e)}")
            import traceback
            logger.error(f"Echo mode traceback: {traceback.format_exc()}")
    
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
        """Broadcast message to the active session (single-session model)"""
        if self.active_session:
            try:
                await self.active_session.send_json(message)
                logger.info(f"Broadcasted message to active session: {self.active_session.session_id}")
            except Exception as e:
                logger.warning(f"Failed to broadcast to active session {self.active_session.session_id}: {e}")
        else:
            logger.info("No active session to broadcast to")


# Global manager instance
websocket_manager = WebSocketManager()
