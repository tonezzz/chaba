#!/usr/bin/env python3
"""bloat-report.py — MDDB growth snapshot for the refresh digest.

One compact block: totals (docs, revisions, db size, rev/doc ratio) and
the worst churn offenders so regrowth is visible weekly instead of
discovered during an outage. MDDB-down tolerant — prints an empty block.

  bloat-report.py            # print the digest block
  bloat-report.py --json     # machine-readable
"""

import json
import sys
import urllib.request

MDDB = "http://100.74.146.0:11023/v1"
# rev/doc above this is "churny" even after caps — worth a look
WARN_RATIO = 25


def fetch_stats() -> dict | None:
    try:
        with urllib.request.urlopen(f"{MDDB}/stats", timeout=15) as r:
            return json.loads(r.read())
    except Exception:
        return None


def main() -> int:
    stats = fetch_stats()
    if stats is None:
        print("## mddb-bloat\n(mddb unreachable)")
        return 0

    cols = stats["collections"]
    docs = sum(c["documentCount"] for c in cols)
    revs = sum(c.get("revisionCount", 0) for c in cols)
    size = stats.get("databaseSizeBytes", 0)
    ratio = revs / docs if docs else 0
    gib = size / (1024 ** 3)

    worst = sorted(
        (c for c in cols if c["documentCount"] and
         c.get("revisionCount", 0) / c["documentCount"] > WARN_RATIO),
        key=lambda c: -c["revisionCount"] / c["documentCount"])[:8]

    if "--json" in sys.argv:
        print(json.dumps({"docs": docs, "revisions": revs,
                          "size_gib": round(gib, 3),
                          "rev_per_doc": round(ratio, 1),
                          "churny": [
                              {"name": c["name"],
                               "docs": c["documentCount"],
                               "revs": c["revisionCount"]}
                              for c in worst]}, indent=1))
        return 0

    lines = [f"## mddb-bloat",
             f"{docs:,} docs · {revs:,} revisions ({ratio:.1f}/doc) · {gib:.2f} GiB"]
    if worst:
        lines.append("churny:")
        for c in worst:
            r = c["revisionCount"] / c["documentCount"]
            lines.append(f"  {c['name']}: {r:.0f} rev/doc "
                         f"({c['documentCount']} docs)")
    else:
        lines.append("no collection above churn threshold")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
