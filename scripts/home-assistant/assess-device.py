#!/usr/bin/env python3
"""Assess a Home Assistant device or entity by instance/identifier.

Usage:
    assess-device.py michael-ha/sensor.my_sensor
    assess-device.py michael-ha/living_room_light     # searches friendly names/ids
    assess-device.py --format json tony-ha/sr258

Environment variables override file defaults:
    HA_URL, HA_TOKEN   for michael-ha
    DEV_URL, DEV_TOKEN for michael-dev
    TONY_URL, TONY_TOKEN for tony-ha
"""
import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

INSTANCES = {
    "michael-ha": {
        "url_env": "HA_URL",
        "default_url": "http://michael-ha:8123",
        "token_envs": ["HA_TOKEN", "HASS_TOKEN"],
        "token_files": [
            "~/.config/secrets/ha-michael-live.env",
            "~/.local/share/home-assistant-michael/ha-token",
        ],
    },
    "michael-dev": {
        "url_env": "DEV_URL",
        "default_url": "https://tony-dell.taila0626a.ts.net:8124",
        "token_envs": ["DEV_TOKEN", "HASS_TOKEN"],
        "token_files": ["~/.config/secrets/ha-michael-dev.env"],
    },
    "tony-ha": {
        "url_env": "TONY_URL",
        "default_url": "https://tony-dell.taila0626a.ts.net:8123",
        "token_envs": ["TONY_TOKEN", "HASS_TOKEN"],
        "token_files": ["~/.config/secrets/home-assistant-token.env"],
    },
}


def load_token(instance):
    for e in instance["token_envs"]:
        v = os.environ.get(e)
        if v:
            return v
    for p in instance["token_files"]:
        p = os.path.expanduser(p)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() in ("HASS_TOKEN", "HA_TOKEN", "DEV_TOKEN", "TONY_TOKEN"):
                        return v.strip().strip("\"'")
                else:
                    return line
    return None


def get_json(url, token, path):
    req = urllib.request.Request(
        f"{url}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    ctx = None
    if url.startswith("https"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return {"_error": f"HTTP {e.code}", "_message": body}
    except Exception as e:
        return {"_error": str(e)}


def summarize_entity(e, compact=True):
    out = {
        "entity_id": e.get("entity_id"),
        "state": e.get("state"),
        "last_changed": e.get("last_changed"),
        "last_updated": e.get("last_updated"),
    }
    attrs = e.get("attributes") or {}
    out["friendly_name"] = attrs.get("friendly_name")
    out["device_class"] = attrs.get("device_class")
    out["unit"] = attrs.get("unit_of_measurement")
    if not compact:
        out["context"] = {
            k: v
            for k, v in attrs.items()
            if k not in ("friendly_name", "unit_of_measurement", "device_class")
        }
    return out


def search_states(url, token, query, limit=10):
    states = get_json(url, token, "/api/states")
    if not isinstance(states, list):
        return [], states

    q = query.lower()
    exact = []
    fuzzy = []
    for s in states:
        eid = s.get("entity_id") or ""
        fn = (s.get("attributes") or {}).get("friendly_name") or ""
        if query in eid or query in fn:
            exact.append(s)
        elif q in eid.lower() or q in fn.lower():
            fuzzy.append(s)
    matches = (exact or fuzzy)[:limit]
    return matches, None


def main():
    parser = argparse.ArgumentParser(description="Assess a HA device or entity")
    parser.add_argument("target", help="instance/identifier, e.g. michael-ha/sr258")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--limit", type=int, default=10, help="max matches for name search")
    parser.add_argument("--verbose", action="store_true", help="include full attributes in json output")
    args = parser.parse_args()

    if "/" not in args.target:
        print("target must be instance/identifier", file=sys.stderr)
        return 1
    instance_name, ident = args.target.split("/", 1)
    if instance_name not in INSTANCES:
        known = ", ".join(INSTANCES)
        print(f"unknown instance: {instance_name} (known: {known})", file=sys.stderr)
        return 1

    cfg = INSTANCES[instance_name]
    url = os.environ.get(cfg["url_env"], cfg["default_url"]).rstrip("/")
    token = load_token(cfg)
    if not token:
        print(f"no token for {instance_name}", file=sys.stderr)
        return 1

    if "." in ident:
        data = get_json(url, token, f"/api/states/{ident}")
        if isinstance(data, dict) and data.get("entity_id"):
            result = {
                "found": True,
                "type": "entity",
                "instance": instance_name,
                "data": summarize_entity(data, compact=not args.verbose),
            }
        else:
            result = {
                "found": False,
                "type": "entity",
                "instance": instance_name,
                "identifier": ident,
                "error": data,
            }
    else:
        matches, err = search_states(url, token, ident, args.limit)
        if err:
            result = {"found": False, "type": "search", "instance": instance_name, "query": ident, "error": err}
        else:
            result = {
                "found": bool(matches),
                "type": "search",
                "instance": instance_name,
                "query": ident,
                "matches": [summarize_entity(m, compact=not args.verbose) for m in matches],
            }

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        if not result.get("found"):
            print(f"[{instance_name}] not found: {ident}")
            if "error" in result:
                err = result["error"]
                if isinstance(err, dict):
                    print(f"  error: {err.get('_error') or err}")
                    if err.get("_message"):
                        print(f"  message: {err['_message'][:200]}")
                else:
                    print(f"  error: {err}")
            return 1

        if result["type"] == "entity":
            d = result["data"]
            unit = d.get("unit") or ""
            print(f"[{instance_name}] {d['entity_id']}: {d['state']} {unit}")
            if d.get("friendly_name"):
                print(f"  friendly_name: {d['friendly_name']}")
            print(f"  last_changed: {d.get('last_changed')}")
            if d.get("device_class"):
                print(f"  device_class: {d['device_class']}")
        else:
            print(f"[{instance_name}] {len(result['matches'])} match(es) for '{ident}':")
            for m in result["matches"]:
                unit = m.get("unit") or ""
                fn = m.get("friendly_name") or ""
                print(f"  - {m['entity_id']}: {m['state']} {unit}  ({fn})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
