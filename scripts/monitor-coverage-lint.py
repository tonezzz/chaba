#!/usr/bin/env python3
"""Coverage lint: every live-declared service must have a health check or exemption.

Reads ssot.services.yml (live services) + ssot.health*.yml (declared checks +
exemptions) and reports the gap. Warn mode by default; --strict exits 1 on gaps.
The evolve-hook: a new service surfaces here until it gets a check or a
declared `no_health:` reason in ssot.health.yml → coverage.exempt.
"""
import argparse
import glob
import re
import sys

import yaml

SERVICES = "docs/ssot/infrastructure/ssot.services.yml"
HEALTH_GLOB = "docs/ssot/infrastructure/ssot.health*.yml"
HOSTS = ("tony-dell", "tony-omen", "michael", "mn01", "idc01", "idc03",
         "tony-ha", "michael-ha")
LIVE = re.compile(r"^(implemented|active|running)", re.I)
# non-service config blocks that appear under host sections
NOT_SERVICE = {"notes", "deployment", "secrets", "network"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when gaps are found")
    args = ap.parse_args()

    d = yaml.safe_load(open(SERVICES)) or {}
    live, no_status = [], []
    for host in HOSTS:
        for svc, cfg in (d.get(host) or {}).items():
            if not isinstance(cfg, dict) or svc in NOT_SERVICE:
                continue
            st = str(cfg.get("status", ""))
            if not st:
                no_status.append((host, svc))
            elif LIVE.match(st):
                live.append((host, svc))

    # checks + exemptions
    check_names, exempt = set(), {}
    for f in glob.glob(HEALTH_GLOB):
        h = yaml.safe_load(open(f)) or {}
        for svc in h.get("services", []) or []:
            if isinstance(svc, dict):
                for key in ("id", "name", "service"):
                    if svc.get(key):
                        check_names.add(norm(svc[key]))
        cov = h.get("coverage", {}) or {}
        for name, reason in (cov.get("exempt", {}) or {}).items():
            exempt[norm(name)] = reason

    covered, uncovered = [], []
    for host, svc in live:
        n = norm(svc)
        if n in exempt:
            continue
        hit = any(n and (n in c or c in n) for c in check_names)
        (covered if hit else uncovered).append((host, svc))

    print(f"live services: {len(live)} | covered: {len(covered)} | "
          f"uncovered: {len(uncovered)} | exempt: {len(exempt)} | "
          f"no-status: {len(no_status)}")
    if uncovered:
        print("\nUNCOVERED (add a check or coverage.exempt entry):")
        for h, s in uncovered:
            print(f"  {h}: {s}")
    if no_status:
        print("\nNO STATUS (can't tell if live — declare status:):")
        for h, s in no_status:
            print(f"  {h}: {s}")
    sys.exit(1 if (args.strict and (uncovered or no_status)) else 0)


if __name__ == "__main__":
    main()
