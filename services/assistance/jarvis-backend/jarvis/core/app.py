from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jarvis.api.agents import router as agents_router
from jarvis.agents.dispatch import agent_dispatcher
from jarvis.memory.cache import memory_cache

logger = logging.getLogger(__name__)

MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://mcp-bundle-assistance:3050").strip()

# Feature flags for faster startup (treat any non-empty value as skip)
def _is_enabled(env_var: str) -> bool:
    val = os.getenv(env_var, "").strip().lower()
    return val and val not in ("0", "false", "no", "off", "")

JARVIS_SKIP_AGENTS = _is_enabled("JARVIS_SKIP_AGENTS")
JARVIS_SKIP_MEMORY_CACHE = _is_enabled("JARVIS_SKIP_MEMORY_CACHE")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(title="jarvis-backend", version="0.1.0")
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(agents_router, prefix="/jarvis/api", tags=["agents"])
    
    # Register startup events
    @app.on_event("startup")
    async def startup_event():
        """Initialize application on startup"""
        logger.info("Jarvis backend starting up...")
        
        # Load agents (optional for faster startup)
        if JARVIS_SKIP_AGENTS:
            logger.info("Agents loading skipped (JARVIS_SKIP_AGENTS=1)")
        else:
            agent_dispatcher.load_agents()
            logger.info(f"Loaded {len(agent_dispatcher.agents)} agents")
        
        # Initialize memory cache (optional for faster startup)
        if JARVIS_SKIP_MEMORY_CACHE:
            logger.info("Memory cache initialization skipped (JARVIS_SKIP_MEMORY_CACHE=1)")
        else:
            logger.info("Memory cache initialized")
        
        logger.info("Jarvis backend startup complete")
    
    # Register shutdown events
    @app.on_event("shutdown")
    async def shutdown_event():
        """Cleanup on shutdown"""
        logger.info("Jarvis backend shutting down...")
        
        # Cleanup memory cache (only if not skipped)
        if not JARVIS_SKIP_MEMORY_CACHE:
            memory_cache.prune_gems_drafts()
        
        logger.info("Jarvis backend shutdown complete")
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint"""
        agents_count = len(agent_dispatcher.agents) if not JARVIS_SKIP_AGENTS else 0
        return {
            "status": "healthy",
            "version": "0.1.0",
            "agents_loaded": agents_count,
            "agents_skipped": JARVIS_SKIP_AGENTS,
            "memory_cache_skipped": JARVIS_SKIP_MEMORY_CACHE,
            "mcp_base_url": MCP_BASE_URL
        }
    
    return app


def get_app() -> FastAPI:
    """Get the FastAPI application instance"""
    return create_app()
