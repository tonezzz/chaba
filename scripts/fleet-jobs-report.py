#!/usr/bin/env python3
"""fleet-jobs-report.py — Aggregator for per-host jobs/queue/lane status.

Emits a daily Markdown artifact + L2 metadata, then upserts one
`fleet-jobs-report` CMS page through board-api.
Reads from existing deterministic sources (no new instrumentation):
- Timer-timeline CMS rollup (MDDB ada-cms-pages doc `timer-timeline`,
  produced by scripts/ada/timer-timeline-update.py)
- Runner fleet health + claim queue (board-api GET /queue —
  heartbeats, verdicts, claimed/active work)
- Board API /cards compact action projection (claim stats)
- Evidence-bound monthly lane usage (scripts/board/lane-savings.py)
- LiteLLM spend ledger (psql on litellm-db)
- Declared timers (docs/ssot/generated/jobs.<host>.yml)

Env: BOARD_API (default http://127.0.0.1:8787 — the loopback bind on
     idc03 where this job runs), MDDB_BASE_URL (default
     http://100.102.134.91:11027/v1).
"""
import datetime
import json
import os
import re
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
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11027/v1").rstrip("/")
CLAIM_STATES = ("queued", "claimed", "running", "done", "failed")
STATUS_ALIASES = {"doing": "running"}

# timer-timeline rollup state glyphs -> report bucket
STATE_MARKS = {"🟢": "ok", "🟡": "late", "🔴": "failing",
               "⬛": "off"}
ROLLUP_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|(.*)$")
MAX_BAD_ROWS = 15


