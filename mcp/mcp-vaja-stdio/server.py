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

server = Server("vaja-mcp")

AI4THAI_API_KEY = (os.getenv("AI4THAI_API_KEY") or "").strip()
VAJA_ENDPOINT = (os.getenv("VAJA_ENDPOINT") or "https://api.aiforthai.in.th/vaja").strip()


def _require_configured() -> None:
    if not AI4THAI_API_KEY:
        raise ValueError("AI4THAI_API_KEY is not configured")


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name="synthesize_speech",
            description="Generate Thai speech audio via VAJA (AI4Thai).",
            inputSchema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 400},
                    "speaker": {
                        "type": "string",
                        "enum": [
                            "nana",
                            "noina",
                            "farah",
                            "mewzy",
                            "farsai",
                            "prim",
                            "ped",
                            "poom",
                            "doikham",
                            "praw",
                            "wayu",
                            "namphueng",
                            "toon",
                            "sanooch",
                            "thanwa",
                        ],
                    },
                    "style": {"type": "string"},
                    "download": {
                        "type": "boolean",
                        "description": "If true, download audio and return size; otherwise return audio_url.",
                    },
                },
            },
        )
    ]


async def _request_vaja(text: str, speaker: str, style: Optional[str]) -> Dict[str, Any]:
    _require_configured()

    payload: Dict[str, Any] = {"text": text, "speaker": speaker}
    if style:
        payload["style"] = style

    headers = {"Content-Type": "application/json", "Apikey": AI4THAI_API_KEY}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(VAJA_ENDPOINT, json=payload, headers=headers)

    if resp.status_code >= 400:
        raise RuntimeError(resp.text or f"vaja_http_{resp.status_code}")

    data = resp.json()
    if not isinstance(data, dict) or not data.get("audio_url"):
        raise RuntimeError("VAJA response missing audio_url")

    return data


async def _download_audio(audio_url: str) -> int:
    headers = {"Apikey": AI4THAI_API_KEY}

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(audio_url, headers=headers)
        resp.raise_for_status()
        return len(resp.content)


@server.call_tool()
async def handle_call_tool(name: str, arguments: Optional[Dict[str, Any]] = None) -> List[types.TextContent]:
    arguments = arguments or {}

    try:
        if name != "synthesize_speech":
            raise ValueError(f"Unknown tool: {name}")

        text = str(arguments.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")

        speaker = str(arguments.get("speaker") or "noina").strip() or "noina"
        style = arguments.get("style")
        style = str(style).strip() if isinstance(style, str) else None
        download = bool(arguments.get("download"))

        data = await _request_vaja(text=text, speaker=speaker, style=style)
        audio_url = str(data.get("audio_url"))

        if download:
            size = await _download_audio(audio_url)
            return [types.TextContent(type="text", text=f"audio_url={audio_url}\nbytes={size}")]

        return [types.TextContent(type="text", text=f"audio_url={audio_url}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="vaja-mcp",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
