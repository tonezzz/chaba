#!/usr/bin/env python3
"""burn-watch.py — guard the voice-burn ledger.

Sums today's Live minutes per lane and alerts once/day when a lane (or
the fleet total) crosses its threshold. Alerts land as a comment on the
spend-cap card via board-api.

Origin — 2026-10-14 incident: the hourly scenario smoke tier burned
~700 Live-min/day for days because scenario-report.py never passed
--text, and nothing watched the ledger. The data existed; nobody read
it. This script is the reader.

Thresholds reflect post-BEN-0573 expectations: dev lanes should run
~1 Live-min/hr (the speech-stall sentinel), human lanes vary.
"""

import datetime
import json
import os
import sys
import urllib.request

LEDGER = os.path.expanduser("~/.local/share/ada/voice-burn")
STATE = os.path.expanduser("~/.local/share/ada/burn-watch-state.json")
BOARD_API = os.environ.get("BOARD_API",
                           "http://tony-dell/apps/board-api")
CARD = os.environ.get("BURN_WATCH_CARD", "ada-gemini-live-spend-cap")

# Lane → max Live-min/day before alerting. Test lanes run text-mode
# smoke; only the audio sentinel should log Live sessions.
THRESHOLDS = {
    "dev": 60,
    "kk-dev": 60,
    "tony": 180,
    "michael": 120,
    "kk": 400,
}
TOTAL_MAX = 700


def lane_minutes(day: str) -> dict:
    per: dict = {}
    try:
        with open(os.path.join(LEDGER, f"{day}.jsonl")) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                # mode=text rows are REST-provider sessions — free-tier
                # text, not billed Live minutes. Only live rows count.
                if e.get("mode") == "text":
                    continue
                lane = e.get("lane") or "?"
                per[lane] = per.get(lane, 0.0) + float(e.get("minutes") or 0)
    except FileNotFoundError:
        pass
    return per


def alert(text: str) -> bool:
    payload = json.dumps(
        {"id": CARD, "from": "burn-watch", "text": text}).encode()
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/comment", data=payload,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except Exception as exc:                    # noqa: BLE001 — alert path
        print(f"burn-watch: board alert failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    today = datetime.date.today().isoformat()
    per = lane_minutes(today)
    total = sum(per.values())

    try:
        state = json.load(open(STATE))
    except (OSError, ValueError):
        state = {}
    alerted = set(state.get(today) or [])

    breaches = []
    for lane, mins in sorted(per.items()):
        limit = THRESHOLDS.get(lane, TOTAL_MAX)
        if mins > limit and lane not in alerted:
            breaches.append(f"{lane}: {mins:.0f}min (limit {limit})")
            alerted.add(lane)
    if total > TOTAL_MAX and "__total__" not in alerted:
        breaches.append(f"TOTAL {total:.0f}min (limit {TOTAL_MAX})")
        alerted.add("__total__")

    if breaches:
        msg = (f"[burn-watch] {today} Live-minute breach: "
               + "; ".join(breaches)
               + ". Check which lane/timer is opening billed sessions.")
        print(msg)
        alert(msg)

    state[today] = sorted(alerted)
    # keep only recent days
    for k in list(state):
        if k != today:
            del state[k]
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE)

    if not per:
        print(f"burn-watch: {today} no ledger entries")
    else:
        print("burn-watch: " + ", ".join(
            f"{l}={m:.0f}m" for l, m in sorted(per.items()))
              + f" | total={total:.0f}m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
