#!/usr/bin/env python3
"""lane-watcher.py — poll registered render lanes and auto-land completions.

Reads a pending-jobs registry (JSON list) and, for each entry, asks
land-render.py for status; on 'completed' it invokes land-render.py to
land the artifact into the campaign's 30-generated-raw/ and removes the
entry. Also samples KK-Mac admission (heartbeat) and logs transitions so
wake-ups are visible without manual checks.

Registry entry:
  {"lane": "omen-sd"|"kk-mac-nest", "job": "...", "port": 8400,
   "campaign": "AS-...", "asset_id": "...", "request_id": "...",
   "remote": "gdrive:ada-nest-adobe-stock", "label": "optional"}

Usage:
  lane-watcher.py --pending ~/.local/state/adobe-stock-lane-watcher/pending.json
  lane-watcher.py --add omen-sd job_XXX --port 8400 --campaign AS-... \
      --asset-id comparison-g --request-id render-004
  lane-watcher.py --list

Designed for cron: */15 * * * * python3 .../lane-watcher.py
State/log live next to the registry (.state.json, watcher.log).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAND = HERE / "land-render.py"
DEFAULT_PENDING = Path.home() / ".local/state/adobe-stock-lane-watcher/pending.json"


def load_pending(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_pending(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=1) + "\n")


def log(path: Path, msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {msg}"
    print(line)
    with open(path.with_suffix(".log"), "a") as f:
        f.write(line + "\n")


def land_render_status(entry: dict) -> dict:
    cmd = [sys.executable, str(LAND), "--lane", entry["lane"],
           "--job", entry["job"], "--campaign", entry["campaign"],
           "--status-only"]
    if entry["lane"] == "omen-sd":
        cmd += ["--port", str(entry.get("port", 8399))]
    if entry["lane"] == "kk-mac-nest":
        cmd += ["--pack", entry.get("pack") or entry["job"],
                "--remote", entry.get("remote",
                                     "gdrive:ada-nest-adobe-stock")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    try:
        return json.loads(r.stdout[r.stdout.index("{"):])
    except Exception:
        return {"status": "probe_error",
                "error": (r.stderr or r.stdout)[-200:]}


def land_render_full(entry: dict) -> dict:
    cmd = [sys.executable, str(LAND), "--lane", entry["lane"],
           "--job", entry["job"], "--campaign", entry["campaign"],
           "--asset-id", entry.get("asset_id", ""),
           "--request-id", entry.get("request_id", entry["job"]),
           "--timeout-s", "600"]
    if entry["lane"] == "omen-sd":
        cmd += ["--port", str(entry.get("port", 8399))]
    if entry["lane"] == "kk-mac-nest":
        cmd += ["--pack", entry.get("pack") or entry["job"],
                "--remote", entry.get("remote",
                                     "gdrive:ada-nest-adobe-stock")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    try:
        return json.loads(r.stdout[r.stdout.index("{"):])
    except Exception:
        return {"ok": False,
                "error": (r.stderr or r.stdout)[-300:]}


def kk_mac_probe(state_path: Path) -> None:
    """Log KK-Mac heartbeat eligibility transitions (wake detection)."""
    try:
        sys.path.insert(0, str(HERE.parent / "devnest"))
        import kk_mac_admission  # noqa: PLC0415
        snap = kk_mac_admission.snapshot()
    except Exception as exc:
        snap = {"eligible": False, "reasons": [f"probe_error:{exc}"]}
    prev = {}
    if state_path.exists():
        prev = json.loads(state_path.read_text())
    cur = {"eligible": snap.get("eligible"),
           "heartbeat_age_s": snap.get("heartbeat_age_s"),
           "reasons": snap.get("reasons"),
           "at": time.time()}
    if prev.get("eligible") != cur["eligible"]:
        log(state_path, f"kk-mac heartbeat: eligible {prev.get('eligible')} "
                        f"-> {cur['eligible']} reasons={cur['reasons']}")
    state_path.write_text(json.dumps(cur, indent=1) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pending", default=str(DEFAULT_PENDING))
    ap.add_argument("--add", nargs="+", metavar="KV",
                    help="lane job k=v ... e.g. --add omen-sd job_X port=8400 campaign=AS-.. asset_id=x")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-heartbeat", action="store_true")
    args = ap.parse_args()

    ppath = Path(args.pending)
    entries = load_pending(ppath)

    if args.add:
        lane, job = args.add[0], args.add[1]
        kv = dict(x.split("=", 1) for x in args.add[2:])
        entry = {"lane": lane, "job": job,
                 "campaign": kv.get("campaign", ""),
                 "asset_id": kv.get("asset_id", ""),
                 "request_id": kv.get("request_id", job),
                 "label": kv.get("label", "")}
        for k in ("port", "pack", "remote"):
            if k in kv:
                entry[k] = int(kv[k]) if k == "port" else kv[k]
        entries = [e for e in entries
                   if not (e["lane"] == lane and e["job"] == job)]
        entries.append(entry)
        save_pending(ppath, entries)
        print(json.dumps({"added": entry, "pending": len(entries)}, indent=1))
        return 0

    if args.list:
        print(json.dumps(entries, indent=1))
        return 0

    state = ppath.with_suffix(".state.json")
    if not args.no_heartbeat:
        kk_mac_probe(state)

    remaining = []
    for e in entries:
        st = land_render_status(e)
        status = st.get("status")
        if status == "completed":
            out = land_render_full(e)
            log(ppath, f"LANDED {e['lane']} {e['job']} -> "
                       f"{json.dumps(out)[:300]}")
            if not out.get("ok"):
                remaining.append(e)  # keep for retry next tick
        elif status in ("failed", "error", "expired"):
            log(ppath, f"DEAD {e['lane']} {e['job']} status={status} "
                       f"err={st.get('error')} — dropped from registry")
        else:
            remaining.append(e)
    save_pending(ppath, remaining)
    log(ppath, f"tick: {len(entries)} checked, {len(remaining)} pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
