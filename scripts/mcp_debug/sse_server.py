"""SSE/HTTP MCP server for mcp-debug.

Runs as a persistent process on a known port (default 9101). The Devin/Windsurf
client can connect via `url: http://localhost:9101/sse` instead of re-spawning
the stdio wrapper for every call.
"""
import json
import logging
import os
import sys

import mcp_types as types
import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))

from mcp_debug import server as mcp_debug_server

logger = logging.getLogger(__name__)


async def on_list_tools(ctx, params: types.ListToolsRequestParams | None):
    del ctx, params
    response = mcp_debug_server.handle_tools_list(0)
    raw_tools = response.get("result", {}).get("tools", [])
    tools = []
    for t in raw_tools:
        tools.append(
            types.Tool(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {"type": "object"}),
            )
        )
    return types.ListToolsResult(tools=tools)


async def on_call_tool(ctx, params: types.CallToolRequestParams):
    del ctx
    response = mcp_debug_server.handle_tools_call(
        0, {"name": params.name, "arguments": json.loads(params.arguments) if isinstance(params.arguments, str) else params.arguments}
    )
    if "error" in response:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(response["error"]))],
            isError=True,
        )
    text = response["result"]["content"][0]["text"]
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


mcp = Server("mcp-debug", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


def create_app():
    transport = SseServerTransport("/messages/")

    async def sse_app(scope, receive, send):
        async with transport.connect_sse(scope, receive, send) as (read_stream, write_stream):
            await mcp.run(
                read_stream,
                write_stream,
                mcp.create_initialization_options(),
            )

    return Starlette(
        debug=True,
        routes=[
            Mount("/sse", app=sse_app),
            Mount("/messages", app=transport.handle_post_message),
        ],
    )


def main():
    logging.basicConfig(level=logging.INFO)
    host = os.environ.get("MCP_DEBUG_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_DEBUG_PORT", "9101"))
    logger.info("mcp-debug SSE server starting on %s:%d", host, port)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
