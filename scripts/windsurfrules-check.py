#!/usr/bin/env python3
"""Validate and optionally fix .windsurfrules Documentation Search Standards across workspaces."""

import argparse
import re
import sys
from pathlib import Path

BASE = Path('/home/tony/CascadeProjects')
CANONICAL_WS = 'chaba'
TARGETS = ['chaba-h3', 'chaba-kbman', 'chaba-omen', 'chaba-raceman', 'chaba-yomi']
SECTION = 'Documentation Search Standards'


def split_by_headings(text):
    return re.split(r'\n(?=## )', text)


def get_section(parts, title):
    for i, part in enumerate(parts):
        if part.startswith(f'## {title}'):
            return i, part
    return None, None


def main():
    parser = argparse.ArgumentParser(description='Check/fix .windsurfrules shared sections')
    parser.add_argument('--fix', action='store_true', help='Apply fixes')
    args = parser.parse_args()

    canonical_path = BASE / CANONICAL_WS / '.windsurfrules'
    canonical = canonical_path.read_text()
    c_parts = split_by_headings(canonical)
    c_idx, c_section = get_section(c_parts, SECTION)
    if c_idx is None:
        print(f'Section {SECTION!r} not found in canonical {canonical_path}', file=sys.stderr)
        sys.exit(1)

    drift = False
    for ws in TARGETS:
        path = BASE / ws / '.windsurfrules'
        text = path.read_text()
        parts = split_by_headings(text)
        sec_idx, _ = get_section(parts, SECTION)

        if sec_idx is not None:
            current = parts[sec_idx]
            if current == c_section:
                print(f'{ws}: OK')
                continue
            drift = True
            if args.fix:
                parts[sec_idx] = c_section
                path.write_text('\n'.join(parts))
                print(f'{ws}: fixed')
            else:
                print(f'{ws}: DRIFT')
        else:
            drift = True
            if args.fix:
                host_idx = None
                for i, part in enumerate(parts):
                    if part.startswith('## Hostname Usage Standards'):
                        host_idx = i
                        break
                if host_idx is not None:
                    parts.insert(host_idx + 1, c_section)
                else:
                    parts.append(c_section)
                path.write_text('\n'.join(parts))
                print(f'{ws}: added')
            else:
                print(f'{ws}: MISSING')

    sys.exit(1 if drift and not args.fix else 0)


if __name__ == '__main__':
    main()
