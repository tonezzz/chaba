import json
import os
import time
import uuid
from typing import Any, Dict, Iterator, List, Literal, Optional

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

APP_NAME = "deka-chat-api"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8190"))

MCP_RAG_DEKA_URL = (os.getenv("MCP_RAG_DEKA_URL") or "http://mcp-rag-deka:8055").rstrip("/")
MCP_GLAMA_URL = (os.getenv("MCP_GLAMA_URL") or "http://mcp-glama:8014").rstrip("/")

DEFAULT_TOP_K = int(os.getenv("DEKA_TOP_K", "6"))
MIN_TOP_SCORE = float(os.getenv("DEKA_MIN_TOP_SCORE", "0.12"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("DEKA_CHAT_TIMEOUT_SECONDS", "60"))


def _utc_ts() -> int:
    return int(time.time())


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="deka-rag")
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = Field(default=None, alias="max_tokens")


app = FastAPI(title=APP_NAME, version=APP_VERSION)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "timestamp": _utc_ts(),
        "mcpRag": MCP_RAG_DEKA_URL,
        "mcpGlama": MCP_GLAMA_URL,
    }


@app.get("/status")
def status() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "timestamp": _utc_ts(),
        "mcpRag": MCP_RAG_DEKA_URL,
        "mcpGlama": MCP_GLAMA_URL,
        "topK": DEFAULT_TOP_K,
        "minTopScore": MIN_TOP_SCORE,
        "timeoutSeconds": HTTP_TIMEOUT_SECONDS,
    }


def _model_list() -> Dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": "deka-rag",
                "object": "model",
                "created": 0,
                "owned_by": APP_NAME,
            }
        ],
    }


@app.get("/v1/models")
def list_models_v1() -> Dict[str, Any]:
    return _model_list()


@app.get("/models")
def list_models() -> Dict[str, Any]:
    return _model_list()


