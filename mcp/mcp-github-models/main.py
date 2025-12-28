from __future__ import annotations

import os
from datetime import datetime, timezone
import time
from statistics import mean
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator, validator

load_dotenv()

APP_NAME = "mcp-github-models"
APP_VERSION = "0.1.0"

GITHUB_MODELS_API_URL = (
    os.getenv("GITHUB_MODELS_API_URL")
    or os.getenv("GITHUB_MODELS_URL")
    or os.getenv("GITHUB_MODELS_OPENAI_URL")
    or ""
).strip()
GITHUB_MODELS_API_KEY = (os.getenv("GITHUB_MODELS_API_KEY") or os.getenv("GITHUB_TOKEN") or "").strip()
GITHUB_MODELS_MODEL_DEFAULT = (
    os.getenv("GITHUB_MODELS_MODEL")
    or os.getenv("GITHUB_MODELS_MODEL_LLM")
    or os.getenv("GITHUB_MODELS_MODEL_DEFAULT")
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


GITHUB_MODELS_TEMPERATURE_DEFAULT = _float_env("GITHUB_MODELS_TEMPERATURE", 0.2)
GITHUB_MODELS_MAX_TOKENS_DEFAULT = int(os.getenv("GITHUB_MODELS_MAX_TOKENS", "900"))
REQUEST_TIMEOUT_SECONDS = _float_env("GITHUB_MODELS_TIMEOUT_SECONDS", 30.0)


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
    messages: Optional[List[ChatMessage]] = None
    prompt: Optional[str] = None
    system_prompt: Optional[str] = Field(default=None, alias="systemPrompt")
    model: Optional[str] = None
    max_tokens: Optional[int] = Field(default=None, alias="maxTokens")
    temperature: Optional[float] = None

    @validator("prompt")
    def validate_prompt(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = (value or "").strip()
        if not text:
            raise ValueError("prompt cannot be empty")
        return text

    @validator("system_prompt")
    def validate_system_prompt(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = (value or "").strip()
        if not text:
            raise ValueError("system_prompt cannot be empty")
        return text

    @model_validator(mode="after")
    def validate_one_of_messages_or_prompt(self) -> "InvokeArguments":
        messages = self.messages
        prompt = self.prompt
        if (not messages or len(messages) == 0) and not prompt:
            raise ValueError("Either 'messages' or 'prompt' is required")
        if messages and prompt:
            raise ValueError("Provide either 'messages' or 'prompt', not both")
        return self


class InvokePayload(BaseModel):
    tool: str
    arguments: InvokeArguments


class BenchmarkArguments(BaseModel):
    models: List[str] = Field(..., min_items=1)
    trials: int = Field(default=1, ge=1, le=10)
    messages: Optional[List[ChatMessage]] = None
    prompt: Optional[str] = None
    system_prompt: Optional[str] = Field(default=None, alias="systemPrompt")
    max_tokens: Optional[int] = Field(default=None, alias="maxTokens")
    temperature: Optional[float] = None

    @validator("models")
    def validate_models(cls, value: List[str]) -> List[str]:
        cleaned = [item.strip() for item in (value or []) if isinstance(item, str) and item.strip()]
        if not cleaned:
            raise ValueError("models cannot be empty")
        return cleaned

    @validator("prompt")
    def validate_prompt(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = (value or "").strip()
        if not text:
            raise ValueError("prompt cannot be empty")
        return text

    @validator("system_prompt")
    def validate_system_prompt(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = (value or "").strip()
        if not text:
            raise ValueError("system_prompt cannot be empty")
        return text

    @model_validator(mode="after")
    def validate_one_of_messages_or_prompt(self) -> "BenchmarkArguments":
        messages = self.messages
        prompt = self.prompt
        if (not messages or len(messages) == 0) and not prompt:
            raise ValueError("Either 'messages' or 'prompt' is required")
        if messages and prompt:
            raise ValueError("Provide either 'messages' or 'prompt', not both")
        return self


class BenchmarkPayload(BaseModel):
    tool: str
    arguments: BenchmarkArguments


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Any
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


def github_models_ready() -> bool:
    return bool(GITHUB_MODELS_API_KEY and GITHUB_MODELS_API_URL)


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "chat_completion",
            "description": "Send OpenAI-compatible chat messages to GitHub Models.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "minLength": 1},
                    "system_prompt": {"type": "string", "minLength": 1},
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
                "anyOf": [{"required": ["messages"]}, {"required": ["prompt"]}],
            },
        },
        {
            "name": "benchmark_models",
            "description": "Benchmark GitHub Models availability and latency using a fixed prompt/messages input.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "models": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
                    "trials": {"type": "integer", "minimum": 1, "maximum": 10, "default": 1},
                    "prompt": {"type": "string", "minLength": 1},
                    "system_prompt": {"type": "string", "minLength": 1},
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
                    "max_tokens": {"type": "integer", "minimum": 1},
                    "temperature": {"type": "number", "minimum": 0, "maximum": 2},
                },
                "required": ["models"],
                "anyOf": [{"required": ["messages"]}, {"required": ["prompt"]}],
            },
        },
    ]


