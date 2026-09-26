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
import sys
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
META = REPO / "reports" / "meta.system-report.yml"
TIMELINE_TAIL = 20

_LAYER_ORDER = ["L0-raw", "L1-producer", "L2-domain", "L3-overview"]
_BADGE = {
    "ok": "OK", "delta": "DELTA", "stale": "STALE", "error": "ERROR",
    "missing": "MISSING", "untracked": "untracked", "remote": "remote",
    "planned": "planned",
}
_WORST = {"ok": 0, "remote": 0, "untracked": 1, "planned": 1,
          "delta": 2, "stale": 2, "missing": 3, "error": 4}


def _fmt_ts(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.datetime.fromisoformat(str(iso))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(iso)[:16]


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
        s["status"] in ("missing", "stale", "error", "delta") for s in states
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
                f"| {_fmt_ts(s['last_run'])} | {s['summary'] or s['purpose'] or ''} |"]
        return " ".join(bits)

    def table(rows: list[str]) -> list[str]:
        return [
            "| Node | Layer | Status | Last run | Summary |",
            "|------|-------|--------|----------|---------|",
            *rows,
            "",
        ]

    # L3 node first
    l3 = [s for s in states if s["layer"] == "L3-overview"]
    if l3:
        lines += ["## Overview", ""] + table([node_row(s) for s in l3])

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
    }, sort_keys=False, allow_unicode=True), encoding="utf-8")

    bad = [s["id"] for s in states
           if s["status"] in ("missing", "stale", "error", "delta")]
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

    print(f"Wrote {args.output}")
    print(f"Wrote {args.yml_output}")
    print(f"Status: {status} — {summary}")
    if bad:
        print("Attention:", ", ".join(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
