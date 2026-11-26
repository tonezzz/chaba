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
  opencode_map_unwritable  --write asked but the provider block lacks
                           options.baseURL (map would be dead config)
Non-breaking (report only):
  route_not_registered     LiteLLM route absent from the opencode map
                           (only blocks runs if a profile/card picks it)
  map_entry_stale          opencode map entry with no LiteLLM route
  route_unused             LiteLLM route in no profile allowlist
  opencode_map_absent      no opencode.json at --opencode (map checks
                           skipped — nothing to drift yet)
  foreign_provider_ref     profile ref under a non-LiteLLM provider
                           (opencode/, openrouter/, ollama/, ...) —
                           validated by that provider, not this script

Only refs under --provider (default litellm) are checked against the
route list; bare refs count as the synced provider.

Usage:
  sync-opencode-models.py --from-config stacks/idc03/litellm/config.yaml \
      --opencode ~/.config/opencode/opencode.json --check
  sync-opencode-models.py --from-api http://HOST:4000/v1 \
      --key-env LITELLM_MASTER_KEY --write --prune
  sync-opencode-models.py --from-config ... --write --alert   # timer job
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

import yaml

INBOX_API = os.environ.get(
    "CHABA_BOARD_API", "https://idc03.taila0626a.ts.net:10000")
ALERT_STATE = Path(os.environ.get(
    "CHABA_OPENCODE_SYNC_ALERT_STATE",
    "~/var/chaba/opencode-models-sync-alerts.json")).expanduser()
REPEAT_H = 24

# --from-api key discovery: first env var that is set wins; when none is
# set, the litellm secrets files are scanned in the same order
# opencode_profiles.litellm_key() uses. Virtual keys return a PER-KEY
# /v1/models view — fine for "what can this key call" probes, wrong as
# fleet route truth; the timer job therefore uses --from-config.
KEY_VARS = ("LITELLM_MASTER_KEY", "LITELLM_KEY", "LITELLM_KEY_CHABA",
            "LITELLM_KEY_BENCH", "LITELLM_KEY_ADA")
KEY_FILES = (("litellm-keys.env", KEY_VARS),
             ("litellm-chaba.env", ("LITELLM_KEY",)))


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


def resolve_key(key_envs: list[str]) -> tuple[str | None, str | None]:
    """-> (key, source-label). Env first, then secrets files."""
    for var in key_envs:
        if os.environ.get(var):
            return os.environ[var], f"env:{var}"
    for fname, vars_ in KEY_FILES:
        f = Path.home() / ".config" / "secrets" / fname
        if not f.is_file():
            continue
        try:
            lines = f.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            for var in vars_:
                if var in key_envs and line.startswith(var + "="):
                    return (line.split("=", 1)[1].strip()
                            .strip('"').strip("'")), f"file:{fname}:{var}"
    return None, None


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


def provider_of(ref: str, default: str) -> str:
    """litellm/or-gemini-3.5-flash -> litellm; bare name -> default."""
    return ref.split("/", 1)[0] if "/" in ref else default


def strip_provider(ref: str) -> str:
    """litellm/or-gemini-3.5-flash -> or-gemini-3.5-flash."""
    return ref.split("/", 1)[1] if "/" in ref else ref


def load_opencode(path: Path):
    """-> (cfg dict|None, error str|None)."""
    if not path.is_file():
        return None, "absent"
    try:
        return json.loads(path.read_text()), None
    except (OSError, ValueError) as e:
        return None, f"unreadable:{e}"


