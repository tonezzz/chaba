#!/usr/bin/env python3
"""Lesson drift check — flag lessons whose source docs changed after the
lesson was last written (card lesson-drift-check-...-dd7ed2, OPS-0794).

Reads the docs-mcp index (the same lastModified the docs-trade MCP serves
via get_page) plus real file mtimes under docs_root, compares each covered
page against its WP lesson's `modified` (via board-api /lesson op:list —
the job host holds no WP creds), and files ONE deduplicated focus-inbox
entry via board-api /inbox when the stale set changes.

Flag-only by design — the card's decision point: auto-regen writes worse
prose than a session that actually re-learned the material, so this job
only flags; a dispatch/session does the rewrite.

Runs under the job dispatcher (ssot.jobs.yml `lesson-drift-check`,
every: 1d, host tony_dell where ~/CascadeProjects/trade lives).

Usage:
  lesson-drift-check.py [--dry-run] [--json] [--grace-hours N]
                        [--map FILE] [--state FILE]
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MAP = SCRIPT_DIR / "lesson-drift-map.yml"
DEFAULT_STATE = Path("~/var/chaba/jobs/lesson-drift-check.json")

sys.path.insert(0, str(SCRIPT_DIR / "board"))
try:
    import dispatch_repos as dr
    API = dr.board_api_base()
except Exception:
    API = "https://idc03.taila0626a.ts.net:10000"


def api(path: str, body: dict) -> dict:
    body = {**body, "from": "devin"}
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def parse_ts(s: str):
    """ISO timestamp -> epoch. Naive treated as UTC (see grace note)."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def doc_mtime(page: str, index: dict, docs_root: Path):
    """Newest known mtime for a docs-mcp page: index lastModified, or the
    real file's mtime if newer (the index can lag live edits)."""
    best = None
    ent = index.get(page)
    if ent:
        best = parse_ts(ent.get("lastModified"))
    cand = docs_root / f"{page}.md"
    if not cand.exists() and cand.parent.is_dir():
        low = f"{page.rsplit('/', 1)[-1]}.md".lower()
        for f in cand.parent.iterdir():
            if f.name.lower() == low:
                cand = f
                break
    if cand.exists():
        fm = cand.stat().st_mtime
        best = fm if best is None else max(best, fm)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default=str(DEFAULT_MAP))
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--grace-hours", type=float, default=8.0,
                    help="doc must be this much newer than the lesson to "
                         "flag (covers WP site-tz vs UTC slop; default 8)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report only — no inbox write, no state update")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()

    cfg = yaml.safe_load(Path(a.map).read_text())
    docs_root = Path(os.path.expanduser(cfg["docs_root"]))
    index_path = Path(os.path.expanduser(cfg["index_json"]))
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    lessons_cfg = cfg.get("lessons") or {}
    grace_s = a.grace_hours * 3600

    listed = api("/lesson", {"op": "list"}).get("lessons") or []
    by_slug = {l["slug"]: l for l in listed}

    findings, missing_pages, missing_lessons = {}, [], []
    for slug, spec in lessons_cfg.items():
        les = by_slug.get(slug)
        if not les:
            missing_lessons.append(slug)
            continue
        lmod = parse_ts(les.get("modified"))
        stale = []
        for page in spec.get("pages") or []:
            mt = doc_mtime(page, index, docs_root)
            if mt is None:
                missing_pages.append(page)
            elif lmod is not None and mt > lmod + grace_s:
                stale.append({
                    "page": page,
                    "doc_modified": datetime.fromtimestamp(
                        mt, timezone.utc).isoformat(timespec="seconds"),
                    "newer_by_h": round((mt - lmod) / 3600, 1)})
        if stale:
            findings[slug] = {"topic": les.get("topic"),
                              "lesson_modified": les.get("modified"),
                              "stale_pages": stale}

    # family coverage check: a family-prefixed lesson with no map entry
    # means the hub's inventory (and this map) is out of date.
    prefix = cfg.get("family_prefix") or ""
    extra = sorted(l.get("topic") for l in listed
                   if (l.get("topic") or "").startswith(prefix)
                   and l["slug"] not in lessons_cfg)
    hub = cfg.get("hub_slug")

    stale_keys = sorted(f"{s}:{p['page']}:{p['doc_modified']}"
                        for s, f in findings.items() for p in f["stale_pages"])
    stale_keys += [f"extra:{t}" for t in extra]
    stale_keys += [f"missing-lesson:{s}" for s in missing_lessons]
    fp = hashlib.sha1("|".join(stale_keys).encode()).hexdigest()

    report = {"checked_lessons": len(lessons_cfg),
              "stale_lessons": len(findings), "findings": findings,
              "extra_family_topics": extra,
              "missing_pages": missing_pages,
              "missing_lessons": missing_lessons,
              "fingerprint": fp}
    print(json.dumps(report, indent=1) if a.as_json
          else f"{len(findings)} stale lesson(s), {len(extra)} unmapped "
               f"family topic(s), {len(missing_pages)} missing page(s)")
    if not a.as_json:
        for slug, f in findings.items():
            print(f"  STALE {f['topic']} ({slug}) lesson {f['lesson_modified']}")
            for p in f["stale_pages"]:
                print(f"      {p['page']}  doc {p['doc_modified']} "
                      f"+{p['newer_by_h']}h")
        for t in extra:
            print(f"  UNMAPPED family topic: {t} -> hub {hub} out of date")
        for p in missing_pages:
            print(f"  MISSING page: {p}")

    state_path = Path(os.path.expanduser(a.state))
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except Exception:
            state = {}
    changed = fp != state.get("fingerprint")
    if a.dry_run:
        print("dry-run: no inbox write, no state update"
              + (" (fingerprint unchanged)" if not changed else ""))
        return 0

    if changed and (findings or extra or missing_lessons):
        lines = [f"Lesson drift check {datetime.now().date().isoformat()} "
                 f"— {len(findings)} trade lesson(s) summarize docs that "
                 f"changed after the lesson was written:", ""]
        for slug, f in findings.items():
            lines.append(f"• {f['topic']} ({slug}, lesson modified "
                         f"{f['lesson_modified']}):")
            for p in f["stale_pages"]:
                lines.append(f"    – {p['page']} — doc {p['doc_modified']}"
                             f" (+{p['newer_by_h']}h)")
        for t in extra:
            lines.append(f"• unmapped family topic '{t}' — the trade-map "
                         f"hub inventory and scripts/lesson-drift-map.yml "
                         f"need a new entry")
        for s in missing_lessons:
            lines.append(f"• mapped lesson {s} not found in WP — map or "
                         f"lesson needs fixing")
        lines += ["", "Flag-only per OPS-0794: re-learn the topic in a "
                  "session and re-file via /lesson (same slug upserts); "
                  "this job does not rewrite prose.",
                  f"fingerprint {fp[:10]}"]
        r = api("/inbox", {
            "label": f"lesson-drift: {len(findings)} stale trade lesson(s)",
            "text": "\n".join(lines)[:4000],
            "priority": "medium",
            "tags": ["education", "lessons", "drift", "trade"],
            "session": "lesson-drift-check"})
        print("inbox:", r.get("message"))
    elif not (findings or extra or missing_lessons):
        print("drift resolved since last run — nothing filed"
              if changed and state.get("fingerprint")
              else "no drift — nothing filed")

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "fingerprint": fp,
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stale_lessons": len(findings)}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as e:
        print(f"lesson-drift-check: board-api unreachable: {e}",
              file=sys.stderr)
        sys.exit(1)
