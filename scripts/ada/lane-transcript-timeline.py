#!/usr/bin/env python3
"""Lane transcript -> WP timeline sync (idempotent).

Builds a "Timeline — <lane>" timeline_block post from an ada lane's voice/chat
session transcripts. Lanes share one transcript pool
(~/.local/share/ada/transcripts/<date>-<session>.md) with no lane tag in the
file, so lane membership is resolved via the service journal: session ids the
unit logged in the window -> matching transcript files -> turn items.

Items: per-turn entries "<role> [HH:MM:SS] text", newest first, MAX_ITEMS cap.
Designed for systemd timers on idc03 (5-15min cadence) — same pattern as
line-chat-timeline.py but text-only (no media upload).

Usage:
    lane-transcript-timeline.py                # all configured lanes
    lane-transcript-timeline.py --dry-run      # count items, no writes

Env:
    WP_BOARDS_ENV   path to wp-boards.env (parsed, never sourced)
"""
import base64
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

# lane -> (systemd unit that owns the sessions, timeline_block post id)
LANES = {
    "mn-ha": ("ada-ai-kraut.service", 872),
}

TRANSCRIPT_DIR = os.path.expanduser("~/.local/share/ada/transcripts")
WINDOW = "--since=7 days ago"   # sessions seen in the unit journal
MAX_ITEMS = 200

env = {}
for _l in open(os.path.expanduser(
        os.environ.get("WP_BOARDS_ENV",
                       "~/.config/secrets/wp-boards.env"))):
    if "=" in _l:
        k, v = _l.rstrip("\n").split("=", 1)
        env[k] = v
BASE = env["WP_SITE_URL"].strip().rstrip("/")
AUTH = "Basic " + base64.b64encode(
    f"{env['WP_APP_USER'].strip()}:{env['WP_APP_PASSWORD'].strip()}".encode()
).decode()
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

ICON = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'>"
        "<path d='M256 32C114.6 32 0 125.1 0 240c0 49.6 21.4 95 57 130.7C44.5"
        " 421.1 2.7 466 2.2 466.5c-2.2 2.3-2.8 5.7-1.5 8.7S4.8 480 8 480c66.3"
        " 0 116-31.8 140.6-51.4 32.7 12.3 69 19.4 107.4 19.4 141.4 0 256-93.1"
        " 256-208S397.4 32 256 32z'/></svg>")

TURN_RE = re.compile(r"^## (\S+)(?: \[([0-9:]+)\])?\s*$")


def api(method, route, data=None):
    url = (f"{BASE}/index.php?rest_route="
           f"{urllib.parse.quote('/wp/v2/' + route, safe='/=&')}")
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", AUTH)
    req.add_header("User-Agent", UA)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": e.read()[:200].decode(errors="replace")}


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def lane_sessions(unit):
    """Session ids this unit logged in the window."""
    try:
        out = subprocess.run(
            ["journalctl", "--user", "-u", unit, WINDOW, "--no-pager", "-q"],
            capture_output=True, text=True, timeout=60).stdout
    except Exception as e:
        print(f"  warn: journalctl {unit}: {e}", file=sys.stderr)
        return set()
    return set(re.findall(r"session=([0-9a-f]{8,12})", out))


def session_files(sids):
    files = []
    try:
        names = os.listdir(TRANSCRIPT_DIR)
    except OSError:
        return files
    for fn in names:
        if not fn.endswith(".md"):
            continue
        stem = fn[:-3]
        sid = stem.rsplit("-", 1)[-1]
        if sid in sids:
            files.append(os.path.join(TRANSCRIPT_DIR, fn))
    return sorted(files)


def parse_turns(path):
    """[(date_label, role, text)] from a transcript markdown file."""
    # filename date prefix is authoritative for the day; turn stamps are times
    day = os.path.basename(path)[:10]
    try:
        day_lbl = datetime.strptime(day, "%Y-%m-%d").strftime("%d %b")
    except ValueError:
        day_lbl = day
    turns, role, stamp, buf = [], None, None, []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = TURN_RE.match(line.rstrip("\n"))
        if m:
            if role and buf:
                turns.append((day_lbl, role, stamp or "", " ".join(buf)))
            role, stamp, buf = m.group(1), m.group(2), []
        elif role and line.strip():
            buf.append(line.strip())
    if role and buf:
        turns.append((day_lbl, role, stamp or "", " ".join(buf)))
    return turns


def main():
    dry = "--dry-run" in sys.argv
    for lane, (unit, post_id) in LANES.items():
        sids = lane_sessions(unit)
        files = session_files(sids)
        items = []
        for f in files:
            sid = os.path.basename(f)[11:-3]
            for day_lbl, role, stamp, text in parse_turns(f):
                label = "kraut" if role.lower() in ("ada", "assistant") \
                    else role.lower()
                desc = esc(text[:600])
                if len(text) > 600:
                    desc += "…"
                items.append({
                    "icon": ICON,
                    "date": f"{day_lbl} {stamp[:5]}",
                    "label": f"{label} · {sid[:6]}",
                    "description": desc.replace("\n", "<br>"),
                    "isAddTinyEditor": False,
                })
        items = list(reversed(items[-MAX_ITEMS:]))
        if dry:
            print(f"{lane}: {len(sids)} sessions, {len(files)} transcripts, "
                  f"{len(items)} items")
            continue
        if not post_id:
            print(f"{lane}: no timeline post id configured — create one first",
                  file=sys.stderr)
            continue
        content = ("<!-- wp:tlgb/b-timeline-block " +
                   json.dumps({"timelines": items, "type": "vertical",
                               "itemPosition": "right",
                               "labelLocation": "right"},
                              ensure_ascii=False) + " /-->")
        s, res = api("POST", f"timeline_block/{post_id}",
                     {"content": content})
        print(f"{lane}: items={len(items)} update={s} "
              f"modified={res.get('modified', '?')}")


if __name__ == "__main__":
    main()