def _get_json(url: str, timeout: int = 30) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def _post_json(url: str, payload: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def safe_load_yaml(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def norm_host(name: str) -> str:
    """Generated files use ssot host ids (tony_dell); runtime sources use
    canonical hostnames (tony-dell)."""
    return str(name or "").strip().replace("_", "-")


def read_timer_rollup() -> dict:
    """Fetch the timer-timeline fleet rollup from MDDB ada-cms-pages and
    parse its status table. Returns {hosts, updated, total, counts}."""
    doc = _post_json(f"{MDDB}/get", {
        "collection": "ada-cms-pages",
        "key": "timer-timeline",
        "lang": "en"}, timeout=30)
    content = doc.get("contentMd") or ""
    meta = doc.get("meta") or {}
    updated = ""
    for v in (meta.get("updated") or []):
        updated = str(v)
        break

    hosts: dict = {}
    counts = {"ok": 0, "late": 0, "failing": 0, "off": 0}
    total = 0
    rows_seen = 0
    for line in content.splitlines():
        m = ROLLUP_ROW.match(line)
        if not m:
            # first non-row after the table ends it — the rollup repeats
            # bad rows under "## Attention"; never count them twice
            if rows_seen:
                break
            continue
        rows_seen += 1
        name = m.group(1).strip()
        cells = [c.strip() for c in
                 m.group(2).rstrip().rstrip("|").split("|")]
        joined = " ".join(cells)
        if "unreachable" in joined or "⚠️" in joined:
            # unreachable rows carry the host in the name cell
            hosts.setdefault(name, {
                "timers": {}, "counts": {k: 0 for k in counts},
                "unreachable": "unreachable"})
            hosts[name]["unreachable"] = joined or "unreachable"
            continue
        host, last, result = cells[0], cells[1], cells[2]
        state = ""
        for glyph, bucket in STATE_MARKS.items():
            if glyph in cells[-1]:
                state = bucket
                break
        entry = hosts.setdefault(host, {
            "timers": {}, "counts": {k: 0 for k in counts},
            "unreachable": ""})
        if name in entry["timers"]:
            continue
        entry["timers"][name] = {
            "state": state or "unknown", "last": last, "result": result}
        if state:
            entry["counts"][state] += 1
            counts[state] += 1
            total += 1
    return {"hosts": hosts, "updated": updated,
            "total": total, "counts": counts}


def read_queue() -> dict:
    """GET /queue — runner heartbeats, per-runner verdicts, in-flight
    claims, queued and human-waiting cards (KNB-1007 projection)."""
    out = _get_json(f"{BOARD_API}/queue", timeout=30)
    if not isinstance(out, dict) or not out.get("ok"):
        raise RuntimeError("board-api /queue returned an invalid payload")
    return out


def read_declared_timers() -> dict:
    generated_dir = REPO / "docs/ssot/generated"
    timers_by_host = {}
    if generated_dir.exists():
        for p in generated_dir.glob("jobs.*.yml"):
            host = norm_host(p.stem.split(".", 1)[1])
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

        host = norm_host(action.get("runner") or action.get("host")
                         or action.get("target_host") or "unassigned")
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
        page = _get_json(url, timeout=30)
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


def render_report(date_str: str, rollup: dict, queue: dict,
                  claims: dict, spend: list[dict],
                  timers_by_host: dict, savings: dict,
                  errors: dict) -> str:
    rollup_hosts = rollup.get("hosts") or {}
    queue_hosts = queue.get("hosts") or {}
    hosts = (set(timers_by_host) | set(rollup_hosts) | set(queue_hosts)
             | (set(claims.get("by_host", {})) - {"unassigned"}))

    md = [f"# Fleet Jobs Report - {date_str}", ""]
    freshness = []
    if rollup.get("updated"):
        freshness.append(f"timer-timeline updated {rollup['updated']}")
    if queue.get("at"):
        freshness.append(f"queue snapshot {queue['at']}")
    if freshness:
        md.append("_Sources: " + " · ".join(freshness) + "_")
        md.append("")
    for name, err in errors.items():
        md.append(f"> ⚠️ source unavailable: **{name}** — {err}")
    if errors:
        md.append("")

    md.append("## Fleet Claim Totals")
    for state in CLAIM_STATES:
        md.append(f"- {state.title()}: {claims.get(state, 0)}")
    unassigned = claims.get("by_host", {}).get("unassigned", {})
    md.append(f"- Unassigned queued: {unassigned.get('queued', 0)}")
    md.append("")

    # Runner heartbeats + queue depth
    md.extend(["## Runner Fleet (board-api /queue)"])
    counts = queue.get("counts") or {}
    md.append(f"- Queued claimable: {counts.get('queued', 0)} · "
              f"Claimed/in-flight: {counts.get('claimed', 0)} · "
              f"Human-waiting: {counts.get('human_waiting', 0)}")
    if queue_hosts:
        md.extend(["", "| Runner | Heartbeat age | Stale | Active work |",
                   "|---|---:|---|---|"])
        for host in sorted(queue_hosts):
            hb = queue_hosts[host] or {}
            active = ", ".join(
                str(a.get("id") or a.get("unit") or "?")
                for a in (hb.get("active") or [])) or "—"
            md.append(f"| {host} | {hb.get('age_s', '?')}s | "
                      f"{'yes' if hb.get('stale') else 'no'} | {active} |")
    md.append("")

    for host in sorted(hosts):
        md.extend([f"## Host: {host}", ""])

        declared = timers_by_host.get(host, [])
        observed = (rollup_hosts.get(host) or {}).get("timers") or {}
        md.append("### Declared Timers (ssot) vs Observed (timer-timeline)")
        md.append(f"- Declared jobs: {len(declared)} · "
                  f"Observed timers: {len(observed)}")
        if (rollup_hosts.get(host) or {}).get("unreachable"):
            md.append(f"- ⚠️ host unreachable in last timer sweep: "
                      f"{(rollup_hosts[host] or {}).get('unreachable')}")
        if declared:
            for job in declared:
                jid = str(job.get('id', 'unknown'))
                seen = observed.get(jid) or observed.get(f"{jid}.timer") \
                    or {}
                state = f" — {seen['state']}" if seen.get("state") else ""
                md.append(f"  - `{jid}` ({job.get('dispatch', 'unknown')})"
                          f"{state}")
        md.append("")

        rcounts = (rollup_hosts.get(host) or {}).get("counts") or {}
        md.append("### Timer States")
        if observed or rcounts:
            md.append(f"- ok {rcounts.get('ok', 0)} · "
                      f"late {rcounts.get('late', 0)} · "
                      f"failing {rcounts.get('failing', 0)} · "
                      f"off {rcounts.get('off', 0)}")
            bad = [(n, t) for n, t in sorted(observed.items())
                   if t.get("state") in ("failing", "late")]
            if bad:
                md.append("")
                md.extend(["| timer | state | last run | result |",
                           "|---|---|---|---|"])
                for name, t in bad[:MAX_BAD_ROWS]:
                    md.append(f"| `{name}` | {t['state']} | {t['last']} |"
                              f" {t['result']} |")
                if len(bad) > MAX_BAD_ROWS:
                    md.append(f"| … +{len(bad) - MAX_BAD_ROWS} more | | | |")
        else:
            md.append("- _(no timer-timeline rows for this host)_")
        md.append("")

        md.append("### Assigned Card Actions")
        host_stats = claims.get("by_host", {}).get(host, {})
        for state in CLAIM_STATES:
            md.append(f"- {state.title()}: {host_stats.get(state, 0)}")
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


def _source(name, fn, errors, default):
    try:
        return fn()
    except Exception as e:
        errors[name] = str(e)[:300]
        return default


def main() -> int:
    date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    output_md = REPO / f"reports/fleet-jobs-{date_str}.md"
    output_md.parent.mkdir(parents=True, exist_ok=True)

    errors: dict = {}
    rollup = _source("timer-timeline", read_timer_rollup, errors,
                     {"hosts": {}, "counts": {}, "total": 0})
    queue = _source("board-api /queue", read_queue, errors, {})
    claims = _source("board-api /cards", read_claim_stats, errors, {})
    savings = _source("lane-savings", read_lane_savings, errors, {})
    spend = extract_litellm_spend()
    timers_by_host = read_declared_timers()

    rollup_hosts = rollup.get("hosts") or {}
    hosts = (set(timers_by_host) | set(rollup_hosts)
             | set(queue.get("hosts") or {})
             | (set(claims.get("by_host", {})) - {"unassigned"}))
    content_md = render_report(date_str, rollup, queue, claims, spend,
                               timers_by_host, savings, errors)
    output_md.write_text(content_md, encoding="utf-8")

    failing = (rollup.get("counts") or {}).get("failing", 0)
    summary = (f"{len(hosts)} hosts; {rollup.get('total', 0)} timers "
               f"({failing} failing); "
               f"{(queue.get('counts') or {}).get('claimed', 0)} claimed; "
               f"{len(spend)} spend rows.")
    publish_error = ""
    try:
        publish_cms(content_md, date_str, summary)
    except Exception as e:
        publish_error = str(e)[:300]
        print(f"fleet-jobs-report: CMS publication failed: {publish_error}",
              file=sys.stderr)

    if errors or publish_error:
        status = "error"
    elif failing:
        status = "delta"
    else:
        status = "ok"
    meta_path = REPO / "reports/meta.fleet-jobs-report.yml"
    write_meta(
        meta_path,
        node="fleet-jobs-report",
        layer="L2-domain",
        generated_by="scripts/fleet-jobs-report.py",
        status=status,
        purpose="per-host jobs/queue/lane status from existing sources",
        summary=summary,
        sources=["mddb ada-cms-pages/timer-timeline", "board-api /queue",
                 "board-api /cards projection", "litellm-db",
                 "jobs.*.yml", "lane-savings.py", "board-api /report"],
        children=[],
        extra={"hosts": sorted(hosts), "claims": claims,
               "timer_counts": rollup.get("counts"),
               "queue_counts": queue.get("counts"),
               "lane_savings_month": savings.get("month"),
               "lane_savings_error": savings.get("error") or None,
               "source_errors": errors or None,
               "publish_error": publish_error or None},
    )
    append_timeline(
        node="fleet-jobs-report",
        layer="L2-domain",
        status=status,
        summary=summary if not (errors or publish_error) else
        f"{summary} errors: {dict(errors, publish=publish_error)}",
        ref=output_md,
    )
    print(f"Generated {output_md} and {meta_path}")
    return 1 if publish_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
