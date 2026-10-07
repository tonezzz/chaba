#!/usr/bin/env python3
"""Render the L3 system overview from the layered reporting registry.

Walks every node declared in docs/ssot/infrastructure/ssot.reports.yml,
resolves observed state (meta.yml -> artifacts -> missing) via
scripts/lib/report.py, and writes:

  reports/SYSTEM-REPORT.md   human digest — the single overview
  reports/system-report.yml  machine summary of node states
  reports/meta.system-report.yml  this node's own meta
  ~/var/chaba/reports/timeline.jsonl  one appended event

Missing and stale nodes are first-class output — the overview's job is to
make absence loud.

Usage:
  python3 scripts/report-system.py            # render
  python3 scripts/report-system.py --print    # render to stdout only
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import yaml  # noqa: E402

from lib.report import (  # noqa: E402
    REGISTRY_PATH, TIMELINE_PATH, append_timeline, load_registry,
    now_iso, resolve_all, write_meta,
)

OUT_MD = REPO / "reports" / "SYSTEM-REPORT.md"
OUT_YML = REPO / "reports" / "system-report.yml"
CMS_SLUG = "system-report"
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
META = REPO / "reports" / "meta.system-report.yml"
FOCUS_META = REPO / "reports" / "meta.focus-inbox.yml"
FOCUS_DIR = REPO / "docs" / "ssot" / "focus-inbox"
TIMELINE_TAIL = 20

_LAYER_ORDER = ["L0-raw", "L1-producer", "L2-domain", "L3-overview"]
_BADGE = {
    "ok": "OK", "delta": "DELTA", "stale": "STALE", "error": "ERROR",
    "unreachable": "UNREACH",
    "missing": "MISSING", "untracked": "untracked", "remote": "remote",
    "planned": "planned",
}
_WORST = {"ok": 0, "remote": 0, "untracked": 1, "planned": 1,
          "delta": 2, "stale": 2, "missing": 3, "error": 4,
          "unreachable": 4}


def _fmt_ts(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.datetime.fromisoformat(str(iso))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(iso)[:16]


def _fmt_age(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.datetime.fromisoformat(str(iso))
        secs = max(0, int((datetime.datetime.now(
            datetime.timezone.utc) - dt).total_seconds()))
    except ValueError:
        return "-"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h{(secs % 3600) // 60}m"
    return f"{secs // 86400}d{(secs % 86400) // 3600}h"


AUDIT_HOSTS_DIR = REPO / "reports" / "audit-hosts"
HOST_LOADS_YML = REPO / "reports" / "host-loads" / "host-loads.yml"
HOST_LOADS_MAX_AGE_H = 4


def _mb_human(mb) -> str | None:
    if mb is None:
        return None
    return f"{mb / 1024:.1f}Gi" if mb >= 1024 else f"{int(mb)}Mi"


def _host_loads() -> list[dict]:
    """Per-host load view. Prefers the 5-min host-loads sampler output;
    falls back to the 24h audit-hosts snapshots when the sampler is dark."""
    try:
        live = yaml.safe_load(HOST_LOADS_YML.read_text(encoding="utf-8")) or {}
        gen = live.get("generated_at")
        age_ok = _fmt_age(gen) != "-" and (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.datetime.fromisoformat(str(gen))
        ).total_seconds() < HOST_LOADS_MAX_AGE_H * 3600
    except Exception:
        live, gen, age_ok = {}, None, False
    if age_ok:
        rows = []
        for h in live.get("hosts") or []:
            load = h.get("load") or {}
            rows.append({
                "host": h.get("host"),
                "unreachable": bool(h.get("unreachable")),
                "load_1m": load.get("1m"), "load_5m": load.get("5m"),
                "load_15m": load.get("15m"),
                "mem_used": _mb_human(h.get("mem_used_mb")),
                "mem_avail": _mb_human(h.get("mem_avail_mb")),
                "disk_pct": h.get("disk_pct"),
                "oom_24h": None,
                "snapshot_ts": h.get("ts"),
                "snapshot_age": _fmt_age(h.get("ts")),
            })
        return sorted(rows, key=lambda r: r["host"] or "")

    latest: dict[str, Path] = {}
    for p in sorted(AUDIT_HOSTS_DIR.glob("*-????????-??????.yml")):
        host = p.stem.rsplit("-", 2)[0]
        latest[host] = p
    rows = []
    for host, path in sorted(latest.items()):
        try:
            d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        load = d.get("load") or {}
        mem = d.get("memory") or {}
        disk = d.get("disk") or {}
        oom = d.get("oom_kills_24h") or {}
        rows.append({
            "host": host,
            "unreachable": bool(d.get("unreachable")),
            "load_1m": load.get("1m"), "load_5m": load.get("5m"),
            "load_15m": load.get("15m"),
            "mem_used": mem.get("used"), "mem_avail": mem.get("available"),
            "disk_pct": disk.get("percent"),
            "oom_24h": (oom.get("user", 0) or 0) + (oom.get("system", 0) or 0),
            "uptime": d.get("uptime"),
            "snapshot_ts": d.get("timestamp"),
            "snapshot_age": _fmt_age(d.get("timestamp")),
        })
    return rows


def _load_timeline_tail(path: Path, n: int) -> list[dict]:
    if not path.is_file():
        return []
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    events = []
    for line in lines[-n:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def render_markdown(doc: dict, states: list[dict], timeline_path: Path) -> str:
    by_id = {s["id"]: s for s in states}
    counts = {}
    for s in states:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    overall = "OK" if not any(
        s["status"] in ("missing", "stale", "error", "delta", "unreachable") for s in states
    ) else "ATTENTION"

    lines = [
        "# System Report",
        "",
        f"- Generated: {now_iso()} by `scripts/report-system.py`",
        f"- Registry: `{REGISTRY_PATH.relative_to(REPO)}`",
        f"- Overall: **{overall}** — " + ", ".join(
            f"{_BADGE[k]} {v}" for k, v in sorted(
                counts.items(), key=lambda kv: -_WORST.get(kv[0], 0))),
        "",
        "Layered reporting standard: L0 raw -> L1 producer -> L2 domain -> L3 "
        "overview. Each node's `meta.yml` is observed state; the registry is "
        "declared intent. See `docs/ssot/infrastructure/ssot.reports.yml`.",
        "",
    ]

    rendered = set()

    def node_row(s: dict) -> str:
        rendered.add(s["id"])
        bits = [f"| `{s['id']}` | {s['layer']} | {_BADGE.get(s['status'], s['status'])}",
                f"| {_fmt_ts(s['last_run'])} | {_fmt_age(s['last_run'])}",
                f"| {s['summary'] or s['purpose'] or ''} |"]
        return " ".join(bits)

    def table(rows: list[str]) -> list[str]:
        return [
            "| Node | Layer | Status | Last run | Age | Summary |",
            "|------|-------|--------|----------|-----|---------|",
            *rows,
            "",
        ]

    # L3 node first
    l3 = [s for s in states if s["layer"] == "L3-overview"]
    if l3:
        lines += ["## Overview", ""] + table([node_row(s) for s in l3])

    # Host loads — from the latest audit-hosts snapshots
    loads = _host_loads()
    if loads:
        lines += [
            "## Host loads",
            "",
            "From `reports/host-loads/host-loads.yml` (5-min sampler via "
            "tony-dell-monitor) when fresh, else the 24h "
            "`reports/audit-hosts/<host>-*.yml` snapshots. "
            "*Age* = how stale each host's data is.",
            "",
            "| Host | Load 1/5/15m | Mem used/avail | Disk % | OOM 24h | "
            "Snapshot age |",
            "|------|---------------|----------------|--------|---------|"
            "---------------|",
        ]
        for r in loads:
            if r["unreachable"]:
                lines.append(f"| `{r['host']}` | - | - | - | - | "
                             f"unreachable ({r['snapshot_age']}) |")
            else:
                lines.append(
                    f"| `{r['host']}` | {r['load_1m']} / {r['load_5m']} / "
                    f"{r['load_15m']} | {r['mem_used'] or '-'} / "
                    f"{r['mem_avail'] or '-'} | {r['disk_pct']}% | "
                    f"{r['oom_24h'] if r['oom_24h'] is not None else '-'} | "
                    f"{r['snapshot_age']} |")
        lines.append("")

    # L2 domains with their children
    lines += ["## Domains", ""]
    for s in states:
        if s["layer"] != "L2-domain":
            continue
        node = next(n for n in doc.get("nodes", []) if n.get("id") == s["id"])
        lines.append(f"### {s['id']}")
        lines.append("")
        lines.append(f"_{s['purpose'] or ''}_")
        lines.append("")
        rows = [node_row(s)]
        for child_id in node.get("children") or []:
            if child_id in by_id:
                rows.append(node_row(by_id[child_id]))
        lines += table(rows)

    # L1 producers not claimed by any L2
    orphan = [s for s in states
              if s["layer"] == "L1-producer" and s["id"] not in rendered]
    if orphan:
        lines += ["## Producers (ungrouped)", ""] + table(
            [node_row(s) for s in orphan])

    # Timeline tail
    events = _load_timeline_tail(timeline_path, TIMELINE_TAIL)
    lines += [
        "## Recent timeline",
        "",
        f"Last {len(events)} of `{timeline_path}` "
        "(append-only, full history):",
        "",
    ]
    if events:
        lines += [
            "| Time | Node | Status | Summary |",
            "|------|------|--------|---------|",
            *[f"| {_fmt_ts(e.get('ts'))} | `{e.get('node')}` | "
              f"{e.get('status')} | {e.get('summary', '')} |"
              for e in reversed(events)],
            "",
        ]
    else:
        lines += ["_No timeline events yet._", ""]

    lines += [
        "## Raw data",
        "",
        "- `reports/audit-hosts/` — per-host snapshots",
        "- `reports/audits/` — audit suite outputs",
        "- `~/var/chaba/health/` — monitor snapshots",
        f"- `{timeline_path}` — full event history",
        "",
        "_Generated file — do not hand-edit._",
        "",
    ]
    return "\n".join(lines)


def write_focus_inbox_meta() -> None:
    """focus-inbox has no single generator — the L3 renderer observes the
    inbox dir itself and writes the node's meta before resolution."""
    try:
        items = [p.name for p in FOCUS_DIR.iterdir()
                 if p.is_file() and p.suffix in (".yml", ".yaml")
                 and not p.name.startswith("TEMPLATE")]
    except OSError:
        return
    n = len(items)
    write_meta(
        FOCUS_META,
        node="focus-inbox",
        layer="L1-producer",
        purpose="Unprocessed attention items — alert ymls written by audits/monitors",
        generated_by="scripts/report-system.py (inbox observation)",
        status="delta" if n else "ok",
        summary=f"{n} open item(s)" if n else "inbox clear",
        children=[],
        extra={"open_items": sorted(items)},
    )


