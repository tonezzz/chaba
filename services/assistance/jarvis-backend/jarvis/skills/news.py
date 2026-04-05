from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class NewsSkill:
    """Skill for handling news-related operations"""
    
    def __init__(self):
        self.name = "news"
        self.description = "Handles news fetching, processing, and briefing"
    
    async def handle_current_news(self, ws: WebSocket, text: str, trace_id: str) -> bool:
        """Handle current news request"""
        try:
            await self._send_progress(ws, "Fetching current news...", trace_id)
            
            # Use the working MCP client functions
            from mcp_client import mcp_tools_call
            from main import MCP_BASE_URL
            
            # Call MCP news_run tool with correct tool name format
            result = await mcp_tools_call(MCP_BASE_URL, "news_1mcp_news_run", {
                "start_at": "fetch", "stop_after": "render"
            })
            
            if "error" in result:
                await self._send_text(ws, f"News fetch failed: {result['error']}", trace_id)
                return False
            
            # Extract and return the brief
            brief = result.get("brief", "")
            if brief:
                await self._send_text(ws, brief, trace_id)
            else:
                await self._send_text(ws, "News fetched but no brief generated", trace_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error in news skill: {e}")
            await self._send_text(ws, f"Sorry, I encountered an error fetching news: {str(e)}", trace_id)
            return False
    
    async def handle_follow_news(self, ws: WebSocket, text: str, trace_id: str) -> bool:
        """Handle follow news request"""
        try:
            await self._send_progress(ws, "Setting up news following...", trace_id)
            
            # For now, just return a message about follow-up
            await self._send_text(ws, "News following feature is being integrated. You can ask for current news updates.", trace_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error in follow news skill: {e}")
            await self._send_text(ws, f"Sorry, I encountered an error setting up news following: {str(e)}", trace_id)
            return False
    
    async def _send_progress(self, ws: WebSocket, message: str, trace_id: str) -> None:
        """Send progress message"""
        try:
            await ws.send_json({
                "type": "progress",
                "text": message,
                "phase": "progress",
                "instance_id": "news_skill",
                "trace_id": trace_id
            })
        except Exception as e:
            logger.error(f"Failed to send progress: {e}")
    
    async def _send_text(self, ws: WebSocket, text: str, trace_id: str) -> None:
        """Send text message"""
        try:
            await ws.send_json({
                "type": "text",
                "text": text,
                "instance_id": "news_skill",
                "trace_id": trace_id
            })
        except Exception as e:
            logger.error(f"Failed to send text: {e}")


# Global skill instance
news_skill = NewsSkill()
