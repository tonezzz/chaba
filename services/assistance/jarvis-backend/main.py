import asyncio
import base64
import os
import logging
import sqlite3
import time
from typing import Any, Optional

import httpx
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv

from google import genai
from google.genai import types


def _require_env(name: str) -> str:
    value = str(os.getenv(name, "") or "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


load_dotenv()

MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")

logger = logging.getLogger("jarvis-backend")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="jarvis-backend", version="0.1.0")


TRIP_BASE_URL = str(os.getenv("TRIP_BASE_URL") or "http://trip:8000").strip().rstrip("/")
TRIP_API_TOKEN = str(os.getenv("TRIP_API_TOKEN") or "").strip()


SESSION_DB_PATH = os.getenv("JARVIS_SESSION_DB", "/app/jarvis_sessions.sqlite")


def _init_session_db() -> None:
    os.makedirs(os.path.dirname(SESSION_DB_PATH) or ".", exist_ok=True)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              active_trip_id TEXT,
              active_trip_name TEXT,
              updated_at INTEGER
            )
            """
        )
        conn.commit()


def _get_session_state(session_id: str) -> dict[str, Optional[str]]:
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT active_trip_id, active_trip_name FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"active_trip_id": None, "active_trip_name": None}
        return {"active_trip_id": row[0], "active_trip_name": row[1]}


def _set_session_state(session_id: str, active_trip_id: Optional[str], active_trip_name: Optional[str]) -> None:
    now = int(time.time())
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions(session_id, active_trip_id, active_trip_name, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              active_trip_id=excluded.active_trip_id,
              active_trip_name=excluded.active_trip_name,
              updated_at=excluded.updated_at
            """,
            (session_id, active_trip_id, active_trip_name, now),
        )
        conn.commit()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"] ,
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "jarvis-backend"}


async def _trip_get(path: str) -> Any:
    if not TRIP_API_TOKEN:
        raise HTTPException(status_code=500, detail="missing_TRIP_API_TOKEN")
    url = f"{TRIP_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(url, headers={"X-Api-Token": TRIP_API_TOKEN})
        res.raise_for_status()
        return res.json()


async def _trip_post(path: str, payload: Any) -> Any:
    if not TRIP_API_TOKEN:
        raise HTTPException(status_code=500, detail="missing_TRIP_API_TOKEN")
    url = f"{TRIP_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(url, json=payload, headers={"X-Api-Token": TRIP_API_TOKEN})
        res.raise_for_status()
        return res.json()


def _require_confirmation(confirm: bool, action: str, payload: Any) -> None:
    if confirm:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "requires_confirmation": True,
            "action": action,
            "payload": payload,
        },
    )


@app.get("/trip/by_token/categories")
async def trip_by_token_categories() -> Any:
    return await _trip_get("/api/by_token/categories")


@app.post("/trip/by_token/google_search")
async def trip_by_token_google_search(payload: dict[str, Any] = Body(...)) -> Any:
    return await _trip_post("/api/by_token/google-search", payload)


@app.post("/trip/by_token/place")
async def trip_by_token_create_place(payload: dict[str, Any] = Body(...)) -> Any:
    confirm = bool(payload.pop("confirm", False))
    _require_confirmation(confirm, action="trip_create_place", payload=payload)
    return await _trip_post("/api/by_token/place", payload)


async def _ws_to_gemini_loop(ws: WebSocket, session: Any) -> None:
    audio_frames = 0
    while True:
        msg = await ws.receive_json()
        msg_type = msg.get("type")

        # Session control messages (handled locally, never forwarded to Gemini)
        if msg_type == "get_active_trip":
            session_id = getattr(ws.state, "session_id", None)
            if not session_id:
                await ws.send_json({"type": "active_trip", "active_trip_id": None, "active_trip_name": None})
                continue
            state = _get_session_state(str(session_id))
            await ws.send_json({"type": "active_trip", **state})
            continue

        if msg_type == "set_active_trip":
            session_id = getattr(ws.state, "session_id", None)
            active_trip_id = msg.get("active_trip_id")
            active_trip_name = msg.get("active_trip_name")
            if not session_id:
                await ws.send_json({"type": "error", "message": "missing_session_id"})
                continue
            _set_session_state(
                str(session_id),
                str(active_trip_id) if active_trip_id is not None else None,
                str(active_trip_name) if active_trip_name is not None else None,
            )
            state = _get_session_state(str(session_id))
            await ws.send_json({"type": "active_trip", **state})
            continue

        if msg_type == "audio":
            data_b64 = str(msg.get("data") or "")
            mime_type = str(msg.get("mimeType") or "audio/pcm;rate=16000")
            if not data_b64:
                continue
            audio_bytes = base64.b64decode(data_b64)
            await session.send_realtime_input(audio=types.Blob(data=audio_bytes, mime_type=mime_type))
            audio_frames += 1
            if audio_frames % 50 == 0:
                logger.info("forwarded_audio_frames=%s", audio_frames)
            continue

        if msg_type == "text":
            text = str(msg.get("text") or "")
            if not text:
                continue
            await session.send_client_content(turns=text, turn_complete=True)
            continue

        if msg_type == "audio_stream_end":
            await session.send_realtime_input(audio_stream_end=True)
            continue

        if msg_type == "close":
            return


