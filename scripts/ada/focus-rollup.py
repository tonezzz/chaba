#!/usr/bin/env python3
"""L2 focus rollup: group per-session reports into per-thread digests.

Consumes reports/*.json produced by session-report.py and emits:

  focus-index.json  {canonical_tag: [report files]} — rollup bookkeeping
  focus-digest.md   '## focus: <tag>' blocks in rolling-log format, so the
                    digest can be injected via the same session-log source
                    kind as session-memory.md (render-memory.py)

Tags are emergent (model-suggested per session), so near-duplicates are
merged via a small alias map plus --alias a=b for ad-hoc merges. This is
a mechanical pass — no LLM — so it is cheap to run after every batch.

Usage:
  focus-rollup.py [--reports DIR] [--out DIR] [--alias rika-weather-station=weather-station]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_REPORTS = Path.home() / ".local/share/ada-review/reports"

# Known same-thread aliases discovered on the first 30-report batch.
# Canonical form is the RIGHT-hand side; extend as new near-dups appear.
ALIASES = {
    # the Rika RK600/RK900 station at Noble Park
    "rika-weather-station": "weather-station",
    "rika-weather": "weather-station",
    "rika-rk600": "weather-station",
    "weather": "weather-station",
    "weather-sensor": "weather-station",
    # the Nobito PM2.5 air-quality monitor
    "nobito-pm2-5": "air-quality",
    "nobito-monitor": "air-quality",
    "pm2-5": "air-quality",
    # person/contact records
    "person-profiles": "person-records",
    "personal-records": "person-records",
    "contact-records": "person-records",
    "personal-contacts": "person-records",
    # ada platform work
    "ada": "ada-dev",
    "ada-development": "ada-dev",
    "speaker-recognition": "speaker-id",
    "speaker-enrollment": "speaker-id",
    # ha
    "ha": "home-assistant",
    "home-assistant-logs": "home-assistant",
    # memory system
    "memory": "memory-bank",
    "memory-banks": "memory-bank",
    "memory-inspection": "memory-bank",
    "memory-management": "memory-bank",
    "memory-search": "memory-bank",
}


def slug(tag: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(tag).strip().lower()).strip("-")
    return s or "misc"


def load_reports(d: Path) -> list[dict]:
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"warn: {p.name}: {e}", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    ap.add_argument("--out", type=Path, default=None,
                    help="output dir (default <reports>/..)")
    ap.add_argument("--alias", action="append", default=[],
                    help="extra tag merge, form raw=canonical (repeatable)")
    ap.add_argument("--max-loops", type=int, default=3,
                    help="open loops kept per focus block")
    args = ap.parse_args()

    aliases = dict(ALIASES)
    for a in args.alias:
        if "=" in a:
            k, v = a.split("=", 1)
            aliases[slug(k)] = slug(v)

    reports = load_reports(args.reports.expanduser())
    if not reports:
        print(f"no reports in {args.reports}", file=sys.stderr)
        return 1

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in reports:
        tags = [aliases.get(slug(t), slug(t)) for t in r.get("focus", [])]
        for t in set(tags) or {"misc"}:
            groups[t].append(r)

    outdir = (args.out or args.reports.parent).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    index = {t: [r["file"] for r in rs] for t, rs in sorted(groups.items())}
    (outdir / "focus-index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    blocks = []
    for tag, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        rs = sorted(rs, key=lambda r: r.get("date", ""))
        first, last = rs[0].get("date", "?"), rs[-1].get("date", "?")
        dates = first if first == last else f"{first} → {last}"

        loops: list[str] = []
        for r in reversed(rs):  # newest loops first, dedup by lowercase
            for lp in r.get("open_loops", []) or []:
                s = str(lp).strip()
                if s and s.lower() not in {x.lower() for x in loops}:
                    loops.append(s)

        people = sorted({str(p) for r in rs for p in r.get("people", [])})
        actions = sum(len(r.get("actions_taken", []) or []) for r in rs)

        lines = [f"## focus: {tag}",
                 f"{len(rs)} session(s), {dates}; {actions} action(s) done."]
        if people:
            lines.append("people: " + ", ".join(people[:8]))
        if loops:
            lines.append("open:")
            lines.extend(f"- {l}" for l in loops[: args.max_loops])
            if len(loops) > args.max_loops:
                lines.append(f"- …({len(loops) - args.max_loops} more)")
        blocks.append("\n".join(lines))

    digest = "\n\n".join(blocks) + "\n"
    (outdir / "focus-digest.md").write_text(digest, encoding="utf-8")
    print(f"{len(reports)} reports -> {len(groups)} focus threads")
    print(f"wrote {outdir / 'focus-index.json'}")
    print(f"wrote {outdir / 'focus-digest.md'}")
    for tag, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"  {tag}: {len(rs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
