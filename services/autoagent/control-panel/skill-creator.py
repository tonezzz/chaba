#!/usr/bin/env python3
"""
Skill Creator - Natural language skill development
Minimal prototype for text-driven skill creation
"""

import os
import json
import requests
import re
from typing import Dict, Optional

# Configuration
WIKI_API_URL = os.getenv("WIKI_API_URL", "http://mcp-wiki:8080")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
API_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


class SkillCreator:
    """Create skills from natural language descriptions"""
    
    def __init__(self):
        self.wiki_base = WIKI_API_URL
        self.api_key = OPENROUTER_API_KEY
    
    def _call_llm(self, prompt: str, system: str = None) -> str:
        """Call LLM via OpenRouter"""
        if not self.api_key:
            return "Error: OPENROUTER_API_KEY not set"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
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
                timeout=120
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error: {e}"
    
    def interpret_intent(self, user_input: str) -> Dict:
        """Parse natural language into skill parameters"""
        
        system = """You are a skill interpreter. Extract skill configuration from natural language.

Output ONLY valid JSON:
{
  "skill_name": "snake_case_identifier",
  "purpose": "what this skill does",
  "trigger_phrases": ["phrase1", "phrase2"],
  "handler_type": "tool_call|ws_message|python_module",
  "suggested_tool": "tool_name_if_known",
  "category": "utility|info|action|system",
  "examples": ["user input example"],
  "priority": 10
}"""
        
        prompt = f"Interpret this skill request: \"{user_input}\""
        
        result = self._call_llm(prompt, system)
        
        # Try to extract JSON
        try:
            json_match = re.search(r'```json\n(.*?)\n```', result, re.DOTALL)
            if json_match:
                result = json_match.group(1)
            return json.loads(result)
        except:
            # Fallback: return structured guess
            return {
                "skill_name": self._extract_name(user_input),
                "purpose": user_input,
                "trigger_phrases": [user_input.split()[0]] if user_input else ["trigger"],
                "handler_type": "tool_call",
                "category": "utility",
                "examples": [user_input],
                "priority": 10
            }
    
    def _extract_name(self, text: str) -> str:
        """Extract a snake_case name from text"""
        words = re.findall(r'\b[a-zA-Z]+\b', text.lower())[:3]
        return "_".join(words) if words else "new_skill"
    
    def generate_skill_markdown(self, config: Dict, user_input: str) -> str:
        """Generate skill markdown from config"""
        
        name = config.get("skill_name", "unnamed_skill")
        purpose = config.get("purpose", user_input)
        triggers = config.get("trigger_phrases", [name])
        handler = config.get("handler_type", "tool_call")
        category = config.get("category", "utility")
        examples = config.get("examples", triggers[:1])
        priority = config.get("priority", 10)
        tool = config.get("suggested_tool", "TODO")
        
        trigger_section = "\n".join([f'- "{t}"' for t in triggers])
        example_section = "\n".join([f"| \"{ex}\" | Calls {tool} |" for ex in examples])
        
        return f"""# Skill: {name}

## Metadata
- **Name**: {name}
- **Status**: draft
- **Version**: 1.0.0
- **Author**: text-input
- **Tags**: skill-draft, skill-category-{category}, skill-handler-{handler}
- **Source Input**: "{user_input}"

## Purpose
{purpose}

## Trigger Definition
- **Match Type**: prefix
- **Patterns**:
{trigger_section}
- **Priority**: {priority}
- **Languages**: en

## Handler Configuration
- **Type**: {handler}
- **Target**: {tool}

## Arguments Schema
```json
{{
  "tool": "{tool}",
  "args": {{}}
}}
```

## Examples
| Input | Expected Behavior |
|-------|-------------------|
{example_section}

## Development Notes
- Created from: "{user_input}"
- Need to: Define tool arguments, test patterns

## Testing Checklist
- [ ] Pattern matches trigger phrases
- [ ] Handler exists
- [ ] Args schema defined

## Changelog
- v1.0.0 - Draft created via text input
"""
    
    def save_to_wiki(self, name: str, content: str, category: str, handler: str) -> Dict:
        """Save skill draft to wiki"""
        title = f"Skill: {name}"
        
        try:
            resp = requests.post(
                f"{self.wiki_base}/api/articles",
                json={
                    "title": title,
                    "content": content,
                    "tags": ["skill-draft", f"skill-category-{category}", f"skill-handler-{handler}"],
                    "classification": "skill"
                },
                timeout=10
            )
            
            if resp.status_code in [200, 201]:
                return {
                    "ok": True,
                    "title": title,
                    "url": f"{self.wiki_base}/articles/{name}"
                }
            else:
                return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def create_from_text(self, user_input: str) -> Dict:
        """Main entry: text -> skill draft"""
        
        print(f"📝 Interpreting: \"{user_input}\"")
        
        # Step 1: Interpret intent
        config = self.interpret_intent(user_input)
        print(f"   → Skill name: {config.get('skill_name')}")
        print(f"   → Handler: {config.get('handler_type')}")
        print(f"   → Triggers: {config.get('trigger_phrases', [])}")
        
        # Step 2: Generate markdown
        markdown = self.generate_skill_markdown(config, user_input)
        
        # Step 3: Save to wiki
        result = self.save_to_wiki(
            config.get("skill_name", "unnamed"),
            markdown,
            config.get("category", "utility"),
            config.get("handler_type", "tool_call")
        )
        
        if result.get("ok"):
            print(f"✅ Saved to wiki: {result['title']}")
        else:
            print(f"❌ Failed: {result.get('error')}")
        
        return {
            "input": user_input,
            "config": config,
            "saved": result.get("ok"),
            "wiki_title": result.get("title"),
            "markdown_preview": markdown[:500] + "..." if len(markdown) > 500 else markdown
        }
    
    def revise_skill(self, name: str, revision_request: str) -> Dict:
        """Revise existing skill based on feedback"""
        
        # Fetch existing
        try:
            resp = requests.get(f"{self.wiki_base}/api/articles/Skill:%20{name}", timeout=10)
            if resp.status_code != 200:
                return {"error": f"Skill not found: {name}"}
            existing = resp.json()
        except Exception as e:
            return {"error": str(e)}
        
        current_content = existing.get("content", "")
        
        # Generate revision
        system = """You are a skill editor. Apply the user's revision request to the skill markdown.
Preserve structure, update only relevant sections."""
        
        prompt = f"""Current skill:
```markdown
{current_content}
```

Revision request: "{revision_request}"

Generate updated markdown:"""
        
        updated = self._call_llm(prompt, system)
        
        # Clean up
        if "```markdown" in updated:
            updated = updated.split("```markdown")[1].split("```")[0].strip()
        
        # Save as new version
        title = f"Skill: {name}"
        tags = existing.get("tags", "").split(",") if existing.get("tags") else []
        
        # Add revision note
        timestamp = __import__('datetime').datetime.now().isoformat()
        revision_note = f"\n\n## Revision ({timestamp})\n- Request: {revision_request}\n- Applied: auto-generated"
        updated += revision_note
        
        try:
            resp = requests.post(
                f"{self.wiki_base}/api/articles",
                json={
                    "title": title,
                    "content": updated,
                    "tags": tags
                },
                timeout=10
            )
            
            return {
                "ok": resp.status_code in [200, 201],
                "skill": name,
                "revision": revision_request,
                "changes": "see wiki for full content"
            }
        except Exception as e:
            return {"error": str(e)}


