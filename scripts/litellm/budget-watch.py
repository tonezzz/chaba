#!/usr/bin/env python3
"""budget-watch.py — LiteLLM virtual-key budget monitor (card
model-key-usage-control, SEC-0962).

The 2026-10-24 incident showed the gap: the chaba key hit its $5/30d cap
mid-eval (422 storm in the proxy log), an operator had to bump caps
manually, and nobody noticed until callers died. key-watch.py covers OR
keys/HA/CF/Gemini-direct probes but NOT LiteLLM VerificationToken
budgets — this closes that hole.

Reads LiteLLM_VerificationToken (key_alias, max_budget, spend,
budget_duration, budget_reset_at, models allowlist) and judges each key:
  spend >= max_budget            -> alert (callers are 422ing NOW)
  spend >= max_budget * warn_pct -> warn  (approaching cap)
  max_budget is null/0           -> note  (uncapped key — flagged, not judged)
Report is metadata only — key aliases, never key values.

Sources (same duality as daily-ledger.py):
  psql   podman exec litellm-db psql        — run on idc03 (default)
  api    GET /key/list w/ LITELLM_MASTER_KEY — off-host fallback
  file   --json <path>  canned rows          — tests/selftest

Output: JSON report to stdout; one kind=ops-event doc per run
(type: budget_watch) in ada-ha-events-tony; LINE push + incident card
on alert findings unless --dry-run. Quiet hours defer the push only
(same policy as key-watch).

    python3 scripts/litellm/budget-watch.py              # probe + emit
    python3 scripts/litellm/budget-watch.py --dry-run    # print only
    python3 scripts/litellm/budget-watch.py --selftest
    python3 scripts/litellm/budget-watch.py --json fixture.json --dry-run

Env: LITELLM_URL, LITELLM_MASTER_KEY, LITELLM_DB_CONTAINER,
     MDDB_BASE_URL, BOARD_API, KEY_WATCH_RELAY_URL,
     BUDGET_WATCH_WARN_PCT (default 80), BUDGET_WATCH_QUIET ("0-7"),
     BUDGET_WATCH_STATE, BUDGET_WATCH_RESEND_MIN.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ICT = datetime.timezone(datetime.timedelta(hours=7))

GW = os.environ.get("LITELLM_URL", "http://100.102.134.91:4000").rstrip("/")
MASTER = os.environ.get("LITELLM_MASTER_KEY", "")
DB_CONTAINER = os.environ.get("LITELLM_DB_CONTAINER", "litellm-db")
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
OPS_COLLECTION = "ada-ha-events-tony"
RELAY_URL = os.environ.get("KEY_WATCH_RELAY_URL", "http://127.0.0.1:8912/send")
STATE = Path(os.environ.get(
    "BUDGET_WATCH_STATE", "~/.local/state/litellm-budget-watch.json")
    ).expanduser()
WARN_PCT = float(os.environ.get("BUDGET_WATCH_WARN_PCT", "80"))
QUIET = tuple(int(x) for x in
              os.environ.get("BUDGET_WATCH_QUIET", "0-7").split("-", 1))
RESEND_MIN = int(os.environ.get("BUDGET_WATCH_RESEND_MIN", "240"))

SQL = """
SELECT coalesce(key_alias,'<unnamed>'), max_budget, budget_duration,
       spend, budget_reset_at, models
