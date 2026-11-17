#!/usr/bin/env python3
"""fleet-jobs-report.py — Aggregator for per-host jobs/queue/lane status.

Emits a daily Markdown artifact + L2 metadata, then upserts one
`fleet-jobs-report` CMS page through board-api.
Reads from existing deterministic sources:
- Timer timelines (timeline.jsonl)
- Runner fleet health (~/var/chaba/health/)
- Board API /cards compact action projection
- Evidence-bound monthly lane usage (scripts/board/lane-savings.py)
- LiteLLM spend ledger (psql on litellm-db)
- Declared timers (docs/ssot/generated/jobs.<host>.yml)
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from lib.report import append_timeline, write_meta  # noqa: E402

BOARD_API = os.environ.get("BOARD_API", "http://127.0.0.1:8787").rstrip("/")
CLAIM_STATES = ("queued", "claimed", "running", "done", "failed")
STATUS_ALIASES = {"doing": "running"}


def safe_load_yaml(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

def read_timer_timelines() -> list[dict]:
    reports_dir = Path(os.environ.get("CHABA_REPORTS_DIR", "~/var/chaba/reports")).expanduser()
    timeline_path = reports_dir / "timeline.jsonl"
    events = []
    if timeline_path.exists():
        try:
            with open(timeline_path, "r", encoding="utf-8") as f:
                # Read last 1000 lines to avoid blowing up memory on huge logs
                lines = f.readlines()[-1000:]
                for line in lines:
                    if line.strip():
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception:
            pass
    return events

def read_runner_fleet_health() -> dict:
    health_dir = Path("~/var/chaba/health/").expanduser()
    health_data = {}
    if health_dir.exists():
        for p in health_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    health_data[p.stem] = json.load(f)
            except Exception:
                pass
    return health_data

def read_declared_timers() -> dict:
    generated_dir = REPO / "docs/ssot/generated"
    timers_by_host = {}
    if generated_dir.exists():
        for p in generated_dir.glob("jobs.*.yml"):
            host = p.stem.split(".")[1]
            data = safe_load_yaml(p)
            timers_by_host[host] = data.get("jobs", [])
    return timers_by_host


def collect_claim_stats(cards: list[dict]) -> dict:
    """Count real action states globally and by assigned runner/lane."""
    stats = {state: 0 for state in CLAIM_STATES}
    stats.update({"by_host": {}, "by_lane": {}})

    def bucket(mapping: dict, key: str) -> dict:
        return mapping.setdefault(key, {state: 0 for state in CLAIM_STATES})

    for data in cards:
        action = data.get("action") or {}
        status = STATUS_ALIASES.get(action.get("status"),
                                     action.get("status"))
        if status not in CLAIM_STATES:
            continue
        stats[status] += 1

        host = str(action.get("runner") or action.get("host")
                   or action.get("target_host") or "unassigned").strip()
        bucket(stats["by_host"], host)[status] += 1

        lane = str(action.get("lane") or "").strip()
        if lane:
            bucket(stats["by_lane"], lane)[status] += 1
    return stats


def read_claim_stats() -> dict:
    cards = []
    offset = 0
    page_size = 500
    while True:
        url = (f"{BOARD_API}/cards?fields=id,action&limit={page_size}"
               f"&offset={offset}")
        with urllib.request.urlopen(url, timeout=30) as response:
            page = json.load(response)
        if not isinstance(page, dict) or not page.get("ok"):
            raise RuntimeError("board-api returned an invalid card projection")
        batch = page.get("cards") or []
        cards.extend(batch)
        if not page.get("truncated"):
            break
        if not batch:
            raise RuntimeError("board-api pagination made no progress")
        offset += len(batch)
    return collect_claim_stats(cards)

def extract_litellm_spend() -> list[dict]:
    SPEND_SQL = """
    SELECT coalesce(api_key,'<master>') AS key_alias, model,
           count(*) AS calls, round(sum(spend)::numeric, 6) AS spend_usd,
           sum(total_tokens) AS tokens
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= now() - interval '24 hours'
    GROUP BY 1,2 ORDER BY spend_usd DESC;
    """
    rows = []
    try:
        out = subprocess.run(
            ["podman", "exec", "litellm-db", "psql", "-U", "litellm", "-d", "litellm",
             "-At", "-F", "|", "-c", SPEND_SQL],
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            for line in out.stdout.strip().splitlines():
                parts = line.split("|")
                if len(parts) >= 5:
                    key, model, calls, spend, toks = parts[:5]
                    rows.append({
                        "key": key,
                        "model": model,
                        "calls": int(calls or 0),
                        "spend_usd": float(spend or 0),
                        "tokens": int(toks or 0)
                    })
    except Exception:
        pass
    return rows


def read_lane_savings() -> dict:
    """Run the evidence-bound lane report into a temporary JSON artifact."""
    script = REPO / "scripts/board/lane-savings.py"
    try:
        with tempfile.TemporaryDirectory(prefix="fleet-lane-savings-") as td:
            output = Path(td) / "lane-savings.json"
            result = subprocess.run(
                [sys.executable, str(script), "--json-out", str(output)],
                capture_output=True, text=True, timeout=90)
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout)[-300:])
            return json.loads(output.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": str(e)[:300]}

def render_report(date_str: str, events: list[dict], health: dict,
                  claims: dict, spend: list[dict],
                  timers_by_host: dict, savings: dict) -> str:
    hosts = set(timers_by_host) | set(health)
    hosts |= set(claims.get("by_host", {})) - {"unassigned"}
    md = [f"# Fleet Jobs Report - {date_str}", "", "## Fleet Claim Totals"]
    for state in CLAIM_STATES:
        md.append(f"- {state.title()}: {claims.get(state, 0)}")
    unassigned = claims.get("by_host", {}).get("unassigned", {})
    md.append(f"- Unassigned queued: {unassigned.get('queued', 0)}")
    md.append("")

    for host in sorted(hosts):
        md.extend([
            f"## Host: {host}", "",
            "### Declared Timers (runtime state not probed)",
        ])
        declared = timers_by_host.get(host, [])
        md.append(f"- Declared jobs: {len(declared)}")
        for job in declared:
            md.append(
                f"  - `{job.get('id', 'unknown')}` "
                f"({job.get('dispatch', 'unknown')})")
        md.extend(["", "### Assigned Card Actions"])
        host_stats = claims.get("by_host", {}).get(host, {})
        for state in CLAIM_STATES:
            md.append(f"- {state.title()}: {host_stats.get(state, 0)}")

        md.extend(["", "### Last-run Failures"])
        failed_jobs = list((health.get(host) or {}).get("failed") or [])
        failed_jobs.extend(
            ev.get("timer", "unknown") for ev in events
            if ev.get("host") == host and ev.get("status") == "failing")
        if failed_jobs:
            md.extend(f"- `{fail}`" for fail in sorted(set(failed_jobs)))
        else:
            md.append("- No failures detected in the available sources.")
        md.append("")

    md.extend(["## Lanes", "### Action Status by Lane"])
    by_lane = claims.get("by_lane") or {}
    if by_lane:
        md.extend([
            "| Lane | Queued | Claimed | Running | Done | Failed |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for lane, row in sorted(by_lane.items()):
            md.append(
                f"| {lane} | {row.get('queued', 0)} | "
                f"{row.get('claimed', 0)} | {row.get('running', 0)} | "
                f"{row.get('done', 0)} | {row.get('failed', 0)} |")
    else:
        md.append("_(No lane-tagged actions.)_")
    md.extend(["", "### Evidence-bound Lane Usage"])
    lane_rows = savings.get("lanes") or {}
    if lane_rows:
        md.extend([
            "| Lane | Completed | Verified | Usage-evidenced tokens |",
            "|---|---:|---:|---:|",
        ])
        for lane, row in sorted(lane_rows.items()):
            md.append(
                f"| {lane} | {row.get('completed', 0)} | "
                f"{row.get('verified', 0)} | "
                f"{row.get('tokens_total', 0)} |")
        md.append(
            f"Pack-lane usage: {savings.get('pack_tokens', 0)} tokens; "
            f"recorded cost ${savings.get('pack_cost_usd', 0)}. "
            "These are usage totals, not an avoided-cost estimate.")
        if savings.get("unevidenced_lane_uses"):
            md.append(
                f"Unevidenced lane selections: "
                f"{len(savings['unevidenced_lane_uses'])}; excluded from "
                "savings claims.")
    elif savings.get("error"):
        md.append(f"_(Lane usage unavailable: {savings['error']})_")
    else:
        md.append("_(No lane-usage data for this period.)_")
    md.extend(["", "### LiteLLM Spend (trailing 24h)"])
    if spend:
        md.extend([
            "| Key | Model | Calls | Tokens | Spend (USD) |",
            "|---|---|---:|---:|---:|",
        ])
        for row in spend:
            md.append(
                f"| {row['key']} | {row['model']} | {row['calls']} | "
                f"{row['tokens']} | ${row['spend_usd']} |")
    else:
        md.append("_(No spend data available)_")
    return "\n".join(md) + "\n"


def publish_cms(content_md: str, date_str: str, summary: str) -> dict:
    body = {
        "mode": "create",
        "slug": "fleet-jobs-report",
        "title": f"Fleet Jobs Report - {date_str}",
        "content_md": content_md,
        "meta": {
            "layer": "L2-domain",
            "purpose": "per-host jobs/queue/lane status from existing sources",
            "summary": summary[:240],
            "fresh_for": "4h",
            "generated_by": "scripts/fleet-jobs-report.py",
        },
    }
    req = urllib.request.Request(
        f"{BOARD_API}/report",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def main() -> int:
    date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    output_md = REPO / f"reports/fleet-jobs-{date_str}.md"
    output_md.parent.mkdir(parents=True, exist_ok=True)
    events = read_timer_timelines()
    health = read_runner_fleet_health()
    claims = read_claim_stats()
    spend = extract_litellm_spend()
    timers_by_host = read_declared_timers()
    savings = read_lane_savings()
    hosts = set(timers_by_host) | set(health)
    hosts |= set(claims.get("by_host", {})) - {"unassigned"}
    content_md = render_report(date_str, events, health, claims, spend,
                                timers_by_host, savings)
    output_md.write_text(content_md, encoding="utf-8")

    summary = (f"Processed fleet jobs for {len(hosts)} hosts; "
               f"{claims.get('running', 0)} actions running; "
               f"{len(spend)} spend rows.")
    publish_error = ""
    try:
        publish_cms(content_md, date_str, summary)
    except Exception as e:
        publish_error = str(e)[:300]
        print(f"fleet-jobs-report: CMS publication failed: {publish_error}",
              file=sys.stderr)

    status = "error" if publish_error else "ok"
    meta_path = REPO / "reports/meta.fleet-jobs-report.yml"
    write_meta(
        meta_path,
        node="fleet-jobs-report",
        layer="L2-domain",
        generated_by="scripts/fleet-jobs-report.py",
        status=status,
        purpose="per-host jobs/queue/lane status from existing sources",
        summary=summary,
        sources=["timeline.jsonl", "health/", "board-api cards projection",
                 "litellm-db",
                 "jobs.*.yml", "lane-savings.py", "board-api /report"],
        children=[],
        extra={"hosts": sorted(hosts), "claims": claims,
               "lane_savings_month": savings.get("month"),
               "lane_savings_error": savings.get("error") or None,
               "publish_error": publish_error or None},
    )
    append_timeline(
        node="fleet-jobs-report",
        layer="L2-domain",
        status="ok" if not publish_error else "error",
        summary=summary if not publish_error else
        f"{summary} CMS publish failed: {publish_error}",
        ref=output_md,
    )
    print(f"Generated {output_md} and {meta_path}")
    return 1 if publish_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
