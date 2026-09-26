#!/usr/bin/env python3
"""Network inventory digest (L1.5e): deltas from the nightly arp scan.

Reads the newest reports/network-inventory-scan-*.json produced by
scripts/arp-inventory-scan.py (runs via its own timer on tony-omen) —
no rescan here, just a digest of conflicts / new devices / changed MACs.
Personal-tier data: local review dir only.

Usage:
  net-report.py [--reports DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS = REPO_ROOT / "reports"
DEFAULT_OUT = Path.home() / ".local/share/ada-review"

INTEREST = ("conflict", "new_devices", "mac_changed",
            "new_ip_for_known_device", "duplicate_macs")


def _latest_scan(d: Path) -> Path | None:
    scans = sorted(d.glob("network-inventory-scan-*.json"),
                   key=lambda p: p.stat().st_mtime)
    return scans[-1] if scans else None


def _device(e: dict) -> str:
    return (e.get("device_id") or e.get("mac_device")
            or "/".join(str(e.get("ip_devices") or "?"))
            or e.get("mac") or "?")


def net_block(rows: list[dict], since: str, detail: int = 3) -> str:
    if not rows:
        return "## network\nno scans found"
    lines = [f"## network ({since})"]
    if len(rows) > detail:
        flagged = sum(1 for r in rows[:-detail] if any(
            r["summary"].get(k)
            for k in ("conflict", "new_devices", "duplicate_macs")))
        lines.append(f"older: {len(rows) - detail} scan(s), "
                     f"{flagged} with findings")
    for r in rows[-detail:]:
        s = r["summary"]
        flag = " ⚠" if any(s.get(k) for k in
                           ("conflict", "new_devices", "duplicate_macs")) else ""
        detail = ", ".join(f"{k} {s.get(k, 0)}" for k in INTEREST
                           if s.get(k)) or "all clean"
        lines.append(
            f"{r['scanned_at'][:16]}: {s.get('discovered', '?')} seen, "
            f"{s.get('consistent', '?')} ok — {detail}{flag}")
        for k in INTEREST:
            for e in (r["detail"].get(k) or [])[:4]:
                lines.append(f"  {k}: {_device(e)} "
                             f"{e.get('ip', '')} {e.get('mac', '')}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    ap.add_argument("--days", type=int, default=7,
                    help="keep scan reports newer than this")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    d = args.reports.expanduser()
    cutoff = time.time() - args.days * 86400
    rows = []
    for p in sorted(d.glob("network-inventory-scan-*.json"),
                    key=lambda p: p.stat().st_mtime):
        if p.stat().st_mtime < cutoff:
            continue
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            rows.append({"scanned_at": j.get("scanned_at", p.name[23:38]),
                         "file": p.name,
                         "summary": j.get("summary") or {},
                         "detail": {k: j.get("results", {}).get(k)
                                    for k in INTEREST}})
        except Exception as e:
            print(f"warn: {p.name}: {e}", file=sys.stderr)

    args.out.mkdir(parents=True, exist_ok=True)
    ops = args.out / "net-ops.jsonl"
    with ops.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} scan(s) -> {ops}")
    print(net_block(rows, f"{args.days}d"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
