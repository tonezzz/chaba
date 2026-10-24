#!/usr/bin/env python3
"""lesson-polish pack run — deterministic audit + report (nest-style).

Runs on any worker (dell/colab). Calls board-api /lesson read door,
applies the policy rules, writes an audit report to Drive out/.
The agent polish pass (Fable, post-OR-reset) is a second pack.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime

API = os.environ.get("LESSON_API", "https://idc03.taila0626a.ts.net:10000/lesson")
TODAY = date.today().isoformat()
OUT = os.environ.get("LESSON_OUT", "out")
os.makedirs(OUT, exist_ok=True)


def api(body: dict) -> dict:
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())


def audit_one(slug, topic, level, nxt, content):
    flags = []
    if level not in ("intro", "working", "deep"):
        flags.append("R1:level-invalid")
    if not nxt:
        flags.append("R1:no-next-review")
    elif nxt < TODAY:
        flags.append("R1:overdue")
    body_len = len(re.sub(r"<[^>]+>", "", content or "").strip())
    if body_len < 500:
        flags.append(f"R2:thin({body_len}ch)")
    if re.search(r"verdict|decision|winner|recommend", content or "", re.I) and \
       not re.search(r"devin-kb|SSOT|ai-workforce-eval|docs/tools", content or ""):
        flags.append("R3:no-pointer")
    if any(topic.lower().startswith(p) for p in ("ai-", "ada-nest-", "voice-")) and \
       not re.search(r"hub|family|related:|companion", content or "", re.I):
        flags.append("R4:orphan")
    if not re.search(r"[\u0e00-\u0e7f]", content or ""):
        flags.append("R5:consider-thai")
    return {"slug": slug, "topic": topic, "level": level, "next_review": nxt,
            "flags": flags, "body_chars": body_len}


def main():
    d = api({"op": "list"})
    rows = []
    for l in d.get("lessons", []):
        try:
            g = api({"op": "get", "slug": l["slug"]})
            content = g.get("content", "")
        except Exception:
            content = ""
        rows.append(audit_one(l["slug"], l.get("topic", ""), l.get("level", ""),
                              l.get("next_review", ""), content))
    flagged = [r for r in rows if r["flags"]]
    counts = {}
    for r in flagged:
        for f in r["flags"]:
            counts[f] = counts.get(f, 0) + 1
    report = {"generated": datetime.now(timezone_utc()).isoformat(),
              "total": len(rows), "flagged": len(flagged),
              "flag_counts": counts, "flagged_rows": flagged}
    path = os.path.join(OUT, f"lesson-audit-{TODAY}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print(f"audit: {len(rows)} lessons, {len(flagged)} flagged -> {path}")
    print(json.dumps(counts, indent=1))
    return 0


def timezone_utc():
    import datetime as dt
    return dt.timezone.utc


if __name__ == "__main__":
    sys.exit(main())