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

LINE_USE_GLAMA = (os.getenv("LINE_USE_GLAMA") or "").strip().lower() in ("1", "true", "yes", "y")
MCP_GLAMA_URL = (os.getenv("MCP_GLAMA_URL") or "http://host.docker.internal:7441").rstrip("/")


async def _glama_reply(text: str) -> Optional[str]:
    if not LINE_USE_GLAMA:
        return None

    if not MCP_GLAMA_URL:
        return None

    invoke = {
        "tool": "chat_completion",
        "arguments": {
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful assistant responding to LINE messages. Reply briefly.",
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
            "maxTokens": 300,
        },
    }

    try:
        timeout = httpx.Timeout(timeout=12.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{MCP_GLAMA_URL}/invoke", json=invoke)
        if resp.status_code >= 400:
            return None
        data = resp.json() if resp.content else {}
        result = (data or {}).get("result") or {}
        out = (result.get("response") or "").strip()
        return out or None
    except Exception:
        return None


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


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "signatureConfigured": bool(LINE_CHANNEL_SECRET),
        "accessTokenConfigured": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "useGlama": LINE_USE_GLAMA,
        "mcpGlamaUrl": MCP_GLAMA_URL,
    }


@app.post("/webhook/line")
async def webhook_line(
    request: Request,
    x_line_signature: Optional[str] = Header(default=None, convert_underscores=False),
) -> Any:
    raw = await request.body()
    
    # Debug logging
    print(f"Received raw body: {raw}")
    print(f"Received signature: {x_line_signature}")
    
    if not _verify_line_signature(raw, x_line_signature):
        print("Signature verification failed")
        raise HTTPException(status_code=401, detail="invalid_signature")
    
    print("Signature verification passed")

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
                prompt = (text or "").strip()
                if not prompt:
                    continue

                generated = await _glama_reply(prompt)
                reply_text = generated if generated else f"ok: {prompt}"
                await _reply_message(reply_token=reply_token, text=reply_text)
        except Exception as exc:
            reply_errors.append(str(exc))

    return JSONResponse({"status": "ok", "events": len(events), "replyErrors": reply_errors})
