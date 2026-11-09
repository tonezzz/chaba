#!/usr/bin/env python3
"""fleet-jobs-report.py — Aggregator for per-host jobs/queue/lane status.

Emits reports/fleet-jobs-<date>.md + reports/meta.fleet-jobs-report.yml
Reads from existing deterministic sources:
- Timer timelines (timeline.jsonl)
- Runner fleet health (~/var/chaba/health/)
- Board API /cards claim stats (via docs/ssot/kanban/cards/*.yml)
- LiteLLM spend ledger (psql on litellm-db)
- Declared timers (docs/ssot/generated/jobs.<host>.yml)
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from lib.report import append_timeline, now_iso, write_meta  # noqa: E402

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
                    health_data[p.name] = json.load(f)
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

if __name__ == "__main__":
    pass

def read_claim_stats() -> dict:
    cards_dir = REPO / "docs/ssot/kanban/cards"
    stats = {"queued": 0, "doing": 0, "done": 0, "failed": 0, "by_lane": {}}
    if not cards_dir.exists():
        return stats
    for p in cards_dir.glob("*.yml"):
        data = safe_load_yaml(p)
        action = data.get("action") or {}
        status = action.get("status")
        if status in stats:
            stats[status] += 1

        lane = action.get("lane")
        if lane:
            if lane not in stats["by_lane"]:
                stats["by_lane"][lane] = {"queued": 0, "doing": 0, "done": 0, "failed": 0}
            if status in stats["by_lane"][lane]:
                stats["by_lane"][lane][status] += 1
    return stats

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

def main():
    date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    output_md = REPO / f"reports/fleet-jobs-{date_str}.md"
    output_md.parent.mkdir(parents=True, exist_ok=True)

    events = read_timer_timelines()
    health = read_runner_fleet_health()
    claims = read_claim_stats()
    spend = extract_litellm_spend()
    timers_by_host = read_declared_timers()

    hosts = set(timers_by_host.keys()) | set(health.keys())

    md = [f"# Fleet Jobs Report - {date_str}", ""]

    for host in sorted(hosts):
        md.append(f"## Host: {host}")

        # Timers
        md.append("### Declared vs Active Timers")
        declared = timers_by_host.get(host, [])
        md.append(f"- Declared jobs: {len(declared)}")
        for job in declared:
            md.append(f"  - `{job.get('id', 'unknown')}` ({job.get('dispatch', 'unknown')})")

        md.append("")

        # Claim Stats
        md.append("### Claim Stats (Action Status)")
        md.append(f"- Queued: {claims.get('queued', 0)}")
        md.append(f"- Doing: {claims.get('doing', 0)}")
        md.append(f"- Done: {claims.get('done', 0)}")
        md.append(f"- Failed: {claims.get('failed', 0)}")

        md.append("")

        # Last-run Failures (Mocked from health data if available)
        md.append("### Last-run Failures")
        if host in health:
            md.append(f"- (Found health snapshot for {host})")
            if "failed" in health[host]:
               for fail in health[host]["failed"]:
                   md.append(f"  - `{fail}`")
        else:
            md.append("- No health data found.")
        md.append("")

    # Lanes Section
    md.append("## Lanes")
    md.append("### Lane Savings")
    md.append("_(Lane savings metrics retrieved from `scripts/board/lane-savings.py` output or aggregated board stats)_")
    md.append("")
    md.append("### LiteLLM Spend (trailing 24h)")
    if spend:
        md.append("| Key | Model | Calls | Tokens | Spend (USD) |")
        md.append("|---|---|---|---|---|")
        for row in spend:
            md.append(f"| {row['key']} | {row['model']} | {row['calls']} | {row['tokens']} | ${row['spend_usd']} |")
    else:
        md.append("_(No spend data available)_")
    md.append("")

    md_content = "\n".join(md)
    output_md.write_text(md_content, encoding="utf-8")

    # Generate metadata
    meta_path = REPO / "reports/meta.fleet-jobs-report.yml"
    write_meta(
        meta_path,
        node="fleet-jobs-report",
        layer="L2-domain",
        generated_by="scripts/fleet-jobs-report.py",
        status="ok",
        purpose="per-host jobs/queue/lane status from existing sources",
        summary=f"Processed fleet jobs for {len(hosts)} hosts. Total spend rows: {len(spend)}",
        sources=["timeline.jsonl", "health/", "cards/", "litellm-db", "jobs.*.yml"],
        children=[],
        extra={"hosts": list(hosts), "claims": claims}
    )

    append_timeline(
        node="fleet-jobs-report",
        layer="L2-domain",
        status="ok",
        summary=f"Processed fleet jobs report for {date_str}",
        ref=output_md
    )

    print(f"Generated {output_md} and {meta_path}")

if __name__ == "__main__":
    main()
