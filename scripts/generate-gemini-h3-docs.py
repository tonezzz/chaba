#!/usr/bin/env python3
"""Generate the chaba.h3 /apps/docs/gemini-models/ data file from the SSOT registry."""

import os
import yaml

SRC = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                   'docs', 'ssot', 'infrastructure', 'ssot.gemini-models.yml')
DST = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                   '..', 'chaba-h3', 'public', 'apps', 'docs', 'gemini-models', 'gemini-models.yml')

FAMILY_ORDER = {f: i for i, f in enumerate([
    'Gemma', 'Gemini 1.5', 'Gemini 2', 'Gemini 2.5', 'Gemini 3',
    'Antigravity', 'Deep Research', 'Embedding', 'Imagen', 'Lyria',
    'Omni', 'Robotics', 'Veo', 'Other'
])}


def main():
    with open(SRC) as f:
        data = yaml.safe_load(f)

    models = []
    for api, m in data['models'].items():
        models.append({
            'api_name': m.get('api_name'),
            'display_name': m.get('display_name'),
            'family': m.get('family'),
            'category': m.get('category'),
            'params': m.get('params'),
            'context_window': m.get('context_window'),
            'free_tier': {k: v for k, v in m.get('free_tier', {}).items()
                          if k in ('rpm', 'tpm', 'rpd', 'status')},
            'status': m.get('status'),
        })

    models.sort(key=lambda m: (
        FAMILY_ORDER.get(m['family'], 99),
        str(m.get('display_name') or m.get('api_name'))
    ))

    out = {
        'title': data.get('title', 'Gemini Models'),
        'last_verified': data['source']['last_verified'],
        'models': models
    }

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, 'w') as f:
        yaml.dump(out, f, default_flow_style=False, sort_keys=False,
                  allow_unicode=True, width=200)

    print(f'Wrote {len(models)} models to {DST}')


if __name__ == '__main__':
    main()
