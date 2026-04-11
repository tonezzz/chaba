from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jarvis.api.agents import router as agents_router
from jarvis.api.dialog import router as dialog_router
from jarvis.api.models import router as models_router
from jarvis.api.providers import router as providers_router
from jarvis.agents.dispatch import agent_dispatcher
from jarvis.memory.cache import memory_cache
from jarvis.models import seed_all_models, get_model_registry_summary
from jarvis.providers import get_provider_router

logger = logging.getLogger(__name__)

MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://mcp-bundle-assistance:3050").strip()


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
    app.include_router(dialog_router, prefix="/jarvis/api", tags=["dialog"])
    app.include_router(models_router, prefix="/jarvis/api", tags=["models"])
    app.include_router(providers_router, prefix="/jarvis/api", tags=["providers"])
    
    # Register startup events
    @app.on_event("startup")
    async def startup_event():
        """Initialize application on startup"""
        logger.info("Jarvis backend starting up...")
        
        # Load agents
        agent_dispatcher.load_agents()
        logger.info(f"Loaded {len(agent_dispatcher.agents)} agents")
        
        # Initialize memory cache (could preload from storage here)
        logger.info("Memory cache initialized")
        
        # Initialize model registry
        seed_all_models()
        models = get_model_registry_summary()
        free_count = sum(1 for m in models if m["cost_input"] == "0")
        logger.info("Model registry initialized: %s models (%s free)", len(models), free_count)
        for m in models[:5]:  # Log first 5
            logger.info("  - %s (%s): %s ctx, tools=%s", m["id"], m["provider"], m["context_window"], m["supports_tools"])
        
        # Initialize providers
        router = get_provider_router()
        healthy = router.get_healthy_providers()
        logger.info("Providers initialized: %s", healthy)
        
        logger.info("Jarvis backend startup complete")
    
    # Register shutdown events
    @app.on_event("shutdown")
    async def shutdown_event():
        """Cleanup on shutdown"""
        logger.info("Jarvis backend shutting down...")
        
        # Cleanup memory cache
        memory_cache.prune_gems_drafts()
        
        logger.info("Jarvis backend shutdown complete")
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint"""
        models = get_model_registry_summary()
        router = get_provider_router()
        return {
            "status": "healthy",
            "version": "0.1.0",
            "agents_loaded": len(agent_dispatcher.agents),
            "mcp_base_url": MCP_BASE_URL,
            "models_registered": len(models),
            "free_models_available": sum(1 for m in models if m["cost_input"] == "0"),
            "providers": router.get_provider_status(),
        }
    
    return app


def get_app() -> FastAPI:
    """Get the FastAPI application instance"""
    return create_app()