def file_alert(breaking: list[str]) -> None:
    """One deduped board-api /inbox entry per REPEAT_H window."""
    try:
        st = json.loads(ALERT_STATE.read_text())
    except Exception:
        st = {}
    now = dt.datetime.now(dt.timezone.utc)
    last = st.get("last_alert")
    if last:
        try:
            if (now - dt.datetime.fromisoformat(last)).total_seconds() \
                    < REPEAT_H * 3600:
                return
        except ValueError:
            pass
    text = ("opencode-models-sync: " + str(len(breaking)) +
            " breaking drift finding(s) — " + "; ".join(breaking[:5]) +
            (" …" if len(breaking) > 5 else "") +
            ". Profile allowlists name routes LiteLLM doesn't serve; "
            "fix evals/opencode-lane/profiles/*/profile.yml or the "
            "LiteLLM config. Check: scripts/devnest/"
            "sync-opencode-models.py --from-config "
            "stacks/idc03/litellm/config.yaml --check")
    body = {"text": text,
            "label": "OpenCode model drift",
            "priority": "normal",
            "tags": ["ops", "opencode", "model-drift"],
            "owner": "tony"}
    try:
        req = urllib.request.Request(
            INBOX_API + "/inbox", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = 200 <= resp.status < 300
    except Exception as e:
        sys.stderr.write(f"inbox post failed: {e}\n")
        ok = False
    if ok:
        ALERT_STATE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_STATE.write_text(json.dumps({"last_alert": now.isoformat()}))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-api", metavar="URL",
                     help="LiteLLM base URL, e.g. http://host:4000/v1")
    src.add_argument("--from-config", type=Path,
                     help="litellm config.yaml to parse model_name entries")
    src.add_argument("--models", help="comma-separated explicit route list")
    ap.add_argument("--key-env", default=",".join(KEY_VARS),
                    help="comma-separated env vars tried in order for "
                         "--from-api auth; secrets files are the fallback "
                         "(default %(default)s)")
    ap.add_argument("--opencode", type=Path,
                    default=Path.home() / ".config/opencode/opencode.json",
                    help="opencode.json with provider.<name>.models map")
    ap.add_argument("--profiles-root", type=Path,
                    default=Path("evals/opencode-lane/profiles"))
    ap.add_argument("--provider", default="litellm",
                    help="opencode provider key to sync (default litellm)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report only (default)")
    mode.add_argument("--write", action="store_true", help="add missing to map")
    ap.add_argument("--prune", action="store_true",
                    help="with --write: remove map entries with no route")
    ap.add_argument("--alert", action="store_true",
                    help="file a deduped board-api /inbox entry on "
                         "breaking findings (24h repeat window)")
    args = ap.parse_args()

    key_envs = [v.strip() for v in args.key_env.split(",") if v.strip()]
    route_source = ""
    key_label = None
    if args.from_api:
        key, key_label = resolve_key(key_envs)
        routes = routes_from_api(args.from_api, key)
        route_source = "api"
        if key_label and "MASTER" not in key_label:
            route_source += ":per-key-filtered"
    elif args.from_config:
        routes = routes_from_config(args.from_config)
        route_source = f"config:{args.from_config}"
    else:
        routes = sorted(m.strip() for m in args.models.split(",")
                        if m.strip())
        route_source = "explicit"
    if not routes:
        print("no routes discovered — refusing to act on an empty truth",
              file=sys.stderr)
        return 2
    route_set = set(routes)

    ocfg, oc_err = load_opencode(args.opencode)
    mmap = {}
    prov_ready = False
    if oc_err == "absent":
        pass
    elif oc_err:
        oc_err = f"unreadable:{oc_err}"
    else:
        prov = (ocfg.get("provider") or {}).get(args.provider) or {}
        mmap = prov.get("models") or {}
        # --write may only maintain a map inside a provider block that
        # already knows where LiteLLM lives — otherwise it would mint a
        # dead provider.litellm.models stub with no baseURL/apiKey.
        prov_ready = bool(
            (prov.get("options") or {}).get("baseURL"))

    breaking, notes = [], []

    # profile refs under the synced provider must exist as real routes
    profiles = load_profiles(args.profiles_root) \
        if args.profiles_root.is_dir() else {}
    foreign = 0
    for pid, p in profiles.items():
        if p["status"] == "disabled":
            continue
        own = []
        for ref in p["allowed"]:
            if provider_of(ref, args.provider) == args.provider:
                own.append(ref)
            else:
                foreign += 1
        for ref in own:
            r = strip_provider(ref)
            if r not in route_set:
                breaking.append(
                    f"profile_route_missing: {pid} allows {ref} — "
                    "no such route")
        if p["default"]:
            if provider_of(p["default"], args.provider) == args.provider:
                if strip_provider(p["default"]) not in route_set:
                    breaking.append(
                        f"profile_route_missing: {pid} default "
                        f"{p['default']} — no such route")
            # empty allowed = any model in tier (check_envelope:269) —
            # the unallowed check only applies to a non-empty list
            if p["allowed"] and p["default"] not in p["allowed"]:
                breaking.append(
                    f"profile_default_unallowed: {pid} default "
                    f"{p['default']} not in allowed")
    if foreign:
        notes.append(f"foreign_provider_refs_skipped: {foreign}")

    if oc_err == "absent":
        notes.append(f"opencode_map_absent: {args.opencode}")
    elif oc_err:
        breaking.append(f"opencode_map_unreadable: {args.opencode} "
                        f"({oc_err}) — fix or rename; sync cannot "
                        "maintain it")
    elif not prov_ready:
        notes.append(f"provider_block_absent: provider.{args.provider} "
                     ".options.baseURL missing — map checks skipped")
    else:
        missing_in_map = sorted(r for r in routes if r not in mmap)
        stale_in_map = sorted(k for k in mmap if k not in route_set)
        for r in missing_in_map:
            notes.append(f"route_not_registered: {r}")
        for k in stale_in_map:
            notes.append(f"map_entry_stale: {k}")
        used = set()
        for p in profiles.values():
            for ref in list(p["allowed"]) + [p["default"]]:
                if ref and provider_of(ref, args.provider) == \
                        args.provider:
                    used.add(strip_provider(ref))
        for r in sorted(route_set - used):
            notes.append(f"route_unused: {r}")

        if args.write:
            for r in missing_in_map:
                mmap[r] = {"name": r}
            pruned = []
            if args.prune:
                for k in stale_in_map:
                    mmap.pop(k, None)
                    pruned.append(k)
            ocfg["provider"][args.provider]["models"] = mmap
            args.opencode.parent.mkdir(parents=True, exist_ok=True)
            args.opencode.write_text(json.dumps(ocfg, indent=2) + "\n")
            notes.append("map_written: "
                         + json.dumps({"added": missing_in_map,
                                       "pruned": pruned,
                                       "path": str(args.opencode)}))

    if args.write and oc_err is None and not prov_ready:
        breaking.append(
            f"opencode_map_unwritable: provider.{args.provider} lacks "
            "options.baseURL — configure the provider block once by "
            "hand, then rerun --write")

    report = {
        "ok": not breaking,
        "provider": args.provider,
        "route_source": route_source,
        "key_env": key_label,
        "routes": len(routes),
        "profiles": len(profiles),
        "opencode": str(args.opencode),
        "breaking": breaking,
        "notes": notes,
    }

    if args.alert and breaking:
        file_alert(breaking)

    print(json.dumps(report, indent=1))
    return 1 if breaking else 0


if __name__ == "__main__":
    sys.exit(main())
