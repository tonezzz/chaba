#!/usr/bin/env python3
"""Sync SSOT YAML files to MDDB for semantic search"""
import os
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yaml
from pathlib import Path


SSOT_DIR = os.environ.get("SSOT_DIR", str(Path(__file__).resolve().parent.parent / "docs" / "ssot"))
MDBB_SERVER = os.environ.get("MDDB_BASE", "http://100.74.146.0:11023") + "/v1"

# Reusable session with retries to survive transient connection drops
_mddb_session = requests.Session()
retry_strategy = Retry(
    total=5,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
)
_mddb_session.mount("http://", HTTPAdapter(max_retries=retry_strategy))
_mddb_session.mount("https://", HTTPAdapter(max_retries=retry_strategy))

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
                "collection": collection
            }
        }
    }

def _flatten_values(data, prefix=""):
    rows = []
    if isinstance(data, dict):
        for k, v in data.items():
            new_prefix = f"{prefix}.{k}" if prefix else str(k)
            rows.extend(_flatten_values(v, new_prefix))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            rows.extend(_flatten_values(v, f"{prefix}[{i}]"))
    else:
        rows.append(f"{prefix}: {data}")
    return rows


def build_glossary_document(values_path):
    """Build a natural-language glossary document from ssot.values.yml"""
    with open(values_path, 'r') as f:
        yaml_content = f.read()
    values = yaml.safe_load(yaml_content) or {}

    # Turn values into natural-language statements for semantic search
    statements = _flatten_values(values)
    glossary_lines = []
    for s in statements:
        # e.g. hosts.tony_dell.tailscale_ip: 100.68.142.13
        key, _, value = s.partition(": ")
        parts = key.split(".")
        if len(parts) >= 2:
            category = parts[0]
            dotted = ".".join(parts[1:])
            glossary_lines.append(
                f"- The SSOT value for **{dotted}** in category **{category}** is **{value}**. "
                f"(key: `{key}`)"
            )
        else:
            glossary_lines.append(f"- The SSOT value for **{key}** is **{value}**.")

    content_md = f"""# SSOT Values Glossary

This document contains canonical values from `ssot.values.yml` expressed in plain English for semantic search.

## Canonical values

{chr(10).join(glossary_lines)}
"""

    return {
        "collection": "chaba-glossary",
        "key": "ssot-values-glossary",
        "lang": "en",
        "contentMd": content_md,
        "meta": {
            "title": ["SSOT Values Glossary"],
            "source": ["ssot"],
            "original_path": ["docs/ssot/infrastructure/ssot.values.yml"],
            "type": ["glossary"],
            "collection": ["chaba-glossary"],
        }
    }


def sync_file(yaml_path, rel_path):
    """Sync a single SSOT YAML file to MDDB"""
    payload = convert_yaml_to_mddb(yaml_path, rel_path)
    args = payload["arguments"]

    try:
        # MDDB expects meta values to be string arrays
        meta_arrays = {k: [v] if isinstance(v, str) else v for k, v in args["meta"].items()}
        response = _mddb_session.post(
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

    # Sync natural-language glossary for ssot.values.yml
    values_path = os.path.join(SSOT_DIR, "infrastructure", "ssot.values.yml")
    print(f"📄 Syncing: SSOT glossary", end=" ... ")
    glossary_doc = build_glossary_document(values_path)
    try:
        response = _mddb_session.post(
            f"{MDBB_SERVER}/add",
            json=glossary_doc
        )
        response.raise_for_status()
        print(f"✅ ({glossary_doc['collection']})")
        collection_counts[glossary_doc['collection']] = collection_counts.get(glossary_doc['collection'], 0) + 1
        success_count += 1
    except Exception as e:
        print(f"❌ {e}")

    print(f"\n🎉 SSOT sync completed!")
    print(f"📊 Files synced: {success_count}/{total_files}")
    print(f"📁 Collection breakdown:")
    for collection, count in collection_counts.items():
        print(f"   - {collection}: {count}")

if __name__ == "__main__":
    main()