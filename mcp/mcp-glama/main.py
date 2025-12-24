from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

load_dotenv()

APP_NAME = "mcp-glama"
APP_VERSION = "0.1.0"

GLAMA_API_URL = (os.getenv("GLAMA_API_URL") or os.getenv("GLAMA_URL") or "").strip()
GLAMA_API_KEY = (os.getenv("GLAMA_API_KEY") or "").strip()
GLAMA_MODEL_DEFAULT = (
    os.getenv("GLAMA_MODEL")
    or os.getenv("GLAMA_MODEL_LLM")
    or os.getenv("GLAMA_MODEL_DEFAULT")
    or "gpt-4o-mini"
).strip()

def _float_env(name: str, fallback: float) -> float:
    try:
        value = float(os.getenv(name, fallback))
        if value != value:  # NaN guard
            return fallback
        return value
    except (TypeError, ValueError):
        return fallback


GLAMA_TEMPERATURE_DEFAULT = _float_env("GLAMA_TEMPERATURE", 0.2)
GLAMA_MAX_TOKENS_DEFAULT = int(os.getenv("GLAMA_MAX_TOKENS", "900"))
REQUEST_TIMEOUT_SECONDS = _float_env("GLAMA_TIMEOUT_SECONDS", 30.0)


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str

    @validator("content")
    def validate_content(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("content cannot be empty")
        return text


class InvokeArguments(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    max_tokens: Optional[int] = Field(default=None, alias="maxTokens")
    temperature: Optional[float] = None


class InvokePayload(BaseModel):
    tool: str
    arguments: InvokeArguments


class _JsonRpcRequest(BaseModel):
    jsonrpc: str
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


def _mcp_tools_list() -> List[Dict[str, Any]]:
    return [
        {
            "name": "chat_completion",
            "description": "Send OpenAI-compatible chat messages to Glama gateway.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string", "enum": ["user", "assistant", "system"]},
                                "content": {"type": "string"},
                            },
                            "required": ["role", "content"],
                        },
                        "minItems": 1,
                    },
                    "model": {"type": "string"},
                    "max_tokens": {"type": "integer", "minimum": 1},
                    "temperature": {"type": "number", "minimum": 0, "maximum": 2},
                },
                "required": ["messages"],
            },
        }
    ]


@app.post("/mcp")
async def mcp_endpoint(
    request: _JsonRpcRequest,
    response: Response,
    mcp_session_id: Optional[str] = Header(default=None, alias="Mcp-Session-Id"),
) -> Any:
    session_id = mcp_session_id or str(uuid.uuid4())
    response.headers["Mcp-Session-Id"] = session_id

    method = (request.method or "").strip()
    params = request.params or {}

    if request.jsonrpc != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    if request.id is None:
        if method == "notifications/initialized":
            return Response(status_code=204)
        return Response(status_code=204)

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "result": {
                "protocolVersion": (params.get("protocolVersion") or "2024-11-05"),
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                "capabilities": {"tools": {}},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request.id, "result": {"tools": _mcp_tools_list()}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != "chat_completion":
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            }

        try:
            invoke_args = InvokeArguments.model_validate(arguments)
            result = await call_glama(invoke_args)
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "result": {"content": [{"type": "text", "text": result.get("response", "")}]},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {"code": -32000, "message": str(exc)},
            }

    return {
        "jsonrpc": "2.0",
        "id": request.id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def glama_ready() -> bool:
    return bool(GLAMA_API_KEY and GLAMA_API_URL)


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "chat_completion",
            "description": "Send OpenAI-compatible chat messages to Glama gateway.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string", "enum": ["user", "assistant", "system"]},
                                "content": {"type": "string"},
                            },
                            "required": ["role", "content"],
                        },
                        "minItems": 1,
                    },
                    "model": {"type": "string"},
                    "max_tokens": {"type": "integer", "minimum": 1},
                    "temperature": {"type": "number", "minimum": 0, "maximum": 2},
                },
                "required": ["messages"],
            },
        }
    ]


async def call_glama(arguments: InvokeArguments) -> Dict[str, Any]:
    if not glama_ready():
        raise HTTPException(status_code=503, detail="glama_unconfigured")

    payload = {
        "model": (arguments.model or GLAMA_MODEL_DEFAULT).strip() or GLAMA_MODEL_DEFAULT,
        "max_tokens": arguments.max_tokens or GLAMA_MAX_TOKENS_DEFAULT,
        "temperature": (
            arguments.temperature
            if isinstance(arguments.temperature, (int, float))
            else GLAMA_TEMPERATURE_DEFAULT
        ),
        "messages": [message.dict() for message in arguments.messages],
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GLAMA_API_KEY}",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(GLAMA_API_URL, json=payload, headers=headers)

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text or f"glama_http_{response.status_code}")

    data = response.json()
    choices = data.get("choices") or []
    combined_text = "\n".join(
        filter(
            None,
            [choice.get("message", {}).get("content", "").strip() for choice in choices],
        )
    ).strip()

    return {
        "response": combined_text,
        "raw": data,
    }


@app.get("/health")
async def health() -> Dict[str, Any]:
    status = "ok" if glama_ready() else "degraded"
    return {
        "status": status,
        "glamaReady": glama_ready(),
        "model": GLAMA_MODEL_DEFAULT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": tool_definitions()}


@app.get("/.well-known/mcp.json")
async def well_known_manifest() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "Glama chat MCP provider",
        "capabilities": {
            "tools": tool_definitions(),
        },
    }


@app.post("/invoke")
async def invoke(payload: InvokePayload) -> Dict[str, Any]:
    if payload.tool != "chat_completion":
        raise HTTPException(status_code=404, detail=f"unknown tool '{payload.tool}'")

    result = await call_glama(payload.arguments)
    return {
        "tool": payload.tool,
        "result": result,
    }


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "status": "ok",
    }
