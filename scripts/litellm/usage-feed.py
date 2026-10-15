#!/usr/bin/env python3
"""usage-feed.py — aggregate usage feed for the Plesk pull-render worker.

(card wp-usage-pull-render-plesk-worker, OPS-0661) Emits ONE aggregate
JSON — flat day x lane rows only, no raw session data — that the
chaba-boards PHP worker pulls through the token-gated idc02 caddy-edge
path and buckets into the report CPT / usage timeline. All bucketing is
Plesk-side; this file only aggregates.

Sources (all on idc03):
  * ~/CascadeProjects/ada-voice/data/usage.jsonl — backend usage ledger
    (usage_tracker.py). Row -> {date, lane, turns, sessions, aux_calls,
    tok_in, tok_out, tok_cached, tool_use, est_usd}. Lane = rec.unit/lane/
    backend when present, else "ada-backends" (the file is shared across
    ada-* units; journald caller-share stays out of the feed — per-lane
    truth for gateway traffic comes from SpendLogs key aliases).
    est_usd uses the same RATES_PER_MILLION table as usage_tracker /
    spend-ledger.py — verify against ai.google.dev pricing when it drifts.
  * LiteLLM_SpendLogs (podman exec litellm-db psql; admin API fallback)
    -> {date, lane, key, model, calls, tokens, spend_usd}. Lane from
    --key-lanes map (alias -> lane), default passthrough.

Output:
  {"feed": "chaba-usage/v1", "generated_at": <utc>, "window_days": N,
   "sources": {...}, "usage": [...], "spend": [...]}

Transport: --push scp's the JSON to the idc02 caddy-edge webroot
(default ~/.config/containers/caddy/data/www/feeds/usage.json — same
docroot cms-publish-site.py writes; caddy serves it under a bearer gate).
Fleet ssh mesh (scripts/ops/ssh-mesh-sync.sh) supplies idc03->idc02.

Usage:
  usage-feed.py                    # write feed to stdout
  usage-feed.py --days 14 --out /tmp/usage.json
  usage-feed.py --push             # + scp to idc02 webroot
  usage-feed.py --dry-run          # print feed, no writes

Env: ADA_USAGE_LOG, LITELLM_URL, LITELLM_MASTER_KEY (API fallback),
USAGE_FEED_TARGET (default "idc2:.config/containers/caddy/data/www/feeds/usage.json"
— ssh name per ssh-mesh), USAGE_FEED_KEY_LANES (JSON alias->lane).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

USAGE_LOG = Path(os.environ.get(
    "ADA_USAGE_LOG",
    "~/CascadeProjects/ada-voice/data/usage.jsonl")).expanduser()
GW = os.environ.get("LITELLM_URL", "http://100.102.134.91:4000").rstrip("/")
MASTER = os.environ.get("LITELLM_MASTER_KEY", "")
PUSH_TARGET = os.environ.get(
    "USAGE_FEED_TARGET",
    "idc02:.config/containers/caddy/data/www/feeds/usage.json")

# Virtual-key alias -> member lane. Passthrough default = the alias
# itself. LITELLM_KEY_* names minted by scripts/litellm/mint-key.sh.
KEY_LANES = {"chaba": "tony", "michael": "michael", "kk": "kk",
             "bench": "bench", "<master>": "master"}
try:
    KEY_LANES.update(json.loads(os.environ.get("USAGE_FEED_KEY_LANES", "{}")))
except ValueError:
    pass

# Mirror of backend/usage_tracker.py RATES_PER_MILLION (USD/1M tokens,
# Sept-2026 Flash-Live audio + Flash-Lite) — keep in sync with
# scripts/ada/spend-ledger.py.
RATES_PER_MILLION = {
    "audio": {"in": 3.00, "out": 12.00},
    "text": {"in": 0.30, "out": 0.60},
    "image": {"in": 0.30, "out": 0.0},
    "video": {"in": 0.30, "out": 0.0},
    "document": {"in": 0.30, "out": 0.0},
    "unknown": {"in": 3.00, "out": 12.00},
}
CACHED_RATE_FRACTION = 0.25

SPEND_SQL = """
SELECT date_trunc('day', "startTime")::date AS day,
       coalesce(api_key,'<master>') AS key_alias, model,
       count(*) AS calls, round(sum(spend)::numeric, 6) AS spend_usd,
       sum(total_tokens) AS tokens