async def call_github_models(arguments: InvokeArguments) -> Dict[str, Any]:
    if not github_models_ready():
        raise HTTPException(status_code=503, detail="github_models_unconfigured")

    if arguments.prompt:
        messages: List[ChatMessage] = []
        if arguments.system_prompt:
            messages.append(ChatMessage(role="system", content=arguments.system_prompt))
        messages.append(ChatMessage(role="user", content=arguments.prompt))
    else:
        messages = list(arguments.messages or [])

    payload = {
        "model": (arguments.model or GITHUB_MODELS_MODEL_DEFAULT).strip() or GITHUB_MODELS_MODEL_DEFAULT,
        "max_tokens": arguments.max_tokens or GITHUB_MODELS_MAX_TOKENS_DEFAULT,
        "temperature": (
            arguments.temperature if isinstance(arguments.temperature, (int, float)) else GITHUB_MODELS_TEMPERATURE_DEFAULT
        ),
        "messages": [message.dict() for message in messages],
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GITHUB_MODELS_API_KEY}",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(GITHUB_MODELS_API_URL, json=payload, headers=headers)

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text or f"github_models_http_{response.status_code}")

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


async def benchmark_models(arguments: BenchmarkArguments) -> Dict[str, Any]:
    if not github_models_ready():
        raise HTTPException(status_code=503, detail="github_models_unconfigured")

    base_args = InvokeArguments(
        messages=arguments.messages,
        prompt=arguments.prompt,
        systemPrompt=arguments.system_prompt,
        maxTokens=arguments.max_tokens,
        temperature=arguments.temperature,
    )

    results: List[Dict[str, Any]] = []

    for model in arguments.models:
        model_entry: Dict[str, Any] = {
            "model": model,
            "ok": False,
            "error": None,
            "trials": [],
            "latency_ms": None,
        }

        latencies: List[int] = []
        try:
            for _ in range(arguments.trials):
                started = time.perf_counter()
                out = await call_github_models(
                    InvokeArguments(
                        messages=base_args.messages,
                        prompt=base_args.prompt,
                        systemPrompt=base_args.system_prompt,
                        model=model,
                        maxTokens=base_args.max_tokens,
                        temperature=base_args.temperature,
                    )
                )
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                latencies.append(elapsed_ms)
                model_entry["trials"].append(
                    {
                        "ok": True,
                        "latency_ms": elapsed_ms,
                        "response_len": len(out.get("response") or ""),
                    }
                )

            model_entry["ok"] = True
            model_entry["latency_ms"] = int(mean(latencies)) if latencies else None
        except Exception as exc:  # noqa: BLE001
            model_entry["error"] = str(exc)
            model_entry["trials"].append(
                {
                    "ok": False,
                    "latency_ms": None,
                    "error": str(exc),
                }
            )

        results.append(model_entry)

    ok_models = [item for item in results if item.get("ok")]
    best_latency = None
    if ok_models:
        best_latency = sorted(ok_models, key=lambda item: item.get("latency_ms") or 10**12)[0].get("model")

    return {
        "models": results,
        "summary": {
            "best_by_latency": best_latency,
            "ok_count": len(ok_models),
            "total": len(results),
        },
    }


@app.get("/health")
async def health() -> Dict[str, Any]:
    status = "ok" if github_models_ready() else "degraded"
    return {
        "status": status,
        "githubModelsReady": github_models_ready(),
        "model": GITHUB_MODELS_MODEL_DEFAULT,
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
        "description": "GitHub Models chat MCP provider",
        "capabilities": {
            "tools": tool_definitions(),
        },
    }


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    if tool == "chat_completion":
        parsed = InvokePayload(**payload)
        result = await call_github_models(parsed.arguments)
        return {"tool": parsed.tool, "result": result}
    if tool == "benchmark_models":
        parsed = BenchmarkPayload(**payload)
        result = await benchmark_models(parsed.arguments)
        return {"tool": parsed.tool, "result": result}
    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "status": "ok",
    }


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> JsonRpcResponse:
    return JsonRpcResponse(
        id=id_value,
        error=JsonRpcError(code=code, message=message, data=data),
    )


@app.post("/mcp")
async def mcp_endpoint(payload: Dict[str, Any] = Body(...)):
    request = JsonRpcRequest(**(payload or {}))

    if request.id is None:
        return None

    method = (request.method or "").strip()
    params = request.params or {}

    if method == "initialize":
        return JsonRpcResponse(
            id=request.id,
            result={
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                "capabilities": {"tools": {}},
            },
        ).model_dump(exclude_none=True)

    if method in ("tools/list", "list_tools"):
        return JsonRpcResponse(
            id=request.id,
            result={"tools": tool_definitions()},
        ).model_dump(exclude_none=True)

    if method in ("tools/call", "call_tool"):
        tool_name = (params.get("name") or params.get("tool") or "").strip()
        arguments_raw = params.get("arguments") or {}
        if not tool_name:
            return _jsonrpc_error(request.id, -32602, "Missing tool name").model_dump(exclude_none=True)

        if tool_name == "chat_completion":
            parsed = InvokeArguments(**(arguments_raw or {}))
            out = await call_github_models(parsed)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": out.get("response") or ""}]},
            ).model_dump(exclude_none=True)

        if tool_name == "benchmark_models":
            parsed = BenchmarkArguments(**(arguments_raw or {}))
            out = await benchmark_models(parsed)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'").model_dump(exclude_none=True)

    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'").model_dump(exclude_none=True)
