"""
News API Router
Handles current news fetching via MCP.
"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

# Determine MCP base URL based on environment
import os
MCP_ENV = os.getenv("JARVIS_ENV", "development")
if MCP_ENV == "test":
    MCP_BASE_URL = "http://mcp-bundle-assistance-test:3151"
else:
    MCP_BASE_URL = "http://mcp-bundle-assistance:3050"

router = APIRouter()


@router.get("/current-news")
async def get_current_news():
    """Get current news via MCP."""
    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            # Use the working MCP client functions
            from mcp_client import mcp_tools_call

            # Call MCP news_run tool
            result = await mcp_tools_call(MCP_BASE_URL, "news_1mcp_news_run", {
                "start_at": "fetch",
                "stop_after": "render"
            })

            if "error" in result:
                if attempt < max_retries - 1:
                    logger.warning(f"News fetch attempt {attempt + 1} failed, retrying in {retry_delay}s: {result['error']}")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    # Return fallback response on final attempt
                    return {
                        "status": "ok",
                        "brief": "📰 **News Brief** - Service Temporarily Unavailable\n\n• The news service is currently experiencing technical difficulties\n• Please try again in a few moments\n• Alternative: Check your preferred news source directly\n\n*We're working to restore full news functionality ASAP.*",
                        "full_result": {"fallback": True, "error": result['error']},
                        "fallback": True
                    }

            # Extract and return the brief
            brief = result.get("brief", "")
            if brief:
                return {
                    "status": "ok",
                    "brief": brief,
                    "full_result": result
                }
            else:
                if attempt < max_retries - 1:
                    logger.warning(f"News fetch attempt {attempt + 1} returned empty brief, retrying...")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    return {
                        "status": "ok",
                        "message": "News fetched but no brief generated",
                        "result": result,
                        "fallback": True
                    }

        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"News fetch attempt {attempt + 1} failed, retrying in {retry_delay}s: {str(e)}")
                await asyncio.sleep(retry_delay)
                continue
            else:
                logger.error(f"Error in current news endpoint after {max_retries} attempts: {e}")
                return {
                    "status": "ok",
                    "brief": "📰 **News Brief** - Service Unavailable\n\n• Unable to connect to news service at this time\n• This may be due to temporary server maintenance\n• Please try again shortly\n\n*Technical team has been notified.*",
                    "fallback": True
                }
