from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import struct
import uuid
from typing import Any, Optional

import httpx
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from jarvis.feature_flags import feature_enabled

logger = logging.getLogger(__name__)


_JARVIS_DISABLE_GEMINI_LIVE = str(os.getenv("JARVIS_DISABLE_GEMINI_LIVE") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


async def _google_tts_synthesize_linear16(
    *,
    text: str,
    sample_rate_hz: int = 24000,
) -> bytes:
    api_key = str(os.getenv("GOOGLE_TTS_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("missing_google_tts_api_key")

    language_code = str(os.getenv("JARVIS_GOOGLE_TTS_LANGUAGE") or "en-US").strip() or "en-US"
    voice_name = str(os.getenv("JARVIS_GOOGLE_TTS_VOICE") or "").strip()

    payload: dict[str, Any] = {
        "input": {"text": text},
        "voice": {"languageCode": language_code},
        "audioConfig": {
            "audioEncoding": "LINEAR16",
            "sampleRateHertz": int(sample_rate_hz),
        },
    }
    if voice_name:
        payload["voice"]["name"] = voice_name

    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()

    b64 = str((data or {}).get("audioContent") or "").strip()
    if not b64:
        raise RuntimeError("google_tts_empty_audio")
    return base64.b64decode(b64)


_SIDECAR_STT_CACHE_PATH = str(
    os.getenv("JARVIS_SIDECAR_STT_CACHE_PATH")
    or os.getenv("JARVIS_LIVE_MODEL_CACHE_PATH")
    or "/data/jarvis_sidecar_stt_model_cache.json"
).strip()

_SIDECAR_STT_WORKING_MODEL: str | None = None


def sidecar_stt_cache_status() -> dict[str, Any]:
    _sidecar_stt_load_cached_model()
    return {
        "cache_path": _SIDECAR_STT_CACHE_PATH,
        "cached": _SIDECAR_STT_WORKING_MODEL,
    }


def _sidecar_stt_load_cached_model() -> str | None:
    global _SIDECAR_STT_WORKING_MODEL

    if _SIDECAR_STT_WORKING_MODEL:
        return _SIDECAR_STT_WORKING_MODEL

    if not _SIDECAR_STT_CACHE_PATH:
        return None

    try:
        if not os.path.exists(_SIDECAR_STT_CACHE_PATH):
            return None
        with open(_SIDECAR_STT_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        model = str((data or {}).get("model") or "").strip()
        if model:
            _SIDECAR_STT_WORKING_MODEL = model
            return model
    except Exception:
        return None
    return None


def sidecar_stt_set_working_model(model: str) -> None:
    global _SIDECAR_STT_WORKING_MODEL

    m = str(model or "").strip()
    if not m:
        return
    _SIDECAR_STT_WORKING_MODEL = m
    if not _SIDECAR_STT_CACHE_PATH:
        return
    try:
        d = os.path.dirname(_SIDECAR_STT_CACHE_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(_SIDECAR_STT_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"model": m}, f)
    except Exception:
        return


def sidecar_stt_get_model(fallback: str) -> str:
    model, _source = sidecar_stt_resolve_model(fallback)
    return model


def sidecar_stt_resolve_model(fallback: str) -> tuple[str, str]:
    explicit = str(os.getenv("JARVIS_SIDECAR_STT_MODEL") or "").strip()
    if explicit:
        return explicit, "env:JARVIS_SIDECAR_STT_MODEL"

    cached = _sidecar_stt_load_cached_model()
    if cached:
        return cached, "cache"

    fb = str(fallback or "").strip() or "gemini-flash-latest"
    return fb, "fallback"

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

_LIVE_WORKING_MODEL_AND_CONFIG: Optional[tuple[str, "types.LiveConnectConfig"]] = None
_LIVE_LISTED_MODELS_ONCE: bool = False
_LIVE_CACHE_PATH = os.getenv("JARVIS_LIVE_MODEL_CACHE_PATH", "/data/jarvis_live_model_cache.json").strip()
_LIVE_PROBE_ON_CONNECT = str(os.getenv("JARVIS_LIVE_PROBE_ON_CONNECT", "false")).strip().lower() == "true"


def _live_is_native_audio_model(model: str) -> bool:
    m = str(model or "").lower()
    return "native-audio" in m


def _live_configs_for_model() -> tuple[list["types.LiveConnectConfig"], list["types.LiveConnectConfig"]]:
    text_cfgs: list[types.LiveConnectConfig] = [
        types.LiveConnectConfig(
            response_modalities=["TEXT"],
        ),
        types.LiveConnectConfig(
            temperature=0.7,
            response_modalities=["TEXT"],
            generation_config=types.GenerationConfig(
                max_output_tokens=1024,
                temperature=0.7,
            ),
        ),
    ]
    audio_cfgs: list[types.LiveConnectConfig] = [
        types.LiveConnectConfig(
            response_modalities=["AUDIO"],
        ),
        types.LiveConnectConfig(
            temperature=0.7,
            response_modalities=["AUDIO", "TEXT"],
        ),
    ]
    return text_cfgs, audio_cfgs

try:
    if _LIVE_CACHE_PATH:
        with open(_LIVE_CACHE_PATH, "r", encoding="utf-8") as f:
            cached = json.load(f)
        cached_model = str(cached.get("model") or "").strip()
        cached_config_idx = cached.get("config_idx")
        if cached_model and isinstance(cached_config_idx, int):
            _LIVE_WORKING_MODEL_AND_CONFIG = (cached_model, cached_config_idx)
except Exception:
    pass

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
        
        # Live session is established later (after WebSocket accept) so we don't do heavy
        # work before the handshake and so we only log success once the session is usable.
        self.session = None
        self.config = None
        
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
            # Accept early so clients connect reliably even if Gemini initialization fails.
            await session.ws.accept()
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
        global _LIVE_WORKING_MODEL_AND_CONFIG
        global _LIVE_LISTED_MODELS_ONCE

        if _JARVIS_DISABLE_GEMINI_LIVE:
            logger.info("Gemini Live disabled; using voice fallback mode")
            await self._handle_voice_fallback_mode(session)
            return

        # B3 behavior: Do NOT probe models/configs on every WS connect.
        # Only try the cached model/config if we have one; otherwise fall back immediately.
        if (not _LIVE_PROBE_ON_CONNECT) and (_LIVE_WORKING_MODEL_AND_CONFIG is None):
            logger.info("Live probing disabled on connect and no cached Live model; using smart fallback mode")
            await self._handle_smart_fallback_mode(session)
            return

        models_to_try: list[str] = []
        configs_to_try: list[types.LiveConnectConfig] = []
        cached_config_idx: Optional[int] = None

        if _LIVE_WORKING_MODEL_AND_CONFIG is not None:
            cached_model, cached_cfg = _LIVE_WORKING_MODEL_AND_CONFIG
            models_to_try.append(cached_model)
            if isinstance(cached_cfg, int):
                cached_config_idx = cached_cfg

        if (not _LIVE_PROBE_ON_CONNECT) and (_LIVE_WORKING_MODEL_AND_CONFIG is not None):
            # Only attempt the cached model; do not extend probe list.
            probe_models: list[str] = []
        else:
            # Extend with probe set (only if cache missing or cache fails)
            preferred_live_model = str(os.getenv("GEMINI_LIVE_MODEL") or "").strip()
            try_text_live_preview = str(os.getenv("JARVIS_LIVE_TRY_TEXT_PREVIEW") or "false").strip().lower() == "true"
            probe_models = [
                # If operator configured a preferred Live model, try it first.
                preferred_live_model,
                # Text-live preview is opt-in. Some deployments see 1011 errors; keep it out
                # of the default probe path unless explicitly requested.
                "gemini-3.1-flash-live-preview" if (preferred_live_model == "gemini-3.1-flash-live-preview" or try_text_live_preview) else "",

                # Audio/live-adjacent models (may require audio input depending on client behavior)
                "gemini-2.5-flash-native-audio-latest",
                "gemini-2.5-flash-native-audio-preview-12-2025",
                "lyria-realtime-exp",

                # General text models (may not support bidiGenerateContent but keep for coverage)
                "gemini-2.5-flash",
                "gemini-2.5-pro",
                "gemini-2.0-flash",
                "gemini-2.0-flash-001",
                "gemini-2.0-flash-lite",
                "gemini-2.0-flash-lite-001",
                "gemini-flash-latest",
                "gemini-flash-lite-latest",
                "gemini-pro-latest",
            ]

            probe_models = [m for m in probe_models if m]

        for m in probe_models:
            if m not in models_to_try:
                models_to_try.append(m)

        text_cfgs, audio_cfgs = _live_configs_for_model()

        for model_name in models_to_try:
            clean_model_name = model_name[7:] if model_name.startswith("models/") else model_name
            # Live best-practice: one modality per session.
            # - For native-audio models, only try AUDIO configs.
            # - For live preview, default to TEXT configs.
            configs_to_try = audio_cfgs if _live_is_native_audio_model(clean_model_name) else text_cfgs

            # If cached config exists and applies to this model, try it first.
            if (
                cached_config_idx is not None
                and _LIVE_WORKING_MODEL_AND_CONFIG is not None
                and clean_model_name == _LIVE_WORKING_MODEL_AND_CONFIG[0]
                and 0 <= cached_config_idx < len(configs_to_try)
            ):
                configs_to_try = [configs_to_try[cached_config_idx]] + [
                    c for i, c in enumerate(configs_to_try) if i != cached_config_idx
                ]

            for config_idx, config in enumerate(configs_to_try):
                try:
                    logger.info(f"Trying Live model: {clean_model_name} with config {config_idx + 1}")

                    # Only consider Live usable if we successfully enter the context.
                    connect_attempts = 2
                    last_exc: Optional[Exception] = None
                    for attempt in range(connect_attempts):
                        try:
                            async with session.client.aio.live.connect(
                                model=clean_model_name,
                                config=config,
                            ) as gemini_session:
                                logger.info(
                                    f"✅ Gemini Live session established (validated) model={clean_model_name} config={config_idx + 1}"
                                )

                                _LIVE_WORKING_MODEL_AND_CONFIG = (clean_model_name, config_idx)
                                try:
                                    if _LIVE_CACHE_PATH:
                                        os.makedirs(os.path.dirname(_LIVE_CACHE_PATH), exist_ok=True)
                                        with open(_LIVE_CACHE_PATH, "w", encoding="utf-8") as f:
                                            json.dump({"model": clean_model_name, "config_idx": config_idx}, f)
                                except Exception:
                                    pass

                                ws_to_gemini_task = asyncio.create_task(
                                    self._ws_to_gemini_with_session(
                                        session,
                                        gemini_session,
                                        clean_model_name,
                                    )
                                )
                                gemini_to_ws_task = asyncio.create_task(
                                    self._gemini_to_ws_with_session(session, gemini_session)
                                )

                                # Keep the Live session open as long as the WS is open.
                                # gemini_to_ws can legitimately complete early if the model emits no events.
                                try:
                                    await ws_to_gemini_task
                                    logger.info(
                                        f"Live WS->Gemini loop ended model={clean_model_name} config={config_idx + 1}"
                                    )
                                finally:
                                    if not gemini_to_ws_task.done():
                                        gemini_to_ws_task.cancel()
                                        try:
                                            await gemini_to_ws_task
                                        except asyncio.CancelledError:
                                            pass
                                    else:
                                        try:
                                            exc = gemini_to_ws_task.exception()
                                        except Exception:
                                            exc = None
                                        if exc is not None:
                                            logger.warning(
                                                f"Live Gemini->WS loop exited with error model={clean_model_name}: {exc}"
                                            )

                                return
                        except Exception as ie:
                            last_exc = ie
                            if "1011" in str(ie):
                                await asyncio.sleep(0.5)
                                continue
                            raise

                    if last_exc is not None:
                        raise last_exc

                except Exception as e:
                    # If cached model/config fails, invalidate cache and continue probing.
                    if _LIVE_WORKING_MODEL_AND_CONFIG is not None and _LIVE_WORKING_MODEL_AND_CONFIG[0] == clean_model_name:
                        _LIVE_WORKING_MODEL_AND_CONFIG = None

                        if not _LIVE_PROBE_ON_CONNECT:
                            # If the client already disconnected, don't try to start fallback.
                            try:
                                disconnected = session.ws.client_state.name.lower() != "connected"
                            except Exception:
                                disconnected = False

                            if disconnected:
                                logger.info("Cached Live model failed but WS is already disconnected; skipping fallback")
                                return

                            logger.info("Cached Live model failed and probing is disabled; using smart fallback mode")
                            await self._handle_smart_fallback_mode(session)
                            return

                    if (not _LIVE_LISTED_MODELS_ONCE) and ("1008" in str(e)):
                        _LIVE_LISTED_MODELS_ONCE = True
                        try:
                            models = session.client.models.list()
                            available_models = [m.name for m in models]
                            logger.info(f"Live model listing (one-time): {available_models}")
                        except Exception as list_err:
                            logger.warning(f"Failed to list models (one-time): {list_err}")

                    logger.warning(
                        f"❌ Live model failed model={clean_model_name} config={config_idx + 1}: {e}"
                    )
                    if "Cannot extract voices from a non-audio request" in str(e):
                        # Audio-only model invoked with a non-audio config; don't try other configs.
                        break
                    continue

        logger.info("Live API unavailable; using smart fallback mode")
        await self._handle_smart_fallback_mode(session)
        return

    async def _ws_to_gemini_with_session(
        self, session: WebSocketSession, gemini_session: Any, live_model_name: str
    ) -> None:
        """Forward WS client input (text/audio) into an active Gemini Live session."""
        from google.genai import types

        logger.info("Live WS->Gemini loop started")

        transcriber: _StreamingSidecarTranscriber | None = None
        try:
            # Sidecar transcription: native-audio models often can't enable AUDIO+TEXT at
            # Live connect time, so we stream partial transcripts via separate calls.
            if _live_is_native_audio_model(live_model_name):
                transcriber = _StreamingSidecarTranscriber(session=session)
                transcriber.start()
                logger.info(
                    "Sidecar STT started model=%s stt_model=%s stt_model_source=%s interval_s=%s chunk_s=%s overlap_s=%s",
                    str(live_model_name),
                    str(transcriber._model),
                    str(getattr(transcriber, "_model_source", "unknown")),
                    str(transcriber._interval_seconds),
                    str(transcriber._chunk_seconds),
                    str(transcriber._overlap_seconds),
                )
        except Exception:
            transcriber = None

        try:
            while True:
                data = await session.ws.receive_text()
                try:
                    msg = json.loads(data)
                except Exception:
                    continue

                mtype = str(msg.get("type") or "").strip().lower()
                if mtype in ("ping", "pong"):
                    continue

                if mtype == "text":
                    text = str(msg.get("text") or "").strip()
                    if not text:
                        continue

                    # Status query: report news job progress if a news job is running.
                    t = text.lower()
                    if (
                        t.strip() in ("news status", "status news")
                        or "news status" in t
                        or "ข่าวถึงไหน" in t
                        or "สถานะข่าว" in t
                    ):
                        try:
                            from jarvis.skills.news import news_skill

                            trace_id = str(msg.get("trace_id") or "news_status")
                            ok = await news_skill.handle_news_status(session.ws, trace_id)
                            if ok:
                                continue
                        except Exception as ne:
                            logger.warning(f"News status shortcut failed: {ne}")

                    # Server-side shortcut: route news requests to MCP-News instead of relying on Gemini tool calls.
                    if (
                        "current news" in t
                        or "news today" in t
                        or "latest news" in t
                        or "ข่าวล่าสุด" in t
                        or "ข่าววันนี้" in t
                        or "ข่าวตอนนี้" in t
                        or ("ข่าว" in t and len(t) <= 40)
                        or (t.strip() == "news")
                    ):
                        try:
                            from jarvis.skills.news import news_skill

                            trace_id = str(msg.get("trace_id") or "news")
                            ok = await news_skill.handle_current_news(session.ws, text, trace_id)
                            if ok:
                                continue
                        except Exception as ne:
                            logger.warning(f"News shortcut failed: {ne}")

                    await gemini_session.send_realtime_input(text=text)
                    continue

                if mtype == "audio":
                    b64 = msg.get("data")
                    if not b64:
                        continue
                    try:
                        mime_type = str(msg.get("mimeType") or msg.get("mime_type") or "audio/pcm;rate=16000").strip()
                        logger.info(
                            "Live audio received from client mime=%s b64_len=%s",
                            mime_type,
                            str(len(b64) if isinstance(b64, str) else "?"),
                        )
                    except Exception:
                        mime_type = str(msg.get("mimeType") or msg.get("mime_type") or "audio/pcm;rate=16000").strip()
                    try:
                        pcm = base64.b64decode(str(b64))
                    except Exception:
                        continue

                    if transcriber is not None:
                        try:
                            transcriber.ingest_pcm16(pcm)
                            # Kick transcription immediately (best-effort) so short utterances
                            # don't have to wait for the periodic timer.
                            transcriber.kick()
                        except Exception:
                            pass

                    await gemini_session.send_realtime_input(audio=types.Blob(data=pcm, mime_type=mime_type))
                    continue

                if mtype == "audio_stream_end":
                    logger.info("Live audio_stream_end received")
                    if transcriber is not None:
                        try:
                            await transcriber.flush_and_reset()
                        except Exception:
                            pass
                    continue

                if mtype == "close":
                    return
        except WebSocketDisconnect:
            logger.info("WS disconnected (Live WS->Gemini loop)")
            return
        finally:
            if transcriber is not None:
                try:
                    await transcriber.stop()
                except Exception:
                    pass
                logger.info("Sidecar STT stopped")
            logger.info("Live WS->Gemini loop exiting")


    async def _gemini_to_ws_with_session(self, session: WebSocketSession, gemini_session: Any) -> None:
        """Forward Gemini Live server events back to the WS client."""
        # Frontend expects:
        # - {type:'transcript', text:'...', source:'input'|'output'}
        # - {type:'audio', data:'<base64>', sampleRate?:number}
        await session.send_json({"type": "state", "state": "connected", "instance_id": INSTANCE_ID})

        async for response in gemini_session.receive():
            content = getattr(response, "server_content", None)
            if not content:
                continue

            # Transcripts
            in_tr = getattr(content, "input_transcription", None)
            if in_tr and getattr(in_tr, "text", None):
                logger.info("Live transcript (input) received")
                await session.send_json(
                    {
                        "type": "transcript",
                        "text": str(in_tr.text),
                        "source": "input",
                        "instance_id": INSTANCE_ID,
                    }
                )

            out_tr = getattr(content, "output_transcription", None)
            if out_tr and getattr(out_tr, "text", None):
                logger.info("Live transcript (output) received")
                await session.send_json(
                    {
                        "type": "transcript",
                        "text": str(out_tr.text),
                        "source": "output",
                        "instance_id": INSTANCE_ID,
                    }
                )

            # Model turn parts (audio)
            model_turn = getattr(content, "model_turn", None)
            parts = getattr(model_turn, "parts", None) if model_turn else None
            if parts:
                for part in parts:
                    # Some models may emit text parts in model_turn.
                    ptxt = getattr(part, "text", None)
                    if ptxt:
                        await session.send_json(
                            {
                                "type": "text",
                                "text": str(ptxt),
                                "instance_id": INSTANCE_ID,
                            }
                        )

                    inline = getattr(part, "inline_data", None)
                    if not inline:
                        continue
                    audio_data = getattr(inline, "data", None)
                    if not audio_data:
                        continue
                    try:
                        if isinstance(audio_data, str):
                            # Some SDK versions may provide base64-encoded strings already.
                            b64 = audio_data
                        else:
                            if isinstance(audio_data, memoryview):
                                audio_data = audio_data.tobytes()
                            b64 = base64.b64encode(bytes(audio_data)).decode("ascii")
                    except Exception:
                        continue

                    logger.info("Live audio chunk forwarded")
                    await session.send_json(
                        {
                            "type": "audio",
                            "data": b64,
                            "sampleRate": 24000,
                            "instance_id": INSTANCE_ID,
                        }
                    )
    
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
            
            previous_interaction_id: Optional[str] = None

            # Handle messages with intelligent responses
            while True:
                try:
                    data = await asyncio.wait_for(session.ws.receive_text(), timeout=30.0)
                    message = json.loads(data)
                    
                    if message.get("type") == "text":
                        user_text = message.get("text", "").strip()
                        if not user_text:
                            continue

                        # Status query: report news job progress if a news job is running.
                        t = user_text.lower()
                        if (
                            t.strip() in ("news status", "status news")
                            or "news status" in t
                            or "ข่าวถึงไหน" in t
                            or "สถานะข่าว" in t
                        ):
                            try:
                                from jarvis.skills.news import news_skill

                                trace_id = str(message.get("trace_id") or "news_status")
                                ok = await news_skill.handle_news_status(session.ws, trace_id)
                                if ok:
                                    continue
                            except Exception as ne:
                                logger.warning(f"News status shortcut failed (fallback): {ne}")

                        # Server-side shortcut: route news requests to MCP-News.
                        if (
                            "current news" in t
                            or "news today" in t
                            or "latest news" in t
                            or "ข่าวล่าสุด" in t
                            or "ข่าววันนี้" in t
                            or "ข่าวตอนนี้" in t
                            or ("ข่าว" in t and len(t) <= 40)
                            or (t.strip() == "news")
                        ):
                            try:
                                from jarvis.skills.news import news_skill

                                trace_id = str(message.get("trace_id") or "news")
                                ok = await news_skill.handle_current_news(session.ws, user_text, trace_id)
                                if ok:
                                    continue
                            except Exception as ne:
                                logger.warning(f"News shortcut failed (fallback): {ne}")
                        
                        logger.info(f"Processing message with Gemini: {user_text[:50]}...")
                        
                        # Get intelligent response from Gemini via HTTP API
                        try:
                            response_text, previous_interaction_id = await self._get_gemini_response(
                                user_text,
                                api_key,
                                previous_interaction_id,
                            )
                            
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

    async def _handle_voice_fallback_mode(self, session: WebSocketSession) -> None:
        """Voice fallback mode: WS audio -> sidecar STT -> Gemini generateContent -> Google TTS audio."""
        transcriber: _StreamingSidecarTranscriber | None = None
        try:
            api_key = os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                await self._handle_echo_mode(session)
                return

            await session.send_json({"type": "state", "state": "connected", "instance_id": INSTANCE_ID})

            transcriber = _StreamingSidecarTranscriber(session=session)
            transcriber.start()
            logger.info(
                "Voice fallback started stt_model=%s source=%s",
                str(transcriber._model),
                str(getattr(transcriber, "_model_source", "unknown")),
            )

            previous_interaction_id: Optional[str] = None

            async def _speak(text: str) -> None:
                pcm = await _google_tts_synthesize_linear16(text=text, sample_rate_hz=24000)
                chunk_size = int(24000 * 2 * 0.4)  # ~400ms
                for i in range(0, len(pcm), chunk_size):
                    b64 = base64.b64encode(pcm[i : i + chunk_size]).decode("ascii")
                    await session.send_json(
                        {
                            "type": "audio",
                            "data": b64,
                            "sampleRate": 24000,
                            "instance_id": INSTANCE_ID,
                        }
                    )

            while True:
                data = await session.ws.receive_text()
                try:
                    msg = json.loads(data)
                except Exception:
                    continue

                mtype = str(msg.get("type") or "").strip().lower()
                if mtype in ("ping", "pong"):
                    continue

                if mtype == "audio":
                    b64 = msg.get("data")
                    if not b64:
                        continue
                    try:
                        pcm16 = base64.b64decode(str(b64))
                    except Exception:
                        continue
                    try:
                        transcriber.ingest_pcm16(pcm16)
                        transcriber.kick()
                    except Exception:
                        pass
                    continue

                if mtype == "audio_stream_end":
                    logger.info("Voice fallback audio_stream_end")
                    try:
                        await transcriber.flush_and_reset()
                    except Exception:
                        pass
                    utterance = transcriber.consume_last_final_transcript()
                    if not utterance:
                        continue

                    try:
                        response_text, previous_interaction_id = await self._get_gemini_response(
                            utterance,
                            api_key,
                            previous_interaction_id,
                        )
                    except Exception:
                        response_text = "I'm having trouble responding right now. Please try again."

                    await session.send_json(
                        {
                            "type": "transcript",
                            "text": str(response_text),
                            "source": "output",
                            "instance_id": INSTANCE_ID,
                        }
                    )
                    await session.send_json(
                        {
                            "type": "text",
                            "text": str(response_text),
                            "instance_id": INSTANCE_ID,
                        }
                    )
                    try:
                        await _speak(str(response_text))
                    except Exception as te:
                        logger.warning("Voice fallback TTS failed: %s", str(te))
                    continue

                if mtype == "text":
                    user_text = str(msg.get("text") or "").strip()
                    if not user_text:
                        continue
                    response_text, previous_interaction_id = await self._get_gemini_response(
                        user_text,
                        api_key,
                        previous_interaction_id,
                    )
                    await session.send_json(
                        {
                            "type": "text",
                            "text": str(response_text),
                            "instance_id": INSTANCE_ID,
                        }
                    )
                    try:
                        await _speak(str(response_text))
                    except Exception as te:
                        logger.warning("Voice fallback TTS failed: %s", str(te))
                    continue

                if mtype == "close":
                    return

        except WebSocketDisconnect:
            return
        finally:
            if transcriber is not None:
                try:
                    await transcriber.stop()
                except Exception:
                    pass
    
    async def _get_gemini_response(
        self,
        user_text: str,
        api_key: str,
        previous_interaction_id: Optional[str],
    ) -> tuple[str, Optional[str]]:
        """Get response from Gemini API via HTTP"""
        try:
            from google import genai

            model_name = str(os.getenv("GEMINI_TEXT_MODEL") or "gemini-3-flash-preview").strip()
            if model_name.startswith("models/"):
                model_name = model_name[len("models/") :]

            client = genai.Client(api_key=api_key)
            try:
                interaction = await client.aio.interactions.create(
                    model=model_name,
                    input=user_text,
                    previous_interaction_id=previous_interaction_id,
                )
            except Exception as ie:
                # If Interactions is not supported for this model/key, fall back to stateless
                # generate_content so smart fallback still works.
                if "invalid_request" in str(ie) or "not supported" in str(ie) or "Model family" in str(ie):
                    resp = await client.aio.models.generate_content(model=model_name, contents=user_text)
                    txt = (getattr(resp, "text", None) or "").strip()
                    if not txt:
                        txt = str(resp)
                    return txt, previous_interaction_id
                raise

            txt: str = ""
            outputs = getattr(interaction, "output", None)
            if outputs:
                last = outputs[-1]
                content = getattr(last, "content", None)
                if content:
                    txt = str(getattr(content, "text", "") or "").strip()
            if not txt:
                txt = str(getattr(interaction, "text", "") or "").strip()
            if not txt:
                txt = "I'm not sure how to respond to that. Could you try asking differently?"

            new_id = getattr(interaction, "id", None)
            return txt, str(new_id) if new_id else previous_interaction_id
                    
        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}")
            return "I'm having trouble connecting to my brain right now. Please try again in a moment.", previous_interaction_id
    
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
                        # Echo back the message
                        echo_response = {
                            "type": "text",
                            "text": f"Echo: {message.get('text', 'No text')}",
                            "instance_id": INSTANCE_ID,
                            "mode": "echo",
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



class _StreamingSidecarTranscriber:
    def __init__(self, session: WebSocketSession):
        self._session = session
        self._buf = bytearray()
        self._lock = asyncio.Lock()
        self._kick_event = asyncio.Event()
        self._next_allowed_ts = 0.0
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._last_emitted: str = ""

        self._sample_rate = 16000
        self._chunk_seconds = float(str(os.getenv("JARVIS_SIDECAR_STT_CHUNK_S") or "1.5").strip() or "1.5")
        self._interval_seconds = float(str(os.getenv("JARVIS_SIDECAR_STT_INTERVAL_S") or "1.0").strip() or "1.0")
        self._overlap_seconds = float(str(os.getenv("JARVIS_SIDECAR_STT_OVERLAP_S") or "0.5").strip() or "0.5")
        self._final_max_seconds = float(str(os.getenv("JARVIS_SIDECAR_STT_FINAL_MAX_S") or "12.0").strip() or "12.0")
        self._timeout_seconds = float(str(os.getenv("JARVIS_SIDECAR_STT_TIMEOUT_S") or "20.0").strip() or "20.0")
        self._final_timeout_seconds = float(str(os.getenv("JARVIS_SIDECAR_STT_FINAL_TIMEOUT_S") or "45.0").strip() or "45.0")
        self._language = str(os.getenv("JARVIS_SIDECAR_STT_LANGUAGE") or "").strip()
        self._enable_partials = str(os.getenv("JARVIS_SIDECAR_STT_ENABLE_PARTIALS") or "0").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        self._chunk_bytes = max(1, int(self._sample_rate * self._chunk_seconds) * 2)
        self._overlap_bytes = max(0, int(self._sample_rate * self._overlap_seconds) * 2)
        self._read_offset = 0

        self._model, self._model_source = sidecar_stt_resolve_model(
            str(os.getenv("GEMINI_TEXT_MODEL") or "").strip() or "gemini-flash-latest"
        )

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def consume_last_final_transcript(self) -> str:
        try:
            t = str(getattr(self, "_last_final_transcript", "") or "").strip()
            self._last_final_transcript = ""
            return t
        except Exception:
            return ""

    def kick(self) -> None:
        # Best-effort scheduling; no-op if already stopped.
        if self._stopped.is_set():
            return
        try:
            self._kick_event.set()
        except Exception:
            pass

    def ingest_pcm16(self, pcm16: bytes) -> None:
        if not pcm16 or self._stopped.is_set():
            return
        self._buf.extend(pcm16)

    async def flush_and_stop(self) -> None:
        await self._transcribe_available(final_flush=True)
        await self.stop()

    async def flush_and_reset(self) -> None:
        # Flush any remaining audio for this utterance, then reset state so we can
        # transcribe the next utterance within the same Live connection.
        await self._transcribe_available(final_flush=True)
        self._buf.clear()
        self._read_offset = 0
        self._last_emitted = ""

    async def stop(self) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except Exception:
                try:
                    self._task.cancel()
                except Exception:
                    pass
        self._task = None

    async def _run(self) -> None:
        try:
            while not self._stopped.is_set():
                try:
                    await asyncio.wait_for(
                        self._kick_event.wait(),
                        timeout=self._interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

                try:
                    self._kick_event.clear()
                except Exception:
                    pass

                await self._transcribe_available(final_flush=False)
        except Exception:
            return

    def _retry_after_seconds_from_error(self, err: Exception) -> float | None:
        """Parse RetryInfo or 'Please retry in Xs.' from Gemini API errors."""
        try:
            msg = str(err)
            m = re.search(r"retry in\s+([0-9.]+)s", msg, re.IGNORECASE)
            if m:
                return float(m.group(1))
            m_ms = re.search(r"retry in\s+([0-9.]+)ms", msg, re.IGNORECASE)
            if m_ms:
                return float(m_ms.group(1)) / 1000.0
        except Exception:
            return None
        return None

    def _is_transient_unavailable(self, err: Exception) -> bool:
        s = str(err or "")
        if "503" in s and "UNAVAILABLE" in s:
            return True
        if "high demand" in s.lower():
            return True
        return False

    async def _call_stt_with_model(self, model: str, prompt: str, wav_bytes: bytes, timeout_s: float) -> str:
        from google.genai import types

        resp0 = await asyncio.wait_for(
            self._session.client.aio.models.generate_content(
                model=model,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                ],
                config={
                    "system_instruction": "You are a speech-to-text transcription engine.",
                },
            ),
            timeout=max(1.0, float(timeout_s)),
        )
        return str(getattr(resp0, "text", "") or "").strip()

    def _pcm16le_to_wav(self, pcm16le: bytes) -> bytes:
        num_channels = 1
        bits_per_sample = 16
        byte_rate = self._sample_rate * num_channels * (bits_per_sample // 8)
        block_align = num_channels * (bits_per_sample // 8)
        data_size = len(pcm16le)
        riff_size = 36 + data_size

        return b"".join(
            [
                b"RIFF",
                struct.pack("<I", riff_size),
                b"WAVE",
                b"fmt ",
                struct.pack("<I", 16),
                struct.pack("<H", 1),
                struct.pack("<H", num_channels),
                struct.pack("<I", self._sample_rate),
                struct.pack("<I", byte_rate),
                struct.pack("<H", block_align),
                struct.pack("<H", bits_per_sample),
                b"data",
                struct.pack("<I", data_size),
                pcm16le,
            ]
        )

    async def _transcribe_available(self, final_flush: bool) -> None:
        from google.genai import types

        if self._stopped.is_set():
            return

        if final_flush:
            logger.info("Sidecar STT final flush requested")
        elif not self._enable_partials:
            return

        # If a partial transcription is already in-flight, we skip additional partials.
        # But for final_flush (audio_stream_end), we should wait and then flush remaining
        # audio so the utterance isn't truncated.
        if self._lock.locked() and not final_flush:
            return

        if not final_flush:
            now = asyncio.get_running_loop().time()
            if now < self._next_allowed_ts:
                return

        async with self._lock:
            if not final_flush:
                now = asyncio.get_running_loop().time()
                if now < self._next_allowed_ts:
                    return

            buf_len = len(self._buf)
            if buf_len <= self._read_offset:
                if final_flush:
                    logger.info(
                        "Sidecar STT skip (no new audio) buf_len=%s read_offset=%s",
                        str(buf_len),
                        str(self._read_offset),
                    )
                return

            available = buf_len - self._read_offset
            if not final_flush and available < self._chunk_bytes:
                return

            if final_flush and available <= 0:
                logger.info(
                    "Sidecar STT skip (final but empty) buf_len=%s read_offset=%s",
                    str(buf_len),
                    str(self._read_offset),
                )
                return

            start = max(0, self._read_offset - self._overlap_bytes)
            if final_flush:
                # On utterance end, transcribe the entire remaining audio for better quality.
                max_bytes = int(self._final_max_seconds * self._sample_rate) * 2
                end = buf_len
                # Ignore read_offset here: partial transcriptions advance read_offset, but on
                # final flush we want the full utterance (up to the cap) not just the tail.
                if max_bytes > 0:
                    start = max(0, end - max_bytes)
            else:
                end = min(buf_len, self._read_offset + self._chunk_bytes)
            pcm_chunk = bytes(self._buf[start:end])
            if not pcm_chunk:
                if final_flush:
                    logger.info(
                        "Sidecar STT skip (empty chunk) start=%s end=%s buf_len=%s",
                        str(start),
                        str(end),
                        str(buf_len),
                    )
                return

            wav_bytes = self._pcm16le_to_wav(pcm_chunk)
            lang_hint = f" The language is {self._language}." if self._language else ""
            prompt = (
                "Transcribe the audio." + lang_hint + " The speaker may switch languages. Preserve the original language of each word/phrase. Return only the spoken words. "
                "Do not add commentary, timestamps, or punctuation unless spoken."
            )

            timeout_s = self._final_timeout_seconds if final_flush else self._timeout_seconds
            try:
                logger.info(
                    "Sidecar STT transcribing bytes=%s final=%s",
                    str(len(wav_bytes)),
                    "true" if final_flush else "false",
                )
                text = await self._call_stt_with_model(self._model, prompt, wav_bytes, timeout_s=timeout_s)
            except asyncio.CancelledError:
                return
            except Exception as e:
                retry_after = self._retry_after_seconds_from_error(e)
                if retry_after is None and self._is_transient_unavailable(e):
                    retry_after = 2.0
                if retry_after is None and isinstance(e, TimeoutError):
                    retry_after = 1.0
                if retry_after is not None:
                    self._next_allowed_ts = asyncio.get_running_loop().time() + max(
                        retry_after,
                        float(self._interval_seconds),
                    )
                    # For final flush, retry once after the server-provided delay.
                    if final_flush and retry_after > 0:
                        try:
                            await asyncio.sleep(min(retry_after, 2.0))
                            text = await self._call_stt_with_model(self._model, prompt, wav_bytes, timeout_s=timeout_s)
                        except asyncio.CancelledError:
                            return
                        except Exception as e2:
                            # If the model is temporarily unavailable, try a lighter sibling once.
                            if self._is_transient_unavailable(e2) and str(self._model).strip() == "gemini-flash-latest":
                                try:
                                    await asyncio.sleep(0.5)
                                    text = await self._call_stt_with_model(
                                        "gemini-flash-lite-latest",
                                        prompt,
                                        wav_bytes,
                                        timeout_s=timeout_s,
                                    )
                                except Exception as e3:
                                    logger.exception(
                                        "Sidecar STT error (fallback) model=%s source=%s err_type=%s err=%r",
                                        "gemini-flash-lite-latest",
                                        str(getattr(self, "_model_source", "unknown")),
                                        type(e3).__name__,
                                        e3,
                                    )
                                    return
                                else:
                                    self._model = "gemini-flash-lite-latest"
                                    self._model_source = "fallback_on_503"
                                    logger.warning("Sidecar STT switched model to gemini-flash-lite-latest due to 503")
                                    # Success on fallback.
                                    pass
                            else:
                                logger.exception(
                                    "Sidecar STT error (retry) model=%s source=%s err_type=%s err=%r",
                                    str(self._model),
                                    str(getattr(self, "_model_source", "unknown")),
                                    type(e2).__name__,
                                    e2,
                                )
                                return
                    return
                logger.exception(
                    "Sidecar STT error model=%s source=%s err_type=%s err=%r",
                    str(self._model),
                    str(getattr(self, "_model_source", "unknown")),
                    type(e).__name__,
                    e,
                )
                return

            # Only advance once we successfully called the STT model.
            self._read_offset = end
            self._next_allowed_ts = asyncio.get_running_loop().time() + float(self._interval_seconds)

        if not text:
            return

        if final_flush:
            emit = text
            self._last_emitted = text
            try:
                self._last_final_transcript = emit
            except Exception:
                pass
        else:
            emit = text
            if self._last_emitted and emit.startswith(self._last_emitted):
                suffix = emit[len(self._last_emitted) :].strip()
                if suffix:
                    emit = suffix
                else:
                    return

            self._last_emitted = (self._last_emitted + " " + emit).strip() if self._last_emitted else text

        try:
            await self._session.send_json(
                {
                    "type": "transcript",
                    "text": emit,
                    "source": "input",
                    "partial": False if final_flush else True,
                    "instance_id": INSTANCE_ID,
                }
            )
            logger.info("Sidecar STT emitted chars=%s", str(len(emit)))
        except Exception:
            return


websocket_manager = WebSocketManager()


def gemini_list_models() -> list[str]:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("missing_gemini_api_key")
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})
    return [m.name for m in client.models.list()]


def gemini_live_cache_status() -> dict[str, Any]:
    return {
        "cache_path": _LIVE_CACHE_PATH,
        "cached": _LIVE_WORKING_MODEL_AND_CONFIG,
    }


async def gemini_live_probe_and_cache() -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("missing_gemini_api_key")

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})

    probe_models = [
        "gemini-3.1-flash-live-preview",
        "gemini-2.5-flash-native-audio-latest",
        "gemini-2.5-flash-native-audio-preview-12-2025",
        "lyria-realtime-exp",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-2.0-flash-001",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-lite-001",
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
        "gemini-pro-latest",
    ]

    # Use the same configs as the runtime websocket Live connect logic so the cached
    # config_idx maps correctly.
    text_cfgs, audio_cfgs = _live_configs_for_model()

    attempts: list[dict[str, Any]] = []

    # ~200ms of silence at 16kHz, signed 16-bit little-endian PCM.
    _probe_silence_pcm16 = b"\x00\x00" * int(16000 * 0.2)

    for model in probe_models:
        clean_model = model[7:] if model.startswith("models/") else model
        if _live_is_native_audio_model(clean_model):
            # Prefer AUDIO+TEXT (idx=1) first for native-audio models so we can get
            # input/output transcriptions when supported.
            cfg_indices = [1, 0] if len(audio_cfgs) >= 2 else list(range(len(audio_cfgs)))
            cfgs_to_try = [(i, audio_cfgs[i]) for i in cfg_indices if i < len(audio_cfgs)]
        else:
            cfgs_to_try = list(enumerate(text_cfgs))

        for cfg_idx, cfg in cfgs_to_try:
            try:
                async with client.aio.live.connect(model=clean_model, config=cfg) as live_session:
                    if _live_is_native_audio_model(clean_model):
                        await live_session.send_realtime_input(
                            audio=types.Blob(
                                data=_probe_silence_pcm16,
                                mime_type="audio/pcm;rate=16000",
                            )
                        )
                        # Keep the session alive long enough for the server to process the audio.
                        # Otherwise some models/configs return 1007 when the session closes "without audio".
                        try:
                            await asyncio.wait_for(live_session.receive().__anext__(), timeout=1.5)
                        except Exception:
                            pass
                    global _LIVE_WORKING_MODEL_AND_CONFIG
                    _LIVE_WORKING_MODEL_AND_CONFIG = (clean_model, cfg_idx)
                    try:
                        if _LIVE_CACHE_PATH:
                            os.makedirs(os.path.dirname(_LIVE_CACHE_PATH), exist_ok=True)
                            with open(_LIVE_CACHE_PATH, "w", encoding="utf-8") as f:
                                json.dump({"model": clean_model, "config_idx": cfg_idx}, f)
                    except Exception:
                        pass

                    return {
                        "ok": True,
                        "model": clean_model,
                        "config_idx": cfg_idx,
                        "cache_path": _LIVE_CACHE_PATH,
                        "attempts": attempts,
                    }
            except Exception as e:
                attempts.append({"model": clean_model, "config_idx": cfg_idx, "error": str(e)})

    return {
        "ok": False,
        "cache_path": _LIVE_CACHE_PATH,
        "attempts": attempts,
    }
