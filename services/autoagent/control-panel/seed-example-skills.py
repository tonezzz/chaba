#!/usr/bin/env python3
"""
Seed mcp-wiki with example skills for testing
Uses real LLM for interpretation if OPENROUTER_API_KEY is set
"""

import os
import sys
import requests
import json
import re

WIKI_API_URL = os.getenv("WIKI_API_URL", "http://localhost:3008")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
API_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

# Example skill descriptions
EXAMPLE_SKILLS = [
    {
        "description": "check the weather when I ask about temperature or forecast",
        "category": "info",
        "notes": "Weather lookup with location detection"
    },
    {
        "description": "remind me about tasks when I say don't forget or remind me",
        "category": "action", 
        "notes": "Task reminder with time parsing"
    },
    {
        "description": "search wiki articles when I ask find documents or search knowledge base",
        "category": "search",
        "notes": "KB search with semantic similarity"
    },
    {
        "description": "tell me news headlines when I say what's the news or show news",
        "category": "info",
        "notes": "News brief with category filtering"
    },
    {
        "description": "analyze code when I paste a code snippet or say review this code",
        "category": "utility",
        "notes": "Code analysis with suggestions"
    },
    {
        "description": "translate Thai to English when I ask แปลภาษา or translate",
        "category": "utility",
        "notes": "Thai-English translation with context"
    },
    {
        "description": "set a timer when I say set timer for or start countdown",
        "category": "action",
        "notes": "Timer with duration parsing"
    },
    {
        "description": "lookup stock prices when I ask about ticker or stock quote",
        "category": "info",
        "notes": "Stock price lookup with trend"
    }
]


