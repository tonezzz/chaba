#!/usr/bin/env python3
"""
MCP tool for querying GhostRoute discovery.
Can be used as an MCP server or standalone tool.

Tools exposed:
- ghostroute_get_best_model: Get the best ranked model
- ghostroute_get_fallbacks: Get fallback chain
- ghostroute_get_config: Get full recommended config
- ghostroute_list_models: Get all ranked models
"""

import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

DISCOVERY_DIR = Path(os.getenv("GHOSTROUTE_DISCOVERY_DIR", "/workspace/discovery/ghostroute"))

def load_discovery() -> Optional[Dict[str, Any]]:
    """Load the latest discovery data."""
    latest_dir = DISCOVERY_DIR / "latest"
    
    try:
        with open(latest_dir / "recommended_config.json") as f:
            config = json.load(f)
        with open(latest_dir / "models_ranked.json") as f:
            models = json.load(f)
        with open(latest_dir / "test_results.json") as f:
            tests = json.load(f)
        return {
            "config": config,
            "models": models,
            "tests": tests
        }
    except FileNotFoundError:
        return None

def ghostroute_get_best_model() -> str:
    """Get the best performing model from GhostRoute discovery."""
    discovery = load_discovery()
    if not discovery:
        return json.dumps({"error": "Discovery not found. Run test-ghostroute.py first."})
    
    config = discovery["config"]
    return json.dumps({
        "model": config.get("primary_model"),
        "score": config.get("primary_score"),
        "success_rate": config.get("test_summary", {}).get("success_rate")
    }, indent=2)

def ghostroute_get_fallbacks(limit: int = 5) -> str:
    """Get the fallback chain for resilient AI calls."""
    discovery = load_discovery()
    if not discovery:
        return json.dumps({"error": "Discovery not found. Run test-ghostroute.py first."})
    
    config = discovery["config"]
    fallbacks = config.get("fallback_chain", [])[:limit]
    
    return json.dumps({
        "fallbacks": fallbacks,
        "count": len(fallbacks),
        "usage": "Try primary first, then fall through this chain on 429/503 errors"
    }, indent=2)

def ghostroute_get_config() -> str:
    """Get the full recommended configuration for AutoAgent."""
    discovery = load_discovery()
    if not discovery:
        return json.dumps({"error": "Discovery not found. Run test-ghostroute.py first."})
    
    return json.dumps(discovery["config"], indent=2)

def ghostroute_list_models(limit: int = 10) -> str:
    """List top ranked models from GhostRoute."""
    discovery = load_discovery()
    if not discovery:
        return json.dumps({"error": "Discovery not found. Run test-ghostroute.py first."})
    
    models = discovery["models"].get("models", [])[:limit]
    simplified = []
    for m in models:
        simplified.append({
            "id": m.get("id"),
            "name": m.get("name"),
            "context_length": m.get("context_length"),
            "score": m.get("ghostroute_score", {}).get("total_score")
        })
    
    return json.dumps({
        "count": len(simplified),
        "models": simplified
    }, indent=2)

def main():
    """CLI interface for MCP tools."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: mcp-query.py <command> [args]")
        print("Commands: best, fallbacks, config, list")
        return 1
    
    cmd = sys.argv[1]
    
    if cmd == "best":
        print(ghostroute_get_best_model())
    elif cmd == "fallbacks":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        print(ghostroute_get_fallbacks(limit))
    elif cmd == "config":
        print(ghostroute_get_config())
    elif cmd == "list":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        print(ghostroute_list_models(limit))
    else:
        print(f"Unknown command: {cmd}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
