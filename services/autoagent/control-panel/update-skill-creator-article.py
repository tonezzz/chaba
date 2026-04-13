#!/usr/bin/env python3
"""
Update Skill Creator wiki article with Thai + Workflow features
"""

import os
import sys
import requests

WIKI_API_URL = os.getenv("WIKI_API_URL", "http://localhost:3008")

updated_content = """# Skill Creator - Text-Driven Skill Development

## Overview

The Skill Creator enables **natural language-driven skill development** integrated with the wiki system. It allows you to describe what you want a skill to do in plain text, and the system interprets your intent into a structured skill configuration.

**New Features:**
- 🇹🇭 **Thai Language Support** - Full Thai skill templates and configuration
- 📋 **Review/Approval Workflow** - 4-stage lifecycle management

---

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

---

## Web UI

Access the Skill Creator at: `http://localhost:8080/skills`

### Standard Templates

| Template | Description |
|----------|-------------|
| ☁️ Weather check | Check weather conditions |
| ⏰ Reminder | Task reminders |
| 🔍 Wiki search | Search knowledge base |
| 📰 News brief | News headlines |
| 💻 Code analysis | Analyze code snippets |

### 🇹🇭 Thai Language Templates

| Template | Thai Description | Use Case |
|----------|-------------------|----------|
| ☁️ ตรวจสอบอากาศ | ตรวจสอบสภาพอากาศเมื่อถามว่าอากาศเป็นอย่างไร | Weather queries in Thai |
| ⏰ เตือนความจำ | เตือนฉันเกี่ยวกับงานเมื่อพูดว่าอย่าลืม | Thai reminder phrases |
| 🔍 ค้นหา | ค้นหาเอกสารเมื่อถามหาข้อมูล | Thai search commands |
| 🌐 แปลภาษา | แปลภาษาไทยเป็นอังกฤษ | Thai-English translation |
| 📰 ข่าวสาร | บอกข่าวสารล่าสุด | Thai news requests |

**Thai Configuration Panel:**
- **Thai Skill Name**: Localized name (e.g., `ตรวจสอบอากาศ`)
- **Thai Trigger Phrases**: Comma-separated list (e.g., `อากาศวันนี้, ร้อนไหม, หนาวมั้ย`)
- **Auto-detection**: Thai input automatically shows Thai config panel

---

## 📋 Review/Approval Workflow

### Status Pipeline

```
📝 Draft → 👀 Review → ✅ Approved → 🚀 Ready
```

### Workflow States

| Status | Description | Available Actions |
|--------|-------------|-------------------|
| **📝 Draft** | Initial creation, editing allowed | Submit for Review |
| **👀 Review** | Under review by team | Approve / Reject |
| **✅ Approved** | Passed review, awaiting deploy | Mark Ready |
| **🚀 Ready** | Production-ready | Deploy to Jarvis |

### Workflow History

Every status change is recorded in the skill article:

```markdown
## Workflow Update (2026-04-12 13:15:00)
- Status: **REVIEW**
- Action: Submitted for review

## Workflow Update (2026-04-12 14:30:00)
- Status: **APPROVED**
- Action: Approved for deployment
```

### UI Features

- **Visual Status Badges**: Color-coded status indicators
- **Contextual Actions**: Only relevant buttons shown
- **History Timeline**: Complete audit trail
- **Auto-save**: Status changes update wiki article

---

## Features

### Text Input
Describe skill in natural language (English or Thai)

### Example Pills
Click preset examples for quick-start

### Intent Display
Shows interpreted: name, category, triggers, priority, languages

### Markdown Preview
Full skill document with syntax highlighting

### Revision System
Text-driven refinement with quick-action pills:
- 🇹🇭 Add Thai - Add Thai language support
- ⚡ High priority - Change priority value
- ➕ Add trigger - Add trigger phrase
- 🔌 Change handler - Switch handler type

### Save to Wiki
Stores draft as wiki article with `skill-draft` tag

---

## Example Interactions

### Creating a Weather Skill (English)

**Input:** `"check the weather when I ask about temperature or forecast"`

**Interpreted Config:**
```json
{
  "skill_name": "check_weather",
  "category": "info",
  "handler_type": "tool_call",
  "trigger_phrases": [
    "check the weather when I ask about temperature or forecast"
  ],
  "priority": 10,
  "languages": ["en"]
}
```

### Creating a Thai Weather Skill

**Input:** `"ตรวจสอบสภาพอากาศเมื่อถามว่าอากาศเป็นอย่างไร"`

**Thai Config Applied:**
```json
{
  "skill_name": "check_weather_thai",
  "thai_name": "ตรวจสอบอากาศ",
  "languages": ["th"],
  "thai_triggers": [
    "ตรวจสอบสภาพอากาศ",
    "อากาศวันนี้",
    "ร้อนไหม"
  ]
}
```

### Workflow Example

1. **Create** → Status: 📝 Draft
2. **Save to Wiki** → Workflow section appears
3. **Submit for Review** → Status: 👀 Review
4. **Approve** → Status: ✅ Approved
5. **Mark Ready** → Status: 🚀 Ready

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/skills` | GET | Web UI page |
| `/api/skills/interpret` | POST | Text → skill config |
| `/api/skills/revise` | POST | Apply revision |
| `/api/skills/save` | POST | Save to wiki |

### Interpret API

**Request:**
```json
{
  "input": "check weather when I ask",
  "language": "auto"  // or "en", "th"
}
```

**Response:**
```json
{
  "config": {
    "skill_name": "check_weather",
    "category": "info",
    "trigger_phrases": [...]
  },
  "markdown": "# Skill: check_weather...",
  "detected_language": "en"
}
```

---

## Article Schema

Generated skill articles include:

```markdown
# Skill: {name}

## Metadata
- **Name**: {skill_name}
- **Thai Name**: {thai_name} (if applicable)
- **Status**: draft
- **Version**: 1.0.0
- **Tags**: skill-draft, skill-category-{category}

## Purpose
{user_input}

## Trigger Definition
- **Match Type**: prefix
- **Patterns**: [...]
- **Thai Patterns**: [...] (if applicable)
- **Priority**: {priority}
- **Languages**: en, th

## Handler Configuration
## Arguments Schema
## Examples
## Thai Language Support (optional)
## Development Notes
## Testing Checklist
## Changelog
## Workflow Update (auto-generated)
```

---

## Files

| File | Purpose |
|------|---------|
| `skill-creator.py` | Full CLI with LLM integration |
| `skill-creator-demo.py` | Standalone mock demo |
| `skill-creator-ui-demo.html` | Browser demo (no server) |
| `control-server.py` | Web UI integrated into control panel |
| `test-wiki-skills.py` | Interactive CLI tester |
| `seed-example-skills.py` | Seed wiki with examples |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WIKI_API_URL` | `http://mcp-wiki:8080` | Wiki API endpoint |
| `OPENROUTER_API_KEY` | - | For LLM interpretation |

---

## Skill Lifecycle with Workflow

```
Draft → Review → Approved → Ready → Deployed
  ↑       ↓         ↓         ↓         ↓
  └───────┴─────────┴─────────┴─────── Feedback
```

### Role-Based Actions

| Role | Draft | Review | Approved | Ready |
|------|-------|--------|----------|-------|
| **Developer** | Create, Edit | - | - | - |
| **Reviewer** | View | Approve/Reject | - | - |
| **DevOps** | View | View | Mark Ready | Deploy |

---

## Thai Language Best Practices

1. **Use Thai templates** for consistent naming
2. **Add both English and Thai triggers** for bilingual skills
3. **Test Thai character encoding** in wiki storage
4. **Include Thai examples** in documentation
5. **Tag with `thai-language`** for discoverability

---

## Future Enhancements

- [ ] Email/Slack notifications on status change
- [ ] Multi-reviewer approval (require N approvals)
- [ ] Skill comparison/diff view
- [ ] Automated testing before review
- [ ] Thai LLM for better Thai interpretation
- [ ] Voice input for skill creation
- [ ] Batch skill import/export

---

## Related Articles

- [[Skill System]] - How Jarvis skills work
- [[MCP-Wiki]] - Knowledge base documentation
- [[AutoAgent]] - Research and automation framework
- [[Thai Language Support]] - Thai localization guide
"""