def _sse(event: Dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _sse_done() -> str:
    return "data: [DONE]\n\n"


async def _rag_search(query: str, *, limit: int) -> List[Dict[str, Any]]:
    payload = {
        "tool": "search_text",
        "arguments": {
            "query": query,
            "limit": limit,
        },
    }

    timeout = httpx.Timeout(timeout=HTTP_TIMEOUT_SECONDS, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{MCP_RAG_DEKA_URL}/invoke", json=payload)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=r.text or f"mcp_rag_http_{r.status_code}")

    data = r.json() or {}
    result = data.get("result") or {}
    results = result.get("results") or []
    out: List[Dict[str, Any]] = []
    for hit in results:
        if not isinstance(hit, dict):
            continue
        out.append(hit)
    return out


def _extract_user_question(messages: List[ChatMessage]) -> str:
    for msg in reversed(messages or []):
        if msg.role == "user" and (msg.content or "").strip():
            return msg.content.strip()
    return ""


def _build_context_md(hits: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for idx, hit in enumerate(hits, start=1):
        payload = (hit.get("payload") or {}) if isinstance(hit.get("payload"), dict) else {}
        doc_id = str(payload.get("doc_id") or payload.get("docId") or "").strip()
        year = payload.get("source_year") or payload.get("year") or payload.get("sourceYear")
        text = str(payload.get("text") or "").strip()
        score = hit.get("score")

        title = f"{idx}) doc_id {doc_id or '-'}" + (f" (ปี {year})" if year is not None else "")
        lines.append(title)
        if score is not None:
            lines.append(f"score: {score}")
        if text:
            excerpt = text
            if len(excerpt) > 800:
                excerpt = excerpt[:800] + "…"
            lines.append(excerpt)
        lines.append("")

    return "\n".join(lines).strip()


def _build_sources_md(hits: List[Dict[str, Any]]) -> str:
    lines: List[str] = ["\n---\n", "### Sources (DEKA)"]
    for idx, hit in enumerate(hits, start=1):
        payload = (hit.get("payload") or {}) if isinstance(hit.get("payload"), dict) else {}
        doc_id = str(payload.get("doc_id") or payload.get("docId") or "").strip() or "-"
        year = payload.get("source_year") or payload.get("year") or payload.get("sourceYear")
        text = str(payload.get("text") or "").strip()

        excerpt = text
        if len(excerpt) > 240:
            excerpt = excerpt[:240] + "…"

        head = f"{idx}) DEKA doc_id {doc_id}" + (f" (ปี {year})" if year is not None else "")
        lines.append(head)
        if excerpt:
            lines.append(f"> {excerpt.replace('\n', ' ')}")

    return "\n".join(lines).strip() + "\n"


def _build_retrieval_only_answer(question: str, hits: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("โหมดสรุปอัตโนมัติยังไม่พร้อมใช้งาน จะแสดงเฉพาะหลักฐานจากฐาน DEKA ที่ค้นพบ")
    lines.append("")
    lines.append(f"คำถาม: {question}")
    lines.append("")
    lines.append("หลักฐานที่เกี่ยวข้อง (ตัดตอน):")
    for idx, hit in enumerate(hits, start=1):
        payload = (hit.get("payload") or {}) if isinstance(hit.get("payload"), dict) else {}
        doc_id = str(payload.get("doc_id") or payload.get("docId") or "").strip() or "-"
        year = payload.get("source_year") or payload.get("year") or payload.get("sourceYear")
        text = str(payload.get("text") or "").strip()
        excerpt = text
        if len(excerpt) > 600:
            excerpt = excerpt[:600] + "…"
        head = f"{idx}) doc_id {doc_id}" + (f" (ปี {year})" if year is not None else "")
        lines.append(head)
        if excerpt:
            lines.append(excerpt)
        lines.append("")
    return "\n".join(lines).strip()


async def _call_glama(question: str, *, system_prompt: str, temperature: Optional[float], max_tokens: Optional[int]) -> str:
    invoke = {
        "tool": "chat_completion",
        "arguments": {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            "temperature": temperature,
            "maxTokens": max_tokens,
        },
    }

    timeout = httpx.Timeout(timeout=HTTP_TIMEOUT_SECONDS, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{MCP_GLAMA_URL}/invoke", json=invoke)

    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=r.text or f"mcp_glama_http_{r.status_code}")

    data = r.json() or {}
    result = data.get("result") or {}
    text = (result.get("response") or "").strip()
    return text


def _chunk_text(text: str, chunk_size: int = 120) -> Iterator[str]:
    t = text or ""
    i = 0
    while i < len(t):
        yield t[i : i + chunk_size]
        i += chunk_size


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest = Body(...), request: Request = None) -> Any:
    question = _extract_user_question(req.messages)
    if not question:
        raise HTTPException(status_code=400, detail="missing user question")

    hits = await _rag_search(question, limit=max(1, min(DEFAULT_TOP_K, 20)))

    top_score = None
    if hits:
        try:
            top_score = float(hits[0].get("score"))
        except Exception:
            top_score = None

    if not hits or (top_score is not None and top_score < MIN_TOP_SCORE):
        final_text = (
            "ไม่พบข้อมูลในฐาน DEKA ที่จัดทำไว้สำหรับคำถามนี้\n\n"
            "แนะนำให้ลองระบุคำค้นที่เฉพาะเจาะจงขึ้น เช่น คำสำคัญ, มาตรา, หรือบริบทข้อเท็จจริงเพิ่มเติม\n"
        )
        sources_md = "\n---\n\n### Sources (DEKA)\n(ไม่มีหลักฐานที่เพียงพอจากฐานข้อมูลที่จัดทำไว้)\n"
        final_text = final_text + sources_md
    else:
        context_md = _build_context_md(hits)
        sources_md = _build_sources_md(hits)

        system_prompt = (
            "คุณเป็นผู้ช่วยสำหรับการสืบค้นคำพิพากษาศาลฎีกา (DEKA) เท่านั้น\n"
            "- ตอบเป็นภาษาไทยโดยค่าเริ่มต้น\n"
            "- ตอบโดยอ้างอิงเฉพาะข้อความหลักฐาน (excerpts) ที่ให้มาใน CONTEXT เท่านั้น\n"
            "- หากหลักฐานไม่เพียงพอ ให้ตอบว่าไม่พบข้อมูลในฐาน DEKA\n"
            "- ตอบให้กระชับ ชัดเจน และถ้าเป็นไปได้ให้สรุปประเด็นข้อกฎหมาย\n\n"
            "CONTEXT (DEKA excerpts):\n"
            f"{context_md}\n"
        )

        answer: Optional[str] = None
        try:
            answer = await _call_glama(
                question,
                system_prompt=system_prompt,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )
        except HTTPException:
            answer = None
        except Exception:
            answer = None

        if not (answer or "").strip():
            final_text = _build_retrieval_only_answer(question, hits) + "\n" + sources_md
        else:
            final_text = (answer or "").strip() + "\n" + sources_md

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = _utc_ts()

    if not req.stream:
        return JSONResponse(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": req.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": final_text},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    async def gen() -> Iterator[bytes]:
        for part in _chunk_text(final_text, chunk_size=140):
            event = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": req.model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": part},
                        "finish_reason": None,
                    }
                ],
            }
            yield _sse(event).encode("utf-8")
        final_event = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield _sse(final_event).encode("utf-8")
        yield _sse_done().encode("utf-8")

    return StreamingResponse(gen(), media_type="text/event-stream")
