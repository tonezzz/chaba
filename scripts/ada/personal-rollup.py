#!/usr/bin/env python3
"""Personal digest rollup: render personal-tier blocks into one file.

Sister to focus-rollup.py — same '*.jsonl + *_block()' convention, but the
output is personal-digest.md, injected ONLY into the devin context profile
(never synced to Ada banks or the guest profile). Sources are the
personal-tier collectors: devin-report.py, ops-report.py, net-report.py,
plus future ones (caddy, ha-events, spend, tasks).

Usage:
  personal-rollup.py [--devin FILE] [--ops FILE] [--net FILE] [--out DIR]
Each --flag points at the collector's jsonl output; missing/empty files
are skipped silently so the digest renders from whatever is available.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports

DEFAULT_OUT = Path.home() / ".local/share/ada-review"

# flag -> (module, block function, default jsonl name, window label, group)
# group: "personal" -> personal-digest.md (devin session timeline)
#        "infra"    -> infra-digest.md (hosts/network/apps/spend/tasks)
SOURCES = {
    "devin": ("devin-report", "devin_block", "devin-ops.jsonl", "7d",
              "personal"),
    # infra order matters — section hard cap truncates from the tail, so
    # compact high-signal blocks go first; ## hosts last (also in
    # focus-digest via focus-rollup --hosts).
    "net": ("net-report", "net_block", "net-ops.jsonl", "recent", "infra"),
    "ops": ("ops-report", "ops_events_block", "ada-ops-events.jsonl", "72h",
            "infra"),
    "tasks": ("tasks-report", "tasks_block", "tasks-ops.jsonl", "7d",
              "infra"),
    "spend": ("spend-report", "spend_block", "spend-ops.jsonl", "24h",
              "infra"),
    "haevents": ("ha-events-report", "ha_events_block",
                 "ha-events-ops.jsonl", "24h", "infra"),
    "apps": ("caddy-report", "caddy_block", "apps-ops.jsonl", "recent",
             "infra"),
    "hosts": ("host-report", "hosts_block", "host-ops.jsonl", "24h",
              "infra"),
}
GROUPS = ("personal", "infra")


def _rows(path: Path) -> list[dict]:
    try:
        return [json.loads(l) for l in path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"warn: {path}: {e}", file=sys.stderr)
        return []


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    for flag in SOURCES:
        ap.add_argument(f"--{flag}", type=Path, default=None,
                        help=f"{flag} jsonl (default <out>/{SOURCES[flag][2]})")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    outdir = args.out.expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    blocks: dict[str, list[str]] = {g: [] for g in GROUPS}
    for flag, (mod_name, func, default, window, group) in SOURCES.items():
        path = getattr(args, flag) or (outdir / default)
        rows = _rows(path.expanduser())
        if not rows:
            continue
        try:
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, func)
            # net_report accepts a detail cap; keep it tight for the
            # shared section budget
            if flag == "net":
                blocks[group].append(fn(rows, window, detail=2))
            else:
                blocks[group].append(fn(rows, window))
        except Exception as e:
            print(f"warn: {flag} block failed: {e}", file=sys.stderr)

    for g in GROUPS:
        digest = ("\n\n".join(blocks[g]) + "\n" if blocks[g]
                  else f"## {g}\n(empty)\n")
        out = outdir / f"{g}-digest.md"
        out.write_text(digest, encoding="utf-8")
        print(f"wrote {out} ({len(blocks[g])} blocks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
