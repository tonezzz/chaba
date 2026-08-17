#!/usr/bin/env bash
# promote-feature.sh
# Promote an SSOT feature overlay into a target SSOT YAML.
# Usage: promote-feature.sh <feature.yml> <target.yml>
set -euo pipefail

FEATURE="$1"
TARGET="$2"

if [[ ! -f "$FEATURE" ]]; then
    echo "Feature file not found: $FEATURE" >&2
    exit 1
fi
if [[ ! -f "$TARGET" ]]; then
    echo "Target file not found: $TARGET" >&2
    exit 1
fi

FEATURE_ABS="$(cd "$(dirname "$FEATURE")" && pwd)/$(basename "$FEATURE")"
TARGET_ABS="$(cd "$(dirname "$TARGET")" && pwd)/$(basename "$TARGET")"

cd "$(dirname "$0")/.."

python3 - "$FEATURE_ABS" "$TARGET_ABS" <<'PY'
import yaml
import sys
import os
import shutil
import datetime

METADATA_KEYS = {
    'title', 'subtitle', 'status', 'promote_to', 'preview_target',
    'description', 'toggles', 'promotion_checklist', 'ref', 'icon',
    'preview_page', 'feature'
}

def load_and_validate(path):
    with open(path, 'r') as f:
        content = f.read()
    if not content.strip():
        raise ValueError(f'{path} is empty')
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f'YAML syntax error in {path}: {e}')
    if data is None:
        raise ValueError(f'{path} contains no YAML document')
    return data

def strip_refs(obj):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: strip_refs(v) for k, v in obj.items() if k != 'ref'}
    if isinstance(obj, list):
        return [strip_refs(v) for v in obj]
    return obj

def deep_merge(base, overlay):
    if not isinstance(overlay, dict):
        return overlay
    if not isinstance(base, dict):
        base = {}
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def strip_feature_metadata(doc):
    return {k: strip_refs(v) for k, v in doc.items() if k not in METADATA_KEYS}

def main():
    feature_path = sys.argv[1]
    target_path = sys.argv[2]

    feature_doc = load_and_validate(feature_path)
    target_doc = load_and_validate(target_path)

    overlay = strip_feature_metadata(feature_doc)
    merged = deep_merge(target_doc, overlay)

    backup = f"{target_path}.bak.{int(datetime.datetime.now().timestamp())}.yml"
    shutil.copy2(target_path, backup)

    with open(target_path, 'w') as f:
        yaml.safe_dump(merged, f, default_flow_style=False, sort_keys=False)

    feature_doc['status'] = 'promoted'
    feature_doc['promoted_at'] = datetime.datetime.now().isoformat()
    feature_doc['promoted_to'] = os.path.basename(target_path)

    with open(feature_path, 'w') as f:
        yaml.safe_dump(feature_doc, f, default_flow_style=False, sort_keys=False)

    print(f"Promoted overlay from {feature_path} into {target_path}")
    print(f"Backed up target to {backup}")

if __name__ == '__main__':
    main()
PY
