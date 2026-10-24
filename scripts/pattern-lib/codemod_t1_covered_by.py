#!/usr/bin/env python3
"""Codemod: t1 covered_by rule (pattern: pat-elevated-geom-covered-by).

Applies the deterministic transform: any STRtree point-query used to decide
whether elevated geometry COVERS a cell must use predicate="covered_by"
(not "within"), so boundary-touching covered cells count as covered.
Reference in repo: builder.py line ~480 already uses covered_by for sea poly.

Usage: python3 codemod-t1-covered-by.py <repo_path>
"""
import re
import sys
from pathlib import Path

# Only touch the elevated-geometry coverage check, not other predicates.
TARGET = re.compile(
    r'STRtree\(elevated_geoms\)\.query\(pts, predicate="within"\)'
)
REPL = 'STRtree(elevated_geoms).query(pts, predicate="covered_by")'


def main() -> int:
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    target = repo / "terrology" / "builder.py"
    if not target.exists():
        print(f"ERR: {target} not found")
        return 1
    src = target.read_text()
    if "elevated_geoms" not in src:
        print("SKIP: no elevated_geoms section (wrong repo?)")
        return 2
    new, n = TARGET.subn(REPL, src)
    if n == 0:
        print("SKIP: pattern already applied or absent (count=0)")
        return 0
    target.write_text(new)
    print(f"PATCHED {n} occurrence(s): within -> covered_by (elevated_geoms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())