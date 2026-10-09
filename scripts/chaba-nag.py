#!/usr/bin/env python3
"""chaba-nag — the deliberate-friction loop (Tony 2026-10-10):
"make all notifications obvious, notice me repeatedly until I decide —
I don't like it but I need it to push myself forward."

Collects everything waiting on a HUMAN decision and pushes a LINE summary
via the ada-line-relay /send endpoint (loopback on idc03, reached over ssh).
Repeats on a timer until the pending set is empty — silence means done.

Sources (surfacing.standard — the same pinned|auto|proposed pattern):
  1. chaba-nest dashboard tiles with state proposed/auto (spec file)
  2. kanban card requests[] without status: answered (open asks)
  3. focus-inbox items older than STALE_DAYS days (parking that went cold)

Usage: chaba-nag.py [--dry-run] [--now]     --now ignores the resend gap
Timer: chaba-nag.timer (every 30 min; re-sends unchanged sets every
RESEND_MIN minutes, quiet hours 00:00–07:00 ICT).
"""
import argparse, datetime, glob, hashlib, json, os, re, subprocess, sys
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "docs/ssot/infrastructure/ssot.chaba-nest-dashboard.yml")
CARDS = os.path.join(ROOT, "docs/ssot/kanban/cards")
INBOX = os.path.join(ROOT, "docs/ssot/focus-inbox")
STATE = os.path.expanduser("~/.local/state/chaba-nag.json")

RESEND_MIN = 120          # re-push the unchanged pending set every 2h
QUIET = (0, 7)            # no LINE pushes 00:00–07:00 local (ICT on tony-dell)
STALE_DAYS = 3            # focus-inbox files older than this count as pending
RELAY = ["ssh", "idc03", "curl", "-s", "-m", "8", "-X", "POST",
         "http://127.0.0.1:8912/send", "-H", "Content-Type: application/json",
         "-d", "@-"]
MAX_ITEMS = 8             # per section in the LINE message


def proposed_tiles():
    spec = yaml.safe_load(open(SPEC))
    out = []
    for t in spec.get("topics") or []:
        for x in t.get("tiles") or []:
            if isinstance(x, dict) and x.get("state") in ("proposed", "auto"):
                out.append(f"{t['path']}: {x['slug']}")
    return out


def open_requests():
    out = []
    for f in glob.glob(os.path.join(CARDS, "*.yml")):
        try:
            card = yaml.safe_load(open(f))
        except Exception:
            continue
        if not isinstance(card, dict):
            continue
        for r in card.get("requests") or []:
            if isinstance(r, dict) and r.get("status", "open") != "answered":
                out.append(f"{os.path.basename(f)[:-4]}: "
                           f"{(r.get('ask') or r.get('id') or '?')[:70]}")
    return out


def stale_inbox():
    """Pending = old inbox files not yet drained. status: linked|processed
    inside focus: means drained (linked = filed/mined elsewhere, processed =
    resolved/obsolete) — draining is a status write, not a delete."""
    cut = datetime.date.today() - datetime.timedelta(days=STALE_DAYS)
    out = []
    for f in glob.glob(os.path.join(INBOX, "*.yml")):
        base = os.path.basename(f)
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", base)
        if not m or datetime.date(*map(int, m.groups())) >= cut:
            continue
        try:
            d = yaml.safe_load(open(f)) or {}
            foc = d.get("focus") or {}
            if foc.get("status") in ("linked", "processed"):
                continue
            out.append(str(foc.get("label") or base)[:60])
            continue
        except Exception:
            pass
        out.append(base)
    return out


def send_line(text):
    p = subprocess.run(RELAY, input=json.dumps({"text": text}),
                       capture_output=True, text=True, timeout=30)
    ok = '"ok":true' in (p.stdout or "").replace(" ", "")
    return ok, (p.stdout or p.stderr or "").strip()[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", action="store_true")
    a = ap.parse_args()

    now = datetime.datetime.now()
    if QUIET[0] <= now.hour < QUIET[1]:
        print("quiet hours — skipped")
        return

    tiles, reqs, inbox = proposed_tiles(), open_requests(), stale_inbox()
    n = len(tiles) + len(reqs) + len(inbox)
    if n == 0:
        print("nothing pending — silence is the goal state")
        return

    h = hashlib.sha1(
        json.dumps([tiles, reqs, inbox], sort_keys=True).encode()).hexdigest()
    st = {}
    if os.path.exists(STATE):
        st = json.load(open(STATE))
    last = st.get("last_sent")
    gap = (datetime.datetime.now().timestamp()
           - (last or 0)) / 60
    if not (a.now or st.get("hash") != h or gap >= RESEND_MIN):
        print(f"unchanged pending set, sent {gap:.0f}m ago — skip")
        return

    lines = [f"⏰ CHABA — {n} thing(s) need your decision:", ""]
    if tiles:
        lines += [f"▸ Dashboard tiles ({len(tiles)} proposed):"] + \
                 [f"  · {x}" for x in tiles[:MAX_ITEMS]]
        if len(tiles) > MAX_ITEMS:
            lines.append(f"  … +{len(tiles)-MAX_ITEMS} more")
        lines.append("  act: chaba-nest-build.py --accept/--reject <slug>")
    if reqs:
        lines += ["", f"▸ Board requests ({len(reqs)} open):"] + \
                 [f"  · {x}" for x in reqs[:MAX_ITEMS]]
        if len(reqs) > MAX_ITEMS:
            lines.append(f"  … +{len(reqs)-MAX_ITEMS} more")
        lines.append("  act: answer on the board (one-click options)")
    if inbox:
        lines += ["", f"▸ Focus-inbox ({len(inbox)} stale >{STALE_DAYS}d):"] + \
                 [f"  · {x[:60]}" for x in inbox[:MAX_ITEMS]]
    lines += ["", "I'll keep reminding you until these clear — "
                  "that's the deal we made. 🙂"]

    text = "\n".join(lines)
    if a.dry_run:
        print(text)
        return
    ok, info = send_line(text)
    print("LINE push:", "ok" if ok else f"FAILED {info}")
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"hash": h, "last_sent": now.timestamp(), "pending": n},
              open(STATE, "w"))


main()
