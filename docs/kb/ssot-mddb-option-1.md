---
category: operations
---

# Option 1: SSOT YAML → MDDB Sync (Recommended)

### Architecture
```
SSOT YAML Files (Direct Edit)
    ↓ (sync mechanism)
MDDB Collections (SSOT Search)
```

### Implementation
- **Sync Script**: Monitor SSOT YAML files, convert to MDDB format
- **Collection**: `ssot-infrastructure`, `ssot-apps`, `ssot-kb`, etc.
- **Metadata**: `source: ssot`, `original_path: rel_path`, `type: yaml`
- **Trigger**: Manual sync or file watcher

### Conversion Strategy
```python
# YAML → MDDB document
def convert_yaml_to_mddb(yaml_path):
    with open(yaml_path) as f:
        yaml_content = f.read()
    
    return {
        "collection": get_ssot_collection(yaml_path),
        "key": yaml_path.replace('/', '-'),
        "content_md": f"# {yaml_path}\n\n```yaml\n{yaml_content}\n```",
        "meta": {
            "title": yaml_path,
            "source": "ssot",
            "original_path": yaml_path,
            "type": "yaml"
        }
    }
```

### Benefits
- ✅ Preserves direct YAML editing workflow
- ✅ Enables semantic search across SSOT
- ✅ YAML remains source of truth
- ✅ Minimal implementation complexity
- ✅ Can sync on-demand or automated

### Challenges
- ⚠️ Requires sync mechanism maintenance
- ⚠️ Potential sync lag (YAML vs MDDB)
- ⚠️ YAML syntax in Markdown may affect search quality
- ⚠️ Need to handle YAML structure in search

### Implementation Complexity: Medium

