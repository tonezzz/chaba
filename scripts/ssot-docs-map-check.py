#!/usr/bin/env python3
"""Check docs/ssot/infrastructure/ssot.docs-map.yml coverage.

Default: structural check — file parses, all 7 named stores present with
required fields, every doc_types entry resolves to a declared store id,
every lookup recipe is non-empty.

--live: additionally probe the network endpoints declared inside the file
(MDDB planes /v1/stats, wiki api.php, WP origin REST root). Read-only;
probe failures are warnings (exit stays 0) since stores can be
tailnet-scoped from some hosts.

Exit 1 on any structural failure.
"""

import re
import sys
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required: pip install pyyaml")

REPO = Path(__file__).resolve().parent.parent
MAP_FILE = REPO / "docs" / "ssot" / "infrastructure" / "ssot.docs-map.yml"

REQUIRED_STORES = {"repo-kb", "repo-ssot", "repo-reports",
                   "gdrive-ada-nest", "mddb", "wiki", "wp"}
REQUIRED_FIELDS = ["owner", "canonical", "content_types", "write_path",
                   "authority", "volatility", "lookup", "notes_gaps"]

LIVE = "--live" in sys.argv
errors, warnings = [], []


def fail(msg):
    errors.append(msg)
    print(f"  FAIL {msg}")


def warn(msg):
    warnings.append(msg)
    print(f"  WARN {msg}")


def ok(msg):
    print(f"  ok   {msg}")


def probe(name, url, timeout=4):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "docs-map-check/1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ok(f"{name}: HTTP {r.status} {url}")
    except Exception as e:
        warn(f"{name}: {url} unreachable ({e.__class__.__name__}: {e})")


def main():
    print(f"checking {MAP_FILE.relative_to(REPO)}")
    try:
        doc = yaml.safe_load(MAP_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        fail(f"YAML parse: {e}")
        return 1
    if not isinstance(doc, dict):
        fail("top level is not a mapping")
        return 1

    stores = doc.get("stores") or []
    ids = {s.get("id") for s in stores if isinstance(s, dict)}

    missing = REQUIRED_STORES - ids
    if missing:
        fail(f"missing stores: {sorted(missing)}")
    else:
        ok(f"all {len(REQUIRED_STORES)} named stores present")

    for s in stores:
        sid = s.get("id", "?")
        for f in REQUIRED_FIELDS:
            if not s.get(f):
                fail(f"store '{sid}': empty/missing field '{f}'")
        lookup = s.get("lookup") or {}
        if isinstance(lookup, dict):
            for k, v in lookup.items():
                if not v:
                    fail(f"store '{sid}': lookup recipe '{k}' is empty")
        else:
            fail(f"store '{sid}': lookup must be a mapping of recipes")

    doc_types = doc.get("doc_types") or {}
    if not doc_types:
        fail("doc_types map missing/empty")
    for dtype, target in doc_types.items():
        first = str(target).split()[0] if target else ""
        if first not in ids:
            fail(f"doc_types '{dtype}' -> '{first}' not a declared store id")
    else:
        ok(f"{len(doc_types)} doc_types all resolve to declared stores")

    if LIVE:
        print("live probes (read-only):")
        for s in stores:
            planes = s.get("planes") or {}
            for pname, p in planes.items():
                ep = (p or {}).get("endpoint", "")
                m = re.match(r"(https?://[^ )]+)", ep)
                if m:
                    probe(f"mddb-{pname}", m.group(1).rstrip("/") + "/v1/stats")
        probe("wiki-api", "https://wiki.h3.gizmo-thailand.com/api.php"
              "?action=query&meta=siteinfo&format=json")
        probe("wp-origin", "https://boards.h3.gizmo-thailand.com/wp/"
              "index.php?rest_route=/")

    print(f"result: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