def _extract_audio_b64(server_msg: Any) -> Optional[str]:
    try:
        server_content = getattr(server_msg, "server_content", None)
        if not server_content:
            return None
        model_turn = getattr(server_content, "model_turn", None)
        if not model_turn:
            return None
        parts = getattr(model_turn, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if not inline_data:
                continue
            data = getattr(inline_data, "data", None)
            if not data:
                continue
            if isinstance(data, (bytes, bytearray)):
                return base64.b64encode(bytes(data)).decode("ascii")
            if isinstance(data, str):
                return data
            try:
                as_bytes = bytes(data)
                return base64.b64encode(as_bytes).decode("ascii")
            except Exception:
                return str(data)
    except Exception:
        return None
    return None


async def _gemini_to_ws_loop(ws: WebSocket, session: Any) -> None:
    audio_out_frames = 0
    logged_shape = False
    logged_server_content_shape = False
    while True:
        async for server_msg in session.receive():
            transcription = getattr(server_msg, "transcription", None)
            if transcription is not None:
                text = getattr(transcription, "text", None)
                if text:
                    await ws.send_json({"type": "transcript", "text": str(text)})
                    continue
            elif not logged_shape:
                # One-time debug to understand server message fields.
                try:
                    keys = list(getattr(server_msg, "__dict__", {}).keys())
                    logger.info("live_msg_fields=%s", keys)
                except Exception:
                    logger.info("live_msg_type=%s", type(server_msg))
                logged_shape = True

            server_content = getattr(server_msg, "server_content", None)
            if server_content is not None:
                if not logged_server_content_shape:
                    try:
                        keys = list(getattr(server_content, "__dict__", {}).keys())
                        logger.info("live_server_content_fields=%s", keys)
                    except Exception:
                        logger.info("live_server_content_type=%s", type(server_content))
                    logged_server_content_shape = True

                input_tr = getattr(server_content, "input_transcription", None)
                if input_tr is not None:
                    text = getattr(input_tr, "text", None)
                    if text:
                        await ws.send_json({"type": "transcript", "text": str(text), "source": "input"})
                        continue

                output_tr = getattr(server_content, "output_transcription", None)
                if output_tr is not None:
                    text = getattr(output_tr, "text", None)
                    if text:
                        await ws.send_json({"type": "transcript", "text": str(text), "source": "output"})
                        continue

                model_turn = getattr(server_content, "model_turn", None)
                if model_turn is not None:
                    parts = getattr(model_turn, "parts", None) or []
                    for part in parts:
                        part_text = getattr(part, "text", None)
                        if part_text:
                            await ws.send_json({"type": "text", "text": str(part_text)})
                            break

            audio_b64 = _extract_audio_b64(server_msg)
            if audio_b64:
                await ws.send_json({"type": "audio", "data": audio_b64, "sampleRate": 24000})
                audio_out_frames += 1
                if audio_out_frames % 10 == 0:
                    logger.info("sent_audio_frames=%s", audio_out_frames)
                continue

            # Send text if present (useful for debugging / future UI)
            text = getattr(server_msg, "text", None)
            if text:
                await ws.send_json({"type": "text", "text": str(text)})


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()

    # Sticky session support: the frontend provides ?session_id=... so we can persist
    # per-session state (e.g., active trip) across reconnects.
    session_id = str(ws.query_params.get("session_id") or "").strip() or None
    ws.state.session_id = session_id
    if session_id:
        try:
            _init_session_db()
            state = _get_session_state(session_id)
            await ws.send_json({"type": "active_trip", **state})
        except Exception as e:
            logger.warning("session_db_init_failed error=%s", e)

    try:
        api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("Missing required env var: API_KEY (or GEMINI_API_KEY)")
        client = genai.Client(api_key=api_key)
        config = {
            "response_modalities": ["AUDIO"],
            "input_audio_transcription": {},
            "output_audio_transcription": {},
        }

        logger.info("gemini_live_connect model=%s", MODEL)
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            await ws.send_json({"type": "state", "state": "connected"})

            to_gemini = asyncio.create_task(_ws_to_gemini_loop(ws, session))
            to_ws = asyncio.create_task(_gemini_to_ws_loop(ws, session))

            done, pending = await asyncio.wait(
                [to_gemini, to_ws],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                _ = task.result()

    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
        return
