#!/usr/bin/env python3
"""Keep OpenCode provider model maps + profile allowlists in step with
LiteLLM routes (OPS-1020).

Registering one model today means touching four surfaces by hand:
LiteLLM config (live + repo copy), each runner's global
~/.config/opencode/opencode.json provider map, and every profile's
model.allowed. Nothing cross-validates them — drift is silent until an
agent run dies at session create ("Unexpected server error" when the
model isn't in the opencode provider map, nemotron pilot 2026-10-30).

This script reads the LiteLLM route list (live /v1/models or the
config.yaml model_name entries), then:

  --check   report drift, exit 1 if any breaking class found (CI mode)
  --write   add missing models to the opencode provider map; stale map
            entries are reported, removed only with --prune

Breaking classes (fail --check):
  profile_route_missing    model.allowed / model.default names a route
                           LiteLLM doesn't serve — run dies at provider
  profile_default_unallowed default not in its own allowed list
Non-breaking (report only):
  route_not_registered     LiteLLM route absent from the opencode map
                           (only blocks runs if a profile/card picks it)
  map_entry_stale          opencode map entry with no LiteLLM route
  route_unused             LiteLLM route in no profile allowlist

Usage:
  sync-opencode-models.py --from-config stacks/idc03/litellm/config.yaml \
      --opencode ~/.config/opencode/opencode.json --check
  sync-opencode-models.py --from-api http://HOST:4000/v1 \
      --key-env LITELLM_MASTER_KEY --write --prune
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

import yaml


def routes_from_api(base: str, key: str | None) -> list[str]:
    req = urllib.request.Request(base.rstrip("/") + "/models")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    d = json.load(urllib.request.urlopen(req, timeout=15))
    return sorted(m["id"] for m in d.get("data", []))


def routes_from_config(path: Path) -> list[str]:
    cfg = yaml.safe_load(path.read_text())
    out = []
    for m in cfg.get("model_list") or []:
        name = m.get("model_name")
        if name:
            out.append(name)
    return sorted(set(out))


def load_profiles(root: Path) -> dict:
    """profile id -> {allowed, default} model refs (provider-prefixed)."""
    out = {}
    for p in sorted(root.glob("*/profile.yml")):
        prof = yaml.safe_load(p.read_text()) or {}
        mo = prof.get("model") or {}
        out[prof.get("id") or p.parent.name] = {
            "allowed": list(mo.get("allowed") or []),
            "default": mo.get("default") or "",
            "status": prof.get("status") or "",
        }
    return out


def strip_provider(ref: str) -> str:
    """litellm/or-gemini-3.5-flash -> or-gemini-3.5-flash."""
    return ref.split("/", 1)[1] if "/" in ref else ref


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-api", metavar="URL",
                     help="LiteLLM base URL, e.g. http://host:4000/v1")
    src.add_argument("--from-config", type=Path,
                     help="litellm config.yaml to parse model_name entries")
    src.add_argument("--models", help="comma-separated explicit route list")
    ap.add_argument("--key-env", default="LITELLM_MASTER_KEY",
                    help="env var holding the API key (default %(default)s)")
    ap.add_argument("--opencode", type=Path,
                    default=Path.home() / ".config/opencode/opencode.json",
                    help="opencode.json with provider.litellm.models map")
    ap.add_argument("--profiles-root", type=Path,
                    default=Path("evals/opencode-lane/profiles"))
    ap.add_argument("--provider", default="litellm",
                    help="opencode provider key to sync (default litellm)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report only (default)")
    mode.add_argument("--write", action="store_true", help="add missing to map")
    ap.add_argument("--prune", action="store_true",
                    help="with --write: remove map entries with no route")
    args = ap.parse_args()

    if args.from_api:
        key = os.environ.get(args.key_env) or None
        routes = routes_from_api(args.from_api, key)
    elif args.from_config:
        routes = routes_from_config(args.from_config)
    else:
        routes = sorted(m.strip() for m in args.models.split(",") if m.strip())
    if not routes:
        print("no routes discovered — refusing to act on an empty truth", file=sys.stderr)
        return 2
    route_set = set(routes)

    ocfg = {}
    if args.opencode.is_file():
        ocfg = json.loads(args.opencode.read_text())
    prov = ocfg.setdefault("provider", {}).setdefault(args.provider, {})
    mmap = prov.setdefault("models", {})

    breaking, notes = [], []

    # profile refs must exist as real routes
    profiles = load_profiles(args.profiles_root) if args.profiles_root.is_dir() else {}
    for pid, p in profiles.items():
        if p["status"] == "disabled":
            continue
        for ref in p["allowed"]:
            r = strip_provider(ref)
            if r not in route_set:
                breaking.append(f"profile_route_missing: {pid} allows {ref} — no such route")
        if p["default"] and p["default"] not in p["allowed"]:
            breaking.append(f"profile_default_unallowed: {pid} default {p['default']} not in allowed")
        elif p["default"] and strip_provider(p["default"]) not in route_set:
            breaking.append(f"profile_route_missing: {pid} default {p['default']} — no such route")

    missing_in_map = sorted(r for r in routes if r not in mmap)
    stale_in_map = sorted(k for k in mmap if k not in route_set)
    for r in missing_in_map:
        notes.append(f"route_not_registered: {r}")
    for k in stale_in_map:
        notes.append(f"map_entry_stale: {k}")
    used = {strip_provider(ref) for p in profiles.values() for ref in p["allowed"]}
    used |= {strip_provider(p["default"]) for p in profiles.values() if p["default"]}
    for r in sorted(route_set - used):
        notes.append(f"route_unused: {r}")

    report = {
        "ok": not breaking,
        "routes": len(routes),
        "breaking": breaking,
        "notes": notes,
    }

    if args.write:
        for r in missing_in_map:
            mmap[r] = {"name": r}
        pruned = []
        if args.prune:
            for k in stale_in_map:
                mmap.pop(k, None)
                pruned.append(k)
        args.opencode.parent.mkdir(parents=True, exist_ok=True)
        args.opencode.write_text(json.dumps(ocfg, indent=2) + "\n")
        report["written"] = {"added": missing_in_map, "pruned": pruned,
                             "path": str(args.opencode)}

    print(json.dumps(report, indent=1))
    return 1 if breaking else 0


if __name__ == "__main__":
    sys.exit(main())
