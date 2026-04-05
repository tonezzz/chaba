"""
MCP Client utilities for communicating with Model Context Protocol servers.
"""

import json
import uuid
from typing import Any, Optional

import httpx
from fastapi import HTTPException


def extract_mcp_text(result: Any) -> str:
    """Extract text content from MCP result."""
    if not isinstance(result, dict):
        return ""
    content = result.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                t = c.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
        return "\n".join(parts).strip()
    t2 = result.get("text")
    if isinstance(t2, str):
        return t2.strip()
    return ""


def mcp_text_json(result: Any) -> Any:
    """Parse MCP text content as JSON."""
    if not isinstance(result, dict):
        return result
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return result
    first = content[0] if isinstance(content[0], dict) else None
    if not isinstance(first, dict):
        return result
    text = first.get("text")
    if not isinstance(text, str) or not text.strip():
        return result
    try:
        return json.loads(text)
    except Exception:
        return result


def parse_sse_first_message_data(text: str) -> dict[str, Any]:
    """Parse first message data from SSE response."""
    # MCP servers can return multiple SSE events in a single HTTP response.
    # The final JSON-RPC message with the tool call result might not be the first `data:` line.
    last_msg: dict[str, Any] = {}
    for line in (text or "").splitlines():
        if not line.startswith("data: "):
            continue
        try:
            data = line[6:]  # Remove "data: " prefix
            parsed = json.loads(data)
            last_msg = parsed
        except json.JSONDecodeError:
            continue
    return last_msg


class MCPClient:
    """Client for communicating with MCP servers."""
    
    def __init__(self, base_url: str, timeout: int = 30):
        """
        Initialize MCP client.
        
        Args:
            base_url: Base URL of the MCP server
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool on the MCP server.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Arguments to pass to the tool
            
        Returns:
            Tool call result
        """
        try:
            payload = {
                "name": tool_name,
                "arguments": arguments
            }
            
            response = await self.client.post(
                f"{self.base_url}/tools/call",
                json=payload
            )
            response.raise_for_status()
            
            data = response.json()
            return data.get("result", data)
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Tool call failed: {e}")
    
    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from MCP server."""
        try:
            response = await self.client.get(f"{self.base_url}/tools")
            response.raise_for_status()
            data = response.json()
            return data.get("tools", [])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list tools: {e}")
    
    async def health_check(self) -> dict[str, Any]:
        """Check MCP server health."""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"MCP server unavailable: {e}")
