#!/usr/bin/env python3
"""File a lesson into WP lesson CPT — Tony's education ledger.

Thin client of the unified mutation door: POSTs to board-api /lesson,
which owns the WP write (upsert by topic slug, auto-Thai section,
first-learn provenance preserved). Agents never hold WP creds — the
service host does (card nest-api-unified-mutation-service).

Usage:
  lesson-add.py --topic "cloud object storage" --level intro \
      --source chat --content-file /tmp/lesson.html [--next-review 2026-11-15]

Env: BOARD_API (default: the tailnet board-api URL). A non-loopback POST
needs a tailnet identity — tailscale serve injects it on tailnet calls.
"""
import argparse, json, sys, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "board"))

try:
    import dispatch_repos as dr
    API = dr.board_api_base()
except Exception:
    API = "https://idc03.taila0626a.ts.net:10000"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--level", default="intro",
                    choices=["intro", "working", "deep"])
    ap.add_argument("--source", default="chat",
                    choices=["chat", "voice", "link"])
    ap.add_argument("--content-file", required=True)
    ap.add_argument("--next-review", default="",
                    help="ISO date; default = learned_at + 7d (first spaced review)")
    ap.add_argument("--status", default="open")
    ap.add_argument("--no-th", action="store_true",
                    help="skip Thai translation section")
    a = ap.parse_args()

    body = {"topic": a.topic, "level": a.level, "source": a.source,
            "content": Path(a.content_file).read_text(),
            "status": a.status, "no_th": a.no_th, "from": "devin"}
    if a.next_review:
        body["next_review"] = a.next_review
    req = urllib.request.Request(
        f"{API}/lesson", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        print(f"lesson-add: board-api {e.code}: "
              f"{e.read()[:300].decode('utf-8', 'replace')}",
              file=sys.stderr)
        return 1
    except OSError as e:
        print(f"lesson-add: board-api unreachable: {e}", file=sys.stderr)
        return 1
    print(r.get("message") or r)


if __name__ == "__main__":
    sys.exit(main() or 0)
