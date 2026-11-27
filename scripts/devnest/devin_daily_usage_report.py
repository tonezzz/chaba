#!/usr/bin/env python3
"""One daily Devin usage report: local burn + cloud sessions + manual meter.

This is the hands-off half of the quota workflow. It combines:

  * scripts/devin/devin-usage.py --days N --json  (local dispatch burn)
  * v3 GET /organizations/{org}/sessions/<id> for each session launched by
    devin_cloud_runner (per-session ACU / PRs / on-demand)
  * --remaining-pct / --start-pct, the one operator-supplied meter reading
    (plan allowance remaining is NOT machine-readable on Pro)

It writes a single Markdown report plus a JSON artifact under docs/reports/.
It never launches sessions, spends quota, or mutates a board card.

Usage::

    python3 scripts/devnest/devin_daily_usage_report.py --days 1 --remaining-pct 4
"""
from __future__ import annotations

import argparse
import collections
import importlib
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
_runner = importlib.import_module("devin_cloud_runner")

STOP_STATUSES = _runner.STOP_STATUSES
CLI_DB = Path.home() / ".local" / "share" / "devin" / "cli" / "sessions.db"
FREE_WINDOW_END = "2026-12-04 18:00 UTC"
FLEET_HOSTS = ("tony-omen", "tony-dell", "tony-macbook", "con01")
LOCAL_CONFIG = Path.home() / ".config" / "devin" / "config.json"
# Confirmed `[Free]` by `devin models list` on this account (2026-11-26).
# *-lightning variants are paid ($1/$5 per 1M) and must never match.
FREE_MODEL = re.compile(
    r"^swe-(2|2-1|2-flash)(-(medium|high|max|low|xhigh))?$")


def fleet_model_audit() -> list[dict]:
    """Read agent.model from each dispatch host's Devin config, read-only."""
    rows = []

    def read(host: str, text: str | None) -> None:
        model = None
        error = None
        try:
            model = (json.loads(text or "{}").get("agent") or {}).get("model")
        except Exception as exc:
            error = type(exc).__name__
        if model and FREE_MODEL.fullmatch(str(model)) and "lightning" not in str(model):
            verdict = "free-now"
        elif model:
            verdict = "NOT-FREE — flag for review"
        else:
            verdict = "unverified — no pinned model"
        rows.append({"host": host, "model": model, "verdict": verdict,
                     "error": error})

    try:
        read("idc02", LOCAL_CONFIG.read_text(encoding="utf-8"))
    except Exception as exc:
        read("idc02", None)
        rows[-1]["error"] = type(exc).__name__
    for host in FLEET_HOSTS:
        try:
            p = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                 host, "cat /home/tony/.config/devin/config.json"],
                capture_output=True, text=True, timeout=25)
            read(host, p.stdout if p.returncode == 0 else None)
        except Exception as exc:
            read(host, None)
            rows[-1]["error"] = type(exc).__name__
    return rows


def local_cli_sessions(days: int) -> dict:
    """Interactive Devin CLI sessions from sessions.db.

    The DB stores per-message num_tokens but not a prompt/cache/output
    split, so this is an approximate burn signal, not a cost figure.
    """
    if not CLI_DB.exists():
        return {"sessions": 0, "num_tokens": 0, "rows": []}
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    con = sqlite3.connect(f"file:{CLI_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        sessions = [dict(r) for r in con.execute(
            "select id, title, model, created_at from sessions where created_at>=?",
            (cutoff,))]
        per = collections.Counter()
        for r in con.execute(
                "select session_id, chat_message from message_nodes where created_at>=?",
                (cutoff,)):
            try:
                meta = json.loads(r["chat_message"] or "{}").get("metadata") or {}
            except Exception:
                continue
            n = meta.get("num_tokens")
            if isinstance(n, (int, float)):
                per[r["session_id"]] += n
    finally:
        con.close()
    rows = [{"id": s["id"], "title": s["title"], "model": s["model"],
             "num_tokens": int(per.get(s["id"], 0))} for s in sessions]
    rows.sort(key=lambda r: -r["num_tokens"])
    return {"sessions": len(rows),
            "num_tokens": sum(r["num_tokens"] for r in rows),
            "rows": rows[:10],
            "note": "per-message num_tokens only; no prompt/cache/output split"}


