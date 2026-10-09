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


# --- caddy emission (phase 2) --------------------------------------------
# The registry drives the whole Caddyfile. Preamble (global block, the
# :80 docs front, :8080 site head, :8081 dev block) is edge identity and
# stays as a literal template; every per-app route is emitted from the
# registry. Routes marked `custom: true` keep a hand-tuned block here.

CADDY_OUT = REPO / "stacks/web/Caddyfile.generated"

CADDY_PREAMBLE = """{
	admin localhost:2018
	auto_https off
}

# GENERATED FILE — do not edit by hand.
# Source: docs/ssot/infrastructure/ssot.routes.yml + scripts/render-routes.py

http://:80 {
	log {
		output file /data/access.log {
			roll_size 10mb
			roll_keep 5
		}
		format json
	}
	@root80 path /
	handle @root80 {
		reverse_proxy 127.0.0.1:8092 {
			header_up Host 127.0.0.1:8092
		}
	}
	reverse_proxy 127.0.0.1:8080 {
		header_up Host 127.0.0.1:8080
	}
}

http://127.0.0.1:8080 {
	bind 127.0.0.1
	root * /srv/public

	# Ensure PWA shell and catalog metadata are always revalidated
	@pwa_shell path_regexp (\\.(html|json|yml)|/)$
	header @pwa_shell Cache-Control "no-cache"

	# Never let the browser or any intermediary cache the service worker
	handle /apps/sw.js {
		root * /srv/public
		file_server
		header Cache-Control "no-cache, no-store, must-revalidate"
	}
"""

CADDY_POSTAMBLE = """
	# Pretty URLs: /cameras -> /cameras.json
	rewrite /cameras /cameras.json
	file_server
}

# chaba.h3 local dev root
:8081 {
	log {
		output file /data/access-8081.log {
			roll_size 5mb
			roll_keep 3
		}
		format json
	}
	root * /srv/public/chaba-h3
	file_server
}
"""

# Hand-tuned blocks for routes flagged `custom: true` — preserved verbatim
# from the manual Caddyfile (mixed sub-handles, multi-pattern routes).
CUSTOM_BLOCKS = {
    "gev-live": """
	handle /apps/gev-live {
		redir /apps/gev-live/ 308
	}
	handle_path /apps/gev-live/* {
		@ws path /ws
		handle @ws {
			reverse_proxy 127.0.0.1:8789
		}
		handle {
			root * /srv/public/apps/gev-live
			file_server
		}
	}
""",
    "gesture-live": """
	handle /apps/gesture-live {
		redir /apps/gesture-live/ 308
	}
	handle_path /apps/gesture-live/* {
		@ws path /ws
		handle @ws {
			reverse_proxy 100.68.142.13:8794
		}
		# /health (and any future plain-HTTP path) lives on the same
		# relay port — unlike gev-live there is no static side here.
		handle {
			reverse_proxy 100.68.142.13:8794
		}
	}
""",
    "gesture": """
	handle /apps/gesture {
		redir * /apps/gesture/ 308
	}
	handle_path /apps/gesture/* {
		root * /srv/public/apps/gesture
		rewrite /screen /screen.html
		file_server
	}
""",
    "trade-api": """
	handle /apps/trade/api/* {
		uri strip_prefix /apps/trade
		reverse_proxy 100.68.142.13:9002 {
			header_up Host localhost
			header_up X-Forwarded-Prefix /apps/trade
		}
	}

	handle /apps/trade/api/ws/* {
		uri strip_prefix /apps/trade
		reverse_proxy 100.68.142.13:9002 {
			header_up Host localhost
			header_up X-Forwarded-Prefix /apps/trade
			header_up Connection {>Connection}
			header_up Upgrade {>Upgrade}
		}
	}

	handle /api/ws/* {
		reverse_proxy 100.68.142.13:9002 {
			header_up Host localhost
			header_up Connection {>Connection}
			header_up Upgrade {>Upgrade}
		}
	}
""",
    "eye-mddb": """
	# MDDB write lane for /apps/eye — exposes ONLY /v1/add (bench rows
	# bench/edge-* and the eye/latest detections doc). Writes need a
	# tailnet identity; there is no read surface here (CMS scripts read
	# MDDB directly by tailnet IP).
	handle /apps/eye-mddb/v1/add {
		@anon_write_eye-mddb {
			not method GET HEAD
			not header Tailscale-User-Login *
		}
		respond @anon_write_eye-mddb "forbidden: eye-mddb writes need a tailnet identity" 403
		uri strip_prefix /apps/eye-mddb
		reverse_proxy 100.102.134.91:11023
	}
""",
    "helm": """
	@apps_helm path /apps/helm /apps/helm/*
	handle @apps_helm {
		reverse_proxy 127.0.0.1:3003 {
			header_up Host localhost
		}
	}
""",
    "trade": """
	handle_path /apps/trade/* {
		root * /srv/public/apps/trade
		file_server
		header Cache-Control "public, max-age=3600"
	}
""",
    "docs": """
	@root path /
	handle @root {
		reverse_proxy 127.0.0.1:8092 {
			header_up Host 127.0.0.1:8092
		}
	}

	handle /new {
		redir /new/ 308
	}
	handle_path /new/* {
		reverse_proxy 127.0.0.1:8092 {
			header_up Host 127.0.0.1:8092
		}
	}

	handle /decisions {
		reverse_proxy 127.0.0.1:8092 {
			header_up Host 127.0.0.1:8092
		}
	}
	handle /decisions/* {
		reverse_proxy 127.0.0.1:8092 {
			header_up Host 127.0.0.1:8092
		}
	}
	handle /infrastructure {
		reverse_proxy 127.0.0.1:8092 {
			header_up Host 127.0.0.1:8092
		}
	}
	handle /infrastructure/* {
		reverse_proxy 127.0.0.1:8092 {
			header_up Host 127.0.0.1:8092
		}
	}
""",
}