def call_llm(prompt: str, system: str = None) -> str:
    """Call LLM via OpenRouter"""
    if not OPENROUTER_API_KEY:
        return "Error: OPENROUTER_API_KEY not set"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8059"
    }
    
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    
    data = {
        "model": DEFAULT_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    try:
        resp = requests.post(
            f"{API_BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error: {e}"


def interpret_with_llm(user_input: str) -> dict:
    """Use LLM to interpret into skill config"""
    system_prompt = """You are a skill interpreter for an AI assistant. 
Convert natural language descriptions into structured skill configurations.
Respond ONLY with valid JSON in this exact format:
{
    "skill_name": "snake_case_name",
    "purpose": "Clear description of what the skill does",
    "trigger_phrases": ["phrase 1", "phrase 2", "phrase 3", "phrase 4"],
    "handler_type": "tool_call",
    "suggested_tool": "tool_name",
    "category": "info|action|search|utility",
    "examples": ["Example user input 1", "Example user input 2"],
    "priority": 10,
    "languages": ["en"]
}"""
    
    prompt = f"Interpret this skill description: \"{user_input}\""
    
    result = call_llm(prompt, system_prompt)
    
    # Extract JSON
    try:
        if "```json" in result:
            json_str = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            json_str = result.split("```")[1].split("```")[0].strip()
        else:
            json_str = result.strip()
        
        config = json.loads(json_str)
        return config
    except Exception as e:
        print(f"   ⚠️ LLM parse failed: {e}")
        return None


def interpret_with_heuristics(user_input: str, category: str) -> dict:
    """Fallback heuristic interpretation"""
    text = user_input.lower()
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text)[:3]
    name = "_".join(words) if words else "new_skill"
    
    # Extract trigger words
    trigger_words = [w for w in text.split() 
                     if w in ["check", "get", "show", "find", "search", "remind", "tell", 
                              "ask", "say", "paste", "start", "set", "lookup"]]
    if not trigger_words:
        trigger_words = [text.split()[0]] if text.split() else ["trigger"]
    
    # Build trigger phrases
    triggers = [user_input]
    if trigger_words:
        triggers.append(f"{trigger_words[0]} {name.replace('_', ' ')}")
        if len(trigger_words) > 1:
            triggers.append(f"{trigger_words[1]} {name.replace('_', ' ')}")
    
    return {
        "skill_name": name,
        "purpose": user_input,
        "trigger_phrases": triggers[:4],
        "handler_type": "tool_call",
        "suggested_tool": name + "_tool",
        "category": category,
        "examples": [user_input],
        "priority": 10,
        "languages": ["en"]
    }


def generate_markdown(config: dict, user_input: str, notes: str = "") -> str:
    """Generate skill markdown document"""
    trigger_section = "\n".join([f'- "{t}"' for t in config["trigger_phrases"][:4]])
    example_section = "\n".join([f'| "{ex}" | Calls {config["suggested_tool"]} |' for ex in config["examples"][:2]])
    
    notes_section = f"\n## Notes\n{notes}\n" if notes else ""
    
    return f"""# Skill: {config['skill_name']}

## Metadata
- **Name**: {config['skill_name']}
- **Status**: draft
- **Version**: 1.0.0
- **Author**: auto-seed
- **Tags**: skill-draft, skill-category-{config['category']}, skill-handler-{config['handler_type']}
- **Source Input**: "{user_input}"

## Purpose
{config['purpose']}

## Trigger Definition
- **Match Type**: prefix
- **Patterns**:
{trigger_section}
- **Priority**: {config['priority']}
- **Languages**: {', '.join(config.get('languages', ['en']))}

## Handler Configuration
- **Type**: {config['handler_type']}
- **Target**: {config['suggested_tool']}

## Arguments Schema
```json
{{
  "tool": "{config['suggested_tool']}",
  "args": {{}}
}}
```

## Examples
| Input | Expected Behavior |
|-------|-------------------|
{example_section}
{notes_section}
## Development Notes
- Created from: "{user_input}"
- Seed type: {'LLM' if OPENROUTER_API_KEY else 'heuristic'}
- TODO: Define tool implementation
- TODO: Test trigger patterns
- TODO: Add argument schema

## Testing Checklist
- [ ] Pattern matches trigger phrases
- [ ] Handler exists
- [ ] Args schema defined
- [ ] Example inputs work
- [ ] Thai support (if needed)

## Changelog
- v1.0.0 - Draft created via auto-seed
"""


def save_to_wiki(title: str, content: str, tags: str) -> bool:
    """Save article to wiki"""
    url = f"{WIKI_API_URL}/api/articles"
    
    payload = {
        "title": title,
        "content": content,
        "tags": tags
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"   ❌ Wiki error: {e}")
        return False


def test_wiki_connection() -> bool:
    """Test wiki connection"""
    try:
        resp = requests.get(f"{WIKI_API_URL}/api/articles?limit=1", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        count = len(data) if isinstance(data, list) else data.get("total", "unknown")
        print(f"✅ Connected to mcp-wiki at {WIKI_API_URL}")
        print(f"   Current articles: {count}")
        return True
    except Exception as e:
        print(f"❌ Cannot connect to wiki: {e}")
        return False


def main():
    print("=" * 60)
    print("🌱 Seeding mcp-wiki with example skills")
    print("=" * 60)
    print()
    
    # Check connection
    if not test_wiki_connection():
        sys.exit(1)
    
    # Check LLM availability
    llm_available = bool(OPENROUTER_API_KEY)
    if llm_available:
        print(f"🤖 LLM enabled: {DEFAULT_MODEL}")
    else:
        print("⚠️  LLM disabled - using heuristics (set OPENROUTER_API_KEY)")
    print()
    
    # Seed each example skill
    success_count = 0
    
    for i, example in enumerate(EXAMPLE_SKILLS, 1):
        desc = example["description"]
        category = example["category"]
        notes = example.get("notes", "")
        
        print(f"[{i}/{len(EXAMPLE_SKILLS)}] Processing: {desc[:50]}...")
        
        # Interpret with LLM or heuristics
        if llm_available:
            config = interpret_with_llm(desc)
            if config is None:
                print("   Falling back to heuristics...")
                config = interpret_with_heuristics(desc, category)
        else:
            config = interpret_with_heuristics(desc, category)
        
        # Generate markdown
        markdown = generate_markdown(config, desc, notes)
        
        # Save to wiki
        title = f"Skill: {config['skill_name']}"
        tags = f"skill-draft, skill-category-{config['category']}, skill-handler-{config['handler_type']}"
        
        if save_to_wiki(title, markdown, tags):
            print(f"   ✅ Saved: {title}")
            success_count += 1
        else:
            print(f"   ❌ Failed: {title}")
        
        # Small delay to avoid rate limiting
        import time
        time.sleep(0.5)
    
    # Summary
    print()
    print("=" * 60)
    print("📊 Summary")
    print("=" * 60)
    print(f"   Successfully seeded: {success_count}/{len(EXAMPLE_SKILLS)} skills")
    print()
    print("📚 Next steps:")
    print("   1. List skills: python3 test-wiki-skills.py")
    print("   2. Read skill: python3 test-wiki-skills.py (then 'read <title>')")
    print("   3. Create new: python3 test-wiki-skills.py (then 'create <description>')")


if __name__ == "__main__":
    main()
