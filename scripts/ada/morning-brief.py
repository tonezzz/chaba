#!/usr/bin/env python3
"""morning-brief.py — Ada's proactive morning brief -> Tony's TG DM.

Card ada-proactive-digest-morning-brief-via-t-3abb02: Ada is poll-only
(Tony must ask); this is the push half — a short voice/SMS-length brief
posted each morning through the existing ada-tg-relay loopback /send
(docs/kb/msg-lane-standard.md — no new transport, no bot creds here).

Gathers (all best-effort — a missing source degrades its line, never
kills the brief):
  education   due lessons via board-api POST /lesson {op:list,
              source:wiki} — lessons-due.py's fetch_rows/bucket_rows are
              imported so the bucket rule can't drift
  requests    open card `requests:` (the board's needs-Tony list)
  overnight   card action.status done/failed whose `updated` lands in
              the last 24h (card-side view — works on any host that can
              reach board-api, unlike the host-local dispatch ledger)
  health      bad node states in reports/system-report.yml +
              ~/var/chaba/health/meta.yml (same sources daily-brief reads)

Usage:
  morning-brief.py             # gather, render, POST /send
  morning-brief.py --print     # render only, never POST

Env:
  BOARD_API / RUNNER_API   door base (default: idc03 tailnet :10000)
  MB_SEND_URL              /send endpoint (default http://127.0.0.1:8911/send
                           — the ada lane = Tony DM on idc03)
  MB_CHAT_ID               explicit chat_id (default = relay's first
                           allowed chat = Tony)
  BRIEF_PAGE_URL           detail link (default: daily-brief CMS page)
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))

try:
    import dispatch_repos as dr
    API_BASE = dr.board_api_base()
except Exception:
    API_BASE = (os.environ.get("BOARD_API") or os.environ.get("RUNNER_API")
                or "https://idc03.taila0626a.ts.net:10000").rstrip("/")

import yaml  # noqa: E402

SEND_URL = os.environ.get("MB_SEND_URL", "http://127.0.0.1:8911/send")
CHAT_ID = os.environ.get("MB_CHAT_ID", "").strip()
PAGE_URL = os.environ.get(
    "BRIEF_PAGE_URL", "https://idc03.taila0626a.ts.net/cms/#/daily-brief")
SYSTEM_REPORT_YML = REPO / "reports" / "system-report.yml"
HEALTH_DIR = Path("~/var/chaba/health").expanduser()
DISPATCH_DIR = Path(
    os.environ.get("DISPATCH_DIR", "~/.local/share/devin-dispatch")
).expanduser() / "tasks"
WINDOW_H = 24
MAX_LINES = 9          # voice/SMS-length contract, incl. [tag] + link
TOP_N = 3              # items named per section

_LOCAL = datetime.datetime.now().astimezone().tzinfo


def _load_lessons_due():
    """Import lessons-due.py (dash-named) for fetch_rows/bucket_rows."""
    spec = importlib.util.spec_from_file_location(
        "lessons_due", REPO / "scripts" / "lessons-due.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_card_ts(s) -> datetime.datetime | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).replace(
                tzinfo=_LOCAL)
        except ValueError:
            continue
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt.astimezone() if dt.tzinfo
            else dt.replace(tzinfo=_LOCAL))


# ---------------------------------------------------------------- gather

def education_due() -> dict:
    """-> {'count': int, 'topics': [..]} or {'error': str}."""
    try:
        mod = _load_lessons_due()
        rows = mod.fetch_rows("wiki", API_BASE)
        due, _up = mod.bucket_rows(
            rows, datetime.date.today().isoformat())
        return {"count": len(due),
                "topics": [r["topic"] for r in due[:TOP_N]]}
    except Exception as e:
        return {"error": str(e)[:80]}


def load_cards() -> list[dict]:
    req = urllib.request.Request(f"{API_BASE}/cards")
    with urllib.request.urlopen(req, timeout=15) as r:
        payload = json.loads(r.read())
    cards = payload.get("cards", payload) if isinstance(
        payload, dict) else payload
    return cards if isinstance(cards, list) else []


def open_requests(cards: list[dict]) -> list[dict]:
    out = []
    for c in cards:
        for r in c.get("requests") or []:
            if not isinstance(r, dict):
                r = {"status": "open", "ask": str(r)}
            if r.get("status") == "open":
                out.append({"card": c.get("id"), "ask": r.get("ask", "")})
    return out


def _parse_iso(s) -> datetime.datetime | None:
    if not s:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt.astimezone() if dt.tzinfo
            else dt.replace(tzinfo=_LOCAL))


def overnight_outcomes(cards: list[dict],
                       since: datetime.datetime) -> dict:
    """Dispatch results in window. Preferred: the host-local
    devin-dispatch ledger (finished_at in window — the truthful signal,
    same source daily-brief reads). Fallback: card-side action.status +
    `updated` (noisy — sweeps bump updated — but the brief only runs on
    hosts where the ledger may legitimately be absent)."""
    done, failed = [], []
    if DISPATCH_DIR.is_dir():
        for d in DISPATCH_DIR.iterdir():
            meta_p = d / "meta.json"
            if not meta_p.is_file():
                continue
            try:
                m = json.loads(meta_p.read_text())
            except Exception:
                continue
            fin = _parse_iso(m.get("finished_at"))
            if not (fin and fin >= since):
                continue
            result = m.get("result")
            try:
                code = int((d / "exit_code").read_text().strip())
                if code != 0 and result == "success":
                    result = "exit-code"
            except Exception:
                pass
            (done if result == "success" else failed).append(d.name)
        return {"done": done, "failed": failed, "source": "ledger"}
    for c in cards:
        a = c.get("action") or {}
        if a.get("status") not in ("done", "failed"):
            continue
        upd = _parse_card_ts(c.get("updated"))
        if not (upd and upd >= since):
            continue
        (done if a["status"] == "done" else failed).append(c.get("id"))
    return {"done": done, "failed": failed, "source": "cards"}


def health_flags() -> list[str]:
    """Same red-flag sources as report-daily-brief.health_flags (kept
    inline — that module is dash-named and tied to its own main())."""
    flags = []
    try:
        doc = yaml.safe_load(SYSTEM_REPORT_YML.read_text()) or {}
        for n in doc.get("nodes") or []:
            if n.get("status") in ("missing", "stale", "error"):
                flags.append(f"{n.get('id')}={n.get('status')}")
    except Exception:
        pass
    try:
        meta = yaml.safe_load((HEALTH_DIR / "meta.yml").read_text()) or {}
        bad = (meta.get("extra") or {}).get("unhealthy") or 0
        if meta.get("status") not in ("ok", None) or bad:
            flags.append(f"health: {meta.get('summary', 'unhealthy')}")
    except Exception:
        pass
    return flags


# ---------------------------------------------------------------- render

def render(edu: dict, reqs: list, outcomes: dict,
           flags: list[str]) -> str:
    today = datetime.date.today().strftime("%a %Y-%m-%d")
    lines = [f"[ada] morning brief — {today}"]

    if "error" in edu:
        lines.append(f"Education: (due list unavailable: {edu['error']})")
    elif edu["count"]:
        topics = ", ".join(edu["topics"])
        more = f" +{edu['count'] - TOP_N}" if edu["count"] > TOP_N else ""
        lines.append(f"Education: {edu['count']} due — {topics}{more}")
    else:
        lines.append("Education: nothing due")

    if reqs:
        first = reqs[0]["ask"][:70].replace("\n", " ")
        more = f" +{len(reqs) - 1} more" if len(reqs) > 1 else ""
        lines.append(f"Board: {len(reqs)} open request(s) — "
                     f"\"{first}\"{more}")
    else:
        lines.append("Board: no open requests")

    d, f = outcomes["done"], outcomes["failed"]
    line = f"Overnight: {len(d)} done, {len(f)} failed"
    if f:
        first = f[0][:45]
        line += f" — {first}" + (f" +{len(f) - 1}" if len(f) > 1 else "")
    lines.append(line)

    if flags:
        lines.append("Health: " + "; ".join(flags[:TOP_N]))

    lines.append(f"Details: {PAGE_URL}")
    return "\n".join(lines[:MAX_LINES])


# ---------------------------------------------------------------- send

def send(text: str) -> bool:
    """ada-tg-relay loopback /send — same contract as board_notify:
    no token (loopback only), no chat_id = first allowed chat (Tony)."""
    payload = {"text": text[:3500]}
    if CHAT_ID:
        try:
            payload["chat_id"] = int(CHAT_ID)
        except ValueError:
            print(f"warn: bad MB_CHAT_ID {CHAT_ID!r}", file=sys.stderr)
    try:
        req = urllib.request.Request(
            SEND_URL, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except Exception as e:
        print(f"warn: /send failed ({e})", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--print", dest="print_only", action="store_true",
                    help="render the brief, never POST")
    a = ap.parse_args()

    since = datetime.datetime.now(_LOCAL) - datetime.timedelta(
        hours=WINDOW_H)
    edu = education_due()
    try:
        cards = load_cards()
        reqs = open_requests(cards)
        outcomes = overnight_outcomes(cards, since)
    except Exception as e:
        print(f"warn: card sources failed ({e})", file=sys.stderr)
        reqs, outcomes = [], {"done": [], "failed": []}
    flags = health_flags()

    text = render(edu, reqs, outcomes, flags)
    if a.print_only:
        print(f"--- -> {SEND_URL} ---\n{text}")
        return 0
    ok = send(text)
    print(f"morning-brief: {'sent' if ok else 'FAILED'} -> {SEND_URL}")
    if not ok:
        print(text, file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
