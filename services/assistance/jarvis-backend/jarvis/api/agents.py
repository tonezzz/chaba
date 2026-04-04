from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from jarvis.agents.dispatch import agent_dispatcher

router = APIRouter()


@router.get("/agents", response_model=List[Dict[str, Any]])
async def list_agents():
    """List all available agents"""
    try:
        return agent_dispatcher.get_agents_snapshot()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list agents: {str(e)}")


@router.get("/debug/agents", response_model=Dict[str, Any])
async def debug_agents():
    """Get detailed debug information about agents"""
    try:
        return agent_dispatcher.get_debug_agents_snapshot()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get debug agents: {str(e)}")


@router.post("/agents/{agent_id}/status")
async def update_agent_status(agent_id: str, status: Dict[str, Any]):
    """Update agent status"""
    try:
        agent_dispatcher.upsert_agent_status(agent_id, status)
        return {"ok": True, "agent_id": agent_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update agent status: {str(e)}")


@router.get("/daily-brief", response_model=Dict[str, Any])
async def get_daily_brief():
    """Get daily brief with agent statuses"""
    try:
        agent_statuses = agent_dispatcher.get_agent_statuses()
        return {
            "ok": True,
            "timestamp": int(time.time()),
            "agent_statuses": agent_statuses
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get daily brief: {str(e)}")
