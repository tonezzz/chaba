#!/usr/bin/env python3
"""
GhostRoute Discovery Test for AutoAgent

Tests GhostRoute's model ranking and captures discovery for reuse.
Saves results to discovery/ghostroute/latest/

Usage:
  cd /app && python test-ghostroute.py
"""

import os
import json
import time
import requests
from datetime import datetime
from pathlib import Path

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DISCOVERY_DIR = Path("/workspace/discovery/ghostroute")
TEST_PROMPT = "What is 2+2? Answer with just the number."

# GhostRoute ranking weights (from their docs)
WEIGHTS = {
    "context_length": 0.40,
    "capabilities": 0.30,
    "recency": 0.20,
    "provider_trust": 0.10
}

# Provider trust scores (heuristic based on reliability)
PROVIDER_TRUST = {
    "anthropic": 0.95,
    "google": 0.90,
    "openai": 0.90,
    "meta": 0.85,
    "mistral": 0.85,
    "microsoft": 0.85,
    "amazon": 0.80,
    "other": 0.70
}

def fetch_free_models():
    """Fetch free models from OpenRouter API."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/tonezzz/chaba",
        "X-Title": "GhostRoute Discovery Test"
    }
    
    try:
        resp = requests.get(
            f"{OPENROUTER_BASE_URL}/models",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        
        # Filter for free models only
        free_models = []
        for model in data.get("data", []):
            model_id = model.get("id", "")
            # Free models end with ":free" or have 0 cost
            pricing = model.get("pricing", {})
            is_free = (
                model_id.endswith(":free") or
                (pricing.get("prompt", 0) == 0 and pricing.get("completion", 0) == 0)
            )
            if is_free:
                free_models.append(model)
        
        return free_models
    except Exception as e:
        print(f"Error fetching models: {e}")
        return []

def score_model(model):
    """Score a model using GhostRoute's algorithm."""
    # Context length score (normalized to typical max)
    context = model.get("context_length", 4096)
    context_score = min(context / 200000, 1.0)  # 200k is near top tier
    
    # Capabilities score based on supported features
    capabilities = 0.5  # base
    if model.get("architecture", {}).get("modality") == "text+image":
        capabilities += 0.2
    if model.get("top_provider", {}).get("is_moderated") is False:
        capabilities += 0.1  # less restricted
    if model.get("per_request_limits"):
        capabilities += 0.1
    capabilities = min(capabilities, 1.0)
    
    # Recency score (newer = better, heuristic based on model ID patterns)
    model_id = model.get("id", "").lower()
    recency = 0.5
    if any(x in model_id for x in ["2025", "-25-", "latest"]):
        recency = 0.9
    elif any(x in model_id for x in ["2024", "-24-"]):
        recency = 0.8
    elif any(x in model_id for x in ["2023", "-23-"]):
        recency = 0.6
    
    # Provider trust score
    provider = model.get("id", "").split("/")[0] if "/" in model.get("id", "") else "other"
    trust = PROVIDER_TRUST.get(provider, PROVIDER_TRUST["other"])
    
    # Calculate weighted score
    score = (
        context_score * WEIGHTS["context_length"] +
        capabilities * WEIGHTS["capabilities"] +
        recency * WEIGHTS["recency"] +
        trust * WEIGHTS["provider_trust"]
    )
    
    return {
        "context_score": round(context_score, 3),
        "capabilities_score": round(capabilities, 3),
        "recency_score": round(recency, 3),
        "trust_score": round(trust, 3),
        "total_score": round(score, 3)
    }

