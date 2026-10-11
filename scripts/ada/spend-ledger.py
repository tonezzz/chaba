#!/usr/bin/env python3
"""spend-ledger — daily Ada API burn ledger -> CMS spend-ledger page.

(card scenario-spend-guard, 2026-10-11) Answers "what did yesterday's
Live sessions + aux calls cost" before the next billing surprise:

  * tokens + sessions from the backend's own usage ledger
    (~/CascadeProjects/ada-pi/data/usage.jsonl, written by
    backend/usage_tracker.py — all ada-* units share the file; source=live
    rows are Live turns, every other source is an aux generateContent
    call). est $ recomputed with the same RATES_PER_MILLION table —
    verify both against ai.google.dev pricing when it drifts.
  * ws churn from journald: 'client connected' + 'provider reconnected'
    per ada-ha-* unit — the connect volume that multiplies into spend.

Output:
  * ada-cms-pages/spend-ledger  kind:report, domain:ops — a rolling
    14-day table. domain=ops makes it a member of the nightly
    ops-digest, so the ledger line lands in the CMS ops rollup without
    fighting the 15-min ops-health page (full-regen, ada-pi-owned).
  * ada-ha-scenario-reports/report/spend-<date>  daily snapshot doc —
    the ledger survives page rewrites; ops collection has no embedder so
    /add is cheap.
  * ~/.local/share/ada-review/spend-ledger.jsonl — local merge-by-date
    history the digest pipeline can also pick up.

Warns to chaba-events when a day crosses --warn-usd / --warn-sessions
(throttled, once per day per tripwire).

Usage:
  spend-ledger.py                # aggregate today + trailing 13 days, publish
  spend-ledger.py --days 7       # window
  spend-ledger.py --dry-run      # render to stdout, no writes
  spend-ledger.py --no-journal   # skip journald churn columns (off-host runs)

Env: MDDB_BASE_URL / MDDB_OPS_URL, ADA_USAGE_LOG (path to usage.jsonl),
SPEND_WARN_USD (default 2.0), SPEND_WARN_SESSIONS (default 300),
GATE_STATE_FILE (shared throttle state with scenario-provider-gate).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MDDB = (os.environ.get("MDDB_OPS_URL")
        or os.environ.get("MDDB_BASE_URL")
        or "http://100.102.134.91:11023/v1").rstrip("/")
USAGE_LOG = Path(os.environ.get(
    "ADA_USAGE_LOG",
    "~/CascadeProjects/ada-pi/data/usage.jsonl")).expanduser()
LOCAL_OUT = Path.home() / ".local/share/ada-review"
STATE = Path(os.environ.get(
    "GATE_STATE_FILE",
    "~/.local/share/ada-scenario-runner/gate-state.json")).expanduser()

COLLECTION = "ada-cms-pages"
REPORTS = "ada-ha-scenario-reports"
PAGE_KEY = "spend-ledger"
KEEP_DAYS = 14

UNITS = ["ada-ha-tony", "ada-ha-michael", "ada-dev", "ada-pi-pwa",
         "ada-kk"]

# Mirror of backend/usage_tracker.py RATES_PER_MILLION (USD/1M tokens,
# Sept-2026 Flash-Live audio + Flash-Lite). Keep in sync — last verified
# 2026-10-11.
RATES_PER_MILLION = {
    "audio": {"in": 3.00, "out": 12.00},
    "text": {"in": 0.30, "out": 0.60},
    "image": {"in": 0.30, "out": 0.0},
    "video": {"in": 0.30, "out": 0.0},
    "document": {"in": 0.30, "out": 0.0},
    "unknown": {"in": 3.00, "out": 12.00},
}
CACHED_RATE_FRACTION = 0.25


def _post(path: str, payload: dict, timeout: int = 60):
    req = urllib.request.Request(
        f"{MDDB}/{path.lstrip('/')}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _rate(modality: str, direction: str) -> float:
    return RATES_PER_MILLION.get(
        modality, RATES_PER_MILLION["unknown"])[direction]


def _new_day() -> dict:
    return {"in": 0, "out": 0, "cached": 0, "tool_use": 0, "turns": 0,
            "live_sessions": set(), "aux_calls": 0,
            "in_mod": defaultdict(int), "out_mod": defaultdict(int),
            "sources": defaultdict(int)}


def load_usage(path: Path, days: int) -> dict[str, dict]:
    """usage.jsonl -> {local-date: bucket}. Streams; unbounded file."""
    cutoff = (datetime.datetime.now().astimezone()
              - datetime.timedelta(days=days)).date()
    out: dict[str, dict] = {}
    try:
        fh = path.open()
    except OSError as e:
        print(f"warn: usage log unreadable: {e}", file=sys.stderr)
        return out
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                ts = datetime.datetime.fromisoformat(
                    str(rec.get("ts") or ""))
            except ValueError:
                continue
            day = ts.astimezone().date()
            if day < cutoff:
                continue
            b = out.setdefault(day.isoformat(), _new_day())
            src = str(rec.get("source") or "unknown")
            b["sources"][src] += 1
            b["in"] += int(rec.get("in", 0) or 0)
            b["out"] += int(rec.get("out", 0) or 0)
            b["cached"] += int(rec.get("cached", 0) or 0)
            b["tool_use"] += int(rec.get("tool_use", 0) or 0)
            b["turns"] += 1
            for mod, n in (rec.get("in_mod") or {}).items():
                b["in_mod"][str(mod)] += int(n)
            for mod, n in (rec.get("out_mod") or {}).items():
                b["out_mod"][str(mod)] += int(n)
            if src == "live":
                if rec.get("session_id"):
                    b["live_sessions"].add(str(rec["session_id"]))
            else:
                b["aux_calls"] += 1
    return out


def _est_cost(b: dict) -> float:
    cost = 0.0
    for mod, n in b["in_mod"].items():
        cost += n * _rate(mod, "in")
    for mod, n in b["out_mod"].items():
        cost += n * _rate(mod, "out")
    cost += max(0, b["in"] - sum(b["in_mod"].values())) \
        * _rate("unknown", "in")
    cost += max(0, b["out"] - sum(b["out_mod"].values())) \
        * _rate("unknown", "out")
    cost += b["cached"] * _rate("unknown", "in") * CACHED_RATE_FRACTION
    return round(cost / 1_000_000, 4)


def journal_connects(unit: str, since: str, until: str) -> dict[str, int]:
    try:
        out = subprocess.run(
            ["journalctl", "--user", "-u", unit, "--since", since,
             "--until", until, "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return {"ws": -1, "upstream": -1}
    ws = sum(1 for l in out.splitlines() if "client connected" in l)
    up = sum(1 for l in out.splitlines() if "provider reconnected" in l)
    return {"ws": ws, "upstream": up}


def journal_day(unit: str, day: datetime.date) -> dict[str, int]:
    """ws/upstream connects for one local calendar day. Today needs no
    --until (an until in the future is accepted anyway)."""
    nxt = day + datetime.timedelta(days=1)
    return journal_connects(unit, day.isoformat(), nxt.isoformat())


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state))
    except OSError:
        pass


def maybe_emit(state: dict, key: str, payload: dict) -> None:
    if state.get("emitted", {}).get(key):
        print(f"  ledger: event '{key}' already emitted")
        return
    try:
        import chaba_event
        ok, via = chaba_event.send(payload)
        print(f"  ledger: event {'ok via ' + via if ok else 'failed: ' + via}")
        if ok:
            state.setdefault("emitted", {})[key] = (
                datetime.datetime.now().isoformat(timespec="seconds"))
            _save_state(state)
    except Exception as exc:
        print(f"  ledger: event failed: {exc}", file=sys.stderr)


def render(rows: list[dict], churn: dict[str, dict[str, dict]]) -> str:
    now = datetime.datetime.now().astimezone()
    lines = [f"# Spend ledger — {now:%Y-%m-%d %H:%M}", "",
             "Daily Live-session + aux-call burn for the ada-* backends. "
             "est $ uses the usage_tracker rate table "
             "(Flash-Live audio $3/$12, text $0.30/$0.60 per 1M); "
             "ws = 'client connected' journal lines, up = upstream "
             "provider reconnects.", "",
             "| date | live sessions | turns | aux calls | tokens in/out"
             " | ws/up connects | est $ |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        churn_s = " ".join(
            f"{u.replace('ada-ha-', '').replace('ada-', '')}:"
            f"{c.get('ws', 0)}/{c.get('upstream', 0)}"
            for u, c in sorted((churn.get(r["date"]) or {}).items()))
        lines.append(
            f"| {r['date']} | {r['live_sessions']} | {r['turns']} "
            f"| {r['aux_calls']} | {r['in']:,}/{r['out']:,} "
            f"| {churn_s or '—'} | ~${r['est_usd']:.2f} |")
    if not rows:
        lines.append("| — | no usage records | | | | | |")
    lines += ["",
              "## Tripwires", "",
              f"- warn when est $/day > ${os.environ.get('SPEND_WARN_USD', '2.0')}"
              f" or live sessions/day > {os.environ.get('SPEND_WARN_SESSIONS', '300')}",
              "- reconnect churn warn lives in scenario-provider-gate.py "
              "(runs before every smoke tier)",
              "",
              f"*Generated by spend-ledger.py · {now:%Y-%m-%d %H:%M} · "
              "sources: usage.jsonl + journald*"]
    return "\n".join(lines)


def publish(rows: list[dict], body: str, today: str) -> None:
    now = datetime.datetime.now().astimezone()
    latest = rows[-1] if rows else {}
    summary = (f"{today}: {latest.get('live_sessions', 0)} live sessions, "
               f"{latest.get('aux_calls', 0)} aux calls, "
               f"~${latest.get('est_usd', 0):.2f} est — "
               f"{len(rows)}d window")
    meta = {"kind": ["report"], "slug": [PAGE_KEY], "subject": [PAGE_KEY],
            "title": ["Spend ledger"], "format": ["markdown"],
            "lang": ["en"], "domain": ["ops"],
            "summary": [summary[:240]], "fresh_for": ["1d"],
            "confidence": ["medium"], "report_role": ["ledger"],
            "generated_by": ["spend-ledger.py"],
            "written_by": ["spend-ledger.py"], "source": ["api"],
            "bank": ["cms"], "scope": ["tony"], "status": ["active"],
            "attribute": ["ledger"], "sources": ["usage.jsonl", "journald"],
            "valid_from": [now.date().isoformat()],
            "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()],
            "timeline": [f"{now.isoformat(timespec='minutes')} ledger: "
                         f"{summary}"]}
    try:
        old = _post("/get", {"collection": COLLECTION, "key": PAGE_KEY,
                             "lang": "en"})
        if old:
            om = old.get("meta") or {}
            tl = [x for x in (om.get("timeline") or [])
                  if isinstance(x, str)]
            meta["timeline"] = (tl + meta["timeline"])[-40:]
            for k in ("valid_from",):
                if om.get(k):
                    meta[k] = om[k]
    except Exception:
        pass
    _post("/add", {"collection": COLLECTION, "key": PAGE_KEY,
                   "lang": "en", "contentMd": body, "meta": meta})
    _post("/add", {
        "collection": REPORTS, "key": f"report/spend-{today}",
        "lang": "en", "contentMd": body,
        "meta": {"kind": ["report"], "subject": ["spend-ledger"],
                 "scenario": ["spend"], "status": ["pass"],
                 "tier": ["ledger"],
                 "last_verified": [now.date().isoformat()],
                 "valid_until": [(now.date()
                                  + datetime.timedelta(days=30))
                                 .isoformat()]},
        "ttl": 30 * 86400})


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=KEEP_DAYS)
    ap.add_argument("--churn-days", type=int, default=2,
                    help="how many trailing days get journald churn "
                         "columns (older rows keep their last numbers)")
    ap.add_argument("--usage-log", type=Path, default=USAGE_LOG)
    ap.add_argument("--units", default=",".join(UNITS))
    ap.add_argument("--no-journal", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=LOCAL_OUT)
    args = ap.parse_args()

    usage = load_usage(args.usage_log, args.days)
    days = sorted(usage)
    today = datetime.date.today().isoformat()

    # journald churn per unit — only the newest --churn-days days;
    # scanning 14d x 5 units of user journal on every hourly post-smoke
    # refresh is the wrong trade.
    churn: dict[str, dict[str, dict]] = {}
    if not args.no_journal:
        churn_days = (days or [today])[-args.churn_days:]
        if today not in churn_days:
            churn_days.append(today)
        for d in churn_days:
            day = datetime.date.fromisoformat(d)
            churn[d] = {}
            for u in [x.strip() for x in args.units.split(",") if x.strip()]:
                churn[d][u] = journal_day(u, day)

    rows = []
    for d in days:
        b = usage[d]
        rows.append({"date": d, "live_sessions": len(b["live_sessions"]),
                     "turns": b["turns"], "aux_calls": b["aux_calls"],
                     "in": b["in"], "out": b["out"], "cached": b["cached"],
                     "tool_use": b["tool_use"], "est_usd": _est_cost(b),
                     "sources": dict(b["sources"])})

    body = render(rows, churn)
    if args.dry_run:
        print(body)
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    ledger = args.out / "spend-ledger.jsonl"
    merged = {}
    try:
        for line in ledger.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                merged[r["date"]] = r
    except (OSError, ValueError):
        pass
    for r in rows:
        merged[r["date"]] = r
    ledger.write_text("".join(json.dumps(merged[d], ensure_ascii=False)
                              + "\n" for d in sorted(merged)))
    print(f"{len(rows)} days -> {ledger}")

    publish(rows, body, today)
    print(f"published ada-cms-pages/{PAGE_KEY} + report/spend-{today}")

    # tripwires — once per day each
    state = _load_state()
    warn_usd = float(os.environ.get("SPEND_WARN_USD", "2.0"))
    warn_sessions = int(os.environ.get("SPEND_WARN_SESSIONS", "300"))
    for r in rows:
        if r["date"] != today:
            continue
        if r["est_usd"] > warn_usd:
            maybe_emit(state, f"spend-usd:{today}", {
                "title": "spend ledger: est $ over threshold",
                "category": "ada-scenario", "source": "spend-ledger",
                "severity": "warn", "requires_response": False,
                "confidence": 0.7,
                "body": (f"{today}: ~${r['est_usd']:.2f} est burn "
                         f"(>${warn_usd}/day), {r['live_sessions']} live "
                         f"sessions, {r['aux_calls']} aux calls")})
        if r["live_sessions"] > warn_sessions:
            maybe_emit(state, f"spend-sessions:{today}", {
                "title": "spend ledger: live-session count over threshold",
                "category": "ada-scenario", "source": "spend-ledger",
                "severity": "warn", "requires_response": False,
                "confidence": 0.7,
                "body": (f"{today}: {r['live_sessions']} live sessions "
                         f"(>{warn_sessions}/day), ~${r['est_usd']:.2f} est")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
