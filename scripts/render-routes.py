#!/usr/bin/env python3
"""Render the edge route registry (ssot.routes.yml) -> apps/routes.json.

routes.json is the machine-readable contract app code consumes instead of
hardcoding hostnames (the idc01->idc03 card breakage, 2026-10-07). It is
served by the edge as /apps/routes.json and mirrored into HA www dirs as
/local/routes.json for dashboard cards — see `consumers:` in the SSOT.

Also validates: duplicate ids, prefix shadowing, upstream hygiene.
Usage: render-routes.py [--check]   (--check = validate only, no write)
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "docs/ssot/infrastructure/ssot.routes.yml"
OUT = REPO / "stacks/web/public/apps/routes.json"
_TAILNET_RE = re.compile(r"^https?://[a-z0-9-]+\.taila0626a\.ts\.net")
_IP_RE = re.compile(r"^(https?://)?\d{1,3}(\.\d{1,3}){3}")


def _base(path: str) -> str:
    return path.rstrip("/*") or "/"


def build(registry: dict) -> dict:
    routes = {}
    for r in registry["routes"]:
        entry = {"kind": r["kind"], "path": _base(r["path"])}
        if r.get("owner"):
            entry["owner"] = r["owner"]
        ups = r.get("upstream")
        if isinstance(ups, list):
            ups = ups[0]
        if ups:
            if not ups.startswith(("http://", "https://")):
                ups = ("https://" if "ts.net" in ups else "http://") + ups
            host = ups.split("://", 1)[1].split("/")[0].split(":")[0]
            if host in ("127.0.0.1", "localhost", "host.containers.internal") \
                    or "." not in host:
                # loopback/docker-net upstream — consumers use same-origin path
                entry["local"] = True
            else:
                entry["http"] = ups.rstrip("/") + entry["path"].rstrip("/")
                if r.get("ws"):
                    ws_path = r["ws"] if isinstance(r["ws"], str) else "/ws"
                    entry["ws"] = ("wss://" if ups.startswith("https")
                                   else "ws://") \
                                  + ups.split("://", 1)[1].rstrip("/") \
                                  + entry["path"].rstrip("/") + ws_path
        if r.get("target"):
            entry["target"] = r["target"]
        routes[r["id"]] = entry
    return {
        "generated": datetime.now(timezone(timedelta(hours=7)))
        .strftime("%Y-%m-%d %H:%M +07"),
        "schema": registry["schema"],
        "edges": registry.get("edges", {}),
        "services": registry.get("services", {}),
        "routes": routes,
    }


def validate(registry: dict) -> list[str]:
    errs = []
    seen = set()
    paths = []
    for r in registry["routes"]:
        rid = r["id"]
        if rid in seen:
            errs.append(f"duplicate route id: {rid}")
        seen.add(rid)
        if r["kind"] not in ("proxy", "static", "alias"):
            errs.append(f"{rid}: bad kind {r['kind']}")
        if r["kind"] == "proxy" and not r.get("upstream"):
            errs.append(f"{rid}: proxy without upstream")
        ups = r.get("upstream")
        if isinstance(ups, list):
            ups = ups[0]
        if ups and _IP_RE.match(str(ups)) and "100." not in str(ups) \
                and "127." not in str(ups):
            errs.append(f"{rid}: upstream is a non-tailnet IP: {ups}")
        for p in ([r["path"]] if not r["path"].startswith("{")
                  else r["path"].strip("{}").split(",")):
            paths.append((p, rid))
    for i, (pa, ra) in enumerate(paths):
        for pb, rb in paths[i + 1:]:
            pa_, pb_ = _base(pa), _base(pb)
            if ra != rb and pa_ != "/" and pb_ != "/" and \
                    (pa_.startswith(pb_.rstrip("/") + "/")
                     or pb_.startswith(pa_.rstrip("/") + "/")):
                errs.append(f"shadow: {ra}({pa_}) vs {rb}({pb_}) — check order")
    return errs


def main():
    registry = yaml.safe_load(REGISTRY.read_text())
    errs = validate(registry)
    for e in errs:
        print(f"  warn: {e}", file=sys.stderr)
    if "--check" in sys.argv:
        print(f"{len(registry['routes'])} routes, "
              f"{len(errs)} warnings")
        return 0
    payload = build(registry)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {OUT} ({len(payload['routes'])} routes, "
          f"{len(errs)} warnings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
