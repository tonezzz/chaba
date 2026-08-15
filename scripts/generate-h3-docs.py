#!/usr/bin/env python3
"""Generate chaba-h3 docs site artifacts from the docs SSOT."""

import os
import subprocess
from pathlib import Path

import yaml

REPO = Path('/home/tony/CascadeProjects/chaba')
H3 = Path('/home/tony/CascadeProjects/chaba-h3')
SSOT = REPO / 'docs' / 'ssot' / 'apps' / 'ssot.apps.docs.yml'
DOCS_YML = H3 / 'public' / 'apps' / 'docs' / 'docs.yml'
APPS_YML = H3 / 'public' / 'apps' / 'apps.yml'


def main():
    with open(SSOT) as f:
        data = yaml.safe_load(f)

    # Write docs.yml for the docs portal
    pages = []
    for p in data.get('pages', []):
        pages.append({
            'id': p['id'],
            'title': p['title'],
            'description': p.get('description', ''),
            'icon': p.get('icon', ''),
            'href': p['href'],
        })

    out = {
        'title': data.get('title', 'Docs'),
        'nav': data.get('nav', []),
        'pages': pages,
    }

    DOCS_YML.parent.mkdir(parents=True, exist_ok=True)
    with open(DOCS_YML, 'w') as f:
        yaml.dump(out, f, default_flow_style=False, sort_keys=False,
                  allow_unicode=True, width=200)
    print(f'Wrote {DOCS_YML}')

    # Sync the docs app card in apps.yml
    if APPS_YML.exists():
        with open(APPS_YML) as f:
            apps = yaml.safe_load(f)
    else:
        apps = {}

    app = data.get('app', {})
    docs_id = app.get('id', 'docs')
    new_entry = {
        'id': docs_id,
        'title': app.get('title', data.get('title', 'Docs')),
        'description': app.get('description', data.get('subtitle', '')),
        'icon': app.get('icon', data.get('icon', '')),
        'href': app.get('href', '/apps/docs/'),
    }

    apps_list = apps.setdefault('apps', [])
    idx = next((i for i, a in enumerate(apps_list) if a.get('id') == docs_id), None)
    if idx is not None:
        apps_list[idx] = new_entry
    else:
        apps_list.append(new_entry)

    with open(APPS_YML, 'w') as f:
        yaml.dump(apps, f, default_flow_style=False, sort_keys=False,
                  allow_unicode=True, width=200)
    print(f'Updated docs entry in {APPS_YML}')

    # Run per-page generators
    for p in data.get('pages', []):
        gen = p.get('generator')
        if not gen:
            continue
        gen_path = (REPO / gen).resolve()
        if gen_path.exists():
            print(f'Running generator for {p["id"]}: {gen_path}')
            result = subprocess.run(['python3', str(gen_path)], cwd=REPO)
            if result.returncode != 0:
                raise SystemExit(f'Generator failed for {p["id"]}: {gen}')
        else:
            print(f'Warning: generator not found for {p["id"]}: {gen_path}')


if __name__ == '__main__':
    main()
