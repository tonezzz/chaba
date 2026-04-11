#!/usr/bin/env python3
"""Publish GhostRoute discovery results to mcp-wiki"""
import os
import requests
import json
from datetime import datetime

WIKI_API_URL = os.getenv("WIKI_API_URL", "http://localhost:3008")

def read_ghostroute_results():
    """Read the latest ghostroute results."""
    paths = [
        "/tmp/ghostroute-result.log",
        "/workspace/discovery/ghostroute/latest/results.json"
    ]
    for path in paths:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return f.read()
    return None

def publish_to_wiki(title, content, tags=None, classification="ghostroute-discovery"):
    """Publish to mcp-wiki."""
    url = f"{WIKI_API_URL}/api/articles"
    data = {
        "title": title,
        "content": content,
        "tags": tags or [],
        "entities": ["ghostroute", "openrouter", "model-ranking"],
        "classification": classification
    }
    try:
        response = requests.post(url, json=data)
        response.raise_for_status()
        print(f"✅ Published: {title}")
        return True
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False

def main():
    # Read ghostroute results
    results = read_ghostroute_results()
    if not results:
        print("⚠️ No ghostroute results found")
        return 1
    
    # Create wiki content
    today = datetime.now().strftime("%Y-%m-%d")
    content = f"""# GhostRoute Discovery Results - {today}

## Summary
Auto-discovered and ranked free OpenRouter models using GhostRoute algorithm.

## Results
```
{results}
```

## Configuration
- Stack: idc1-db
- Service: ghostroute-test
- Environment: OPENROUTER_API_KEY configured

## Next Steps
Use these models for AutoAgent or Jarvis integration.
"""
    
    # Publish
    success = publish_to_wiki(
        title=f"GhostRoute Discovery {today}",
        content=content,
        tags=["ghostroute", "openrouter", "model-discovery", "idc1-db"]
    )
    
    # Also publish infrastructure changes
    infra_content = f"""# Infrastructure Update - {today}

## Changes Made
1. **GhostRoute Test Service** - Added to idc1-db stack
2. **AutoAgent Image** - Updated to `autoagent-control-panel:idc1-db`
3. **Redis Migration** - Moved to idc1-db stack
4. **Weaviate Migration** - Moved to idc1-db stack

## Services in idc1-db
- postgres
- pgadmin
- mcp-wiki
- redis
- weaviate
- autoagent
- ghostroute-test

## Network
- idc1-db-network (external for cross-stack access)
"""
    
    publish_to_wiki(
        title=f"Infrastructure Update {today}",
        content=infra_content,
        tags=["infrastructure", "idc1-db", "migration", "ghostroute"]
    )
    
    return 0 if success else 1

if __name__ == "__main__":
    exit(main())
