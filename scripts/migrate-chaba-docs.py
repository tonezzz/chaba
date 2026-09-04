#!/usr/bin/env python3
"""Migrate chaba documentation to MDDB for unified search"""
import os
import json
import requests
from pathlib import Path
from datetime import datetime

CHABA_DOCS_DIR = "/home/tony/CascadeProjects/chaba-tony-dell/docs"
MDBB_SERVER = "http://localhost:9001"

def get_collection(rel_path):
    """Determine MDDB collection based on file path"""
    if 'architecture' in rel_path:
        return "chaba-architecture"
    elif 'assessments' in rel_path:
        return "chaba-assessments"
    elif 'reports' in rel_path:
        return "chaba-reports"
    elif 'implementation' in rel_path:
        return "chaba-implementation"
    elif 'ssot' in rel_path:
        return "ssot-general"  # Already synced, skip
    elif 'kb' in rel_path:
        return "kb-system"  # Already migrated, skip
    else:
        return "chaba-general"

def convert_doc_to_mddb(doc_path, rel_path):
    """Convert documentation file to MDDB document format"""
    with open(doc_path, 'r') as f:
        content = f.read()
    
    # Extract title from first line if it's a heading
    title = rel_path
    first_line = content.split('\n')[0]
    if first_line.startswith('#'):
        title = first_line.lstrip('#').strip()
    
    # Format as Markdown
    content_md = f"""# {title}

## File Path
`{rel_path}`

## Content
{content}
"""
    
    # Generate key from relative path
    key = rel_path.replace('/', '-').replace('.md', '')
    
    collection = get_collection(rel_path)
    
    return {
        "name": "add_document",
        "arguments": {
            "collection": collection,
            "key": key,
            "lang": "en",
            "content_md": content_md,
            "meta": {
                "title": title,
                "source": "chaba-docs",
                "original_path": rel_path,
                "type": "documentation",
                "collection": collection,
                "last_synced": datetime.now().isoformat()
            }
        }
    }

def sync_file(doc_path, rel_path):
    """Sync a single documentation file to MDDB"""
    payload = convert_doc_to_mddb(doc_path, rel_path)
    
    try:
        response = requests.post(f"{MDBB_SERVER}/tools/call", json=payload)
        response.raise_for_status()
        return True, payload["arguments"]["collection"]
    except Exception as e:
        print(f"❌ Error syncing {rel_path}: {e}")
        return False, payload["arguments"]["collection"]

def main():
    # Find all documentation files (excluding kb and ssot which are already synced)
    doc_files = []
    for root, dirs, files in os.walk(CHABA_DOCS_DIR):
        # Skip already synced directories
        if 'kb' in root or 'ssot' in root:
            continue
            
        for f in files:
            if f.endswith('.md'):
                rel_path = os.path.relpath(os.path.join(root, f), CHABA_DOCS_DIR)
                doc_files.append(rel_path)
    
    total_files = len(doc_files)
    print(f"📁 Found {total_files} documentation files to migrate")
    
    # Sync files
    success_count = 0
    collection_counts = {}
    skipped_count = 0
    
    for rel_path in doc_files:
        doc_path = os.path.join(CHABA_DOCS_DIR, rel_path)
        collection = get_collection(rel_path)
        
        # Skip already synced collections
        if collection in ["ssot-general", "kb-system"]:
            print(f"⏭️  Skipping: {rel_path} (already synced)")
            skipped_count += 1
            continue
        
        print(f"📄 Migrating: {rel_path}", end=" ... ")
        success, collection = sync_file(doc_path, rel_path)
        
        if success:
            print(f"✅ ({collection})")
            success_count += 1
            collection_counts[collection] = collection_counts.get(collection, 0) + 1
        else:
            print("❌")
    
    print(f"\n🎉 Documentation migration completed!")
    print(f"📊 Files migrated: {success_count}/{total_files}")
    print(f"⏭️  Files skipped: {skipped_count}")
    print(f"📁 Collection breakdown:")
    for collection, count in collection_counts.items():
        print(f"   - {collection}: {count}")

if __name__ == "__main__":
    main()