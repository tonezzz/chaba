#!/usr/bin/env python3
"""weekly-digest.py — digest-of-digests rollup -> CMS page digest-weekly.

Snapshots the current rolling digests (personal + infra), the bloat
watch, and the week's host-logs aggregation into one reviewable page in
ada-cms-pages. Runs weekly via systemd timer on tony-omen (Persistent —
fires on next boot if the laptop was off Monday).

  weekly-digest.py             # build + publish
  weekly-digest.py --dry-run   # render, print, don't write
"""

import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

MDDB = "http://100.74.146.0:11023/v1"
COLLECTION = "ada-cms-pages"
SLUG = "digest-weekly"
REVIEW = Path.home() / ".local/share/ada-review"
ADA_SCRIPTS = Path(__file__).resolve().parent
ICT = timezone(timedelta(hours=7))


def post(path: str, body: dict):
    req = urllib.request.Request(f"{MDDB}{path}",
        data=json.dumps(body).encode(), method="POST",
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def read_digest(name: str) -> str:
    p = REVIEW / name
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def run_json(script: str) -> dict | None:
    try:
        r = subprocess.run(
            [sys.executable, str(ADA_SCRIPTS / script), "--json"],
            capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout)
    except Exception:
        return None


def week_logs() -> str:
    """Per-host kind counts over 7d from the hostlogs jsonl."""
    p = REVIEW / "hostlogs-ops.jsonl"
    try:
        rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    except OSError:
        return ""
    out = []
    for r in rows:
        kinds = ", ".join(f"{k} x{c}" for k, c in
                          sorted((r.get("kinds") or {}).items(),
                                 key=lambda kv: -kv[1])[:5])
        sev = f" · {r['severe']} severe ⚠" if r.get("severe") else ""
        out.append(f"- {r['host']}: {r['total']} lines ({kinds}){sev}")
    return "\n".join(out)


def render() -> str:
    today = datetime.now(ICT).strftime("%Y-%m-%d")
    now = datetime.now(ICT).strftime("%H:%M")
    out = [f"# Weekly Digest — week of {today}", "",
           "TL;DR: rolling snapshot of the week's digests — personal, infra, "
           "host-logs and storage bloat in one place.", ""]

    personal = read_digest("personal-digest.md")
    infra = read_digest("infra-digest.md")
    bloat = run_json("bloat-report.py")
    logs = week_logs()

    if bloat:
        out += ["## Storage",
                f"{bloat['docs']:,} docs · {bloat['revisions']:,} revisions "
                f"({bloat['rev_per_doc']}/doc) · {bloat['size_gib']} GiB", ""]
        if bloat.get("churny"):
            out += ["churny: " + ", ".join(
                f"{c['name']} ({c['revs']} revs)" for c in bloat["churny"]), ""]

    if logs:
        out += ["## Host logs (7d view of current digest)", logs, ""]

    if personal:
        out += ["## Personal digest", personal, ""]
    if infra:
        out += ["## Infra digest", infra, ""]

    out += [f"*Updated {now} ICT*", ""]
    return "\n".join(out)


def main() -> int:
    dry = "--dry-run" in sys.argv
    content = render()
    if dry:
        print(content)
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {"format": ["markdown"], "instance": ["tony"], "kind": ["page"],
            "slug": [SLUG], "lang": ["en"],
            "title": [f"Weekly Digest — {datetime.now(ICT):%Y-%m-%d}"],
            "updated": [now]}
    post("/add", {"collection": COLLECTION, "key": SLUG, "lang": "en",
                  "contentMd": content, "meta": meta})
    print("digest-weekly published")
    return 0


if __name__ == "__main__":
    sys.exit(main())
