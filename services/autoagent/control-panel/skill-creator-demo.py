#!/usr/bin/env python3
"""
Skill Creator Demo - Minimal test without external dependencies
Simulates the text-to-skill flow with mock wiki
"""

import json
import re
from typing import Dict


class MockSkillCreator:
    """Skill creator with mock wiki for testing"""
    
    def __init__(self):
        self.wiki_store = {}  # In-memory wiki
    
    def interpret_intent(self, user_input: str) -> Dict:
        """Parse natural language using simple rules (no LLM needed for demo)"""
        
        # Simple pattern matching for demo
        text = user_input.lower()
        
        # Extract trigger words
        trigger_words = []
        common_starts = ["check", "get", "show", "find", "search", "remind", "tell"]
        for word in text.split():
            if word in common_starts:
                trigger_words.append(word)
        
        if not trigger_words:
            trigger_words = [text.split()[0]] if text.split() else ["trigger"]
        
        # Determine category
        category = "utility"
        if any(x in text for x in ["weather", "time", "date", "news"]):
            category = "info"
        elif any(x in text for x in ["remind", "task", "todo", "schedule"]):
            category = "action"
        elif any(x in text for x in ["search", "find", "lookup"]):
            category = "search"
        
        # Generate name
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text)[:3]
        name = "_".join(words) if words else "new_skill"
        
        # Extract purpose phrase
        purpose = user_input
        
        return {
            "skill_name": name,
            "purpose": purpose,
            "trigger_phrases": [user_input] + [f"{w} {name.replace('_', ' ')}" for w in trigger_words[:2]],
            "handler_type": "tool_call",
            "suggested_tool": name.replace("_", "_") + "_tool",
            "category": category,
            "examples": [user_input],
            "priority": 10
        }
    
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
        
        trigger_section = "\n".join([f'- "{t}"' for t in triggers[:3]])
        example_section = "\n".join([f"| \"{ex}\" | Calls {tool} |" for ex in examples[:2]])
        
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
        """Save to mock wiki"""
        title = f"Skill: {name}"
        
        self.wiki_store[title] = {
            "title": title,
            "content": content,
            "tags": ["skill-draft", f"skill-category-{category}", f"skill-handler-{handler}"],
            "classification": "skill"
        }
        
        return {
            "ok": True,
            "title": title,
            "stored": True
        }
    
    def create_from_text(self, user_input: str) -> Dict:
        """Main flow: text -> skill draft"""
        
        print(f"📝 Input: \"{user_input}\"")
        print()
        
        # Step 1: Interpret
        config = self.interpret_intent(user_input)
        print("📊 Interpreted:")
        print(f"   Name: {config['skill_name']}")
        print(f"   Category: {config['category']}")
        print(f"   Triggers: {config['trigger_phrases']}")
        print()
        
        # Step 2: Generate
        markdown = self.generate_skill_markdown(config, user_input)
        print("📄 Generated Markdown:")
        print("-" * 50)
        print(markdown[:800] + "...")
        print("-" * 50)
        print()
        
        # Step 3: Save
        result = self.save_to_wiki(
            config.get("skill_name", "unnamed"),
            markdown,
            config.get("category", "utility"),
            config.get("handler_type", "tool_call")
        )
        
        if result.get("ok"):
            print(f"✅ Saved to wiki: {result['title']}")
            print(f"   Tags: {self.wiki_store[result['title']]['tags']}")
        
        return {
            "input": user_input,
            "config": config,
            "wiki_entry": result.get("title"),
            "full_markdown": markdown
        }
    
    def revise(self, name: str, revision_request: str) -> Dict:
        """Revise skill based on feedback"""
        title = f"Skill: {name}"
        
        if title not in self.wiki_store:
            return {"error": f"Skill not found: {name}"}
        
        entry = self.wiki_store[title]
        content = entry["content"]
        
        # Apply simple text transformations based on revision request
        new_content = content
        rev_lower = revision_request.lower()
        
        if "thai" in rev_lower or "language" in rev_lower:
            # Add Thai language support
            new_content = new_content.replace(
                "- **Languages**: en",
                "- **Languages**: en, th\n- **Thai Patterns**: TBD"
            )
        
        if "priority" in rev_lower:
            # Extract number if present
            import re
            nums = re.findall(r'\d+', revision_request)
            if nums:
                new_priority = nums[0]
                new_content = re.sub(
                    r'- \*\*Priority\*\*: \d+',
                    f'- **Priority**: {new_priority}',
                    new_content
                )
        
        if "add" in rev_lower and "trigger" in rev_lower:
            # Add a new trigger (simplified)
            new_trigger = revision_request.split("add")[-1].strip().strip('"')
            new_content = new_content.replace(
                "## Trigger Definition",
                f"## Trigger Definition\n- **Added Trigger**: \"{new_trigger}\" (from revision)"
            )
        
        # Add revision note
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        revision_note = f"\n\n## Revision ({timestamp})\n- Request: {revision_request}\n"
        new_content += revision_note
        
        # Update
        self.wiki_store[title]["content"] = new_content
        
        print(f"🔧 Revised: {title}")
        print(f"   Change: {revision_request}")
        print(f"   Revision added")
        
        return {"ok": True, "skill": name, "revision": revision_request}
    
    def list_skills(self):
        """List all skills in mock wiki"""
        print("📚 Skills in Wiki:")
        for title, entry in self.wiki_store.items():
            tags = entry.get("tags", [])
            status = "draft" if "skill-draft" in tags else "unknown"
            print(f"   • {title} [{status}]")


def demo():
    """Run interactive demo"""
    creator = MockSkillCreator()
    
    print("=" * 60)
    print("🛠️  Skill Creator Demo - Text-Driven Development")
    print("=" * 60)
    print()
    print("This demo shows how natural language becomes a skill draft.")
    print("No external dependencies - everything is mocked.")
    print()
    
    # Example 1
    print("🎯 Example 1: Weather skill")
    print()
    creator.create_from_text("check the weather when I ask what's the weather")
    print()
    
    # Example 2
    print("🎯 Example 2: Reminder skill")
    print()
    creator.create_from_text("remind me about tasks when I say don't forget")
    print()
    
    # Show list
    creator.list_skills()
    print()
    
    # Interactive mode
    print("=" * 60)
    print("💬 Interactive Mode (type 'quit' to exit)")
    print("=" * 60)
    print()
    print("Try describing a skill:")
    print('  - "find documents about X"')
    print('  - "tell me news headlines"')
    print('  - "search wiki for articles"')
    print()
    
    while True:
        user_input = input("📝 Your skill idea: ").strip()
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            break
        
        if not user_input:
            continue
        
        # Create
        result = creator.create_from_text(user_input)
        print()
        
        # Offer revision
        revise = input("🔧 Revise? (describe changes or 'no'): ").strip()
        if revise.lower() not in ['no', 'n', '']:
            skill_name = result["config"]["skill_name"]
            creator.revise(skill_name, revise)
            print()
            
            # Show updated
            show = input("📄 Show updated skill? (yes/no): ").strip()
            if show.lower() in ['yes', 'y']:
                title = f"Skill: {skill_name}"
                print()
                print(creator.wiki_store[title]["content"][:600] + "...")
        
        print()
        print("-" * 60)
        print()
    
    # Final state
    print()
    print("=" * 60)
    print("Final Wiki State:")
    creator.list_skills()
    print()
    print("Demo complete!")


if __name__ == "__main__":
    demo()