FROM "LiteLLM_VerificationToken" ORDER BY key_alias;
"""


def rows_via_psql() -> list[dict]:
    out = subprocess.run(
        ["podman", "exec", DB_CONTAINER, "psql", "-U", "litellm",
         "-d", "litellm", "-At", "-F", "|", "-c", SQL],
        capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    rows = []
    for line in out.stdout.strip().splitlines():
        alias, cap, dur, spend, reset, models = \
            (line.split("|") + [""] * 6)[:6]
        rows.append({"key_alias": alias,
                     "max_budget": float(cap) if cap else None,
                     "budget_duration": dur or None,
                     "spend": float(spend or 0),
                     "budget_reset_at": reset or None,
                     "models": models})
    return rows


def rows_via_api() -> list[dict]:
    req = urllib.request.Request(
        f"{GW}/key/list", headers={"Authorization": f"Bearer {MASTER}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    keys = data.get("keys") if isinstance(data, dict) else data
    rows = []
    for k in keys or []:
        info = k if isinstance(k, dict) else {}
        rows.append({"key_alias": info.get("key_alias") or "<unnamed>",
                     "max_budget": info.get("max_budget"),
                     "budget_duration": info.get("budget_duration"),
                     "spend": float(info.get("spend") or 0),
                     "budget_reset_at": info.get("budget_reset_at"),
                     "models": info.get("models")})
    return rows


def judge(row: dict) -> dict:
    """-> {level: ok|warn|alert|note, pct, why} for one key row."""
    alias = row.get("key_alias") or "<unnamed>"
    cap = row.get("max_budget")
    spend = float(row.get("spend") or 0)
    if not cap:
        return {"level": "note", "pct": None,
                "why": f"{alias}: uncapped (no max_budget) — "
                       f"spend ${spend:.3f} unbounded"}
    pct = spend / cap * 100
    reset = row.get("budget_reset_at") or "?"
    base = f"{alias}: ${spend:.3f}/${cap:g} ({pct:.0f}%), reset {reset}"
    if spend >= cap:
        return {"level": "alert", "pct": pct,
                "why": f"{base} — AT/OVER cap, calls are being 422'd"}
    if pct >= WARN_PCT:
        return {"level": "warn", "pct": pct,
                "why": f"{base} — near cap"}
    return {"level": "ok", "pct": pct, "why": base}


def report(rows: list[dict]) -> dict:
    findings = [{"key_alias": r.get("key_alias"), **judge(r),
                 "spend": r.get("spend"), "max_budget": r.get("max_budget"),
                 "budget_duration": r.get("budget_duration"),
                 "budget_reset_at": r.get("budget_reset_at"),
                 "models": r.get("models")} for r in rows]
    alerts = [f for f in findings if f["level"] == "alert"]
    warns = [f for f in findings if f["level"] == "warn"]
    return {"run": datetime.datetime.now(
                datetime.timezone.utc).isoformat(timespec="seconds"),
            "verdict": "alert" if alerts else "warn" if warns else "ok",
            "warn_pct": WARN_PCT,
            "findings": findings,
            "alerts": len(alerts), "warns": len(warns)}


# --- sinks (key-watch.py pattern, trimmed) -----------------------------------

def mddb_post(path: str, payload: dict, timeout: int = 15):
    req = urllib.request.Request(
        f"{MDDB}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def emit_ops_event(rep: dict) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    bad = [f for f in rep["findings"] if f["level"] in ("warn", "alert")]
    md = [f"budget-watch run — verdict {rep['verdict']} "
          f"({len(rep['findings'])} keys, {len(bad)} finding(s))", ""]
    for f in rep["findings"]:
        if f["level"] != "ok":
            md.append(f"- [{f['level'].upper()}] {f['why']}")
    if not bad:
        md.append("- all keys under budget")
    try:
        mddb_post("/add", {
            "collection": OPS_COLLECTION,
            "key": f"ops-budget-watch-{now:%Y%m%d%H%M%S}",
            "lang": "en", "contentMd": "\n".join(md),
            "meta": {"kind": ["ops-event"], "type": ["budget_watch"],
                     "instance": ["idc03"], "verdict": [rep["verdict"]],
                     "findings": [str(len(bad))],
                     "ts": [now.isoformat(timespec="seconds")],
                     "written_by": ["budget-watch"]}})
        return "emitted"
    except Exception as e:
        return f"emit-failed {type(e).__name__}: {e}"


def send_line(text: str) -> tuple[bool, str]:
    payload = json.dumps({"text": text, "class": "critical"})
    try:
        req = urllib.request.Request(
            RELAY_URL, data=payload.encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            if '"ok":true' in r.read().decode().replace(" ", ""):
                return True, "relay-url"
    except Exception:
        pass
    return False, "relay unreachable"


def format_line(rep: dict) -> str:
    bad = [f for f in rep["findings"]
           if f["level"] in ("warn", "alert", "note")]
    lines = [f"💳 BUDGET-WATCH — {rep['alerts']} alert / "
             f"{rep['warns']} warn:"]
    lines += [f"  · {f['why'][:90]}" for f in bad]
    return "\n".join(lines)


def card_id(alias: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", alias.lower()).strip("-")
    return f"budget-watch-{slug}"[:60]


def file_incident(f: dict) -> str:
    cid = card_id(f["key_alias"])
    body = {"id": cid,
            "title": f"budget-watch: {f['key_alias']} at cap — "
                     f"{f['why'][:50]}",
            "column": "review", "review_kind": "triage",
            "brief": f"LiteLLM virtual key {f['key_alias']} hit its "
                     f"budget cap: {f['why']}",
            "note": ("Auto-filed by budget-watch. Raise the cap "
                     "(/key/update) or wait for reset "
                     f"{f.get('budget_reset_at')}, then close the card."),
            "priority": "high", "tags": ["litellm", "spend"],
            "from": "chaba"}
    req = urllib.request.Request(
        f"{BOARD_API}/card", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20):
            return f"filed {cid}"
    except urllib.error.HTTPError:
        req2 = urllib.request.Request(
            f"{BOARD_API}/comment",
            data=json.dumps({"id": cid, "from": "chaba",
                             "text": f"still alerting: {f['why']}"[:400]}
                            ).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req2, timeout=20)
            return f"exists {cid} (comment ok)"
        except Exception as e:
            return f"exists {cid} (comment {type(e).__name__})"
    except Exception as e:
        return f"card-failed {type(e).__name__}: {e}"


# --- selftest -----------------------------------------------------------------

SELFTEST_ROWS = [
    {"key_alias": "chaba", "max_budget": 20.0, "budget_duration": "30d",
     "spend": 19.72, "budget_reset_at": "2026-11-01", "models": "{}"},
    {"key_alias": "ada", "max_budget": 30.0, "budget_duration": "30d",
     "spend": 14.53, "budget_reset_at": "2026-11-01", "models": "{}"},
    {"key_alias": "bench", "max_budget": 2.0, "budget_duration": "30d",
     "spend": 2.01, "budget_reset_at": "2026-11-01", "models": "{bench}"},
    {"key_alias": "mddb", "max_budget": 10.0, "budget_duration": "30d",
     "spend": 0.13, "budget_reset_at": "2026-11-01", "models": "{}"},
    {"key_alias": "uncapped-test", "max_budget": None,
     "budget_duration": None, "spend": 3.0, "budget_reset_at": None,
     "models": "{}"},
]


def selftest() -> int:
    rep = report(SELFTEST_ROWS)
    by = {f["key_alias"]: f for f in rep["findings"]}
    for f in rep["findings"]:
        print(f"  {f['key_alias']:14} -> {f['level']:6} {f['why'][:80]}")
    assert by["bench"]["level"] == "alert", "bench over cap must alert"
    assert by["chaba"]["level"] == "warn", "chaba 98.6% must warn"
    assert by["ada"]["level"] == "ok", "ada 48% must be ok"
    assert by["mddb"]["level"] == "ok"
    assert by["uncapped-test"]["level"] == "note"
    assert rep["verdict"] == "alert"
    print("--- LINE preview ---\n" + format_line(rep))
    print("selftest OK")
    return 0


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", type=Path, help="canned key rows (tests)")
    ap.add_argument("--now", action="store_true",
                    help="ignore the LINE resend gap")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.json:
        rows = json.loads(args.json.read_text())
        source = f"file:{args.json}"
    else:
        rows, source = None, None
        try:
            rows, source = rows_via_psql(), "postgres:VerificationToken"
        except Exception as e:
            if not MASTER:
                sys.exit(f"psql failed ({e}) and no LITELLM_MASTER_KEY "
                         "for API fallback")
            rows, source = rows_via_api(), "admin:/key/list"

    rep = report(rows)
    rep["source"] = source
    print(json.dumps(rep, indent=2))

    st = load_state()
    now_epoch = datetime.datetime.now().timestamp()
    alerts = [f for f in rep["findings"] if f["level"] == "alert"]
    notes = []
    if not args.dry_run:
        open_cards = st.get("open_cards") or {}
        for f in alerts:
            if open_cards.get(f["key_alias"]):
                notes.append(f"{f['key_alias']} already carded")
                continue
            notes.append(file_incident(f))
            open_cards[f["key_alias"]] = card_id(f["key_alias"])
        st["open_cards"] = open_cards

    line_note = "quiet"
    if rep["verdict"] in ("warn", "alert"):
        quiet = QUIET[0] <= datetime.datetime.now(ICT).hour < QUIET[1]
        h = hashlib.sha1(json.dumps(
            [(f["key_alias"], f["level"]) for f in rep["findings"]],
            sort_keys=True).encode()).hexdigest()
        gap_min = (now_epoch - (st.get("line_sent") or 0)) / 60
        resend = st.get("line_hash") != h or gap_min >= RESEND_MIN
        if args.dry_run:
            line_note = "dry-run"
        elif quiet:
            line_note = "quiet-hours deferred"
        elif not (args.now or resend):
            line_note = f"unchanged set, sent {gap_min:.0f}m ago — skip"
        else:
            ok, via = send_line(format_line(rep))
            line_note = f"sent via {via}" if ok else f"FAILED {via}"
            st["line_hash"], st["line_sent"] = h, now_epoch
    print(f"LINE: {line_note}")

    ops = "dry-run" if args.dry_run else emit_ops_event(rep)
    print(f"ops-event: {ops}")
    for n in notes:
        print(f"  {n}")

    if not args.dry_run:
        st.update({"last_run": datetime.datetime.now(ICT).isoformat(
            timespec="seconds"), "verdict": rep["verdict"]})
        save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
