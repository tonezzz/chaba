import asyncio
import base64
import os
import logging
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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


async def _ws_to_gemini_loop(ws: WebSocket, session: Any) -> None:
    audio_frames = 0
    while True:
        msg = await ws.receive_json()
        msg_type = msg.get("type")

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
