#!/usr/bin/env python3
"""Warn when a staged ssot yml carries a folded prose block >40 lines.

Split rule (KNB-1101): ssot/*.yml keeps verdict + pointer; research
depth belongs in a lesson / docs/kb. Data rows and short notes are
fine; paragraph-length folded blocks are the smell.
Usage: check-ssot-prose.py [file ...] — exit 0 always (warn-only).
"""
import re, sys

FOLD = re.compile(r"^\s+\w[\w_]*:\s*[>|]-?\n((?:\s{6,}.+\n)+)", re.M)

def count(path: str) -> int:
    try:
        t = open(path).read()
    except OSError:
        return 0
    n = 0
    for m in FOLD.finditer(t):
        if len([l for l in m.group(1).splitlines() if l.strip()]) >= 40:
            n += 1
    return n

for f in sys.argv[1:]:
    n = count(f)
    if n:
        print(f"⚠️  ssot-prose: {f} has {n} folded block(s) >40 lines —\n"
              f"   research depth belongs in a lesson/docs-kb with a "
              f"pointer row here.", file=sys.stderr)
sys.exit(0)
