from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
    from google.genai import errors as genai_errors
except Exception:
    class _GenaiErrorsStub:
        class ClientError(Exception):
            pass

    class _GenaiStub:
        class Client:
            def __init__(self, *args: Any, **kwargs: Any):
                raise RuntimeError("google-genai is not installed")

    class _GenaiTypesStub:
        pass

    genai = _GenaiStub()
    types = _GenaiTypesStub()
    genai_errors = _GenaiErrorsStub()


class GeminiClient:
    """Wrapper for Gemini AI client"""
    
    def __init__(self):
        self.api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
        self.default_model = str(os.getenv("GEMINI_TEXT_MODEL") or "gemini-3-flash-preview").strip()
    
    def get_client(self) -> Any:
        """Get Gemini client instance"""
        if not self.api_key:
            raise RuntimeError("Gemini API key not configured")
        return genai.Client(api_key=self.api_key)
    
    async def generate_content(
        self,
        contents: str,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        **kwargs
    ) -> Any:
        """Generate content using Gemini"""
        client = self.get_client()
        model_name = model or self.default_model
        
        config = {}
        if system_instruction:
            config["system_instruction"] = system_instruction
        
        config.update(kwargs)
        
        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
            return response
        except Exception as e:
            logger.error(f"Gemini generation error: {e}")
            raise
    
    async def summarize_text(
        self,
        text: str,
        system_instruction: str,
        model: Optional[str] = None
    ) -> str:
        """Summarize text using Gemini"""
        try:
            response = await self.generate_content(
                contents=text,
                model=model,
                system_instruction=system_instruction
            )
            
            result = getattr(response, "text", None)
            if result is None:
                result = str(response)
            
            return str(result or "").strip()
        except Exception as e:
            logger.error(f"Text summarization error: {e}")
            return f"Error: {str(e)}"
    
    def normalize_model_name(self, name: str) -> str:
        """Normalize model name"""
        s = str(name or "").strip()
        if s.startswith("models/"):
            s = s[len("models/") :]
        return s
    
    def parse_model_list(self, value: str) -> list[str]:
        """Parse comma-separated model list"""
        parts = [p.strip() for p in str(value or "").split(",")]
        return [p for p in parts if p]


# Global client instance
gemini_client = GeminiClient()
