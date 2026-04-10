"""API endpoints for provider management and routing."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from jarvis.providers import get_provider_router
from jarvis.providers.smart import get_smart_provider

router = APIRouter()


class GenerateRequest(BaseModel):
    text: str
    has_attachment: bool = False
    budget_tier: str = "auto"
    preferred_provider: str | None = None


class GenerateResponse(BaseModel):
    text: str
    model_id: str
    provider: str
    task_type: str
    input_tokens: int
    output_tokens: int


@router.get("/providers", response_model=dict[str, Any])
async def list_providers():
    """List all initialized providers and their status."""
    router = get_provider_router()
    return {
        "providers": router.get_provider_status(),
        "healthy": router.get_healthy_providers(),
    }


@router.get("/providers/ghostroute")
async def get_ghostroute_status():
    """Get GhostRoute fallback chain status."""
    router = get_provider_router()
    openrouter = router.get_provider("openrouter")

    if not openrouter:
        return {"error": "OpenRouter not initialized"}

    return {
        "ghostroute_loaded": openrouter._ghostroute_loaded,
        "fallback_chain": openrouter.fallback_chain,
        "chain_length": len(openrouter.fallback_chain),
    }


@router.post("/providers/generate", response_model=GenerateResponse)
async def smart_generate(request: GenerateRequest):
    """Generate a response using smart model selection.

    This endpoint demonstrates the full pipeline:
    1. Classify the task
    2. Select best model
    3. Route to appropriate provider
    4. Return response with metadata
    """
    smart = get_smart_provider()
    router = get_provider_router()

    # Override budget tier if specified
    if request.budget_tier != "auto":
        smart.budget_tier = request.budget_tier

    try:
        response = await smart.generate(
            user_text=request.text,
            has_attachment=request.has_attachment,
        )

        return GenerateResponse(
            text=response.text,
            model_id=response.model_id,
            provider=response.provider,
            task_type="unknown",  # Could track this in response
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.error(f"Smart generate failed: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


@router.post("/providers/chat")
async def chat_with_provider(request: GenerateRequest):
    """Simple chat endpoint with smart routing."""
    return await smart_generate(request)