def local_burn(days: int) -> list[dict]:
    script = REPO / "scripts" / "devin" / "devin-usage.py"
    p = subprocess.run(
        [sys.executable, str(script), "--days", str(days), "--json"],
        capture_output=True, text=True, timeout=180,
    )
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[:300])
    return json.loads(p.stdout or "[]")


def cloud_sessions(hours: int) -> list[dict]:
    state = _runner.load_state()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    for entry in state.get("launched", []):
        try:
            at = datetime.fromisoformat(entry["at"])
        except Exception:
            continue
        if at < cutoff or not entry.get("session_id"):
            continue
        try:
            d = _runner.api("GET", f"/v3/organizations/{_runner.org_id()}/sessions/"
                            f"{entry['session_id']}")
        except Exception as exc:
            rows.append({"card_ref": entry.get("card_ref"),
                         "session_id": entry["session_id"],
                         "error": type(exc).__name__})
            continue
        detail = d.get("status_detail")
        rows.append({
            "card_ref": entry.get("card_ref"),
            "task_id": entry.get("task_id"),
            "session_id": d.get("session_id"),
            "url": d.get("url"),
            "mode": entry.get("mode"),
            "launched_at": entry.get("at"),
            "status": d.get("status"),
            "status_detail": detail,
            "acus_consumed": d.get("acus_consumed"),
            "on_demand_usage": d.get("on_demand_usage"),
            "pull_requests": d.get("pull_requests") or [],
            "stop_reason": detail if detail in STOP_STATUSES else None,
        })
    return rows


