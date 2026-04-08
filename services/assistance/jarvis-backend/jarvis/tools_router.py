"""Thin wrapper around MCP tool handlers.

This module re-exports the dispatcher from jarvis.mcp.handlers for backwards compatibility.
All tool logic has been moved to modular handlers in jarvis/mcp/handlers/.

NOTE: jarvis.mcp.handlers module not yet implemented - commented out to unblock pytest.
"""
from __future__ import annotations
from typing import Any, Optional

# TODO: Implement jarvis.mcp.handlers and uncomment
# from jarvis.mcp.handlers import dispatch_mcp_tool_call


async def handle_mcp_tool_call(
    session_id: Optional[str], tool_name: str, args: dict[str, Any], *, deps: dict[str, Any]
) -> Any:
    """Handle MCP tool call by dispatching to appropriate handler module.

    Args:
        session_id: WebSocket session ID
        tool_name: Name of the tool to invoke
        args: Tool arguments
        deps: Dependency injection dictionary

    Returns:
        Tool call result
    """
    # TODO: Uncomment when jarvis.mcp.handlers is implemented
    # return await dispatch_mcp_tool_call(session_id, tool_name, args, deps=deps)
    raise NotImplementedError("MCP tool handlers not yet implemented")


# Re-export for backwards compatibility
__all__ = ["handle_mcp_tool_call"]
