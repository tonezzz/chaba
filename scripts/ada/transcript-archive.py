#!/usr/bin/env python3
"""transcript-archive.py — deep-archive aging Ada voice transcripts to NotebookLM.

Card ada-transcript-archive-retention, leg 1 of 3. Raw transcripts live at
~/.local/share/ada/transcripts/*.md on the ada runtime host (idc03) and are
local-only — the per-session NotebookLM upload is best-effort REST (it broke
for weeks while lane envs pointed at the retired dell :3011; repointed to
idc02 2026-11-25), so this job is the standing deep-archive backstop: every
week it pushes transcripts older than
--min-age-hours into the "Ada — Transcript Archive" NotebookLM notebook as
text sources, so the deep tier keeps the full-fidelity record that MDDB
extracts only summarize.

Lane attribution: ada-voice writes kind=session-summary docs keyed
session-<date>-<sid> into ada-ha-recall-summary-<instance>; matching the
transcript's <sid> against those keys recovers the lane (tony/kk/michael/
dev). Sessions with no summary doc archive as lane=unknown — they are
never dropped, only tagged.

Upload path: the nlm CLI lives in the notebooklm-mcp container on mn01
(REST lives on idc02 — ssot.services.yml notebooklm-rest; MCP/nlm on mn01
per ssot.values.yml notebooklm.mcp_host). This
script runs on idc03 and reaches it via
  ssh mn01 'podman exec -i notebooklm-mcp nlm source add ...'
transcript content goes as --text (files never leave idc03).

State: ~/.local/share/ada/transcript-archive-state.json records uploaded
session ids so re-runs are incremental; failures are NOT recorded and are
retried next run (bounded by --limit).

Usage:
  transcript-archive.py                # archive run (weekly timer)
  transcript-archive.py --dry-run      # list what would upload
  transcript-archive.py --limit 5      # cap uploads this run
  transcript-archive.py --min-age-hours 48

Env:
  ADA_TRANSCRIPT_DIR     default ~/.local/share/ada/transcripts
  ADA_ARCHIVE_MDDB       default http://100.102.134.91:11023/v1
  ADA_ARCHIVE_INSTANCES  default tony,kk,michael,dev
  ADA_ARCHIVE_NOTEBOOK   default c36cd0fc-ca98-484a-a2bd-b1ee405f3773
                         ("Ada — Transcript Archive")
  NLM_SSH_HOST           default mn01   (host running notebooklm-mcp)
  NLM_EXEC               default "podman exec -i notebooklm-mcp nlm"
  BOARD_API_URL          default http://127.0.0.1:8787 (card comment log)
  ADA_ARCHIVE_CARD       default ada-transcript-archive-retention
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TRANSCRIPT_DIR = Path(os.environ.get(
    "ADA_TRANSCRIPT_DIR",
    os.path.expanduser("~/.local/share/ada/transcripts")))
STATE_PATH = TRANSCRIPT_DIR.parent / "transcript-archive-state.json"
MDDB = os.environ.get("ADA_ARCHIVE_MDDB",
                      "http://100.102.134.91:11023/v1").rstrip("/")
INSTANCES = [s.strip() for s in os.environ.get(
    "ADA_ARCHIVE_INSTANCES", "tony,kk,michael,dev").split(",") if s.strip()]
NOTEBOOK = os.environ.get(
    "ADA_ARCHIVE_NOTEBOOK", "c36cd0fc-ca98-484a-a2bd-b1ee405f3773")
NLM_HOST = os.environ.get("NLM_SSH_HOST", "mn01")
NLM_EXEC = os.environ.get("NLM_EXEC", "podman exec -i notebooklm-mcp nlm")
BOARD_API = os.environ.get("BOARD_API_URL", "http://127.0.0.1:8787")
CARD_ID = os.environ.get("ADA_ARCHIVE_CARD",
                         "ada-transcript-archive-retention")

NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([0-9a-f]{6,})\.md$")
PAGE = 1000


def post(path: str, body: dict, timeout: int = 60) -> object:
    req = urllib.request.Request(
        f"{MDDB}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {"version": 1, "uploaded": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True))


def lane_map() -> dict[str, str]:
    """session-id -> instance, from recall-summary session-* doc keys."""
    out: dict[str, str] = {}
    for inst in INSTANCES:
        coll = f"ada-ha-recall-summary-{inst}"
        offset = 0
        while True:
            try:
                page = post("/search", {"collection": coll, "query": "",
                                        "limit": PAGE, "offset": offset})
            except Exception as e:
                print(f"  ! lane-map {coll}: {e}", file=sys.stderr)
                break
            docs = page if isinstance(page, list) else []
            for d in docs:
                key = str(d.get("key") or "")
                if key.startswith("session-"):
                    sid = key.rsplit("-", 1)[-1]
                    out.setdefault(sid, inst)
            if len(docs) < PAGE:
                break
            offset += len(docs)
    return out


def iter_candidates(min_age_s: float, limit: int):
    """Oldest-first transcript files not yet uploaded, up to limit."""
    now = time.time()
    files = []
    for p in TRANSCRIPT_DIR.glob("*.md"):
        m = NAME_RE.match(p.name)
        if not m:
            continue
        try:
            age = now - p.stat().st_mtime
        except OSError:
            continue
        if age < min_age_s:
            continue
        files.append((p.stat().st_mtime, m.group(1), m.group(2), p))
    files.sort()
    return files[:limit]


def nlm_add(title: str, content: str) -> tuple[bool, str]:
    remote = f"{NLM_EXEC} source add {shlex.quote(NOTEBOOK)} " \
             f"--title {shlex.quote(title)} --text {shlex.quote(content)}"
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             NLM_HOST, remote],
            capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if r.returncode == 0:
        return True, (r.stdout or "").strip()[:200]
    return False, (r.stderr or r.stdout or "").strip()[:300]


def card_comment(text: str) -> bool:
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/comment",
            data=json.dumps({"id": CARD_ID, "from": "chaba",
                             "text": text}).encode(),
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print(f"  ! card comment failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=100,
                    help="max uploads this run (default 100)")
    ap.add_argument("--min-age-hours", type=float, default=48.0,
                    help="only archive transcripts older than this (default 48h)")
    args = ap.parse_args()

    state = load_state()
    uploaded = state.setdefault("uploaded", {})

    # candidates = old enough AND not already archived
    pool = [c for c in iter_candidates(args.min_age_hours * 3600,
                                     args.limit * 4)
            if c[2] not in uploaded]
    if not pool:
        print("nothing to archive")
        return 0

    lanes = lane_map()
    batch = pool[: args.limit]
    print(f"archive run: {len(batch)} transcript(s) -> notebook {NOTEBOOK[:8]}… "
          f"(pool {len(pool)}, lane-map {len(lanes)} sessions)")

    ok = failed = 0
    per_lane: dict[str, int] = {}
    for _mtime, date_s, sid, path in batch:
        lane = lanes.get(sid, "unknown")
        title = f"ada-transcript {date_s} {sid} lane={lane}"
        content = path.read_text(encoding="utf-8", errors="replace")
        if args.dry_run:
            print(f"  [dry] {path.name} lane={lane} ({len(content)}B)")
            ok += 1
            continue
        good, info = nlm_add(title, content)
        if good:
            uploaded[sid] = {"lane": lane, "title": title,
                             "ts": datetime.now(timezone.utc).isoformat()}
            ok += 1
            per_lane[lane] = per_lane.get(lane, 0) + 1
            print(f"  + {path.name} lane={lane}")
        else:
            failed += 1
            print(f"  ! {path.name} lane={lane} FAILED: {info}",
                  file=sys.stderr)

    if not args.dry_run:
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        lane_str = ", ".join(f"{k}={v}" for k, v in sorted(per_lane.items()))
        card_comment(
            f"transcript-archive run {state['last_run']}: uploaded {ok}, "
            f"failed {failed} (limit {args.limit}, min-age "
            f"{args.min_age_hours}h). lanes: {lane_str or 'none'}. "
            f"notebook=Ada — Transcript Archive ({NOTEBOOK[:8]}…). "
            f"state={STATE_PATH}")
    print(f"done: {ok} uploaded, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