HLS_BLOCK = """
	header Access-Control-Allow-Origin "*"
	header Access-Control-Allow-Headers "Origin, Range"
	header Access-Control-Expose-Headers "Content-Length, Content-Range"
	header Cache-Control "no-cache, no-store"
	@m3u8{r} path *.m3u8
	header @m3u8{r} Content-Type "application/vnd.apple.mpegurl"
	@ts{r} path *.ts
	header @ts{r} Content-Type "video/mp2t"
	@vtt{r} path *.vtt
	header @vtt{r} Content-Type "text/vtt"
"""

AUTH_WRITE_BLOCK = """		@anon_write_{r} {
			not method GET HEAD
			not header Tailscale-User-Login *
		}
		respond @anon_write_{r} "forbidden: {r} writes need a tailnet identity" 403
"""


def _emit_route(r: dict) -> str:
    rid, kind, path = r["id"], r["kind"], r["path"]
    if r.get("custom"):
        return CUSTOM_BLOCKS[rid]
    base = path.rstrip("/*")
    exact = not path.endswith("*")
    out = []
    if kind == "alias":
        tgt = r["target"]
        if "{uri}" in tgt:
            pre = tgt.replace("{uri}", "")
            out += [f"\thandle {base} {{", f"\t\tredir * {pre} 308", "\t}"]
            out += [f"\thandle_path {base}/* {{", f"\t\tredir * {tgt} 308", "\t}"]
        elif exact:
            out += [f"\thandle {base} {{", f"\t\tredir * {tgt} 308", "\t}"]
        else:
            out += [f"\thandle {base}* {{", f"\t\tredir * {tgt} 308", "\t}"]
        return "\n".join(out) + "\n"
    if kind == "static":
        if not exact:
            out += [f"\thandle {base} {{", f"\t\tredir * {base}/ 308", "\t}"]
            body = [f"	handle_path {base}/* {{"]
        else:
            body = [f"	handle {base} {{"]
        body.append(f"		root * /srv/public{base}")
        if r.get("hls"):
            body.append(HLS_BLOCK.replace("{r}", rid.replace("-", "_")).rstrip())
        for k, v in (r.get("headers") or {}).items():
            body.append(f'		header {k} "{v}"')
        body.append("		file_server")
        body.append("	}")
        out.append("\n".join(body))
        return "\n".join(out) + "\n"
    if kind == "proxy":
        strip = r.get("strip")
        use_handle_path = (not exact) and strip and strip.rstrip("/") == base
        if not exact:
            out += [f"\thandle {base} {{", f"\t\tredir * {base}/ 308", "\t}"]
        if use_handle_path:
            body = [f"	handle_path {base}/* {{"]
        elif exact and strip:
            body = [f"	handle_path {base} {{"]
        elif exact:
            body = [f"	handle {base} {{"]
        else:
            body = [f"	handle {base}/* {{"]
        if strip and not use_handle_path:
            body.append(f"		uri strip_prefix {strip}")
        if r.get("auth") == "tailnet-identity-write":
            body.append(AUTH_WRITE_BLOCK.replace("{r}", rid).rstrip())
        ups = r["upstream"]
        ups = ups if isinstance(ups, list) else [ups]
        inner = []
        if r.get("upstream_host"):
            inner.append(f"header_up Host {r['upstream_host']}")
        if r.get("lb"):
            inner += [f"lb_policy {r['lb']}", "lb_retries 2", "fail_duration 15s"]
        if inner:
            body.append("		reverse_proxy " + " ".join(ups) + " {")
            body += ["			" + i for i in inner]
            body.append("		}")
        else:
            body.append("		reverse_proxy " + " ".join(ups))
        body.append("	}")
        out.append("\n".join(body))
        return "\n".join(out) + "\n"
    return ""


def emit_caddy(registry: dict) -> str:
    parts = [CADDY_PREAMBLE]
    for r in registry["routes"]:
        if r.get("edges") and "tony-dell-web" not in r["edges"]:
            continue
        block = _emit_route(r)
        if block:
            parts.append(block)
    parts.append(CADDY_POSTAMBLE)
    return "\n".join(parts)


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
    if "--caddy" in sys.argv:
        CADDY_OUT.write_text(emit_caddy(registry))
        print(f"wrote {CADDY_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
