#!/usr/bin/env python3
"""Add PWA manifest + meta tags to every /apps/<app>/index.html listed in apps.yml."""
import json
import os
import re
import yaml

BASE = '/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/public/apps'
SW_SNIPPET = '''\n<script>
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/apps/sw.js', { scope: '/apps/' })
      .then((r) => console.log('SW registered', r.scope))
      .catch((e) => console.error('SW registration failed', e));
  }
</script>\n'''


def make_manifest(app):
    href = app.get('href', '')
    if not href.endswith('/'):
        href += '/'
    name = app.get('title') or app.get('id')
    short = name[:12] if len(name) > 12 else name
    return {
        'name': name,
        'short_name': short,
        'description': app.get('description') or f'{name} on tony-dell',
        'start_url': href,
        'scope': href,
        'id': href,
        'display': 'standalone',
        'background_color': '#16213e',
        'theme_color': '#1a1a2e',
        'orientation': 'portrait',
        'icons': [
            {'src': '/apps/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any maskable'},
            {'src': '/apps/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'},
        ],
        'categories': ['utilities', 'productivity']
    }


def inject_head(html, title):
    if re.search(r'rel=["\']manifest["\']', html):
        return html
    head_inject = f'''\n  <meta name="theme-color" content="#1a1a2e">
  <meta name="background-color" content="#16213e">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="{title}">
  <link rel="manifest" href="manifest.json">
  <link rel="icon" href="/apps/favicon.ico" sizes="any">
  <link rel="apple-touch-icon" href="/apps/apple-touch-icon.png">\n'''
    return re.sub(r'(<head[^>]*>)', r'\1' + head_inject, html, count=1, flags=re.I)


def inject_body(html):
    if 'serviceWorker.register' in html:
        return html
    if re.search(r'</body>', html, flags=re.I):
        return re.sub(r'(</body>)', SW_SNIPPET + r'\1', html, count=1, flags=re.I)
    if re.search(r'</html>', html, flags=re.I):
        return re.sub(r'(</html>)', SW_SNIPPET + r'\1', html, count=1, flags=re.I)
    return html + SW_SNIPPET


def process_app(app, index_path=None):
    href = app.get('href', '')
    if not href.startswith('/apps/'):
        return
    folder = href[len('/apps/'):].rstrip('/')
    folder_path = os.path.join(BASE, folder)
    if index_path is None:
        index_path = os.path.join(folder_path, 'index.html')
    if not os.path.isfile(index_path):
        print(f"skip {app.get('id')}: {index_path} not found")
        return

    manifest = make_manifest(app)
    manifest_path = os.path.join(folder_path, 'manifest.json')
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    with open(index_path) as f:
        html = f.read()
    html = inject_head(html, manifest['name'])
    html = inject_body(html)
    with open(index_path, 'w') as f:
        f.write(html)
    print(f"updated {app.get('id')}: {index_path} and {manifest_path}")


if __name__ == '__main__':
    apps_yml = os.path.join(BASE, 'apps.yml')
    with open(apps_yml) as f:
        data = yaml.safe_load(f)

    for app in data.get('apps', []):
        process_app(app)
