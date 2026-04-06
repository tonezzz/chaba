from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class NewsSkill:
    """Skill for handling news-related operations"""
    
    def __init__(self):
        self.name = "news"
        self.description = "Handles news fetching, processing, and briefing"

        # session_id -> (phase, message, ts, running)
        self._job_state: Dict[str, Tuple[str, str, float, bool]] = {}

    def _session_key(self, ws: WebSocket) -> str:
        try:
            sid = getattr(getattr(ws, "state", None), "session_id", None)
            if sid:
                return str(sid)
        except Exception:
            pass
        return "unknown"

    def _set_state(self, ws: WebSocket, phase: str, message: str, running: bool) -> None:
        self._job_state[self._session_key(ws)] = (phase, message, time.time(), running)

    def get_status(self, ws: WebSocket) -> dict[str, Any]:
        key = self._session_key(ws)
        phase, message, ts, running = self._job_state.get(key, ("idle", "", 0.0, False))
        return {
            "phase": phase,
            "message": message,
            "running": bool(running),
            "updated_at": ts,
        }

    async def handle_news_status(self, ws: WebSocket, trace_id: str) -> bool:
        st = self.get_status(ws)
        if st.get("running"):
            await self._send_text(
                ws,
                f"News status: {st.get('phase')} - {st.get('message')}",
                trace_id,
            )
        else:
            await self._send_text(ws, "News status: idle", trace_id)
        return True
    
    async def handle_current_news(self, ws: WebSocket, text: str, trace_id: str) -> bool:
        """Handle current news request"""
        try:
            st = self.get_status(ws)
            if st.get("running"):
                await self._send_text(
                    ws,
                    f"News already running: {st.get('phase')} - {st.get('message')}",
                    trace_id,
                )
                return True

            self._set_state(ws, "start", "starting", True)
            await self._send_progress(ws, "Step 1/3: Fetching current news...", trace_id)
            self._set_state(ws, "fetch", "fetching", True)
            
            # Use the working MCP client functions
            from mcp_client import mcp_tools_call
            from main import MCP_BASE_URL

            # Stepwise pipeline: fetch -> process -> render
            await mcp_tools_call(MCP_BASE_URL, "news_1mcp_news_run", {"start_at": "fetch", "stop_after": "fetch"})

            await self._send_progress(ws, "Step 2/3: Processing news...", trace_id)
            self._set_state(ws, "process", "processing", True)
            await mcp_tools_call(MCP_BASE_URL, "news_1mcp_news_run", {"start_at": "process", "stop_after": "process"})

            await self._send_progress(ws, "Step 3/3: Rendering brief...", trace_id)
            self._set_state(ws, "render", "rendering", True)
            result = await mcp_tools_call(MCP_BASE_URL, "news_1mcp_news_run", {"start_at": "render", "stop_after": "render"})
            
            if "error" in result:
                await self._send_text(ws, f"News fetch failed: {result['error']}", trace_id)
                self._set_state(ws, "error", str(result.get("error") or "error"), False)
                return False
            
            # Extract and return the brief
            brief = result.get("brief", "")
            if brief:
                await self._send_text(ws, brief, trace_id)
                self._set_state(ws, "done", "done", False)
            else:
                await self._send_text(ws, "News fetched but no brief generated", trace_id)
                self._set_state(ws, "done", "no brief", False)
            
            return True
            
        except Exception as e:
            logger.error(f"Error in news skill: {e}")
            await self._send_text(ws, f"Sorry, I encountered an error fetching news: {str(e)}", trace_id)
            self._set_state(ws, "error", str(e), False)
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
