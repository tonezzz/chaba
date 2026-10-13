#!/usr/bin/env python3
"""media-inbox-fixture.py — seed/teardown the media-inbox test fixture.

Creates the archive files + manifest lines the media_inbox live scenario
(tests/scenarios-live/media_inbox.yaml in ada-pi) asserts against:

  mifix-a.txt + mifix-a.txt  two manifest lines, SAME mid  -> T1 transport
                            dedup: one leaf, redeliveries noted on it
  mifix-b.txt               same BYTES as mifix-a, new mid -> T2 content
                            dedup: own leaf, duplicate_of=media-mifix-a
  mifix-c.txt               unique bytes                   -> normal leaf

install:  write files, append manifest lines (idempotent), run
          media-inbox-update.py --lane <lane> once to publish the family
clean:    remove files + manifest lines + every CMS doc matching
          'mifix' (leaves, extract leaves, rollup refresh happens on the
          next timer tick)

Usage (on idc03, beside the relay archive):
  media-inbox-fixture.py install [--lane tony]
  media-inbox-fixture.py clean   [--lane tony]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://127.0.0.1:11027/v1").rstrip("/")
ARCHIVE_DIR = Path(os.environ.get(
    "LINE_MEDIA_ARCHIVE_DIR",
    os.path.expanduser("~/.local/share/ada/line-media")))
URL_BASE = os.environ.get(
    "LINE_PUBLIC_IMG_BASE", "https://157.85.102.125.sslip.io/relay-img")
CHAT = "mi-test"
TAG = "mifix"
LANES = {"tony": "ada-cms-pages", "kk": "ada-cms-pages-kk",
         "kk-dev": "ada-cms-pages-kk-dev"}
PERSONA = {"tony": "chaba", "kk": "kaewta", "kk-dev": "kaewta-cms"}

DOC_A = ("BOOKING CONFIRMATION\nref: TEST-9917\nflight: FD123 "
         "BKK-CNX 2026-11-20\npassenger: Tester\namount: 1850 THB\n")
DOC_C = ("SERVICE RECEIPT\nref: TEST-7788\nitem: router repair\n"
         "date: 2026-10-10\namount: 450 THB\n")


def _post(path: str, payload: dict, timeout: float = 60):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def mline(mid: str, ts: str, fname: str, data: bytes, lane: str) -> dict:
    return {
        "ts": ts, "sender": "Fixture", "chat_id": CHAT, "kind": "file",
        "message_id": mid, "mime": "text/plain",
        "sha256": sha(data), "size": len(data), "file_name": fname,
        "persona": PERSONA[lane], "caller": "user-fixture",
        "path": str(ARCHIVE_DIR / CHAT / f"{mid}.txt"),
        "url": f"{URL_BASE}/arch/{CHAT}/{mid}.txt",
    }


def install(lane: str) -> int:
    d = ARCHIVE_DIR / CHAT
    d.mkdir(parents=True, exist_ok=True)
    a, b, c = DOC_A.encode(), DOC_A.encode(), DOC_C.encode()
    (d / f"{TAG}-a.txt").write_bytes(a)
    (d / f"{TAG}-b.txt").write_bytes(b)
    (d / f"{TAG}-c.txt").write_bytes(c)
    lines = [
        mline(f"{TAG}-a", "2026-10-13T09:00:00", "booking-a.txt", a, lane),
        mline(f"{TAG}-a", "2026-10-13T09:00:01", "booking-a.txt", a, lane),
        mline(f"{TAG}-b", "2026-10-13T09:05:00", "booking-b.txt", b, lane),
        mline(f"{TAG}-c", "2026-10-13T09:10:00", "receipt-c.txt", c, lane),
    ]
    mf = ARCHIVE_DIR / "manifest.jsonl"
    existing = mf.read_text(errors="replace") if mf.is_file() else ""
    added = 0
    with mf.open("a") as fh:
        for e in lines:
            marker = f'"message_id": "{e["message_id"]}"'
            if marker not in existing:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
                added += 1
    print(f"fixture files -> {d}; manifest +{added} line(s)")

    gen = REPO / "scripts" / "ada" / "media-inbox-update.py"
    r = subprocess.run([sys.executable, str(gen), "--lane", lane],
                       capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    return r.returncode


def clean(lane: str) -> int:
    d = ARCHIVE_DIR / CHAT
    if d.is_dir():
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
        print(f"removed {d}")
    mf = ARCHIVE_DIR / "manifest.jsonl"
    if mf.is_file():
        kept = [ln for ln in mf.read_text(errors="replace").splitlines()
                if TAG not in ln]
        mf.write_text("\n".join(kept) + ("\n" if kept else ""))
        print("manifest lines removed")
    col = LANES[lane]
    docs = _post("search", {"collection": col, "limit": 500})
    docs = docs.get("documents") or docs.get("docs") or docs
    for doc in docs:
        if TAG in (str(doc.get("key") or "")
                   + str(doc.get("contentMd") or "")).lower():
            _post("delete", {"collection": col, "key": doc["key"],
                             "lang": doc.get("lang") or "en"})
            print(f"deleted {col}/{doc['key']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["install", "clean"])
    ap.add_argument("--lane", default="tony", choices=sorted(LANES))
    args = ap.parse_args()
    return install(args.lane) if args.action == "install" \
        else clean(args.lane)


if __name__ == "__main__":
    sys.exit(main())
