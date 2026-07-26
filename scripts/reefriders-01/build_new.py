#!/usr/bin/env python3
"""Clean builder for the Reef Riders 01 static mirror."""
import json, re
from pathlib import Path

SRC = Path(__file__).resolve().parent
PAGES = SRC / 'pages'
PARTIALS = SRC / 'partials'
BASE = SRC.parents[1] / 'public' / 'apps' / 'reefriders-01'

LOCAL_PREFIXES = ('wp-content/', 'splide/', 'assets/', 'index.html')
_ATTR_RE = re.compile(
    r'\b(href|src)=(["\']?)('
    + '|'.join(re.escape(p) for p in LOCAL_PREFIXES)
    + r')',
    re.IGNORECASE,
)

def root_for(slug: str) -> str:
    return './' if not slug else '../' * len(Path(slug).parts)

def canonical_for(slug: str, root: str) -> str:
    return root if not slug else root + slug + '/'

def prefix_content(text: str) -> str:
    """Insert {{ROOT}} placeholders before local relative assets in content."""
    return _ATTR_RE.sub(lambda m: m.group(1) + '=' + m.group(2) + '{{ROOT}}' + m.group(3), text)

def build():
    header = (PARTIALS / 'header.html').read_text(encoding='utf-8')
    footer = (PARTIALS / 'footer.html').read_text(encoding='utf-8')
    BASE.mkdir(parents=True, exist_ok=True)

    for page_dir in sorted(PAGES.iterdir()):
        if not page_dir.is_dir():
            continue
        slug = '' if page_dir.name == 'home' else page_dir.name
        meta = json.loads((page_dir / 'meta.json').read_text(encoding='utf-8'))
        content = (page_dir / 'content.html').read_text(encoding='utf-8')
        content = prefix_content(content)
        root = root_for(slug)
        canonical = canonical_for(slug, root)

        out = header + content + footer
        out = out.replace('{{TITLE}}', meta['title'])
        out = out.replace('{{DESCRIPTION}}', meta['description'])
        out = out.replace('{{CANONICAL}}', canonical)
        out = out.replace('{{ROOT}}', root)

        outdir = BASE if not slug else BASE / slug
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / 'index.html').write_text(out, encoding='utf-8')
        print('built', slug or '/')

if __name__ == '__main__':
    build()
