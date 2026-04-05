"""
MCP Router for integrating with Model Context Protocol servers.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException, WebSocket

from .mcp_client import extract_mcp_text, mcp_text_json, parse_sse_first_message_data


logger = logging.getLogger(__name__)


class MCPRouter:
    """Router for MCP (Model Context Protocol) server communication."""
    
    def __init__(self, base_url: str, timeout: int = 30):
        """
        Initialize MCP router.
        
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
    
    async def health_check(self) -> Dict[str, Any]:
        """Check MCP server health."""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"MCP health check failed: {e}")
            raise HTTPException(status_code=503, detail=f"MCP server unavailable: {e}")
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from MCP server."""
        try:
            response = await self.client.get(f"{self.base_url}/tools")
            response.raise_for_status()
            data = response.json()
            return data.get("tools", [])
        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list tools: {e}")
    
    async def call_tool_with_progress(self, ws: WebSocket, tool_name: str, arguments: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        """
        Call a tool on the MCP server with WebSocket progress updates.
        
        Args:
            ws: WebSocket connection for progress updates
            tool_name: Name of the tool to call
            arguments: Arguments to pass to the tool
            trace_id: Trace ID for tracking
            
        Returns:
            Tool call result
        """
        try:
            # For now, just call the tool without progress updates
            # TODO: Implement proper progress reporting via WebSocket
            result = await self.call_tool(tool_name, arguments)
            
            # Send progress update via WebSocket
            try:
                await ws.send_json({
                    "type": "tool_progress",
                    "tool_name": tool_name,
                    "trace_id": trace_id,
                    "status": "completed",
                    "result": result
                })
            except Exception as ws_error:
                logger.warning(f"Failed to send progress update: {ws_error}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to call MCP tool {tool_name} with progress: {e}")
            
            # Send error update via WebSocket
            try:
                await ws.send_json({
                    "type": "tool_progress",
                    "tool_name": tool_name,
                    "trace_id": trace_id,
                    "status": "error",
                    "error": str(e)
                })
            except Exception as ws_error:
                logger.warning(f"Failed to send error update: {ws_error}")
            
            raise HTTPException(status_code=500, detail=f"Tool call failed: {e}")

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
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
            
            # Extract content from MCP response
            if "result" in data and "content" in data["result"]:
                return data["result"]
            else:
                return data
                
        except Exception as e:
            logger.error(f"Failed to call MCP tool {tool_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Tool call failed: {e}")
    
    async def list_resources(self) -> List[Dict[str, Any]]:
        """List available resources from MCP server."""
        try:
            response = await self.client.get(f"{self.base_url}/resources")
            response.raise_for_status()
            data = response.json()
            return data.get("resources", [])
        except Exception as e:
            logger.error(f"Failed to list MCP resources: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list resources: {e}")
    
    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """
        Read a resource from the MCP server.
        
        Args:
            uri: URI of the resource to read
            
        Returns:
            Resource content
        """
        try:
            response = await self.client.get(f"{self.base_url}/resources/{uri}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to read MCP resource {uri}: {e}")
            raise HTTPException(status_code=500, detail=f"Resource read failed: {e}")
    
    async def list_prompts(self) -> List[Dict[str, Any]]:
        """List available prompts from MCP server."""
        try:
            response = await self.client.get(f"{self.base_url}/prompts")
            response.raise_for_status()
            data = response.json()
            return data.get("prompts", [])
        except Exception as e:
            logger.error(f"Failed to list MCP prompts: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list prompts: {e}")
    
    async def get_prompt(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get a prompt from the MCP server.
        
        Args:
            name: Name of the prompt
            arguments: Optional arguments for the prompt
            
        Returns:
            Prompt content
        """
        try:
            payload = {"name": name}
            if arguments:
                payload["arguments"] = arguments
                
            response = await self.client.post(f"{self.base_url}/prompts/get", json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get MCP prompt {name}: {e}")
            raise HTTPException(status_code=500, detail=f"Prompt get failed: {e}")


# Create a global mcp_router instance for backward compatibility
# This will be initialized in main.py with the proper base_url
mcp_router: Optional[MCPRouter] = None