def update_wiki_article():
    """Update the Skill Creator article in wiki"""
    url = f"{WIKI_API_URL}/api/articles"
    
    # First check if article exists
    try:
        check_resp = requests.get(f"{WIKI_API_URL}/api/articles/Skill%20Creator", timeout=5)
        exists = check_resp.status_code == 200
    except:
        exists = False
    
    payload = {
        "title": "Skill Creator",
        "content": updated_content,
        "tags": "skill-system, autoagent, documentation, development, thai-language, workflow"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        print("✅ Skill Creator article updated successfully!")
        print(f"   Title: {result.get('title', 'Skill Creator')}")
        print(f"   ID: {result.get('id', 'N/A')}")
        print(f"   Tags: skill-system, autoagent, documentation, development, thai-language, workflow")
        return True
    except Exception as e:
        print(f"❌ Error updating article: {e}")
        return False


def create_workflow_article():
    """Create separate workflow documentation article"""
    workflow_content = """# Skill Development Workflow

## Overview

The 4-stage workflow for managing skill development lifecycle.

## Stages

### 📝 1. Draft
**Purpose**: Initial skill creation and iteration

**Activities**:
- Create skill from text input
- Revise and refine
- Add Thai language support
- Test trigger patterns

**Exit Criteria**:
- Skill configuration complete
- At least 2 trigger phrases defined
- Handler type selected
- Examples documented

**Next**: Submit for Review

---

### 👀 2. Review
**Purpose**: Quality assurance and validation

**Activities**:
- Review trigger coverage
- Check handler compatibility
- Validate Thai translations (if applicable)
- Verify examples work

**Exit Criteria**:
- Reviewer approval
- Or: Rejection with feedback

**Next**: Approve or Reject

---

### ✅ 3. Approved
**Purpose**: Pre-production validation

**Activities**:
- Final testing
- Documentation review
- Dependencies check

**Exit Criteria**:
- All tests pass
- Ready for deployment

**Next**: Mark Ready

---

### 🚀 4. Ready
**Purpose**: Production deployment

**Activities**:
- Deploy to Jarvis
- Monitor performance
- Collect feedback

**Exit Criteria**:
- Successfully deployed
- Working in production

---

## Role Responsibilities

| Role | Responsibilities |
|------|------------------|
| **Developer** | Create, revise, test skills |
| **Reviewer** | Approve/reject, quality check |
| **DevOps** | Deploy, monitor, maintain |

## Status Transitions

```
Draft --[submit]--> Review
Review --[approve]--> Approved
Review --[reject]--> Draft
Approved --[ready]--> Ready
```

## Automation Rules

1. **Auto-save** on status change
2. **History tracking** - all transitions logged
3. **Notification** - can be added (email/Slack)
4. **Timeout** - review pending > 7 days → reminder
"""

    url = f"{WIKI_API_URL}/api/articles"
    payload = {
        "title": "Skill Development Workflow",
        "content": workflow_content,
        "tags": "skill-system, workflow, documentation, process"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        print(f"✅ Created: {result.get('title')}")
        return True
    except Exception as e:
        print(f"⚠️  Workflow article: {e}")
        return False


def create_thai_guide_article():
    """Create Thai language guide article"""
    thai_content = """# Thai Language Skill Guide

## Overview

Guide for creating Thai-language skills in Jarvis.

## Thai Templates

### Weather
- **Input**: ตรวจสอบสภาพอากาศเมื่อถามว่าอากาศเป็นอย่างไร
- **Triggers**: อากาศวันนี้, ร้อนไหม, หนาวมั้ย, ฝนตกไหม

### Reminder
- **Input**: เตือนฉันเกี่ยวกับงานเมื่อพูดว่าอย่าลืม
- **Triggers**: อย่าลืม, เตือนฉันด้วย, นัดหมาย

### Search
- **Input**: ค้นหาเอกสารเมื่อถามหาข้อมูล
- **Triggers**: หาข้อมูล, ค้นหา, มีอะไรบ้าง

## Character Encoding

- Use UTF-8 for all Thai text
- Test storage in wiki (SQLite supports Thai)
- Verify trigger matching with Thai characters

## Common Thai Phrases for Skills

| English | Thai | Use Case |
|---------|------|----------|
| Check | ตรวจสอบ | Information skills |
| Remind | เตือน | Action skills |
| Search | ค้นหา | Search skills |
| Show | แสดง | Display skills |
| Tell me | บอกฉัน | Information skills |

## Best Practices

1. **Bilingual Support**: Add both English and Thai triggers
2. **Test Coverage**: Include Thai test cases
3. **Documentation**: Use Thai in examples
4. **Tags**: Add `thai-language` tag
5. **Naming**: Use descriptive Thai names

## Thai Input Detection

The system automatically detects Thai input by checking for Thai Unicode range (U+0E00-U+0E7F).

When Thai is detected:
- Thai config panel auto-shows
- Language set to `th`
- Thai name field becomes available

## Related

- [[Skill Creator]] - Main documentation
- [[Skill Development Workflow]] - Approval process
"""

    url = f"{WIKI_API_URL}/api/articles"
    payload = {
        "title": "Thai Language Skill Guide",
        "content": thai_content,
        "tags": "skill-system, thai-language, localization, guide"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        print(f"✅ Created: {result.get('title')}")
        return True
    except Exception as e:
        print(f"⚠️  Thai guide article: {e}")
        return False


def main():
    print("=" * 60)
    print("📝 Updating Wiki Articles")
    print("=" * 60)
    print()
    
    # Update main Skill Creator article
    print("1. Updating Skill Creator article...")
    update_wiki_article()
    print()
    
    # Create workflow article
    print("2. Creating Workflow documentation...")
    create_workflow_article()
    print()
    
    # Create Thai guide
    print("3. Creating Thai Language Guide...")
    create_thai_guide_article()
    print()
    
    print("=" * 60)
    print("✨ Update Complete!")
    print("=" * 60)
    print()
    print("Updated/Created Articles:")
    print("   📄 Skill Creator (updated)")
    print("   📄 Skill Development Workflow (new)")
    print("   📄 Thai Language Skill Guide (new)")
    print()
    print("View at:")
    print(f"   {WIKI_API_URL}/api/articles/Skill%20Creator")
    print(f"   {WIKI_API_URL}/api/articles/Skill%20Development%20Workflow")
    print(f"   {WIKI_API_URL}/api/articles/Thai%20Language%20Skill%20Guide")


if __name__ == "__main__":
    main()
