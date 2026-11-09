#!/usr/bin/env python3
"""render-jobs-catalog — emit per-host schedule views from ssot.jobs.yml.

Single canonical schedule file is docs/ssot/infrastructure/ssot.jobs.yml;
these generated per-host views replace the hand-maintained
ssot.night-jobs.* / ssot.automation.* catalogs that drifted
(ops-1244e). Regenerate after any ssot.jobs.yml edit:
    python3 scripts/render-jobs-catalog.py [--out docs/ssot/generated]
"""
import re, sys, argparse
from pathlib import Path
try:
    import yaml
except ImportError:
    sys.exit("needs PyYAML")

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/ssot/infrastructure/ssot.jobs.yml"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs/ssot/generated"))
    args = ap.parse_args()
    jobs = yaml.safe_load(MANIFEST.read_text()).get("jobs") or []
    by_host = {}
    for j in jobs:
        by_host.setdefault(j.get("host", "?"), []).append(j)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for host, js in sorted(by_host.items()):
        p = out / f"jobs.{host}.yml"
        with p.open("w") as f:
            f.write("title: Scheduled jobs — %s\n" % host)
            f.write("generated: true  # DO NOT EDIT — rendered by "
                    "scripts/render-jobs-catalog.py from "
                    "ssot.jobs.yml\n")
            f.write("source: docs/ssot/infrastructure/ssot.jobs.yml\n")
            f.write("jobs:\n")
            for j in sorted(js, key=lambda x: x.get("id","")):
                sched = j.get("on_calendar") or ("every "+str(j["every"]) if j.get("every") else "-")
                f.write("  - id: %s\n" % j["id"])
                f.write("    schedule: %s\n" % sched)
                f.write("    dispatch: %s\n" % j.get("dispatch","?"))
                if j.get("persistent"):
                    f.write("    persistent: true\n")
        print("wrote", p, len(js), "jobs")

if __name__ == "__main__":
    main()
