import base64
import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types


APP_TITLE = "idc1-chaba01"
INSTANCE_ID = hashlib.sha256(f"{APP_TITLE}:{time.time()}".encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name) or default)
    except Exception:
        return default


def _env_str(name: str, default: str = "") -> str:
    return str(os.getenv(name) or default).strip()


@dataclass
class DocChunk:
    chunk_id: str
    heading: str
    text: str


@dataclass
class DocPack:
    url: str
    title: str
    text: str
    summary: str
    chunks: list[DocChunk]
    updated_at: str
    sha256: str


_DOC: Optional[DocPack] = None
_DOC_LAST_FETCH_TS: float = 0.0


def _chunk_text(text: str, *, max_chars: int = 1200) -> list[DocChunk]:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    paras: list[str] = []
    cur: list[str] = []
    for ln in lines:
        if not ln:
            if cur:
                paras.append(" ".join(cur).strip())
                cur = []
            continue
        cur.append(ln)
    if cur:
        paras.append(" ".join(cur).strip())

    chunks: list[DocChunk] = []
    buf = ""
    idx = 0
    for p in paras:
        if not p:
            continue
        if len(buf) + len(p) + 2 <= max_chars:
            buf = (buf + "\n\n" + p).strip() if buf else p
            continue
        if buf:
            idx += 1
            chunks.append(DocChunk(chunk_id=f"c{idx}", heading=f"chunk {idx}", text=buf))
        buf = p
    if buf:
        idx += 1
        chunks.append(DocChunk(chunk_id=f"c{idx}", heading=f"chunk {idx}", text=buf))
    return chunks


