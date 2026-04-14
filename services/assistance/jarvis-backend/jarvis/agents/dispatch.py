from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

JARVIS_AGENTS_DIR = os.getenv("JARVIS_AGENTS_DIR", "/app/agents").strip()
JARVIS_AGENT_CONTINUE_WINDOW_SECONDS = int(os.getenv("JARVIS_AGENT_CONTINUE_WINDOW_SECONDS", "120"))


class AgentDefinition:
    """Represents an agent definition loaded from markdown"""
    
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.id = ""
        self.name = ""
        self.kind = ""
        self.trigger_phrases: List[str] = []
        self.content = ""
        self.frontmatter: Dict[str, Any] = {}
        self._load_from_file()
    
    def _load_from_file(self) -> None:
        """Load agent definition from markdown file"""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse frontmatter
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    frontmatter_text = parts[1].strip()
                    self.content = parts[2].strip()
                    try:
                        import yaml
                        self.frontmatter = yaml.safe_load(frontmatter_text) or {}
                    except ImportError:
                        # Fallback to simple parsing
                        self.frontmatter = {}
                        for line in frontmatter_text.split('\n'):
                            if ':' in line:
                                key, value = line.split(':', 1)
                                self.frontmatter[key.strip()] = value.strip()
                else:
                    self.content = content.strip()
            else:
                self.content = content.strip()
            
            # Extract key fields
            self.id = str(self.frontmatter.get("id", "")).strip()
            self.name = str(self.frontmatter.get("name", "")).strip()
            self.kind = str(self.frontmatter.get("kind", "")).strip()
            
            # Parse trigger phrases
            trigger_text = str(self.frontmatter.get("trigger_phrases", "")).strip()
            if trigger_text:
                self.trigger_phrases = [phrase.strip() for phrase in trigger_text.split(",") if phrase.strip()]
            
        except Exception as e:
            logger.error(f"Failed to load agent from {self.file_path}: {e}")
            raise
    
    def matches_trigger(self, text: str) -> bool:
        """Check if this agent matches the trigger text"""
        text_normalized = str(text or "").strip().lower()
        for phrase in self.trigger_phrases:
            if phrase.lower() in text_normalized:
                return True
        return False


class AgentDispatcher:
    """Handles agent discovery and dispatch"""
    
    def __init__(self):
        self.agents: Dict[str, AgentDefinition] = {}
        self.trigger_map: Dict[str, str] = {}  # trigger_phrase -> agent_id
        self.continue_sessions: Dict[str, str] = {}  # session_id -> agent_id
        self.agent_statuses: Dict[str, Dict[str, Any]] = {}
    
    def load_agents(self) -> None:
        """Load all agent definitions from the agents directory"""
        agents_dir = Path(JARVIS_AGENTS_DIR)
        if not agents_dir.exists():
            logger.warning(f"Agents directory not found: {agents_dir}")
            return
        
        self.agents.clear()
        self.trigger_map.clear()
        
        for md_file in agents_dir.glob("*.md"):
            try:
                agent = AgentDefinition(md_file)
                if agent.id:
                    self.agents[agent.id] = agent
                    
                    # Build trigger map
                    for phrase in agent.trigger_phrases:
                        normalized_phrase = phrase.strip().lower()
                        if normalized_phrase:
                            self.trigger_map[normalized_phrase] = agent.id
                
                logger.info(f"Loaded agent: {agent.id} from {md_file.name}")
                
            except Exception as e:
                logger.error(f"Failed to load agent from {md_file}: {e}")
    
    def get_agents_snapshot(self) -> List[Dict[str, Any]]:
        """Get snapshot of all agents for API"""
        snapshot = []
        for agent in self.agents.values():
            snapshot.append({
                "id": agent.id,
                "name": agent.name,
                "kind": agent.kind,
                "trigger_phrases": agent.trigger_phrases,
                "file_path": str(agent.file_path)
            })
        return snapshot
    
    def get_debug_agents_snapshot(self) -> Dict[str, Any]:
        """Get detailed debug snapshot including trigger map"""
        return {
            "agents": self.get_agents_snapshot(),
            "trigger_map": self.trigger_map,
            "continue_sessions": self.continue_sessions,
            "agent_statuses": self.agent_statuses
        }
    
    def find_matching_agent(self, text: str) -> Optional[AgentDefinition]:
        """Find agent that matches the trigger text"""
        text_normalized = str(text or "").strip().lower()
        
        # Check for exact trigger matches first
        for phrase, agent_id in self.trigger_map.items():
            if phrase in text_normalized:
                return self.agents.get(agent_id)
        
        return None
    
    def set_continue_agent(self, session_id: str, agent_id: str) -> None:
        """Set an agent to continue handling for a session"""
        self.continue_sessions[session_id] = agent_id
    
    def get_continue_agent(self, session_id: str) -> Optional[AgentDefinition]:
        """Get the continue agent for a session"""
        agent_id = self.continue_sessions.get(session_id)
        if agent_id:
            return self.agents.get(agent_id)
        return None
    
    def clear_continue_agent(self, session_id: str) -> None:
        """Clear continue agent for a session"""
        self.continue_sessions.pop(session_id, None)
    
    def upsert_agent_status(self, agent_id: str, status: Dict[str, Any]) -> None:
        """Update or insert agent status"""
        if agent_id not in self.agents:
            logger.warning(f"Attempted to update status for unknown agent: {agent_id}")
            return
        
        # Add timestamp
        status["updated_at"] = int(time.time())
        self.agent_statuses[agent_id] = status
    
    def get_agent_statuses(self) -> Dict[str, Any]:
        """Get all agent statuses"""
        return self.agent_statuses.copy()
    
    async def dispatch_to_agent(self, ws: WebSocket, text: str, trace_id: str) -> bool:
        """Dispatch text to matching agent handler"""
        # First check for continue agent
        session_id = getattr(ws.state, "session_id", None)
        if session_id:
            continue_agent = self.get_continue_agent(session_id)
            if continue_agent:
                success = await self._handle_agent_dispatch(ws, continue_agent, text, trace_id)
                if success:
                    return True
                else:
                    # Clear continue agent if it failed
                    self.clear_continue_agent(session_id)
        
        # Check for trigger matches
        matching_agent = self.find_matching_agent(text)
        if matching_agent:
            success = await self._handle_agent_dispatch(ws, matching_agent, text, trace_id)
            if success and session_id:
                # Set as continue agent for follow-ups
                self.set_continue_agent(session_id, matching_agent.id)
            return success
        
        return False
    
    async def _handle_agent_dispatch(self, ws: WebSocket, agent: AgentDefinition, text: str, trace_id: str) -> bool:
        """Handle dispatch to specific agent - to be implemented by agent handlers"""
        # This would be implemented by specific agent handlers
        # For now, return False to indicate no handler
        return False


# Global dispatcher instance
agent_dispatcher = AgentDispatcher()
