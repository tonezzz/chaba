#!/usr/bin/env python3
"""Push a pattern record to the mddb code-patterns collection (P1 store).

Upsert via POST /v1/add (same semantics as MCP add_document). Refuses to
push a record whose meta.commit is in the leak guard's banned set for its
repo — benchmark-task fixes never enter the store.

Record format (jsonl line or --fields):
  {key, repo, commit, class, trigger, transform, lang, evidence?}

Usage:
  python3 push_pattern.py --record pattern.jsonl [--guard leak-guard.json] [--dry-run]
  python3 push_pattern.py --key pat-foo --repo x --commit abc1234 \
      --class api/http --trigger "..." --transform "..." --lang go
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

MDDB = "http://100.102.134.91:11023/v1"  # mddb leader on idc03
COLLECTION = "code-patterns"

CONTENT_TMPL = """# {repo} {commit}: {title}

## Trigger
{trigger}

## Class
{cls}

## Transform
{transform}

## Lang
{lang} — {repo} @ {commit}{evidence}
"""


def to_document(rec: dict) -> dict:
    ev = f" ({rec['evidence']})" if rec.get("evidence") else ""
    return {
        "collection": COLLECTION,
        "key": rec["key"],
        "lang": "en",
        "content_md": CONTENT_TMPL.format(
            repo=rec["repo"], commit=rec["commit"],
            title=rec.get("title") or rec["trigger"][:80],
            trigger=rec["trigger"], cls=rec["class"],
            transform=rec["transform"], lang=rec.get("lang", "?"),
            evidence=ev),
        "meta": {
            "repo": rec["repo"], "commit": rec["commit"],
            "class": rec["class"], "trigger": rec["trigger"],
            "lang": rec.get("lang", "?"),
            **({"bench_task": rec["bench_task"]} if rec.get("bench_task") else {}),
        },
    }


def banned(rec: dict, guard_path: Path) -> bool:
    if not guard_path or not guard_path.exists():
        return False
    g = json.loads(guard_path.read_text())
    c = str(rec.get("commit", ""))
    if not c:
        return False
    return any(b.startswith(c) or c.startswith(b)
               for b in g.get("banned", {}).get(rec.get("repo", ""), []))


def push(doc: dict, mddb: str = MDDB) -> dict:
    body = json.dumps(doc).encode()
    req = urllib.request.Request(f"{mddb}/add", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", type=Path, help="jsonl file of records")
    ap.add_argument("--guard", type=Path)
    ap.add_argument("--mddb", default=MDDB)
    ap.add_argument("--dry-run", action="store_true")
    for f in ("key", "repo", "commit", "class", "trigger", "transform",
              "lang", "evidence", "bench_task", "title"):
        ap.add_argument(f"--{f.replace('_', '-')}")
    args = ap.parse_args()

    recs = []
    if args.record:
        recs = [json.loads(l) for l in args.record.read_text().splitlines()
                if l.strip() and not l.startswith("#")]
    elif args.key:
        recs = [{k: v for k, v in vars(args).items()
                 if k in ("key", "repo", "commit", "class", "trigger",
                          "transform", "lang", "evidence", "bench_task",
                          "title") and v}]
    pushed, refused = [], []
    for rec in recs:
        if banned(rec, args.guard):
            refused.append(rec.get("key") or rec.get("commit"))
            continue
        doc = to_document(rec)
        if args.dry_run:
            print(json.dumps(doc, indent=1))
            continue
        push(doc, args.mddb)
        pushed.append(rec["key"])
    print(json.dumps({"pushed": pushed, "refused_banned": refused}))
    return 0 if not refused else 1


if __name__ == "__main__":
    sys.exit(main())
