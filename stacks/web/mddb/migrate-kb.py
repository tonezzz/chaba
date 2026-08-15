#!/usr/bin/env python3
"""Migrate KB content to MDDB using MCP API"""
import os
import json
import requests
import re

KB_DIR = "/home/tony/CascadeProjects/chaba-kbman/docs/kb"
MDBB_SERVER = "http://localhost:9001"

def get_collection(filename):
    """Determine collection based on filename pattern"""
    if re.search(r'(system|infrastructure|architecture|security|caddy|dns|disk|gpu|health|hibernation|mcp|playlive|security|shared|ssot|system|thailand|token|weaviate|worktree|yaml)', filename, re.IGNORECASE):
        return "kb-system"
    elif re.search(r'(development|testing|automation|javascript|documentation|e2e|gemini|language|raceman|test|trade)', filename, re.IGNORECASE):
        return "kb-development"
    elif re.search(r'(operations|monitoring|maintenance|backup|headroom|h3|impact|overnight)', filename, re.IGNORECASE):
        return "kb-operations"
    else:
        return "kb-features"

def migrate_file(filepath, filename):
    """Migrate a single file to MDDB"""
    collection = get_collection(filename)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    payload = {
        "name": "add_document",
        "arguments": {
            "collection": collection,
            "key": filename,
            "lang": "en",
            "content_md": content,
            "meta": {
                "title": filename,
                "source": "chaba-kbman",
                "category": "migrated"
            }
        }
    }
    
    try:
        response = requests.post(f"{MDBB_SERVER}/tools/call", json=payload)
        response.raise_for_status()
        return True, collection
    except Exception as e:
        print(f"❌ Error migrating {filename}: {e}")
        return False, collection

def main():
    # Count files
    md_files = [f for f in os.listdir(KB_DIR) if f.endswith('.md')]
    total_files = len(md_files)
    print(f"📁 Found {total_files} markdown files to migrate")
    
    # Migrate files
    success_count = 0
    collection_counts = {"kb-system": 0, "kb-development": 0, "kb-operations": 0, "kb-features": 0}
    
    for filename in md_files:
        filepath = os.path.join(KB_DIR, filename)
        name_without_ext = filename[:-3]  # Remove .md
        
        print(f"📄 Migrating: {name_without_ext}", end=" ... ")
        success, collection = migrate_file(filepath, name_without_ext)
        
        if success:
            print(f"✅ ({collection})")
            success_count += 1
            collection_counts[collection] += 1
        else:
            print("❌")
    
    print(f"\n🎉 KB migration completed!")
    print(f"📊 Files migrated: {success_count}/{total_files}")
    print(f"📁 Collection breakdown:")
    for collection, count in collection_counts.items():
        print(f"   - {collection}: {count}")

if __name__ == "__main__":
    main()