def _mddb_post(path: str, payload: dict, timeout: int = 30) -> object:
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def publish_cms_page(md: str, summary: str) -> bool:
    """Upsert the rendered report into Ada's CMS (ada-cms-pages) so the
    tony-ha/cms surface and cast displays can show it. Best-effort — an
    MDDB outage must not fail the report."""
    now = now_iso()
    # Merge meta/timeline like cms_publish_page so the page keeps its
    # append-only audit trail across daily refreshes.
    existing = {}
    try:
        docs = _mddb_post("search", {"collection": "ada-cms-pages",
                                     "query": CMS_SLUG, "limit": 50})
        existing = next((d for d in docs
                         if d.get("key") == CMS_SLUG
                         and (d.get("lang") or "en") == "en"), {}) or {}
    except Exception:
        pass
    meta = {
        k: (v if isinstance(v, list) else [v])
        for k, v in ((existing.get("meta") or {})).items()}
    meta.setdefault("bank", ["cms"])
    meta.setdefault("scope", ["tony"])
    meta.setdefault("status", ["active"])
    meta.setdefault("source", ["api"])
    meta.setdefault("subject", [CMS_SLUG])
    meta.setdefault("attribute", ["page"])
    meta.update({
        "kind": ["report"], "slug": [CMS_SLUG],
        "title": [f"System Report — {now[:10]}"],
        "format": ["markdown"], "lang": ["en"],
        "updated": [now], "last_verified": [now[:10]],
        "domain": ["monitoring"], "summary": [summary[:240]],
        "fresh_for": ["30h"], "written_by": ["report-system.py"],
    })
    tl = [x for x in meta.get("timeline", []) if isinstance(x, str)]
    tl.append(f"{now[:16]} published: {meta['title'][0][:80]}")
    meta["timeline"] = tl[-40:]
    _mddb_post("add", {"collection": "ada-cms-pages", "key": CMS_SLUG,
                       "lang": "en", "contentMd": md, "meta": meta},
               timeout=60)
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    p.add_argument("--output", type=Path, default=OUT_MD)
    p.add_argument("--yml-output", type=Path, default=OUT_YML)
    p.add_argument("--meta", type=Path, default=META)
    p.add_argument("--timeline", type=Path, default=TIMELINE_PATH)
    p.add_argument("--print", dest="print_only", action="store_true",
                   help="Render to stdout; write no files")
    args = p.parse_args()

    write_focus_inbox_meta()
    doc = load_registry(args.registry)
    nodes = doc.get("nodes") or []
    states = resolve_all(nodes)
    md = render_markdown(doc, states, args.timeline)

    if args.print_only:
        print(md)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md, encoding="utf-8")

    counts = {}
    for s in states:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    args.yml_output.write_text(yaml.safe_dump({
        "generated_at": now_iso(),
        "registry": str(args.registry),
        "node_count": len(states),
        "status_counts": counts,
        "nodes": states,
        "host_loads": _host_loads(),
    }, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # Publish to the web app (same pattern as audits/run.mjs -> apps/audit/data).
    # The caddy `web` container serves chaba-tony-dell/stacks/web/public until
    # checkout convergence lands — write to both roots when it exists.
    import shutil
    for root in (REPO, Path("/home/tony/CascadeProjects/chaba-tony-dell")):
        web_data = root / "stacks" / "web" / "public" / "apps" / "system-report" / "data"
        if not web_data.parent.parent.exists():
            continue
        web_data.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.output, web_data / "SYSTEM-REPORT.md")
        shutil.copyfile(args.yml_output, web_data / "system-report.yml")

    bad = [s["id"] for s in states
           if s["status"] in ("missing", "stale", "error", "delta", "unreachable")]
    status = "delta" if bad else "ok"
    summary = (f"{len(states)} nodes; " +
               (", ".join(f"{s['id']}={s['status']}" for s in states
                          if s["status"] in ("missing", "stale", "error"))
                or "all healthy"))
    write_meta(args.meta, node="system-report", layer="L3-overview",
               generated_by="scripts/report-system.py",
               purpose="Single human digest across all domains; makes absence loud",
               status=status, summary=summary,
               sources=[str(args.output), str(args.yml_output)],
               children=[s["id"] for s in states
                          if s["layer"] == "L2-domain"])
    append_timeline("system-report", "L3", status, summary,
                    ref=args.output, timeline=args.timeline)

    try:
        if publish_cms_page(md, summary):
            print(f"Published CMS page: {CMS_SLUG}")
    except Exception as e:
        print(f"warn: CMS publish failed ({e})", file=sys.stderr)

    print(f"Wrote {args.output}")
    print(f"Wrote {args.yml_output}")
    print(f"Status: {status} — {summary}")
    if bad:
        print("Attention:", ", ".join(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