def interactive_mode():
    """Interactive CLI for skill development"""
    creator = SkillCreator()
    
    print("=" * 60)
    print("🛠️  Skill Creator - Text-Driven Development")
    print("=" * 60)
    print()
    print("Describe what you want the skill to do.")
    print("Examples:")
    print('  - "a skill to check weather when I say what\'s the weather"')
    print('  - "remind me about tasks when I say don\'t forget"')
    print('  - "search wiki when I ask find docs about X"')
    print()
    
    while True:
        user_input = input("📝 Describe skill (or 'quit'): ").strip()
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            break
        
        if not user_input:
            continue
        
        # Create skill
        result = creator.create_from_text(user_input)
        
        if result.get("saved"):
            print()
            print("Preview:")
            print("-" * 40)
            print(result["markdown_preview"])
            print("-" * 40)
            print()
            
            # Ask for revision
            revise = input("🔧 Want to revise? Describe changes (or 'no'): ").strip()
            if revise.lower() not in ['no', 'n', '']:
                skill_name = result["config"].get("skill_name")
                rev_result = creator.revise_skill(skill_name, revise)
                if rev_result.get("ok"):
                    print(f"✅ Revised: {skill_name}")
                else:
                    print(f"❌ Revision failed: {rev_result.get('error')}")
        
        print()
        print("=" * 60)


def main():
    import sys
    
    if len(sys.argv) < 2:
        interactive_mode()
        return
    
    command = sys.argv[1]
    creator = SkillCreator()
    
    if command == "create":
        if len(sys.argv) < 3:
            print("Usage: skill-creator.py create '<description>'")
            sys.exit(1)
        
        description = sys.argv[2]
        result = creator.create_from_text(description)
        print(json.dumps(result, indent=2))
    
    elif command == "revise":
        if len(sys.argv) < 4:
            print("Usage: skill-creator.py revise <skill_name> '<changes>'")
            sys.exit(1)
        
        skill_name = sys.argv[2]
        changes = sys.argv[3]
        result = creator.revise_skill(skill_name, changes)
        print(json.dumps(result, indent=2))
    
    elif command == "test":
        # Quick test without saving
        if len(sys.argv) < 3:
            print("Usage: skill-creator.py test '<description>'")
            sys.exit(1)
        
        description = sys.argv[2]
        config = creator.interpret_intent(description)
        markdown = creator.generate_skill_markdown(config, description)
        
        print("Interpreted Config:")
        print(json.dumps(config, indent=2))
        print()
        print("Generated Markdown:")
        print("=" * 60)
        print(markdown)
    
    else:
        print("Commands: create, revise, test")
        print()
        print('  skill-creator.py create "check weather"')
        print('  skill-creator.py revise weather_skill "add Thai language support"')
        print('  skill-creator.py test "find documents skill"')


if __name__ == "__main__":
    main()