def markdown(report: dict) -> str:
    now = report["generated_at"]
    q = report["quota"]
    lines = [
        f"# Devin daily usage — {now[:10]}",
        "",
        f"Generated {now}. Source: local task transcripts + Devin v3 session API "
        "+ operator meter reading.",
        "",
        "## Quota",
        "",
        f"- Daily remaining (operator): **{q['remaining_pct']}%**"
        if q.get("remaining_pct") is not None else
        "- Daily remaining: not supplied (read app.devin.ai/settings/usage)",
        f"- Daily used at start: {q['start_used_pct']}%"
        if q.get("start_used_pct") is not None else "- Daily used at start: not supplied",
        "- Allowance remaining is **not machine-readable on Pro** — consumption API "
        "is Enterprise-only, `devin` has no usage subcommand. The percentage above "
        "is the one manual input.",
        "",
        "## Local dispatch burn",
        "",
        f"- Sessions: {report['local']['sessions']}",
        f"- Prompt tokens: {report['local']['prompt']:,}",
        f"- Cached tokens: {report['local']['cached']:,}",
        f"- Output tokens: {report['local']['completion']:,}",
        f"- Models: {', '.join(report['local']['models']) or 'none'}",
        "",
        "| Task | Model | Prompt | Cached | Steps |",
        "|---|---|---:|---:|---:|",
    ]
    for r in report["local"]["rows"][:25]:
        lines.append(f"| {str(r.get('task'))[:48]} | {r.get('model') or '?'} | "
                     f"{(r.get('prompt') or 0):,} | {(r.get('cached') or 0):,} | "
                     f"{r.get('steps') or 0} |")
    cli = report["local_cli"]
    lines += [
        "",
        "## Interactive local CLI sessions",
        "",
        f"- Sessions created: {cli['sessions']}",
        f"- Sum of per-message num_tokens: {cli['num_tokens']:,} "
        "(approximate — no prompt/cache/output split in sessions.db)",
        f"- SWE-2 Flash is free in CLI/Desktop until {FREE_WINDOW_END}; "
        "after that these tokens bill at documented rates.",
        "",
        "| Session | Model | num_tokens |",
        "|---|---|---:|",
    ]
    for r in cli["rows"]:
        lines.append(f"| {str(r.get('title') or r.get('id'))[:48]} | "
                     f"{r.get('model') or '?'} | {r.get('num_tokens', 0):,} |")
    audit = report["model_audit"]
    lines += [
        "",
        "## Local model audit",
        "",
        f"Free-model window ends {FREE_WINDOW_END}; after that these models "
        "bill at documented rates.",
        "",
        "| Host | agent.model | Verdict |",
        "|---|---|---|",
    ]
    for r in audit:
        lines.append(f"| {r['host']} | {r.get('model') or 'none'} | "
                     f"{r['verdict']} |")
    lines += [
        "",
        "## Cloud handoffs",
        "",
        "| Card | Session | Status | ACU | PRs | On-demand |",
        "|---|---|---|---:|---|---|",
    ]
    for r in report["cloud"]:
        prs = ", ".join(p.get("pr_url", "") for p in r.get("pull_requests", [])) or "-"
        lines.append(f"| {r.get('card_ref') or '?'} | {str(r.get('session_id'))[:10]} | "
                     f"{r.get('status')}/{r.get('status_detail') or '-'} | "
                     f"{r.get('acus_consumed')} | {prs} | "
                     f"{r.get('on_demand_usage')} |")
    lines += [
        "",
        "## Cost per useful task",
        "",
        report["cost_note"],
        "",
        "No new sessions were launched by this report.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--hours", type=int, default=24,
                    help="how recent launched cloud sessions must be")
    ap.add_argument("--remaining-pct", type=float, default=None)
    ap.add_argument("--start-used-pct", type=float, default=None,
                    help="daily %% used at the start of the window (e.g. 4)")
    ap.add_argument("--out-dir", default=str(REPO / "docs" / "reports"))
    args = ap.parse_args()

    try:
        burn = local_burn(args.days)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"local burn: {exc}"[:300]}))
        return 2

    cloud = cloud_sessions(args.hours)
    prs = [p for r in cloud for p in r.get("pull_requests", [])
           if p.get("pr_url")]
    if args.remaining_pct is not None and args.start_used_pct is not None and prs:
        used_now = 100.0 - args.remaining_pct
        delta = used_now - args.start_used_pct
        if delta > 0:
            cost_note = (f"Daily used moved from {args.start_used_pct:g}% to "
                         f"{used_now:g}% (+{delta:.1f} points) for {len(prs)} PR(s) "
                         f"→ roughly {delta/len(prs):.1f} quota-points per PR. "
                         "Confirm ACU at completion before setting a hard cap.")
        else:
            cost_note = (f"Daily used is still {used_now:g}% (from "
                         f"{args.start_used_pct:g}%) — the meter has not moved yet; "
                         "both sessions are still running. Recheck after completion.")
    elif args.remaining_pct is not None:
        cost_note = (f"Daily remaining {args.remaining_pct}% — supply "
                     "--start-used-pct to compute the delta per PR.")
    else:
        cost_note = "No meter reading supplied; per-task quota cost cannot be derived here."

    rows = []
    for r in burn:
        rows.append({k: r.get(k) for k in
                     ("task", "session", "model", "prompt", "cached",
                      "completion", "steps", "host", "finished_at")})
    report = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quota": {"remaining_pct": args.remaining_pct,
                  "start_used_pct": args.start_used_pct},
        "local": {
            "sessions": len(burn),
            "prompt": sum(int(r.get("prompt") or 0) for r in burn),
            "cached": sum(int(r.get("cached") or 0) for r in burn),
            "completion": sum(int(r.get("completion") or 0) for r in burn),
            "models": sorted({r.get("model") or "?" for r in burn}),
            "rows": rows,
        },
        "local_cli": local_cli_sessions(args.days),
        "model_audit": fleet_model_audit(),
        "cloud": cloud,
        "cost_note": cost_note,
    }
    out = Path(args.out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    stem = f"devin-daily-usage-{report['generated_at'][:10]}"
    md, js = out / f"{stem}.md", out / f"{stem}.json"
    md.write_text(markdown(report), encoding="utf-8")
    js.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "markdown": str(md), "json": str(js),
                      "local_sessions": len(burn),
                      "local_cli_sessions": report["local_cli"]["sessions"],
                      "cloud_sessions": len(cloud),
                      "prs": len(prs), "cost_note": cost_note}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
