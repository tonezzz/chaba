#!/usr/bin/env python3
"""Sync SSOT YAML files to MDDB for semantic search"""
import os
import json
import requests
import yaml
from pathlib import Path
from datetime import datetime

SSOT_DIR = "/home/tony/CascadeProjects/chaba/docs/ssot"
MDBB_SERVER = "http://tony-dell.taila0626a.ts.net:11023/v1"

def get_ssot_collection(rel_path):
    """Determine MDDB collection based on SSOT file path"""
    # All SSOT documents now go to infrastructure-ssot
    return "infrastructure-ssot"

def convert_yaml_to_mddb(yaml_path, rel_path):
    """Convert SSOT YAML file to MDDB document format"""
    with open(yaml_path, 'r') as f:
        yaml_content = f.read()
    
    # Parse YAML to extract title and description for better search
    try:
        yaml_data = yaml.safe_load(yaml_content)
        title = yaml_data.get('title', rel_path)
        description = yaml_data.get('subtitle', yaml_data.get('description', ''))
    except:
        title = rel_path
        description = ''
    
    # Format as Markdown with YAML code block
    content_md = f"""# {title}

{description}

## File Path
`{rel_path}`

## YAML Content
```yaml
{yaml_content}
```
"""
    
    # Generate key from relative path
    key = rel_path.replace('/', '-').replace('.yml', '')
    
    collection = get_ssot_collection(rel_path)
    
    return {
        "name": "add_document",
        "arguments": {
            "collection": collection,
            "key": key,
            "lang": "en",
            "content_md": content_md,
            "meta": {
                "title": title,
                "source": "ssot",
                "original_path": rel_path,
                "type": "yaml",
                "collection": collection,
                "last_synced": datetime.now().isoformat()
            }
        }
    }

def sync_file(yaml_path, rel_path):
    """Sync a single SSOT YAML file to MDDB"""
    payload = convert_yaml_to_mddb(yaml_path, rel_path)
    args = payload["arguments"]

    try:
        # MDDB expects meta values to be string arrays
        meta_arrays = {k: [v] if isinstance(v, str) else v for k, v in args["meta"].items()}
        response = requests.post(
            f"{MDBB_SERVER}/add",
            json={
                "collection": args["collection"],
                "key": args["key"],
                "lang": args["lang"],
                "contentMd": args["content_md"],
                "meta": meta_arrays
            }
        )
        response.raise_for_status()
        return True, args["collection"]
    except Exception as e:
        print(f"❌ Error syncing {rel_path}: {e}")
        return False, args["collection"]

def main():
    # Find all SSOT YAML files
    ssot_files = []
    for root, dirs, files in os.walk(SSOT_DIR):
        for f in files:
            if f.endswith('.yml'):
                rel_path = os.path.relpath(os.path.join(root, f), SSOT_DIR)
                ssot_files.append(rel_path)
    
    total_files = len(ssot_files)
    print(f"📁 Found {total_files} SSOT YAML files to sync")
    
    # Sync files
    success_count = 0
    collection_counts = {}
    
    for rel_path in ssot_files:
        yaml_path = os.path.join(SSOT_DIR, rel_path)
        
        print(f"📄 Syncing: {rel_path}", end=" ... ")
        success, collection = sync_file(yaml_path, rel_path)
        
        if success:
            print(f"✅ ({collection})")
            success_count += 1
            collection_counts[collection] = collection_counts.get(collection, 0) + 1
        else:
            print("❌")
    
    print(f"\n🎉 SSOT sync completed!")
    print(f"📊 Files synced: {success_count}/{total_files}")
    print(f"📁 Collection breakdown:")
    for collection, count in collection_counts.items():
        print(f"   - {collection}: {count}")

if __name__ == "__main__":
    main()