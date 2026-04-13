#!/usr/bin/env python3
"""
Directly update Skill Creator article in SQLite database
"""

import sqlite3
import os
from datetime import datetime

# Find wiki database
WIKI_DB_PATH = "/home/chaba/chaba/stacks/pc1-wiki/data/wiki.db"

if not os.path.exists(WIKI_DB_PATH):
    # Try alternative paths
    alternatives = [
        "/data/wiki.db",
        "/home/chaba/chaba/data/wiki.db",
        "./data/wiki.db"
    ]
    for path in alternatives:
        if os.path.exists(path):
            WIKI_DB_PATH = path
            break

print(f"Using database: {WIKI_DB_PATH}")
print(f"Database exists: {os.path.exists(WIKI_DB_PATH)}")

if not os.path.exists(WIKI_DB_PATH):
    print("❌ Database not found!")
    exit(1)

# New content
new_content = """# Skill Creator - Text-Driven Skill Development

## Overview

The Skill Creator enables **natural language-driven skill development** integrated with the wiki system. Create skills from text input with Thai language support and review workflow.

## New Features

- 🇹🇭 **Thai Language Support** - Full Thai templates and configuration
- 📋 **Review/Approval Workflow** - 4-stage lifecycle (Draft → Review → Approved → Ready)
- 🎯 **LLM Interpretation** - Powered by OpenRouter (Nemotron model)

## Web UI

Access at: `http://localhost:8080/skills`

### Standard Templates
- ☁️ Weather check
- ⏰ Reminder
- 🔍 Wiki search
- 📰 News brief
- 💻 Code analysis

### 🇹🇭 Thai Language Templates
- ☁️ ตรวจสอบอากาศ - Weather queries
- ⏰ เตือนความจำ - Reminders
- 🔍 ค้นหา - Search
- 🌐 แปลภาษา - Translation
- 📰 ข่าวสาร - News

### Thai Configuration Panel
- Thai Skill Name (e.g., ตรวจสอบอากาศ)
- Thai Trigger Phrases (comma-separated)
- Auto-detection of Thai input

## Workflow Pipeline

```
📝 Draft → 👀 Review → ✅ Approved → 🚀 Ready
```

| Status | Description | Actions |
|--------|-------------|---------|
| Draft | Initial creation | Submit for Review |
| Review | Quality check | Approve / Reject |
| Approved | Pre-production | Mark Ready |
| Ready | Deploy | Deploy to Jarvis |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/skills` | GET | Web UI |
| `/api/skills/interpret` | POST | Text → skill config |
| `/api/skills/revise` | POST | Apply revision |
| `/api/skills/save` | POST | Save to wiki |

## Files

- `skill-creator.py` - CLI with LLM
- `skill-creator-ui-demo.html` - Browser demo
- `control-server.py` - Web UI server
- `test-wiki-skills.py` - Interactive tester

## Environment

- `WIKI_API_URL` - Wiki endpoint
- `OPENROUTER_API_KEY` - LLM API key

## Related Articles

- [[Skill Development Workflow]] - Approval process
- [[Thai Language Skill Guide]] - Thai localization
- [[Skill Testing Guide]] - Testing procedures
"""

new_tags = "skill-system, autoagent, thai-language, workflow, development"

# Update database
conn = sqlite3.connect(WIKI_DB_PATH)
cursor = conn.cursor()

# Check current article
cursor.execute("SELECT id, title, updated_at FROM articles WHERE title = ?", ("Skill Creator",))
existing = cursor.fetchone()

if existing:
    article_id, title, old_updated = existing
    print(f"Found article: ID={article_id}, Title='{title}'")
    print(f"Last updated: {old_updated}")
    
    # Update the article
    cursor.execute("""
        UPDATE articles 
        SET content = ?, tags = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (new_content, new_tags, article_id))
    
    conn.commit()
    
    # Verify update
    cursor.execute("SELECT updated_at FROM articles WHERE id = ?", (article_id,))
    new_updated = cursor.fetchone()[0]
    
    print(f"\n✅ Article updated successfully!")
    print(f"   New update time: {new_updated}")
    print(f"   Content length: {len(new_content)} characters")
    print(f"   Tags: {new_tags}")
else:
    print("Article not found, creating new...")
    
    # Insert new article
    cursor.execute("""
        INSERT INTO articles (title, content, tags, created_at, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, ("Skill Creator", new_content, new_tags))
    
    conn.commit()
    article_id = cursor.lastrowid
    print(f"\n✅ Article created: ID={article_id}")

conn.close()

print("\n" + "="*60)
print("Verification:")
print("="*60)

# Verify via API
import requests
resp = requests.get("http://localhost:3008/api/articles/Skill%20Creator")
if resp.status_code == 200:
    data = resp.json()
    print(f"✅ API confirms update")
    print(f"   Title: {data.get('title')}")
    print(f"   Tags: {data.get('tags')}")
    print(f"   Updated: {data.get('updated_at')}")
else:
    print(f"⚠️  API check failed: {resp.status_code}")
