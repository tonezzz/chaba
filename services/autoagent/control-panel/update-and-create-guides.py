#!/usr/bin/env python3
"""
Update Skill Creator and create testing guide
"""

import os
import sys
import requests
import json

WIKI_API_URL = os.getenv("WIKI_API_URL", "http://localhost:3008")

def save_article(title, content, tags):
    """Save or update article in wiki"""
    url = f"{WIKI_API_URL}/api/articles"
    
    payload = {
        "title": title,
        "content": content,
        "tags": tags
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"   Error: {e}")
        return None


def main():
    print("=" * 60)
    print("📝 Updating/Creating Wiki Articles")
    print("=" * 60)
    print()
    
    # 1. Update Skill Creator (simpler version)
    print("1. Updating Skill Creator article...")
    skill_creator_content = """# Skill Creator

## Overview

Text-driven skill development with Thai language support and review workflow.

## Features

### Text Input
- Natural language skill creation
- English and Thai language support
- LLM-powered interpretation

### Thai Language Support
- Thai templates: ตรวจสอบอากาศ, เตือนความจำ, ค้นหา, แปลภาษา
- Thai trigger phrases
- Auto-detection of Thai input
- Thai configuration panel

### Review Workflow
```
Draft → Review → Approved → Ready
```

**Stages:**
- 📝 Draft - Initial creation
- 👀 Review - Quality check
- ✅ Approved - Passed review
- 🚀 Ready - Production deploy

### UI Components
- Example pills (English & Thai)
- Markdown preview
- Revision system
- Workflow status tracking

## Access

**Web UI:** http://localhost:8080/skills

**CLI:** `python3 test-wiki-skills.py`

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/skills` | Web UI |
| `/api/skills/interpret` | Text → skill config |
| `/api/skills/revise` | Apply revision |
| `/api/skills/save` | Save to wiki |

## Files

- `skill-creator.py` - Full CLI
- `skill-creator-ui-demo.html` - Browser demo
- `control-server.py` - Web UI server
- `test-wiki-skills.py` - Interactive tester

## Related Articles

- [[Skill Development Workflow]] - Approval process
- [[Thai Language Skill Guide]] - Thai localization
- [[Skill Testing Guide]] - Testing procedures
"""

    result = save_article("Skill Creator", skill_creator_content, 
                         "skill-system, autoagent, thai-language, workflow")
    if result:
        print(f"   ✅ Updated: {result.get('title')} (ID: {result.get('id')})")
    else:
        print("   ⚠️  Update failed, article may exist")
    print()
    
    # 2. Create Skill Testing Guide
    print("2. Creating Skill Testing Guide...")
    testing_content = """# Skill Testing Guide

## Overview

Comprehensive guide for testing skills before deployment.

## Testing Levels

### 1. Unit Testing

**Test Trigger Patterns**
```python
# Test exact matches
test_inputs = [
    "check weather",
    "what's the weather",
    "อากาศวันนี้",  # Thai
    "ร้อนไหม"       # Thai variant
]

for input in test_inputs:
    result = skill.match(input)
    assert result.matched == True, f"Failed: {input}"
```

**Test Handler Integration**
```python
# Mock handler call
result = skill.handler.call(mock=True)
assert result.status == "success"
assert result.error is None
```

### 2. Integration Testing

**Test Wiki Storage**
```bash
# 1. Create skill
curl -X POST http://localhost:3008/api/articles \
  -H "Content-Type: application/json" \
  -d '{"title": "Skill: test", "content": "...", "tags": "skill-draft"}'

# 2. Retrieve skill
curl http://localhost:3008/api/articles/Skill:%20test

# 3. Verify content
# Check: Content preserved correctly
# Check: Tags applied
# Check: Thai characters encoded
```

**Test API Endpoints**
```bash
# Test interpret endpoint
curl -X POST http://localhost:8080/api/skills/interpret \
  -H "Content-Type: application/json" \
  -d '{"input": "check weather"}'

# Expected: JSON config with skill_name, triggers, category
```

### 3. Workflow Testing

**Test Status Transitions**
```
1. Create skill → Status: Draft ✓
2. Submit review → Status: Review ✓
3. Approve → Status: Approved ✓
4. Mark ready → Status: Ready ✓
5. Reject → Status: Draft ✓
```

**Verify History Tracking**
```markdown
## Workflow Update (2026-04-12 13:15:00)
- Status: **REVIEW**
- Action: Submitted for review

## Workflow Update (2026-04-12 14:30:00)
- Status: **APPROVED**
- Action: Approved for deployment
```

### 4. Thai Language Testing

**Character Encoding Test**
```python
# Test Thai storage
test_thai = "ตรวจสอบอากาศ"
skill.thai_name = test_thai
saved = wiki.save(skill)
retrieved = wiki.get(skill.title)
assert retrieved.thai_name == test_thai
```

**Trigger Matching Test**
```python
# Test Thai trigger matching
test_cases = [
    ("อากาศวันนี้", True),
    ("อากาศเป็นยังไง", True),
    ("weather today", False)  # Should not match Thai-only skill
]

for input, expected in test_cases:
    result = skill.match(input)
    assert result == expected
```

**Bilingual Skill Test**
```python
# Test skill with both English and Thai
skill.languages = ["en", "th"]
skill.triggers = {
    "en": ["check weather", "weather today"],
    "th": ["ตรวจสอบอากาศ", "อากาศวันนี้"]
}

# Test English
test("check weather")  # → match

# Test Thai
test("ตรวจสอบอากาศ")  # → match

# Test mixed
test("check อากาศ")  # → partial or no match
```

## Test Scenarios

### Scenario 1: Weather Skill (English)

**Create:**
```
Input: "check weather when I ask about temperature"
```

**Test:**
```
Test input: "check weather" → Match ✓
Test input: "what's the temperature" → Match ✓
Test input: "is it raining" → Match ✓
Test input: "hello" → No match ✓
```

### Scenario 2: Weather Skill (Thai)

**Create:**
```
Input: "ตรวจสอบอากาศเมื่อถาม"
Thai triggers: อากาศวันนี้, ร้อนไหม, หนาวมั้ย
```

**Test:**
```
Test input: "อากาศวันนี้" → Match ✓
Test input: "ร้อนไหม" → Match ✓
Test input: "check weather" → No match ✓ (Thai-only)
Test input: "weather" → No match ✓
```

### Scenario 3: Bilingual Reminder

**Create:**
```
Input: "remind me about tasks"
Thai triggers: เตือนฉัน, อย่าลืม
Languages: en, th
```

**Test:**
```
Test input: "remind me" → Match ✓
Test input: "เตือนฉัน" → Match ✓
Test input: "อย่าลืม" → Match ✓
```

## Testing Checklist

### Pre-Review Testing

- [ ] Trigger patterns work for all defined phrases
- [ ] Handler can be called without errors
- [ ] Arguments schema is valid JSON
- [ ] Examples in documentation work
- [ ] Thai characters display correctly
- [ ] Wiki article saves/retrieves correctly
- [ ] Workflow status can be updated

### Review Testing

- [ ] Skill purpose is clear
- [ ] No duplicate trigger phrases
- [ ] Handler exists and is accessible
- [ ] Thai translations are accurate (if applicable)
- [ ] Documentation is complete

### Pre-Deploy Testing

- [ ] All checklists passed
- [ ] Integration tests pass
- [ ] No breaking changes to existing skills
- [ ] Rollback plan documented

## Test Commands

```bash
# Run all tests
python3 test-wiki-skills.py

# List all skills
> list

# Test specific skill
> read "Skill: check_weather"

# Create test skill
> create "test skill for testing"

# Check workflow
> (save, then use workflow buttons)

# Search skills
> search weather
```

## Automation

### CI/CD Testing

```yaml
# .github/workflows/skill-tests.yml
name: Skill Tests
on: [push, pull_request]

jobs:
  test:
    steps:
      - name: Test Wiki Connection
        run: python3 test-wiki-skills.py <<< "list"
      
      - name: Test Skill Creation
        run: |
          python3 test-wiki-skills.py << EOF
          create "test skill"
          yes
          list
          EOF
      
      - name: Verify Thai Encoding
        run: python3 test-thai-encoding.py
```

## Debugging

### Common Issues

**Issue: Thai characters garbled**
- Check: UTF-8 encoding in wiki database
- Fix: Verify `CHARSET=utf8` in connection

**Issue: Trigger not matching**
- Check: Pattern matching logic
- Debug: Print regex pattern
- Test: Exact string comparison

**Issue: Workflow status not saving**
- Check: Markdown append working
- Check: Wiki API responding
- Debug: Print markdown before save

**Issue: LLM interpretation failed**
- Check: OPENROUTER_API_KEY set
- Check: API rate limits
- Fallback: Use heuristic interpretation

## Tools

| Tool | Purpose |
|------|---------|
| `test-wiki-skills.py` | Interactive CLI testing |
| `seed-example-skills.py` | Seed test data |
| `skill-creator-ui-demo.html` | Browser-based testing |
| `curl` | API endpoint testing |

## Related

- [[Skill Creator]] - Creation documentation
- [[Skill Development Workflow]] - Approval process
- [[Thai Language Skill Guide]] - Thai testing specifics
"""

    result = save_article("Skill Testing Guide", testing_content,
                         "skill-system, testing, documentation, qa, guide")
    if result:
        print(f"   ✅ Created: {result.get('title')} (ID: {result.get('id')})")
    else:
        print("   ❌ Failed to create")
    print()
    
    print("=" * 60)
    print("✨ Complete!")
    print("=" * 60)
    print()
    print("Articles ready for review:")
    print("   📄 Skill Creator (updated)")
    print("   📄 Skill Testing Guide (new)")
    print()
    print("View at:")
    print(f"   {WIKI_API_URL}/api/articles/Skill%20Creator")
    print(f"   {WIKI_API_URL}/api/articles/Skill%20Testing%20Guide")


if __name__ == "__main__":
    main()
