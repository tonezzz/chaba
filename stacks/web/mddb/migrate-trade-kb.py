#!/usr/bin/env python3
"""Migrate Trade KB content to MDDB using MCP API"""
import os
import json
import requests
import re

TRADE_KB_DIR = "/home/tony/CascadeProjects/trade/docs"
MDBB_SERVER = "http://localhost:9001"

def get_collection(rel_path):
    """Determine collection based on relative path pattern"""
    # Check the full path for better categorization
    if re.search(r'(system|infrastructure|architecture|configuration|ssot|deployment|setup|core|data)', rel_path, re.IGNORECASE):
        return "trade-kb-system"
    elif re.search(r'(development|workflow|convention|testing|automation|best.practice|pattern|lesson|knowledge)', rel_path, re.IGNORECASE):
        return "trade-kb-development"
    elif re.search(r'(operation|monitoring|maintenance|backup|screen.timeout|troubleshooting)', rel_path, re.IGNORECASE):
        return "trade-kb-operations"
    else:
        return "trade-kb-features"

def migrate_file(filepath, rel_path):
    """Migrate a single file to MDDB"""
    # Use relative path as key, replace / with - for compatibility
    key = rel_path.replace('/', '-').replace('.md', '')
    collection = get_collection(rel_path)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    payload = {
        "name": "add_document",
        "arguments": {
            "collection": collection,
            "key": key,
            "lang": "en",
            "content_md": content,
            "meta": {
                "title": rel_path,
                "source": "trade",
                "category": "migrated",
                "project": "trade",
                "original_path": rel_path
            }
        }
    }
    
    try:
        response = requests.post(f"{MDBB_SERVER}/tools/call", json=payload)
        response.raise_for_status()
        return True, collection
    except Exception as e:
        print(f"❌ Error migrating {rel_path}: {e}")
        return False, collection

def main():
    # Count files recursively
    md_files = []
    for root, dirs, files in os.walk(TRADE_KB_DIR):
        for f in files:
            if f.endswith('.md'):
                # Get relative path from TRADE_KB_DIR
                rel_path = os.path.relpath(os.path.join(root, f), TRADE_KB_DIR)
                md_files.append(rel_path)
    
    total_files = len(md_files)
    print(f"📁 Found {total_files} markdown files to migrate from trade project")
    
    # Migrate files
    success_count = 0
    collection_counts = {"trade-kb-system": 0, "trade-kb-development": 0, "trade-kb-operations": 0, "trade-kb-features": 0}
    
    for rel_path in md_files:
        filepath = os.path.join(TRADE_KB_DIR, rel_path)
        
        print(f"📄 Migrating: {rel_path}", end=" ... ")
        success, collection = migrate_file(filepath, rel_path)
        
        if success:
            print(f"✅ ({collection})")
            success_count += 1
            collection_counts[collection] += 1
        else:
            print("❌")
    
    print(f"\n🎉 Trade KB migration completed!")
    print(f"📊 Files migrated: {success_count}/{total_files}")
    print(f"📁 Collection breakdown:")
    for collection, count in collection_counts.items():
        print(f"   - {collection}: {count}")
    print(f"\n📝 Note: File keys use relative paths with / replaced by - (e.g., 'knowledge/patterns/patterns.md' → 'knowledge-patterns-patterns')")

if __name__ == "__main__":
    main()