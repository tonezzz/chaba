from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
GLAMA_MODEL_LIST = (os.getenv("GLAMA_MODEL_LIST") or "").strip()

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


def _model_allowlist() -> List[str]:
    fallback = [GLAMA_MODEL_DEFAULT, "gpt-4o", "gpt-4.1"]
    from_env = [item.strip() for item in GLAMA_MODEL_LIST.split(",") if item.strip()] if GLAMA_MODEL_LIST else []
    merged: List[str] = []
    for item in from_env + fallback:
        if item and item not in merged:
            merged.append(item)
    return merged


def _resolve_model(requested: Optional[str]) -> str:
    if not requested:
        return GLAMA_MODEL_DEFAULT
    candidate = requested.strip()
    return candidate if candidate in _model_allowlist() else GLAMA_MODEL_DEFAULT


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: Union[str, List[Dict[str, Any]]]

    @validator("content")
    def validate_content(cls, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                raise ValueError("content cannot be empty")
            return text

        if isinstance(value, list):
            if not value:
                raise ValueError("content parts cannot be empty")
            # Best-effort validation for OpenAI-style multi-part content.
            for part in value:
                if not isinstance(part, dict):
                    raise ValueError("content part must be an object")
                part_type = (part.get("type") or "").strip()
                if part_type == "text":
                    text = (part.get("text") or "").strip()
                    if not text:
                        raise ValueError("text part cannot be empty")
                elif part_type == "image_url":
                    image_url = part.get("image_url")
                    url = (image_url.get("url") if isinstance(image_url, dict) else "") or ""
                    if not isinstance(url, str) or not url.strip().startswith("data:image/"):
                        raise ValueError("image_url.url must be a data:image/* data URL")
                else:
                    raise ValueError("unsupported content part type")
            return value

        raise ValueError("content must be a string or list of parts")


class InvokeArguments(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    max_tokens: Optional[int] = Field(default=None, alias="maxTokens")
    temperature: Optional[float] = None


class InvokePayload(BaseModel):
    tool: str
    arguments: InvokeArguments


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


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
                                "content": {
                                    "anyOf": [
                                        {"type": "string"},
                                        {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "type": {"type": "string", "enum": ["text", "image_url"]},
                                                    "text": {"type": "string"},
                                                    "image_url": {
                                                        "type": "object",
                                                        "properties": {
                                                            "url": {"type": "string"}
                                                        },
                                                        "required": ["url"],
                                                    },
                                                },
                                                "required": ["type"],
                                            },
                                            "minItems": 1,
                                        },
                                    ]
                                },
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
        "model": _resolve_model(arguments.model),
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
        "modelAllowlist": _model_allowlist(),
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
