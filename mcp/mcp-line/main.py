import base64
import hmac
import hashlib
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI()

logger = logging.getLogger("mcp-line")

LINE_CHANNEL_SECRET = (os.getenv("LINE_CHANNEL_SECRET") or "").strip()
LINE_CHANNEL_ACCESS_TOKEN = (os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()

LINE_USE_GLAMA = (os.getenv("LINE_USE_GLAMA") or "").strip().lower() in ("1", "true", "yes", "y", "on")
GLAMA_MCP_URL = (os.getenv("GLAMA_MCP_URL") or "").strip()
MCP_GLAMA_URL = (os.getenv("MCP_GLAMA_URL") or "http://host.docker.internal:7441").strip()
GLAMA_MODEL = (os.getenv("GLAMA_MODEL") or "").strip()
GLAMA_SYSTEM_PROMPT = (os.getenv("GLAMA_SYSTEM_PROMPT") or "").strip()


def _verify_line_signature(raw_body: bytes, signature_b64: Optional[str]) -> bool:
    if not LINE_CHANNEL_SECRET:
        return False
    if not signature_b64:
        return False

    mac = hmac.new(LINE_CHANNEL_SECRET.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature_b64)


async def _reply_message(reply_token: str, text: str) -> None:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return

    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            detail = (resp.text or "").strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."
            logger.warning("LINE reply failed: status=%s body=%s", resp.status_code, detail)
            raise RuntimeError(f"line_reply_failed_{resp.status_code}:{detail}")


async def _generate_reply(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return "ok"

    base_url = (GLAMA_MCP_URL or MCP_GLAMA_URL).strip().rstrip("/")
    if not (LINE_USE_GLAMA and base_url):
        return f"ok: {cleaned}"

    system_prompt = GLAMA_SYSTEM_PROMPT or "You are a helpful assistant replying to a LINE chat message. Keep replies concise."
    payload: Dict[str, Any] = {
        "tool": "chat_completion",
        "arguments": {
            "prompt": cleaned,
            "system_prompt": system_prompt,
        },
    }
    if GLAMA_MODEL:
        payload["arguments"]["model"] = GLAMA_MODEL

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base_url}/invoke", json=payload)
        if resp.status_code >= 400:
            logger.warning("Glama invoke failed: status=%s body=%s", resp.status_code, (resp.text or "").strip())
            return f"ok: {cleaned}"

        data = resp.json() if resp.headers.get("content-type", "").lower().startswith("application/json") else {}
        result = (data or {}).get("result") or {}
        out = (result or {}).get("response") or ""
        out = (out or "").strip()
        return out or f"ok: {cleaned}"
    except Exception as exc:
        logger.warning("Glama invoke exception: %s", str(exc))
        return f"ok: {cleaned}"


@app.get("/health")
async def health() -> Dict[str, Any]:
    base_url = (GLAMA_MCP_URL or MCP_GLAMA_URL).strip().rstrip("/")
    return {
        "status": "ok",
        "signatureConfigured": bool(LINE_CHANNEL_SECRET),
        "accessTokenConfigured": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "useGlama": bool(LINE_USE_GLAMA and base_url),
        "glamaUrl": base_url,
    }


@app.post("/webhook/line")
async def webhook_line(
    request: Request,
    x_line_signature: Optional[str] = Header(default=None, alias="X-Line-Signature"),
) -> Any:
    raw = await request.body()

    if not _verify_line_signature(raw, x_line_signature):
        raise HTTPException(status_code=401, detail="invalid_signature")

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_json: {exc}")

    events: List[Dict[str, Any]] = body.get("events") or []

    # Minimal behavior:
    # - If message event with a replyToken, echo back short text.
    # - Always return 200 quickly so LINE considers it delivered.
    reply_errors: List[str] = []

    for evt in events:
        try:
            reply_token = evt.get("replyToken")
            evt_type = evt.get("type")
            message = evt.get("message") or {}
            message_type = message.get("type")
            text = message.get("text")

            if evt_type == "message" and message_type == "text" and reply_token:
                reply_text = await _generate_reply(text=text or "")
                await _reply_message(reply_token=reply_token, text=reply_text)
        except Exception as exc:
            reply_errors.append(str(exc))

    return JSONResponse({"status": "ok", "events": len(events), "replyErrors": reply_errors})
