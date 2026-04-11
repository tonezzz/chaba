#!/usr/bin/env python3
"""
Free Model Research Script - Bypass LiteLLM
Uses OpenRouter free models directly via API calls
"""

import os
import json
import requests
from typing import Optional

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
API_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

# Free models that work (from GhostRoute discovery)
FREE_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "minimax/minimax-m2.5:free",
    "arcee-ai/trinity-large-preview:free",
]


def research(query: str, model: str = DEFAULT_MODEL, system_prompt: Optional[str] = None) -> str:
    """
    Perform research using a free model via direct OpenRouter API
    
    Args:
        query: The research question
        model: Model to use (default: nvidia/nemotron-3-super-120b-a12b:free)
        system_prompt: Optional system instructions
    
    Returns:
        The research response
    """
    if not OPENROUTER_API_KEY:
        return "Error: OPENROUTER_API_KEY not set"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8059",
        "X-Title": "AutoAgent Free Research"
    }
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": query})
    
    data = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=120
        )
        response.raise_for_status()
        
        result = response.json()
        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"]
        else:
            return f"Error: Unexpected response format: {json.dumps(result, indent=2)}"
    
    except requests.exceptions.Timeout:
        return "Error: Request timed out (120s). Model may be slow."
    except requests.exceptions.HTTPError as e:
        return f"Error: HTTP {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return f"Error: {str(e)}"


def list_free_models():
    """List available free models"""
    print("Available Free Models (from GhostRoute discovery):")
    print("=" * 60)
    for i, model in enumerate(FREE_MODELS, 1):
        default = " (DEFAULT)" if model == DEFAULT_MODEL else ""
        print(f"{i}. {model}{default}")
    print()


def main():
    """CLI interface"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python free-research.py '<query>' [model]")
        print()
        list_free_models()
        print("Example:")
        print('  python free-research.py "What is Gemini Live API?"')
        print('  python free-research.py "What is Gemini Live API?" "minimax/minimax-m2.5:free"')
        sys.exit(1)
    
    query = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL
    
    print(f"Researching: {query}")
    print(f"Model: {model}")
    print("=" * 60)
    
    system = "You are a research assistant. Provide comprehensive, accurate information with sources when possible."
    result = research(query, model, system)
    
    print(result)


if __name__ == "__main__":
    main()