def test_model(model_id, timeout=30):
    """Test a single model with a simple prompt."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/tonezzz/chaba",
        "X-Title": "GhostRoute Discovery Test"
    }
    
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": TEST_PROMPT}],
        "max_tokens": 10,
        "temperature": 0
    }
    
    start = time.time()
    try:
        resp = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout
        )
        latency = round(time.time() - start, 3)
        
        success = resp.status_code == 200
        if success:
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {
                "success": True,
                "latency_ms": latency * 1000,
                "response": content.strip(),
                "tokens_used": data.get("usage", {}).get("total_tokens", 0)
            }
        else:
            return {
                "success": False,
                "latency_ms": latency * 1000,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}"
            }
    except Exception as e:
        return {
            "success": False,
            "latency_ms": (time.time() - start) * 1000,
            "error": str(e)
        }

def generate_recommended_config(ranked_models, test_results):
    """Generate recommended AutoAgent config based on test results."""
    # Filter to models that passed testing
    working = [m for m in ranked_models if test_results.get(m["id"], {}).get("success")]
    
    if not working:
        return {"error": "No working models found"}
    
    # Primary: highest scoring working model
    primary = working[0]
    
    # Fallbacks: next 5 working models + openrouter/free as first fallback
    fallbacks = ["openrouter/free"] + [m["id"] for m in working[1:6]]
    
    return {
        "primary_model": primary["id"],
        "primary_score": primary.get("ghostroute_score", {}),
        "fallback_chain": fallbacks,
        "fallback_count": len(fallbacks),
        "test_summary": {
            "tested": len(ranked_models),
            "working": len(working),
            "success_rate": round(len(working) / len(ranked_models) * 100, 1)
        },
        "autoagent_env": {
            "AUTOAGENT_MODEL": primary["id"],
            "AUTOAGENT_API_BASE_URL": "https://openrouter.ai/api/v1",
            "OPENROUTER_API_KEY": "$OPENROUTER_API_KEY"
        }
    }

def main():
    """Main discovery test."""
    print("=" * 60)
    print("GhostRoute Discovery Test for AutoAgent")
    print("=" * 60)
    
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        return 1
    
    # Setup directories
    latest_dir = DISCOVERY_DIR / "latest"
    history_dir = DISCOVERY_DIR / "history" / datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    latest_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n[1/4] Fetching free models from OpenRouter...")
    models = fetch_free_models()
    print(f"      Found {len(models)} free models")
    
    if not models:
        print("ERROR: No free models found. Check API key.")
        return 1
    
    print(f"\n[2/4] Ranking models with GhostRoute algorithm...")
    ranked = []
    for model in models:
        scores = score_model(model)
        ranked.append({
            "id": model.get("id"),
            "name": model.get("name"),
            "context_length": model.get("context_length"),
            "architecture": model.get("architecture"),
            "pricing": model.get("pricing"),
            "ghostroute_score": scores
        })
    
    # Sort by total score descending
    ranked.sort(key=lambda x: x["ghostroute_score"]["total_score"], reverse=True)
    
    # Save ranked list
    with open(latest_dir / "models_ranked.json", "w") as f:
        json.dump({
            "timestamp": datetime.utcnow().isoformat(),
            "model_count": len(ranked),
            "models": ranked
        }, f, indent=2)
    print(f"      Saved ranked models (top: {ranked[0]['id']})")
    
    print(f"\n[3/4] Testing top 10 models...")
    test_results = {}
    for model in ranked[:10]:
        model_id = model["id"]
        print(f"      Testing {model_id}...", end=" ")
        result = test_model(model_id)
        test_results[model_id] = result
        status = "✓" if result["success"] else "✗"
        print(f"{status} ({result.get('latency_ms', 0):.0f}ms)")
        time.sleep(0.5)  # Rate limiting
    
    # Save test results
    with open(latest_dir / "test_results.json", "w") as f:
        json.dump({
            "timestamp": datetime.utcnow().isoformat(),
            "test_prompt": TEST_PROMPT,
            "results": test_results
        }, f, indent=2)
    
    working = sum(1 for r in test_results.values() if r["success"])
    print(f"      {working}/10 models working")
    
    print(f"\n[4/4] Generating recommended config...")
    config = generate_recommended_config(ranked[:10], test_results)
    
    with open(latest_dir / "recommended_config.json", "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"      Primary: {config.get('primary_model', 'N/A')}")
    print(f"      Fallbacks: {config.get('fallback_count', 0)} models")
    
    # Copy to history
    import shutil
    for f in ["models_ranked.json", "test_results.json", "recommended_config.json"]:
        shutil.copy(latest_dir / f, history_dir / f)
    
    print(f"\n[✓] Discovery saved to:")
    print(f"    - {latest_dir}")
    print(f"    - {history_dir}")
    
    return 0

if __name__ == "__main__":
    exit(main())
