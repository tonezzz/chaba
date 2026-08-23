#!/usr/bin/env python3
"""test_generation.py — stdio MCP client for mcp-gpu.

Stops llama, runs a 512x512/4-step lightning text-to-image job,
then restarts llama and reports the saved PNG.
"""
import asyncio
import json
import pathlib
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SERVER = pathlib.Path(__file__).with_name("server.py")


def _text(result) -> str:
    for item in result.content:
        if hasattr(item, "text"):
            return item.text
    return ""


async def call(session: ClientSession, name: str, arguments: dict | None = None):
    result = await session.call_tool(name, arguments=arguments or {})
    return _text(result)


async def main():
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("GPU status before:")
            print(json.dumps(json.loads(await call(session, "gpu_status")), indent=2))

            print("\nRequesting image (mcp-gpu will hold llama)...")
            result_text = await call(
                session,
                "generate_image",
                {
                    "prompt": "a corgi in a cartoon spaceship, high quality",
                    "width": 512,
                    "height": 512,
                    "steps": 4,
                    "seed": 42,
                    "timeout": 300,
                },
            )
            data = json.loads(result_text)
            print(json.dumps(data, indent=2))

            print("\nGPU status after:")
            print(json.dumps(json.loads(await call(session, "gpu_status")), indent=2))

            if not data.get("success"):
                raise SystemExit(1)
            print(
                f"\nPASS: image saved to {data['image_path']} ({data['image_size_bytes']} bytes)"
            )


if __name__ == "__main__":
    asyncio.run(main())
