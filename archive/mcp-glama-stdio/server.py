import asyncio
import os
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio

load_dotenv()

server = Server("glama-mcp")

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
        if value != value:
            return fallback
        return value
    except (TypeError, ValueError):
        return fallback


GLAMA_TEMPERATURE_DEFAULT = _float_env("GLAMA_TEMPERATURE", 0.2)
GLAMA_MAX_TOKENS_DEFAULT = int(os.getenv("GLAMA_MAX_TOKENS", "900"))
REQUEST_TIMEOUT_SECONDS = _float_env("GLAMA_TIMEOUT_SECONDS", 30.0)


def _require_configured() -> None:
    if not GLAMA_API_URL or not GLAMA_API_KEY:
        raise ValueError("glama_unconfigured")


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name="chat_completion",
            description="Send OpenAI-compatible chat messages to Glama gateway.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "minLength": 1},
                    "system_prompt": {"type": "string", "minLength": 1},
                    "messages": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string", "enum": ["user", "assistant", "system"]},
                                "content": {"type": "string"},
                            },
                            "required": ["role", "content"],
                        },
                    },
                    "model": {"type": "string"},
                    "max_tokens": {"type": "integer", "minimum": 1},
                    "temperature": {"type": "number", "minimum": 0, "maximum": 2},
                },
                "anyOf": [{"required": ["messages"]}, {"required": ["prompt"]}],
            },
        )
    ]


async def _call_glama(payload: Dict[str, Any]) -> Dict[str, Any]:
    _require_configured()

    prompt = payload.get("prompt")
    system_prompt = payload.get("system_prompt")
    messages = payload.get("messages")

    if prompt and messages:
        raise ValueError("Provide either 'messages' or 'prompt', not both")

    if prompt:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt cannot be empty")
        computed_messages: List[Dict[str, Any]] = []
        if system_prompt is not None:
            if not isinstance(system_prompt, str) or not system_prompt.strip():
                raise ValueError("system_prompt cannot be empty")
            computed_messages.append({"role": "system", "content": system_prompt.strip()})
        computed_messages.append({"role": "user", "content": prompt.strip()})
        messages = computed_messages
    else:
        if not isinstance(messages, list) or not messages:
            raise ValueError("Either 'messages' or 'prompt' is required")

    model = (payload.get("model") or GLAMA_MODEL_DEFAULT).strip() or GLAMA_MODEL_DEFAULT
    max_tokens = payload.get("max_tokens") or GLAMA_MAX_TOKENS_DEFAULT
    temperature = payload.get("temperature")
    if not isinstance(temperature, (int, float)):
        temperature = GLAMA_TEMPERATURE_DEFAULT

    req = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
        "stream": False,
    }

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {GLAMA_API_KEY}"}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        resp = await client.post(GLAMA_API_URL, json=req, headers=headers)

    if resp.status_code >= 400:
        raise RuntimeError(resp.text or f"glama_http_{resp.status_code}")

    data = resp.json()
    choices = data.get("choices") or []
    combined = "\n".join(
        [
            (choice.get("message") or {}).get("content", "").strip()
            for choice in choices
            if isinstance(choice, dict)
        ]
    ).strip()

    return {"response": combined, "raw": data}


@server.call_tool()
async def handle_call_tool(name: str, arguments: Optional[Dict[str, Any]] = None) -> List[types.TextContent]:
    arguments = arguments or {}

    try:
        if name != "chat_completion":
            raise ValueError(f"Unknown tool: {name}")

        result = await _call_glama(arguments)
        return [types.TextContent(type="text", text=str(result.get("response", "")))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="glama-mcp",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