async def _fetch_source(url: str) -> DocPack:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        content_type = str(r.headers.get("content-type") or "").lower()
        raw = r.text

    title = url
    text = raw
    if "text/html" in content_type or raw.lstrip().startswith("<"):
        soup = BeautifulSoup(raw, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        for tag in soup(["script", "style", "noscript"]):
            try:
                tag.decompose()
            except Exception:
                pass
        text = soup.get_text("\n")

    text = "\n".join([ln.rstrip() for ln in (text or "").splitlines()])
    text = "\n".join([ln for ln in text.splitlines() if ln.strip()])

    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    summary = (text[:700] + "…") if len(text) > 700 else text
    chunks = _chunk_text(text)

    return DocPack(
        url=url,
        title=title,
        text=text,
        summary=summary,
        chunks=chunks,
        updated_at=_now_iso(),
        sha256=sha,
    )


def _score_chunk(query: str, chunk: DocChunk) -> float:
    q = [w for w in (query or "").lower().split() if w]
    if not q:
        return 0.0
    t = (chunk.text or "").lower()
    score = 0.0
    for w in q:
        if len(w) < 3:
            continue
        if w in t:
            score += 1.0
    return score


def _select_chunks(query: str, *, k: int = 5) -> list[dict[str, Any]]:
    global _DOC
    if _DOC is None:
        return []
    scored = []
    for ch in _DOC.chunks:
        s = _score_chunk(query, ch)
        if s <= 0:
            continue
        scored.append((s, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for s, ch in scored[: max(1, k)]:
        out.append(
            {
                "chunk_id": ch.chunk_id,
                "heading": ch.heading,
                "score": s,
                "excerpt": (ch.text[:220] + "…") if len(ch.text) > 220 else ch.text,
            }
        )
    return out


async def _ensure_doc(force: bool = False) -> Optional[DocPack]:
    global _DOC, _DOC_LAST_FETCH_TS
    url = _env_str("SOURCE_URL")
    if not url:
        return None

    ttl = _env_int("SOURCE_REFRESH_TTL_SECONDS", 86400)
    now = time.time()
    if not force and _DOC is not None and _DOC_LAST_FETCH_TS and (now - _DOC_LAST_FETCH_TS) < ttl:
        return _DOC

    _DOC = await _fetch_source(url)
    _DOC_LAST_FETCH_TS = now
    return _DOC


def _ws_url_from_request(ws: WebSocket) -> str:
    proto = "wss" if (ws.url.scheme == "https") else "ws"
    return f"{proto}://{ws.url.hostname}{(':' + str(ws.url.port)) if ws.url.port else ''}/ws/live"


app = FastAPI(title=APP_TITLE)

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/health")
async def health() -> JSONResponse:
    doc = await _ensure_doc(force=False)
    return JSONResponse(
        {
            "ok": True,
            "app": APP_TITLE,
            "instance_id": INSTANCE_ID,
            "time": _now_iso(),
            "source_loaded": bool(doc),
            "source_hash": doc.sha256 if doc else None,
        }
    )


@app.get("/source")
async def source() -> JSONResponse:
    doc = await _ensure_doc(force=False)
    if not doc:
        return JSONResponse({"ok": False, "error": "missing_source_url"}, status_code=400)
    return JSONResponse(
        {
            "ok": True,
            "url": doc.url,
            "title": doc.title,
            "updated_at": doc.updated_at,
            "sha256": doc.sha256,
            "chunk_count": len(doc.chunks),
        }
    )


@app.post("/refresh")
async def refresh() -> JSONResponse:
    doc = await _ensure_doc(force=True)
    if not doc:
        return JSONResponse({"ok": False, "error": "missing_source_url"}, status_code=400)
    return JSONResponse({"ok": True, "updated_at": doc.updated_at, "sha256": doc.sha256})


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


async def _ws_send_json(ws: WebSocket, obj: dict[str, Any]) -> None:
    await ws.send_json({**obj, "instance_id": INSTANCE_ID})


async def _ws_to_gemini_loop(ws: WebSocket, session: Any) -> None:
    while True:
        msg = await ws.receive_json()
        msg_type = msg.get("type")

        if msg_type == "ping":
            await _ws_send_json(ws, {"type": "pong"})
            continue

        if msg_type == "audio":
            data_b64 = str(msg.get("data") or "")
            mime_type = str(msg.get("mimeType") or "audio/pcm;rate=16000")
            if not data_b64:
                continue
            audio_bytes = base64.b64decode(data_b64)
            await session.send_realtime_input(audio=types.Blob(data=audio_bytes, mime_type=mime_type))
            continue

        if msg_type == "audio_stream_end":
            await session.send_realtime_input(audio_stream_end=True)

            # Grounding injection: once the user finishes a voice turn, send a text turn
            # containing the relevant source context plus the most recent input transcript.
            last_tr = str(getattr(ws.state, "last_input_transcript", "") or "").strip()
            if last_tr:
                await _emit_grounded_text_turn(ws, session, last_tr)
            continue

        if msg_type == "text":
            text = str(msg.get("text") or "").strip()
            if not text:
                continue
            await _emit_grounded_text_turn(ws, session, text)
            continue

        if msg_type == "close":
            return


async def _emit_grounded_text_turn(ws: WebSocket, session: Any, user_text: str) -> None:
    doc = await _ensure_doc(force=False)
    selected = _select_chunks(user_text, k=5)

    citations = {
        "type": "citations",
        "source_url": doc.url if doc else None,
        "source_hash": doc.sha256 if doc else None,
        "chunks": selected,
        "query": user_text,
    }
    try:
        await _ws_send_json(ws, citations)
    except Exception:
        pass

    parts: list[str] = []
    parts.append(
        "You are a voice assistant. Answer the user using ONLY the SOURCE_CONTEXT below. "
        "If the answer is not in the source, say you can't find it in the source."
    )
    if doc:
        parts.append(f"SOURCE_TITLE: {doc.title}\nSOURCE_URL: {doc.url}\nSOURCE_UPDATED_AT: {doc.updated_at}")
        parts.append("SOURCE_SUMMARY:\n" + (doc.summary or ""))
    if selected:
        ctx_lines = []
        for ch in selected:
            ctx_lines.append(f"[{ch.get('chunk_id')}] {ch.get('heading')}\n{ch.get('excerpt')}")
        parts.append("SOURCE_CONTEXT_EXCERPTS:\n" + "\n\n".join(ctx_lines))
    parts.append("USER_QUESTION:\n" + user_text)

    payload = "\n\n".join([p for p in parts if p.strip()])
    await session.send_client_content(turns={"parts": [{"text": payload}]}, turn_complete=True)


async def _gemini_to_ws_loop(ws: WebSocket, session: Any) -> None:
    async for server_msg in session.receive():
        # Input transcription (user speech -> text)
        server_content = getattr(server_msg, "server_content", None)
        if server_content is not None:
            input_tr = getattr(server_content, "input_transcription", None)
            if input_tr is not None:
                text = getattr(input_tr, "text", None)
                if text:
                    ws.state.last_input_transcript = str(text)
                    await _ws_send_json(ws, {"type": "transcript", "text": str(text), "source": "input"})

        # Model text
        try:
            if server_content is not None:
                model_turn = getattr(server_content, "model_turn", None)
                if model_turn is not None:
                    parts = getattr(model_turn, "parts", None) or []
                    for part in parts:
                        part_text = getattr(part, "text", None)
                        if part_text:
                            await _ws_send_json(ws, {"type": "text", "text": str(part_text)})
                            break
        except Exception:
            pass

        # Model audio
        audio_b64 = _extract_audio_b64(server_msg)
        if audio_b64:
            await _ws_send_json(ws, {"type": "audio", "data": audio_b64, "sampleRate": 24000})


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()

    api_key = _env_str("GEMINI_API_KEY") or _env_str("API_KEY")
    if not api_key:
        await _ws_send_json(ws, {"type": "error", "message": "missing_api_key"})
        await ws.close(code=1011)
        return

    await _ensure_doc(force=False)

    model = _env_str("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
    doc = _DOC

    system_instruction = (
        "You are a voice assistant. Respond with a spoken answer. "
        "Be concise. Do not reveal hidden reasoning. "
        "If the user asks about the source, answer from it."
    )
    if doc:
        system_instruction = system_instruction + "\n\n" + (
            "SOURCE_SUMMARY (internal; do not repeat verbatim):\n" + (doc.summary or "")
        )

    config = {
        "response_modalities": ["AUDIO", "TEXT"],
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "system_instruction": system_instruction,
    }

    client = genai.Client(api_key=api_key)

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            ws.state.last_input_transcript = ""
            await _ws_send_json(
                ws,
                {
                    "type": "state",
                    "state": "connected",
                    "model": model,
                    "ws_url": _ws_url_from_request(ws),
                    "source": {
                        "url": doc.url if doc else None,
                        "title": doc.title if doc else None,
                        "updated_at": doc.updated_at if doc else None,
                        "sha256": doc.sha256 if doc else None,
                    },
                },
            )

            to_gemini = None
            to_ws = None
            try:
                import asyncio

                to_gemini = asyncio.create_task(_ws_to_gemini_loop(ws, session), name="ws_to_gemini")
                to_ws = asyncio.create_task(_gemini_to_ws_loop(ws, session), name="gemini_to_ws")
                done, pending = await asyncio.wait({to_gemini, to_ws}, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
            finally:
                if to_gemini is not None and not to_gemini.done():
                    to_gemini.cancel()
                if to_ws is not None and not to_ws.done():
                    to_ws.cancel()

    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await _ws_send_json(ws, {"type": "error", "message": "gemini_live_failed", "detail": str(e)})
        except Exception:
            pass
        try:
            await ws.close(code=1011)
        except Exception:
            pass
