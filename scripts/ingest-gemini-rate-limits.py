#!/usr/bin/env python3
"""Bulk-update the Gemini model rate-limits SSOT from a JSON or YAML input.

Input format (JSON or YAML):
  - list of objects, each with at least an `api_name` and `free_tier`.
  - or a dict with a `models` map of the same objects.

Example JSON (free_tier values should be integers):
[
  {
    "api_name": "gemini-2.5-flash",
    "free_tier": {"rpm": 5, "tpm": 250000, "rpd": 20}
  },
  ...
]

Usage:
  python3 scripts/ingest-gemini-rate-limits.py path/to/rate-limits.json

The script updates matching `api_name` entries in:
  docs/ssot/infrastructure/ssot.gemini-models.yml
It also bumps `source.last_verified` to today and records the input file path.
"""

import datetime
import os
import sys

import yaml

SSOT_PATH = 'docs/ssot/infrastructure/ssot.gemini-models.yml'


def main(input_path: str) -> None:
    with open(input_path) as f:
        incoming = yaml.safe_load(f)

    if not incoming:
        raise SystemExit('Input file is empty.')

    if isinstance(incoming, dict) and 'models' in incoming:
        incoming_models = list(incoming['models'].values())
    elif isinstance(incoming, list):
        incoming_models = incoming
    else:
        raise SystemExit(
            'Input must be a list of model objects or a dict with a "models" map.'
        )

    with open(SSOT_PATH) as f:
        data = yaml.safe_load(f)

    today = str(datetime.date.today())
    updated = 0

    for item in incoming_models:
        if not isinstance(item, dict):
            continue
        api = item.get('api_name')
        if not api:
            print(f'Skipping entry without api_name: {item}')
            continue

        if api not in data.get('models', {}):
            print(f'Warning: {api} not found in SSOT; add it first.')
            continue

        target = data['models'][api]

        if 'free_tier' in item:
            target['free_tier'] = item['free_tier']
            target['last_verified'] = today

        for key in ('display_name', 'category', 'status', 'primary_for',
                    'fallback_for', 'notes'):
            if key in item:
                target[key] = item[key]

        updated += 1

    data['source']['last_verified'] = today
    data['source']['input_file'] = os.path.abspath(input_path)

    with open(SSOT_PATH, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False,
                  allow_unicode=True)

    print(f'Updated {updated} entries in {SSOT_PATH}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(
            'Usage: ingest-gemini-rate-limits.py <rate-limits.json|yml>'
        )
    main(sys.argv[1])
