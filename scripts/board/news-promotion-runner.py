#!/usr/bin/env python3
"""Validated, confirmation-gated runner for private-to-public News promotion.

This is intentionally separate from Ada's conversational tool dispatch. It
uses board-api for both the diagnosis and the final publication, and it never
holds Wiki credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_API = "https://idc03.taila0626a.ts.net:10000"


def post(base: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        detail = getattr(exc, "read", lambda: b"")()
        raise RuntimeError(
            f"board-api {path} failed: {detail[:500].decode(errors='replace')}"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-file", required=True,
                        help="JSON canonical public PublicationEvent")
    parser.add_argument("--private-wiki-title", required=True)
    parser.add_argument("--public-wiki-title", required=True)
    parser.add_argument("--review-revid", required=True, type=int)
    parser.add_argument("--card-ref", required=True)
    parser.add_argument("--diagnosis-id", required=True)
    parser.add_argument("--confirm", action="store_true",
                        help="perform the public publication")
    parser.add_argument("--board-api",
                        default=os.environ.get("BOARD_API",
                                               DEFAULT_API))
    args = parser.parse_args()

    event = json.loads(Path(args.event_file).read_text())
    if not isinstance(event, dict):
        raise SystemExit("event file must contain a JSON object")
    event["kind"] = "news"
    event["visibility"] = "public"
    event["confidence"] = "verified"
    event["sinks"] = ["wiki", "json"]
    event["from"] = "promotion-runner"
    event["card"] = args.card_ref
    meta = dict(event.get("meta") or {})
    meta.update({
        "wiki_title": args.public_wiki_title,
        "promotion": "private-to-public",
        "private_wiki_title": args.private_wiki_title,
        "review_revid": args.review_revid,
        "diagnosis_id": args.diagnosis_id,
    })
    event["meta"] = meta

    diagnosis = post(args.board_api, "/wiki/news-diagnose", {
        "private_wiki_title": args.private_wiki_title,
        "public_wiki_title": args.public_wiki_title,
        "review_revid": args.review_revid,
        "card_ref": args.card_ref,
        "from": "promotion-runner",
    })
    if not diagnosis.get("ok") or not diagnosis.get("ready"):
        print(json.dumps({
            "ok": False,
            "stage": "diagnose",
            "diagnosis": diagnosis,
        }, indent=2))
        return 2

    if not args.confirm:
        print(json.dumps({
            "ok": True,
            "stage": "preflight",
            "ready": True,
            "diagnosis_id": diagnosis.get("diagnosis_id"),
            "next": "rerun with --confirm to publish",
        }, indent=2))
        return 0

    result = post(args.board_api, "/publish", event)
    print(json.dumps({
        "ok": bool(result.get("ok")),
        "stage": "publish",
        "diagnosis_id": diagnosis.get("diagnosis_id"),
        "publication": result,
    }, indent=2))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())
