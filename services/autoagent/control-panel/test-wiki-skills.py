#!/usr/bin/env python3
"""
Interactive test for wiki-based skill development
Connects to mcp-wiki for real storage and retrieval
"""

import os
import sys
import requests
import json
import re
from datetime import datetime

WIKI_API_URL = os.getenv("WIKI_API_URL", "http://localhost:3008")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
API_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

class WikiSkillTester:
    """Test skill development with real wiki integration and LLM"""
    
    def __init__(self):
        self.wiki_url = WIKI_API_URL
        self.api_key = OPENROUTER_API_KEY
        self.llm_available = bool(self.api_key)
        self._check_connection()
        if self.llm_available:
            print(f"🤖 LLM integration: Enabled ({DEFAULT_MODEL})")
        else:
            print(f"⚠️  LLM integration: Disabled (set OPENROUTER_API_KEY for real interpretation)")
    
    def _check_connection(self):
        """Verify wiki is accessible"""
        try:
            resp = requests.get(f"{self.wiki_url}/api/articles?limit=1", timeout=5)
            resp.raise_for_status()
            print(f"✅ Connected to mcp-wiki at {self.wiki_url}")
        except Exception as e:
            print(f"❌ Cannot connect to wiki: {e}")
            print(f"   Set WIKI_API_URL or verify mcp-wiki is running")
            sys.exit(1)
    
    def list_skills(self):
        """List all skill articles in wiki"""
        try:
            resp = requests.get(f"{self.wiki_url}/api/articles?limit=50", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            articles = data if isinstance(data, list) else data.get("articles", [])
            
            skills = []
            for article in articles:
                if isinstance(article, dict):
                    title = article.get("title", "")
                    tags = article.get("tags", [])
                    if any(t.startswith("skill-") for t in tags) or "Skill:" in title:
                        skills.append({
                            "title": title,
                            "tags": tags,
                            "updated": article.get("updated_at", "N/A")
                        })
            
            return skills
        except Exception as e:
            print(f"❌ Error listing skills: {e}")
            return []
    
    def get_skill(self, title):
        """Retrieve a skill article"""
        try:
            encoded = requests.utils.quote(title)
            resp = requests.get(f"{self.wiki_url}/api/articles/{encoded}", timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"❌ Error retrieving skill: {e}")
            return None
    
    def save_skill(self, title, content, tags):
        """Save skill to wiki"""
        try:
            payload = {
                "title": title,
                "content": content,
                "tags": tags
            }
            resp = requests.post(f"{self.wiki_url}/api/articles", json=payload, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"❌ Error saving skill: {e}")
            return None
    
    def search_skills(self, query):
        """Search skills by keyword"""
        try:
            resp = requests.get(f"{self.wiki_url}/api/search?q={requests.utils.quote(query)}", timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"❌ Error searching: {e}")
            return []
    
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
                timeout=60
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error: {e}"

    def interpret_with_llm(self, user_input: str) -> dict:
        """Use LLM to interpret natural language into skill config"""
        system_prompt = """You are a skill interpreter for an AI assistant. 
Convert natural language descriptions into structured skill configurations.
Respond ONLY with valid JSON in this exact format:
{
    "skill_name": "snake_case_name",
    "purpose": "Clear description of what the skill does",
    "trigger_phrases": ["phrase 1", "phrase 2", "phrase 3"],
    "handler_type": "tool_call",
    "suggested_tool": "tool_name",
    "category": "info|action|search|utility",
    "examples": ["Example user input"],
    "priority": 10,
    "languages": ["en"]
}"""
        
        prompt = f"Interpret this skill description into the JSON format: \"{user_input}\""
        
        result = self._call_llm(prompt, system_prompt)
        
        # Extract JSON from response
        try:
            # Try to find JSON block
            if "```json" in result:
                json_str = result.split("```json")[1].split("```")[0].strip()
            elif "```" in result:
                json_str = result.split("```")[1].split("```")[0].strip()
            else:
                json_str = result.strip()
            
            config = json.loads(json_str)
            return config
        except Exception as e:
            print(f"⚠️  LLM parsing failed, using fallback: {e}")
            return self.interpret_with_heuristics(user_input)

    def interpret_with_heuristics(self, user_input):
        """Simple heuristic interpretation (fallback)"""
        text = user_input.lower()
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text)[:3]
        name = "_".join(words) if words else "new_skill"
        
        # Determine category
        category = "utility"
        if any(x in text for x in ["weather", "time", "date", "news"]):
            category = "info"
        elif any(x in text for x in ["remind", "task", "todo", "schedule"]):
            category = "action"
        elif any(x in text for x in ["search", "find", "lookup"]):
            category = "search"
        
        trigger_words = [w for w in text.split() if w in ["check", "get", "show", "find", "search", "remind", "tell"]]
        if not trigger_words:
            trigger_words = [text.split()[0]] if text.split() else ["trigger"]
        
        return {
            "skill_name": name,
            "purpose": user_input,
            "trigger_phrases": [user_input] + [f"{w} {name.replace('_', ' ')}" for w in trigger_words[:2]],
            "handler_type": "tool_call",
            "suggested_tool": name + "_tool",
            "category": category,
            "examples": [user_input],
            "priority": 10,
            "languages": ["en"]
        }
    
    def interpret_input(self, user_input: str) -> dict:
        """Interpret input using LLM if available, otherwise heuristics"""
        if self.llm_available:
            print("   🤖 Using LLM interpretation...")
            return self.interpret_with_llm(user_input)
        else:
            print("   📝 Using heuristic interpretation (set OPENROUTER_API_KEY for LLM)")
            return self.interpret_with_heuristics(user_input)
    
    def generate_markdown(self, config, user_input):
        """Generate skill markdown"""
        trigger_section = "\n".join([f'- "{t}"' for t in config["trigger_phrases"][:3]])
        example_section = "\n".join([f'| "{ex}" | Calls {config["suggested_tool"]} |' for ex in config["examples"][:2]])
        
        return f"""# Skill: {config['skill_name']}

## Metadata
- **Name**: {config['skill_name']}
- **Status**: draft
- **Version**: 1.0.0
- **Author**: text-input
- **Tags**: skill-draft, skill-category-{config['category']}, skill-handler-{config['handler_type']}
- **Source Input**: "{user_input}"

## Purpose
{config['purpose']}

## Trigger Definition
- **Match Type**: prefix
- **Patterns**:
{trigger_section}
- **Priority**: {config['priority']}
- **Languages**: en

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


def print_menu():
    print("\n" + "=" * 60)
    print("🛠️  Wiki-Based Skill Development - Test Menu")
    print("=" * 60)
    print("\nCommands:")
    print("  1. create <description>  - Create skill from text")
    print("  2. list                  - List all skill drafts")
    print("  3. read <title>          - Read skill article")
    print("  4. search <query>        - Search skills")
    print("  5. test                  - Interactive creation test")
    print("  6. help                  - Show this menu")
    print("  7. quit                  - Exit")
    print()


def main():
    tester = WikiSkillTester()
    
    print_menu()
    
    while True:
        try:
            cmd = input("📝 > ").strip()
            
            if not cmd:
                continue
            
            parts = cmd.split(maxsplit=1)
            action = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            
            if action in ("quit", "q", "exit"):
                print("👋 Goodbye!")
                break
            
            elif action == "help":
                print_menu()
            
            elif action in ("create", "1"):
                if not arg:
                    print("❌ Usage: create <description>")
                    print("   Example: create check weather when I ask")
                    continue
                
                print(f"\n🎯 Interpreting: \"{arg}\"")
                config = tester.interpret_input(arg)
                markdown = tester.generate_markdown(config, arg)
                
                print(f"\n📊 Generated Skill:")
                print(f"   Name: {config['skill_name']}")
                print(f"   Category: {config['category']}")
                print(f"   Triggers: {', '.join(config['trigger_phrases'][:2])}")
                
                title = f"Skill: {config['skill_name']}"
                tags = f"skill-draft, skill-category-{config['category']}, skill-handler-{config['handler_type']}"
                
                confirm = input(f"\n💾 Save to wiki? (yes/no): ").strip().lower()
                if confirm in ("yes", "y"):
                    result = tester.save_skill(title, markdown, tags)
                    if result:
                        print(f"✅ Saved to wiki: {result.get('title', title)}")
                    else:
                        print("❌ Failed to save")
                else:
                    print("\n📄 Preview:")
                    print(markdown[:500] + "\n...")
            
            elif action in ("list", "2"):
                skills = tester.list_skills()
                if skills:
                    print(f"\n📚 {len(skills)} skill(s) in wiki:")
                    for skill in skills:
                        print(f"   • {skill['title']}")
                        print(f"     Tags: {', '.join(skill['tags'][:3])}")
                else:
                    print("\n📭 No skills found in wiki")
                    print("   Create one with: create <description>")
            
            elif action in ("read", "3"):
                if not arg:
                    print("❌ Usage: read <title>")
                    print("   Example: read 'Skill: check_the_weather'")
                    continue
                
                article = tester.get_skill(arg)
                if article:
                    print(f"\n📄 {article.get('title', 'Untitled')}")
                    print(f"   Tags: {', '.join(article.get('tags', []))}")
                    print(f"   Updated: {article.get('updated_at', 'N/A')}")
                    print("\n" + "-" * 50)
                    print(article.get('content', 'No content'))
                else:
                    print(f"❌ Skill not found: {arg}")
            
            elif action in ("search", "4"):
                if not arg:
                    print("❌ Usage: search <query>")
                    continue
                
                results = tester.search_skills(arg)
                if results:
                    print(f"\n🔍 {len(results)} result(s) for '{arg}':")
                    for r in results:
                        print(f"   • {r.get('title', 'Untitled')}")
                else:
                    print(f"\n📭 No results for '{arg}'")
            
            elif action in ("test", "5"):
                print("\n🧪 Interactive Skill Creation Test")
                print("   Describe what you want the skill to do.")
                print("   Type 'cancel' to abort.\n")
                
                user_input = input("💡 Skill idea: ").strip()
                if user_input.lower() in ("cancel", "quit"):
                    continue
                
                config = tester.interpret_input(user_input)
                markdown = tester.generate_markdown(config, user_input)
                
                print(f"\n📊 Interpreted:")
                print(f"   Name: {config['skill_name']}")
                print(f"   Category: {config['category']}")
                print(f"   Handler: {config['handler_type']}")
                print(f"   Priority: {config['priority']}")
                
                print(f"\n📄 First 10 lines of generated skill:")
                lines = markdown.split('\n')[:10]
                for line in lines:
                    print(f"   {line}")
                print("   ...")
                
                # Simulate revision
                revision = input(f"\n🔧 Revision? (describe or 'no'): ").strip()
                if revision.lower() not in ("no", "n", "", "cancel"):
                    print(f"   Applying: {revision}")
                    # Simple revision simulation
                    if "thai" in revision.lower():
                        markdown = markdown.replace(
                            "- **Languages**: en",
                            "- **Languages**: en, th\n- **Thai Patterns**: TBD"
                        )
                        print("   ✅ Added Thai language support")
                    elif "priority" in revision.lower():
                        import re
                        nums = re.findall(r'\d+', revision)
                        if nums:
                            markdown = markdown.replace(
                                f"- **Priority**: {config['priority']}",
                                f"- **Priority**: {nums[0]}"
                            )
                            print(f"   ✅ Changed priority to {nums[0]}")
                
                save = input(f"\n💾 Save to wiki? (yes/no): ").strip().lower()
                if save in ("yes", "y"):
                    title = f"Skill: {config['skill_name']}"
                    tags = f"skill-draft, skill-category-{config['category']}"
                    result = tester.save_skill(title, markdown, tags)
                    if result:
                        print(f"✅ Saved to wiki!")
                    else:
                        print("❌ Failed to save")
            
            else:
                print(f"❓ Unknown command: {action}")
                print("   Type 'help' for available commands")
        
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
