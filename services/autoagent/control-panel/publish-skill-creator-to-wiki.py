#!/usr/bin/env python3
"""
Publish Skill Creator documentation to mcp-wiki
"""

import os
import sys
import requests
from pathlib import Path

# Wiki API configuration
WIKI_API_URL = os.getenv("WIKI_API_URL", "http://localhost:3008")

def publish_to_wiki(title: str, content: str, tags: str = None):
    """Publish article to wiki via API"""
    url = f"{WIKI_API_URL}/api/articles"
    
    payload = {
        "title": title,
        "content": content,
        "tags": tags or ""
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to wiki at {WIKI_API_URL}")
        print("   Is mcp-wiki running? Check: docker ps | grep wiki")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"❌ Wiki API error: {e}")
        sys.exit(1)


def test_wiki_connection():
    """Test connection to mcp-wiki"""
    try:
        response = requests.get(f"{WIKI_API_URL}/api/articles?limit=1", timeout=5)
        response.raise_for_status()
        data = response.json()
        print(f"✅ Wiki connection OK at {WIKI_API_URL}")
        # Handle both list and dict response formats
        if isinstance(data, list):
            print(f"   Articles in wiki: {len(data)}")
        elif isinstance(data, dict):
            print(f"   Articles in wiki: {data.get('total', len(data.get('articles', [])))}")
        else:
            print(f"   Wiki responding (format: {type(data).__name__})")
        return True
    except Exception as e:
        print(f"❌ Wiki connection failed: {e}")
        return False


def main():
    # Test connection first
    print("=" * 60)
    print("🧪 Testing mcp-wiki connection...")
    print("=" * 60)
    
    if not test_wiki_connection():
        sys.exit(1)
    
    print()
    print("=" * 60)
    print("📝 Publishing Skill Creator documentation...")
    print("=" * 60)
    
    # Skill Creator documentation
    article_content = """# Skill Creator - Text-Driven Skill Development

## Overview

The Skill Creator enables **natural language-driven skill development** integrated with the wiki system. It allows you to describe what you want a skill to do in plain text, and the system interprets your intent into a structured skill configuration.

## Architecture

```mermaid
flowchart LR
    A[Text Input] --> B[Interpret Intent]
    B --> C[Generate Skill Markdown]
    C --> D[Save to Wiki]
    D --> E{Need Changes?}
    E -->|Yes| F[Revise via Text]
    F --> C
    E -->|No| G[Deploy]
```

## Web UI

Access the Skill Creator at: `http://localhost:8080/skills`

### Features

| Feature | Description |
|---------|-------------|
| **Text Input** | Describe skill in natural language |
| **Example Pills** | Quick-start with preset examples |
| **Intent Display** | Shows interpreted config |
| **Markdown Preview** | Full skill document preview |
| **Save to Wiki** | Stores draft as wiki article |
| **Revise** | Text-driven refinement |

### Workflow

1. **Describe** → Type what you want the skill to do
2. **Create** → System interprets intent and generates draft
3. **Review** → Check interpreted config and markdown
4. **Revise** → Request changes via text ("add Thai support", "set priority to 20")
5. **Save** → Store to wiki with `skill-draft` tag

## Example Interactions

### Creating a Weather Skill

**Input:** `"check the weather when I ask what's the weather"`

**Interpreted Config:**
```json
{
  "skill_name": "check_the_weather",
  "category": "info",
  "handler_type": "tool_call",
  "trigger_phrases": [
    "check the weather when I ask what's the weather",
    "check check the weather"
  ],
  "priority": 10
}
```

### Revising a Skill

**Revision Request:** `"add Thai language support"`

**Applied Changes:**
- Adds `th` to languages
- Adds Thai patterns placeholder
- Records revision in changelog

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/skills` | GET | Web UI page |
| `/api/skills/interpret` | POST | Text → skill config |
| `/api/skills/revise` | POST | Apply revision |
| `/api/skills/save` | POST | Save to wiki |

## Article Schema

Generated skill articles include:

```markdown
# Skill: {name}

## Metadata
- **Name**: {skill_name}
- **Status**: draft
- **Version**: 1.0.0
- **Tags**: skill-draft, skill-category-{category}

## Purpose
{user_input}

## Trigger Definition
- **Match Type**: prefix
- **Patterns**: [...]
- **Priority**: {priority}
- **Languages**: en

## Handler Configuration
- **Type**: {handler_type}
- **Target**: {suggested_tool}

## Arguments Schema
## Examples
## Development Notes
## Testing Checklist
## Changelog
```

## Files

| File | Purpose |
|------|---------|
| `skill-creator.py` | Full CLI with LLM integration |
| `skill-creator-demo.py` | Standalone mock demo |
| `control-server.py` | Web UI integrated into control panel |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WIKI_API_URL` | `http://mcp-wiki:8080` | Wiki API endpoint |
| `OPENROUTER_API_KEY` | - | For LLM interpretation |

## Skill Lifecycle

```
Draft → Review → Revise → Approve → Deploy → Monitor
   ↑______↓
   (iterate via text feedback)
```

## Future Enhancements

- [ ] LLM-powered interpretation (currently heuristic)
- [ ] Direct integration with `system_skill_upsert_queue`
- [ ] Auto-deployment from wiki to Jarvis
- [ ] Skill testing/simulation before deploy
- [ ] Multi-language trigger generation
- [ ] Collaborative review workflow

## Related Articles

- [[Skill System]] - How Jarvis skills work
- [[MCP-Wiki]] - Knowledge base documentation
- [[AutoAgent]] - Research and automation framework
"""

    # Publish article
    result = publish_to_wiki(
        title="Skill Creator",
        content=article_content,
        tags="skill-system, autoagent, documentation, development"
    )
    
    print(f"✅ Published: {result.get('title', 'Unknown')}")
    print(f"   ID: {result.get('id', 'N/A')}")
    print(f"   Tags: skill-system, autoagent, documentation, development")
    
    # List all skill-related articles
    print()
    print("=" * 60)
    print("📚 Articles in wiki:")
    print("=" * 60)
    
    try:
        response = requests.get(f"{WIKI_API_URL}/api/articles?limit=50", timeout=5)
        data = response.json()
        
        # Handle both list and dict response formats
        if isinstance(data, list):
            articles = data
        elif isinstance(data, dict):
            articles = data.get("articles", [])
        else:
            articles = []
        
        for article in articles:
            if isinstance(article, dict):
                title = article.get("title", "Untitled")
                if any(tag in title.lower() for tag in ["skill", "creator", "autoagent"]):
                    print(f"   • {title}")
                
    except Exception as e:
        print(f"   (Could not list articles: {e})")
    
    print()
    print("✨ Done! You can view the article at:")
    print(f"   {WIKI_API_URL}/api/articles/Skill%20Creator")
    print(f"   (or use the web UI if configured)")


if __name__ == "__main__":
    main()
