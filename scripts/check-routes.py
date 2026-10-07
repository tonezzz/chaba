#!/usr/bin/env python3
"""Route health lane — probe every route in ssot.routes.yml.

For each route: hit the edge path (http://localhost) and, for proxy
routes, the upstream directly. Emits route-health.json (served at
/apps/route-health.json by the edge) — the tripwire that would have
caught the dead :9005 behind /snapshot and the idc01 card endpoint.

Usage: check-routes.py [--write]   (default: print report only)
"""
import json
import subprocess
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "docs/ssot/infrastructure/ssot.routes.yml"
OUT = REPO / "stacks/web/public/apps/route-health.json"
EDGE = "http://localhost"
TIMEOUT = 5


def probe(url: str) -> tuple[int | None, str]:
    """HTTP status or error class."""
    try:
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "route-health/1"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, "ok"
    except urllib.error.HTTPError as e:
        return e.code, "ok"          # reached a live HTTP server
    except Exception as e:
        return None, type(e).__name__


def check_route(r: dict) -> dict:
    rid, kind, path = r["id"], r["kind"], r["path"]
    base = path.rstrip("*") or "/"
    if base.startswith("{"):
        base = base.strip("{}").split(",")[0].rstrip("*") or "/"
    res = {"id": rid, "kind": kind, "path": base, "owner": r.get("owner")}

    if r.get("expect_down"):
        return {**res, "ok": None,
                "detail": "expected down — " + (r.get("note") or "off by design")}

    if kind == "alias":
        return {**res, "ok": None, "detail": "alias — edge redirect only"}

    if kind == "static":
        root = REPO / "stacks/web/public" / base.lstrip("/")
        if root.exists():
            return {**res, "ok": True, "detail": "static root exists"}
        return {**res, "ok": False, "detail": f"missing {root}"}

    # proxy — edge check
    v = r.get("verify") or {}
    edge_path = base.rstrip("/") + (v.get("get") or "/")
    st, err = probe(EDGE + edge_path)
    edge_ok = st is not None and st < 500
    if v.get("expect") and st is not None:
        edge_ok = st == int(v["expect"])
    res["edge"] = {"url": edge_path, "status": st, "ok": edge_ok}

    # upstream check
    ups = r.get("upstream")
    ups = ups if isinstance(ups, list) else [ups]
    ures = []
    for u in ups:
        if not u.startswith(("http://", "https://")):
            u = ("https://" if "ts.net" in u else "http://") + u
        host = u.split("://", 1)[1].split("/")[0].split(":")[0]
        if host == "host.containers.internal":
            # host gateway — only meaningful inside the container; the
            # edge probe above already covers the path
            ures.append({"upstream": u, "ok": None, "detail": "host gw"})
            continue
        if "." not in host and host != "localhost":
            # docker-net name — probe the container's status instead
            rc = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", host],
                capture_output=True, text=True, timeout=TIMEOUT)
            running = rc.stdout.strip() == "true"
            ures.append({"upstream": u, "ok": running,
                         "detail": f"container running={running}"})
            continue
        st2, err2 = probe(u + "/")
        ures.append({"upstream": u, "status": st2,
                     "ok": st2 is not None, "detail": err2})
    res["upstream"] = ures
    res["ok"] = bool(edge_ok) and all(u["ok"] is not False for u in ures)
    res["detail"] = (f"edge {st or err}" +
                     ("; " + "; ".join(f"{u['upstream']} {u.get('status') or u['detail']}"
                                       for u in ures if not u["ok"])
                      if ures else ""))
    return res


def main():
    registry = yaml.safe_load(REGISTRY.read_text())
    routes = [r for r in registry["routes"]
              if not r.get("edges") or "tony-dell-web" in r["edges"]]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check_route, routes))

    bad = [r for r in results if r["ok"] is False]
    unk = [r for r in results if r["ok"] is None]
    for r in results:
        mark = "✓" if r["ok"] is True else ("✗" if r["ok"] is False else "·")
        print(f"{mark} {r['id']:24} {r['detail']}")
    print(f"\n{sum(r['ok'] is True for r in results)} ok, "
          f"{len(bad)} failing, {len(unk)} skipped")

    payload = {
        "generated": datetime.now(timezone(timedelta(hours=7)))
        .strftime("%Y-%m-%d %H:%M:%S +07"),
        "edge": EDGE,
        "results": results,
    }
    if "--write" in sys.argv:
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"wrote {OUT}")
        return 0   # dead routes are data, not a probe failure
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
