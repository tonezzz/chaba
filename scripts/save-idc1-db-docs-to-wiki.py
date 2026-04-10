#!/usr/bin/env python3
"""
Save idc1-db stack documentation to MCP Wiki
Usage: python scripts/save-idc1-db-docs-to-wiki.py [--wiki-api URL]
"""

import os
import sys
import argparse
import requests
from pathlib import Path
from datetime import datetime

# Configuration
STACK_DIR = Path("stacks/idc1-db")
WIKI_API = os.getenv("WIKI_API_URL", "http://idc1.surf-thailand.com:3008")

def create_wiki_article(title: str, content: str, tags: list, classification: str = "documentation") -> bool:
    """Create article via API"""
    url = f"{WIKI_API}/api/articles"
    
    data = {
        "title": title,
        "content": content,
        "tags": tags,
        "entities": [],
        "classification": classification
    }
    
    try:
        resp = requests.post(url, json=data, timeout=10)
        if resp.status_code == 201:
            print(f"  ✅ Created: {title}")
            return True
        elif resp.status_code == 500 and "UNIQUE constraint" in resp.text:
            print(f"  ⚠️  Already exists: {title}")
            return False
        else:
            print(f"  ❌ Error ({resp.status_code}): {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False

def prepare_service_endpoints_doc() -> str:
    """Prepare Service Endpoints Reference document"""
    return """# IDC1-DB Service Endpoints Reference

Centralized database and AI services running on idc1 host.

## Services Overview

| Service | Port | Purpose | Endpoint |
|---------|------|---------|----------|
| PostgreSQL | 5432 | Primary database | `idc1.surf-thailand.com:5432` |
| pgAdmin | 5050 | Database management UI | `http://idc1.surf-thailand.com:5050` |
| MCP Wiki | 3008 | Knowledge base | `http://idc1.surf-thailand.com:3008` |
| AutoAgent | 8059 | AI agent control panel | `http://idc1.surf-thailand.com:8059` |
| AutoAgent MCP | 8058 | GhostRoute MCP server | `http://idc1.surf-thailand.com:8058` |
| MCP PostgreSQL | - | MCP server for AI access | (stdio via MCP clients) |

## Connection Details

### PostgreSQL
```
Host: idc1.surf-thailand.com
Port: 5432
Database: chaba
User: chaba
Password: (from .env on idc1)
Connection String: postgresql://chaba:password@idc1.surf-thailand.com:5432/chaba
```

### pgAdmin
- URL: http://idc1.surf-thailand.com:5050
- Email: (from PGADMIN_EMAIL in .env)
- Password: (from PGADMIN_PASSWORD in .env)

### MCP Wiki API
- Base URL: http://idc1.surf-thailand.com:3008
- Articles API: `GET/POST /api/articles`
- Search API: `GET /api/search?q=query`

### AutoAgent
- Control Panel: http://idc1.surf-thailand.com:8059
- GhostRoute MCP: http://idc1.surf-thailand.com:8058/mcp

## Health Checks

```bash
# Test PostgreSQL (from idc1)
docker exec idc1-postgres pg_isready -U chaba

# Test MCP Wiki
curl -s http://idc1.surf-thailand.com:3008/api/articles | head -5

# Test AutoAgent
curl -s http://idc1.surf-thailand.com:8059/health
```

## VPN Access

All services require VPN connection from pc1:
- Ensure WireGuard is connected
- Test: `ping idc1.surf-thailand.com`

---

## Metadata
- Stack: idc1-db
- Host: idc1.surf-thailand.com
- Branch: idc1-db
- Updated: {date}
""".format(date=datetime.now().strftime("%Y-%m-%d"))

def prepare_stack_readme_doc() -> str:
    """Prepare Stack README document"""
    readme_path = STACK_DIR / "README.md"
    if readme_path.exists():
        content = readme_path.read_text(encoding='utf-8')
        # Add metadata footer
        content += f"""

---

## Metadata
- Source: stacks/idc1-db/README.md
- Migrated: {datetime.now().strftime("%Y-%m-%d")}
- Stack: idc1-db
"""
        return content
    return ""

def prepare_migration_guide_doc() -> str:
    """Prepare Migration Guide document"""
    guide_path = STACK_DIR / "MIGRATION_GUIDE.md"
    if guide_path.exists():
        content = guide_path.read_text(encoding='utf-8')
        # Add metadata footer
        content += f"""

---

## Metadata
- Source: stacks/idc1-db/MIGRATION_GUIDE.md
- Migrated: {datetime.now().strftime("%Y-%m-%d")}
- Stack: idc1-db
"""
        return content
    return ""

def main():
    global WIKI_API
    
    parser = argparse.ArgumentParser(description="Save idc1-db docs to wiki")
    parser.add_argument("--wiki-api", default=WIKI_API, help="Wiki API URL")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    args = parser.parse_args()
    
    WIKI_API = args.wiki_api
    
    print(f"🌐 Wiki API: {WIKI_API}")
    print(f"📁 Stack dir: {STACK_DIR}")
    print("=" * 60)
    
    docs = [
        {
            "title": "IDC1-DB Service Endpoints Reference",
            "content": prepare_service_endpoints_doc(),
            "tags": ["idc1-db", "reference", "endpoints", "postgresql", "services"],
            "classification": "reference"
        },
        {
            "title": "IDC1-DB Stack README",
            "content": prepare_stack_readme_doc(),
            "tags": ["idc1-db", "readme", "documentation", "postgresql"],
            "classification": "documentation"
        },
        {
            "title": "IDC1-DB Migration Guide",
            "content": prepare_migration_guide_doc(),
            "tags": ["idc1-db", "migration", "guide", "postgresql", "wiki"],
            "classification": "guide"
        }
    ]
    
    if args.dry_run:
        print("🔍 DRY RUN - No articles will be created")
        for doc in docs:
            print(f"\n📄 {doc['title']}")
            print(f"   Tags: {', '.join(doc['tags'])}")
            print(f"   Content length: {len(doc['content'])} chars")
        return
    
    success = 0
    for doc in docs:
        print(f"\n📄 {doc['title']}")
        if doc['content']:
            if create_wiki_article(doc['title'], doc['content'], doc['tags'], doc['classification']):
                success += 1
        else:
            print("  ⚠️  No content available")
    
    print("\n" + "=" * 60)
    print(f"✅ Saved: {success}/{len(docs)} articles")
    print(f"📚 View at: {WIKI_API}")
    
    # Update todo.md
    todo_path = STACK_DIR / "todo.md"
    if todo_path.exists() and success > 0:
        print(f"\n📝 Remember to update {todo_path} to mark docs as saved")

if __name__ == "__main__":
    main()