FROM "LiteLLM_SpendLogs"
WHERE "startTime" >= now() - interval '%d days'
GROUP BY 1,2,3 ORDER BY 1, 5 DESC;
"""


def _rate(modality: str, direction: str) -> float:
    return RATES_PER_MILLION.get(
        modality, RATES_PER_MILLION["unknown"])[direction]


def _new_lane_day() -> dict:
    return {"turns": 0, "aux_calls": 0, "tok_in": 0, "tok_out": 0,
            "tok_cached": 0, "tool_use": 0,
            "live_sessions": set(),
            "in_mod": defaultdict(int), "out_mod": defaultdict(int),
            "sources": defaultdict(int)}


def load_usage(path: Path, days: int) -> tuple[list[dict], str]:
    """usage.jsonl -> flat [{date, lane, ...}] rows + status string."""
    cutoff = (datetime.datetime.now().astimezone()
              - datetime.timedelta(days=days)).date()
    buckets: dict[tuple[str, str], dict] = {}
    try:
        fh = path.open()
    except OSError as e:
        return [], f"unreadable: {e}"
    import re
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
                ts = datetime.datetime.fromisoformat(str(rec.get("ts") or ""))
            except ValueError:
                continue
            day = ts.astimezone().date()
            if day < cutoff:
                continue
            src = str(rec.get("source") or "unknown")
            # skip synthetic test rows — same guard as spend-ledger.py:
            # real live session ids are 10-hex.
            sid = str(rec.get("session_id") or "")
            if src == "live" and sid and \
                    not re.fullmatch(r"[0-9a-f]{10}", sid):
                continue
            lane = str(rec.get("lane") or rec.get("unit")
                       or rec.get("backend") or "ada-backends")
            b = buckets.setdefault((day.isoformat(), lane), _new_lane_day())
            b["sources"][src] += 1
            b["tok_in"] += int(rec.get("in", 0) or 0)
            b["tok_out"] += int(rec.get("out", 0) or 0)
            b["tok_cached"] += int(rec.get("cached", 0) or 0)
            b["tool_use"] += int(rec.get("tool_use", 0) or 0)
            b["turns"] += 1
            for mod, n in (rec.get("in_mod") or {}).items():
                b["in_mod"][str(mod)] += int(n)
            for mod, n in (rec.get("out_mod") or {}).items():
                b["out_mod"][str(mod)] += int(n)
            if src == "live":
                if sid:
                    b["live_sessions"].add(sid)
            else:
                b["aux_calls"] += 1
    rows = []
    for (day, lane), b in sorted(buckets.items()):
        cost = 0.0
        for mod, n in b["in_mod"].items():
            cost += n * _rate(mod, "in")
        for mod, n in b["out_mod"].items():
            cost += n * _rate(mod, "out")
        cost += max(0, b["tok_in"] - sum(b["in_mod"].values())) \
            * _rate("unknown", "in")
        cost += max(0, b["tok_out"] - sum(b["out_mod"].values())) \
            * _rate("unknown", "out")
        cost += b["tok_cached"] * _rate("unknown", "in") * CACHED_RATE_FRACTION
        rows.append({"date": day, "lane": lane,
                     "turns": b["turns"],
                     "sessions": len(b["live_sessions"]),
                     "aux_calls": b["aux_calls"],
                     "tok_in": b["tok_in"], "tok_out": b["tok_out"],
                     "tok_cached": b["tok_cached"],
                     "tool_use": b["tool_use"],
                     "est_usd": round(cost / 1_000_000, 4),
                     "sources": dict(b["sources"])})
    return rows, "ok"


def _lane(alias: str) -> str:
    a = alias.rstrip("…").strip()
    for k, v in KEY_LANES.items():
        if a.startswith(k.rstrip("…")):
            return v
    return a or "unknown"


def spend_via_psql(days: int) -> list[dict]:
    out = subprocess.run(
        ["podman", "exec", "litellm-db", "psql", "-U", "litellm",
         "-d", "litellm", "-At", "-F", "|", "-c", SPEND_SQL % days],
        capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    rows = []
    for line in out.stdout.strip().splitlines():
        day, key, model, calls, spend, toks = \
            (line.split("|") + [""] * 6)[:6]
        rows.append({"date": day, "key": key[:24],
                     "lane": _lane(key), "model": model,
                     "calls": int(calls or 0), "tokens": int(toks or 0),
                     "spend_usd": float(spend or 0)})
    return rows


def spend_via_api(days: int) -> list[dict]:
    start = time.strftime("%Y-%m-%d",
                          time.gmtime(time.time() - days * 86400))
    end = time.strftime("%Y-%m-%d", time.gmtime())
    req = urllib.request.Request(
        f"{GW}/global/spend/report?start_date={start}&end_date={end}",
        headers={"Authorization": f"Bearer {MASTER}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    rows = []
    for grp in data or []:
        meta = grp.get("metadata") or {}
        key = str(meta.get("api_key", "?"))
        rows.append({"date": grp.get("startTime", start)[:10],
                     "key": key[:24], "lane": _lane(key),
                     "model": grp.get("model", "?"),
                     "calls": int(meta.get("api_calls", 0)),
                     "tokens": int(meta.get("total_tokens", 0)),
                     "spend_usd": float(grp.get("spend", 0))})
    return rows


def push(local: Path, target: str) -> str:
    """scp feed -> idc02 webroot via a .tmp + rename (no partial reads)."""
    host, _, rpath = target.partition(":")
    tmp = rpath + ".tmp"
    subprocess.run(["scp", "-q", str(local), f"{host}:{tmp}"],
                   check=True, timeout=60)
    subprocess.run(["ssh", host, f"mv -f '{tmp}' '{rpath}'"],
                   check=True, timeout=30)
    return f"{host}:{rpath}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--usage-log", type=Path, default=USAGE_LOG)
    ap.add_argument("--out", type=Path,
                    default=Path("/tmp/usage-feed.json"))
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--target", default=PUSH_TARGET,
                    help="ssh_host:remote/path — fleet ssh mesh name")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    usage_rows, usage_status = load_usage(args.usage_log, args.days)
    spend_rows, spend_src = [], None
    try:
        spend_rows, spend_src = spend_via_psql(args.days), \
            "postgres:LiteLLM_SpendLogs"
    except Exception as e:
        if MASTER:
            try:
                spend_rows, spend_src = spend_via_api(args.days), \
                    "admin:/global/spend/report"
            except Exception as e2:
                spend_src = f"psql:{e}; api:{e2}"
        else:
            spend_src = f"psql:{e} (no LITELLM_MASTER_KEY for fallback)"

    feed = {"feed": "chaba-usage/v1",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                          time.gmtime()),
            "window_days": args.days,
            "sources": {"usage_jsonl": usage_status,
                        "litellm_spend": spend_src or "no rows"},
            "usage": usage_rows,
            "spend": spend_rows}
    out = json.dumps(feed, indent=1)
    if args.dry_run:
        print(out)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(out + "\n")
    print(f"{len(usage_rows)} usage rows, {len(spend_rows)} spend rows "
          f"-> {args.out} ({len(out)} bytes)")
    if args.push:
        dest = push(args.out, args.target)
        print(f"pushed -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
