#!/usr/bin/env python3
"""voice-burn-ledger.py — Live/voice session ledger per lane from journald.

Answers "where do we burn" — the gateway burn report (llm-burn.sh) only sees
REST traffic; Gemini Live sessions bypass the gateway entirely, so voice/audio
spend was invisible until this ledger. Each run recomputes the trailing window
from journald (self-healing, no state file) and writes:

  ~/.local/share/ada/voice-burn/<YYYY-MM-DD>.jsonl   per-session ledger rows
  ada-cms-pages:voice-burn                           rollup report page

Per lane per day: sessions opened, provider-connect failures (the
depleted-credit retry storms still show up as attempts — they bill ~nothing
but reveal where callers hammer), connected minutes (client-connected ->
closed wall time; Live audio-token billing is a superset of this — minutes
are the floor), openrouter-fallback minutes, and top sessions.

Stdlib only. Env:
  MDDB_BASE_URL   CMS plane (default http://100.102.134.91:11027/v1)
  VOICE_BURN_DIR  default ~/.local/share/ada/voice-burn
  ADA_CMS_BASE    viewer base for view_url in --json output

Usage:
  voice-burn-ledger.py                # all lanes, last 7d, collect + publish
  voice-burn-ledger.py --days 1       # yesterday+today only
  voice-burn-ledger.py --dry-run      # render, write nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11027/v1").rstrip("/")
OUT_DIR = Path(os.environ.get(
    "VOICE_BURN_DIR", os.path.expanduser("~/.local/share/ada/voice-burn")))
COLL = os.environ.get("VOICE_BURN_COLL", "ada-cms-pages")
GENERATOR = "voice-burn-ledger.py"
VERSION = "1.0.0 2026-10-13"

# lane -> user systemd unit holding the voice/pwa server
LANE_UNITS = {
    "tony": "ada-ha-tony",
    "michael": "ada-ha-michael",
    "kk": "ada-kk",
    "dev": "ada-dev",
    "kk-dev": "ada-kk-dev",
    "pwa": "ada-pi-pwa",
}

_RE_OPEN = re.compile(
    r"session=(\w+) client connected \(caller=([^\)]+)\)")
_RE_CLOSE = re.compile(r"session=(\w+) closed")
_RE_PFAIL = re.compile(r"session=(\w+) provider connect failed")
_RE_FALLBACK = re.compile(r"session=(\w+) degraded to openrouter fallback")
_RE_TURN = re.compile(r"session=(\w+) chat text turn")
_RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


def _journal(unit: str, days: int) -> list[tuple[str, str]]:
    out = subprocess.run(
        ["journalctl", "--user", "-u", unit,
         "--since", f"{days} days ago", "-o", "short-iso", "--no-pager"],
        capture_output=True, text=True, timeout=120)
    rows = []
    for ln in out.stdout.splitlines():
        m = _RE_TS.match(ln)
        if m and "session=" in ln:
            rows.append((m.group(1), ln))
    return rows


def scan_lane(lane: str, unit: str, days: int) -> dict:
    """Return {day: {sessions, failed, fallback, minutes, fallback_min,
    callers{}}} plus per-session rows for the jsonl ledger."""
    sess = defaultdict(lambda: {"open": None, "close": None, "caller": "?",
                                "pfail": False, "fallback": False,
                                "turns": 0})
    for ts, ln in _journal(unit, days):
        if (m := _RE_OPEN.search(ln)):
            sess[m.group(1)]["open"] = ts
            sess[m.group(1)]["caller"] = m.group(2)
        elif (m := _RE_CLOSE.search(ln)):
            sess[m.group(1)]["close"] = ts
        elif (m := _RE_PFAIL.search(ln)):
            sess[m.group(1)]["pfail"] = True
        elif (m := _RE_FALLBACK.search(ln)):
            sess[m.group(1)]["fallback"] = True
        elif (m := _RE_TURN.search(ln)):
            sess[m.group(1)]["turns"] += 1

    days_map = defaultdict(lambda: {
        "sessions": 0, "failed": 0, "fallback": 0,
        "minutes": 0.0, "fallback_min": 0.0, "turns": 0,
        "callers": defaultdict(int), "hours": defaultdict(int)})
    rows = []
    for sid, s in sess.items():
        if not s["open"]:
            continue  # close/fail lines for sessions opened before window
        day = s["open"][:10]
        dur = 0.0
        if s["close"]:
            try:
                t0 = dt.datetime.fromisoformat(s["open"])
                t1 = dt.datetime.fromisoformat(s["close"])
                dur = max(0.0, (t1 - t0).total_seconds() / 60.0)
            except ValueError:
                pass
        d = days_map[day]
        d["sessions"] += 1
        d["turns"] += s["turns"]
        d["callers"][s["caller"]] += 1
        # habit profile — session opens bucketed by 3h local hour band;
        # tunes LINE_IDLE_SESSION_S day/night boundary (LINE_NIGHT_HOURS)
        d["hours"][int(s["open"][11:13]) // 3] += 1
        if s["pfail"]:
            d["failed"] += 1
        if s["fallback"]:
            d["fallback"] += 1
            d["fallback_min"] += dur
        else:
            d["minutes"] += dur
        rows.append({"day": day, "lane": lane, "session": sid,
                     "caller": s["caller"], "open": s["open"],
                     "close": s["close"], "minutes": round(dur, 2),
                     "provider_failed": s["pfail"],
                     "fallback": s["fallback"], "turns": s["turns"]})
    return {"days": days_map, "rows": rows}


def _mddb_post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        MDDB + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as exc:
        return {"error": str(exc)}


def render(lanes: dict, window_days: int) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"# Voice burn ledger — {now}\n",
           "Live/voice sessions bypass the gateway — REST burn never sees "
           "this spend. Minutes are wall-clock session time (billing floor); "
           "provider-failed connects bill ~nothing but mark retry storms.\n",
           "| day | lane | sessions | connected | provider-fail | "
           "live min | fallback min | top caller |",
           "|---|---|---|---|---|---|---|---|"]
    totals = defaultdict(float)
    for lane, data in lanes.items():
        for day in sorted(data["days"], reverse=True):
            d = data["days"][day]
            live_min = d["minutes"]
            conn = d["sessions"] - d["failed"]
            caller = max(d["callers"], key=d["callers"].get, default="-")
            out.append(
                f"| {day} | {lane} | {d['sessions']} | {conn} | "
                f"{d['failed']} | {live_min:.1f} | {d['fallback_min']:.1f} | "
                f"{caller} |")
            totals["min"] += live_min
            totals["fail"] += d["failed"]
    out += ["\n## Top sessions (window)\n",
            "| day | lane | session | min | turns | flags |",
            "|---|---|---|---|---|---|"]
    all_rows = sorted(
        (r for d in lanes.values() for r in d["rows"]),
        key=lambda r: r["minutes"], reverse=True)[:15]
    for r in all_rows:
        flags = ",".join(x for x, on in
                         (("provider-fail", r["provider_failed"]),
                          ("fallback", r["fallback"])) if on) or "-"
        out.append(f"| {r['day']} | {r['lane']} | {r['session']} | "
                   f"{r['minutes']:.1f} | {r['turns']} | {flags} |")
    # habit profile — sessions by 3h open-hour band, all days merged;
    # quiet bands are the candidates for LINE_NIGHT_HOURS
    bands = ["00-02", "03-05", "06-08", "09-11", "12-14", "15-17",
             "18-20", "21-23"]
    out += ["\n## Habit profile — session opens by hour band (all days)\n",
            "| lane | " + " | ".join(bands) + " |",
            "|---|" + "---|" * len(bands)]
    merged = defaultdict(lambda: defaultdict(int))
    for lane, data in lanes.items():
        for d in data["days"].values():
            for band, n in d["hours"].items():
                merged[lane][band] += n
    for lane in sorted(merged):
        out.append("| " + lane + " | " + " | ".join(
            str(merged[lane].get(b, 0)) for b in range(len(bands))) + " |")
    out.append(
        f"\n_Total: {totals['min']:.0f} connected min, "
        f"{int(totals['fail'])} failed connects, last {window_days}d. "
        f"Ledger rows: ~/.local/share/ada/voice-burn/<day>.jsonl_")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7,
                    help="journald look-back window (default 7)")
    ap.add_argument("--lanes", default=",".join(LANE_UNITS),
                    help="comma-sep lane subset")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    lanes = {}
    for lane in args.lanes.split(","):
        unit = LANE_UNITS.get(lane.strip())
        if not unit:
            continue
        lanes[lane] = scan_lane(lane.strip(), unit, args.days)

    if args.json:
        print(json.dumps({"lanes": {
            l: {d: {k: (dict(v) if k == "callers" else v)
                    for k, v in dd.items() if k != "callers"} |
                    {"callers": dict(dd["callers"])}
                for d, dd in data["days"].items()}
            for l, data in lanes.items()}}, indent=1))
        return 0

    md = render(lanes, args.days)
    if args.dry_run:
        print(md)
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_day = defaultdict(list)
    for data in lanes.values():
        for r in data["rows"]:
            by_day[r["day"]].append(r)
    for day, rows in by_day.items():
        (OUT_DIR / f"{day}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))

    meta = {"kind": ["report"], "domain": ["ops"], "slug": ["voice-burn"],
            "title": ["Voice burn — Live session ledger"],
            "summary": ["Per-lane voice session minutes + connect failures"],
            "updated": [dt.datetime.now(dt.timezone.utc).isoformat()],
            "fresh_for": ["1h"], "status": ["live"],
            "generated_by": [GENERATOR], "report_role": ["rollup"],
            "parent": ["reports-index"], "public": ["false"],
            "version": [VERSION]}
    res = _mddb_post("/add", {"collection": COLL, "key": "voice-burn",
                              "lang": "en", "contentMd": md, "meta": meta})
    print(json.dumps({"page": res, "ledger_days": len(by_day),
                      "rows": sum(len(v) for v in by_day.values())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
