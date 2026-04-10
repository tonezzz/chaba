#!/usr/bin/env python3
"""
Migrate documentation from /docs to MCP Wiki
Usage: python scripts/migrate-docs-to-wiki.py [file.md]
"""

import os
import sys
import re
import requests
from pathlib import Path
from datetime import datetime

# Configuration
DOCS_DIR = Path("docs")
WIKI_API = os.getenv("WIKI_API_URL", "http://localhost:3008")

def get_title_from_filename(filepath: Path) -> str:
    """Convert filename to wiki title"""
    name = filepath.stem
    # Convert MODULARIZATION_GUIDE to "Modularization Guide"
    title = name.replace("_", " ").title()
    
    # Add type prefix based on content analysis
    content = filepath.read_text(encoding='utf-8')
    
    if "troubleshoot" in name.lower() or "error" in content.lower():
        return f"Troubleshooting: {title}"
    elif "guide" in name.lower() or "how to" in content.lower():
        return f"Guide: {title}"
    elif "policy" in name.lower():
        return f"Policy: {title}"
    elif "status" in name.lower():
        return f"Status: {title}"
    elif "strategy" in name.lower() or "decision" in content.lower():
        return f"Decision: {title}"
    else:
        return f"Reference: {title}"

def infer_tags(filepath: Path, title: str) -> list:
    """Infer tags from filename and content"""
    name = filepath.stem.lower()
    tags = []
    
    # Type tags
    if "guide" in name:
        tags.append("guide")
    if "troubleshoot" in name:
        tags.append("troubleshooting")
    if "policy" in name:
        tags.append("policy")
    if "decision" in name or "strategy" in name:
        tags.append("decision-log")
    if "status" in name:
        tags.append("status")
    
    # Domain tags
    if "modular" in name:
        tags.append("modularization")
    if "mcp" in name or "wiki" in name:
        tags.append("mcp")
        tags.append("wiki")
    if "autoagent" in name:
        tags.append("autoagent")
    
    # Add generic tags
    if not tags:
        tags.append("documentation")
    
    return tags

def convert_markdown_to_wiki(content: str, title: str) -> str:
    """Enhance markdown for wiki format"""
    # Add metadata footer if not present
    if "## Metadata" not in content:
        today = datetime.now().strftime("%Y-%m-%d")
        content += f"""

---

## Metadata
- Migrated: {today}
- Source: docs/{title.replace(' ', '_').upper()}.md
- Status: active
- Auto-tagged: yes
"""
    return content

def create_wiki_article(title: str, content: str, tags: list) -> bool:
    """Create article via API"""
    url = f"{WIKI_API}/api/articles"
    
    data = {
        "title": title,
        "content": content,
        "tags": tags,
        "entities": [],
        "classification": "documentation"
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

def migrate_file(filepath: Path) -> bool:
    """Migrate single markdown file to wiki"""
    print(f"\n📄 {filepath.name}")
    
    title = get_title_from_filename(filepath)
    print(f"   Title: {title}")
    
    tags = infer_tags(filepath, title)
    print(f"   Tags: {', '.join(tags)}")
    
    content = filepath.read_text(encoding='utf-8')
    content = convert_markdown_to_wiki(content, title)
    
    return create_wiki_article(title, content, tags)

def main():
    if len(sys.argv) > 1:
        # Migrate specific file
        filepath = Path(sys.argv[1])
        if not filepath.exists():
            print(f"❌ File not found: {filepath}")
            sys.exit(1)
        migrate_file(filepath)
    else:
        # Migrate all docs
        print(f"🔍 Scanning {DOCS_DIR} for markdown files...")
        print(f"🌐 Wiki API: {WIKI_API}")
        print("=" * 60)
        
        md_files = list(DOCS_DIR.glob("*.md"))
        md_files = [f for f in md_files if f.name != "README.md" and "WIKI_POLICY" not in f.name]
        
        if not md_files:
            print("No markdown files found to migrate.")
            sys.exit(0)
        
        success = 0
        for filepath in md_files:
            if migrate_file(filepath):
                success += 1
        
        print("\n" + "=" * 60)
        print(f"✅ Migrated: {success}/{len(md_files)} articles")
        print(f"📚 View at: {WIKI_API}")
        
        # Next steps
        print("\n📋 Next Steps:")
        print("   1. Review articles in wiki")
        print("   2. Update cross-references")
        print("   3. Archive original files:")
        print("      mkdir docs/archive")
        print("      mv docs/*.md docs/archive/ (except README and WIKI_POLICY)")

if __name__ == "__main__":
    main()
