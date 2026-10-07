#!/usr/bin/env python3
"""vcast-auto-health — vcast/input-bridge lane probes -> kanban cards.

Probes the vcast stack (input-bridge relay on idc03, cast services on
tony-dell) and writes/updates `vcast-auto-*` kanban cards so a dead lane
becomes tracked work instead of a silently broken screen. Mirrors
gev-auto-health.py's lifecycle:

  check fails    -> column=review, note = probe result (updates = incident log)
  check recovers -> column=done, note records the recovery time
  open >= 12h    -> priority bumped to high

Lanes (the card vcast-health-loop spec; recreated 2026-10-07 after the
original dispatch branch was pruned unmerged — kanban-sync.sh had been
calling this file the whole time and every tick logged "failed"):

  relay        GET http://127.0.0.1/api/input-bridge/health -> 200
               (edge proxies to idc03:3010)
  displays     /displays must list the fleet healthy: every label
               matching headless-* / vcast-real-* connected, and no
               screen-N name parked on the wrong slot (the 2026-10-06
               migration scramble: screen-6 sat on slot 1)
  flap         journald on idc03: `screen N superseded`/`disconnected`
               events in the last 24h — the card metric is 0/24h
  flap-check   `node vcast-flap-check.mjs` inside the relay's podman
               image on idc03 — exercises the stale-socket race against
               the DEPLOYED server.mjs, exits 0 on pass
  lease        /capture active leases older than 6h = stale (the
               cast_recast_stale_lease regression surface); camwall zone
               enabled but bound to a disconnected/absent screen = stale
               binding
  audit-cast   systemctl --user show audit-cast.service -p Result ->
               success (timer-triggered oneshot; inactive is normal)
  cast-browser-proxy  GET 127.0.0.1:8799/<bogus> -> any HTTP < 500
  yt-live-api  GET 127.0.0.1:8791/status -> 200

Runs on tony-dell inside the kanban-sync tick; writes into a chaba
checkout. Committing is the caller's job — kanban-sync.sh's `git add
cards/` block commits and pushes whatever this writes.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(os.environ.get(
    "CHABA_REPO",
    str(Path(__file__).resolve().parents[2])))
CARDS = REPO / "docs" / "ssot" / "kanban" / "cards"

EDGE = os.environ.get("VCAST_EDGE", "http://127.0.0.1/api/input-bridge")
RELAY_HOST = os.environ.get("VCAST_RELAY_HOST", "idc03")
FLAP_WINDOW = os.environ.get("VCAST_FLAP_WINDOW", "24 hours ago")
LEASE_STALE_S = 6 * 3600
TIMEOUT_S = 15
ESCALATE_H = 12

# display labels that must exist AND be connected — the scenario fleet
EXPECTED_DISPLAYS = ("headless-", "vcast-real-")


def probe_http(path_url: str, expect_200: bool) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            path_url, headers={"User-Agent": "vcast-auto-health"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            code = r.getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        return False, f"GET {path_url} failed: {e}"
    if expect_200:
        if code == 200:
            return True, "HTTP 200"
        return False, f"GET {path_url} -> HTTP {code} (want 200)"
    if code >= 500:
        return False, f"GET {path_url} -> HTTP {code} (5xx)"
    return True, f"HTTP {code} (server answering)"


def get_json(path_url: str):
    try:
        req = urllib.request.Request(
            path_url, headers={"User-Agent": "vcast-auto-health"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.load(r), None
    except Exception as e:
        return None, f"GET {path_url} failed: {e}"


def ssh_idc03(cmd: str, timeout: int = 30) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             RELAY_HOST, cmd],
            capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return False, f"ssh {RELAY_HOST} failed: {e}"
    if p.returncode != 0:
        return False, f"ssh {RELAY_HOST} rc={p.returncode}: " \
                      f"{p.stderr.strip()[:160]}"
    return True, p.stdout


def probe_displays() -> tuple[bool, str]:
    d, err = get_json(f"{EDGE}/displays")
    if d is None:
        return False, err
    screens = d.get("screens") or []
    problems = []
    for prefix in EXPECTED_DISPLAYS:
        mine = [s for s in screens
                if str(s.get("label") or "").startswith(prefix)]
        if not mine:
            problems.append(f"no {prefix}* display registered")
            continue
        dead = [s["screen"] for s in mine if not s.get("connected")]
        if dead:
            problems.append(f"{prefix}* disconnected: screens {dead}")
    for s in screens:
        m = re.match(r"^screen-(\d+)$", str(s.get("name") or ""))
        if m and int(m.group(1)) != int(s.get("screen") or -1):
            problems.append(
                f"name/slot drift: {s['name']} on slot {s['screen']}")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(screens)} screens, fleet connected, slots aligned"


def probe_flap() -> tuple[bool, str]:
    ok, out = ssh_idc03(
        "journalctl --user -u input-bridge.service "
        f"--since '{FLAP_WINDOW}' --no-pager -o cat 2>/dev/null "
        "| grep -cE 'superseded by new socket|disconnected' || true")
    if not ok:
        return False, out
    try:
        n = int(out.strip() or "0")
    except ValueError:
        n = 0
    if n:
        return False, f"{n} supersede/disconnect events in 24h (want 0)"
    return True, "0 flap events in 24h"


def probe_flap_check() -> tuple[bool, str]:
    ok, out = ssh_idc03(
        "cd ~/apps/input-bridge && podman run --rm --network=host "
        "-v $PWD:/app:ro,Z -w /app docker.io/library/node:22-alpine "
        "node vcast-flap-check.mjs 2>&1 | tail -12",
        timeout=90)
    if not ok:
        return False, out
    if re.search(r"^FAIL", out, re.M):
        return False, "vcast-flap-check failures: " + \
                      "; ".join(re.findall(r"^FAIL.*", out, re.M))[:200]
    return True, "vcast-flap-check all PASS"


def probe_lease() -> tuple[bool, str]:
    caps, err = get_json(f"{EDGE}/capture")
    if caps is None:
        return False, err
    now = time.time()
    stale = []
    for scr, c in (caps.get("captures") or {}).items():
        try:
            age = now - datetime.fromisoformat(
                str(c.get("since") or "").replace("Z", "+00:00")
            ).timestamp()
        except (ValueError, TypeError):
            age = LEASE_STALE_S + 1
        if c.get("active") and age > LEASE_STALE_S:
            stale.append(f"screen {scr} capture lease {int(age/3600)}h old")
    wall, err = get_json(f"{EDGE}/camwall")
    if wall is None:
        return False, err
    disp, _ = get_json(f"{EDGE}/displays")
    live_screens = {int(s["screen"]) for s in (disp or {}).get("screens", [])
                    if s.get("connected")}
    for z, v in (wall.get("zones") or {}).items():
        bound = v.get("screen")
        if v.get("enabled") and bound is not None \
                and int(bound) not in live_screens:
            stale.append(f"zone {z} bound to offline/absent screen {bound}")
    if stale:
        return False, "; ".join(stale)
    return True, "no stale leases/bindings"


def probe_audit_cast() -> tuple[bool, str]:
    try:
        p = subprocess.run(
            ["systemctl", "--user", "show", "audit-cast.service",
             "-p", "Result", "--value"],
            capture_output=True, text=True, timeout=TIMEOUT_S)
    except Exception as e:
        return False, f"systemctl show audit-cast failed: {e}"
    result = (p.stdout or "").strip()
    if p.returncode == 0 and result == "success":
        return True, "last run Result=success"
    return False, f"audit-cast.service Result={result or p.stderr.strip()}"


def checks() -> list[dict]:
    return [
        {
            "slug": "relay",
            "title": "input-bridge relay not healthy",
            "probe": lambda: probe_http(f"{EDGE}/health", expect_200=True),
            "help": ("Relay is a podman quadlet on idc03 "
                     "(100.102.134.91:3010, tailnet-bound). Check: ssh "
                     "idc03 systemctl --user status input-bridge; logs: "
                     "journalctl --user -u input-bridge -n 50; edge route "
                     "is /api/input-bridge/* in stacks/web/Caddyfile"),
        },
        {
            "slug": "displays",
            "title": "vcast display fleet unhealthy (dead/drifted screens)",
            "probe": probe_displays,
            "help": ("Expects headless-* (vcast-headless@N on idc03) and "
                     "vcast-real-* (vcast-real@N on idc02) connected, and "
                     "screen-N names on slot N. Dead headless usually = a "
                     "409-stuck claim (fixed 2026-10-07 by force-reclaim "
                     "+ persisted keys); drift = pre-fix registry, repair "
                     "with POST /release + re-claim or let registerDisplay "
                     "re-home it."),
        },
        {
            "slug": "flap",
            "title": "vcast flap events in last 24h",
            "probe": probe_flap,
            "help": ("Counts 'superseded by new socket' / 'disconnected' "
                     "lines in the idc03 input-bridge journal (metric: "
                     "0/24h). A supersede = a display re-registered over a "
                     "live socket — investigate which device flapped and "
                     "why it reconnected."),
        },
        {
            "slug": "flap-check",
            "title": "vcast-flap-check regression fails on deployed relay",
            "probe": probe_flap_check,
            "help": ("Runs stacks/web/input-bridge/vcast-flap-check.mjs "
                     "inside the relay's podman image on idc03 — exercises "
                     "the stale-socket race against the DEPLOYED "
                     "server.mjs. A FAIL means the deployed bundle "
                     "regressed vs repo: diff ~/apps/input-bridge/"
                     "server.mjs on idc03 against the repo copy."),
        },
        {
            "slug": "lease",
            "title": "stale vcast capture lease / camwall binding",
            "probe": probe_lease,
            "help": ("Active /capture lease >6h or enabled camwall zone "
                     "bound to an offline screen. This is the "
                     "cast_recast_stale_lease regression surface — clear "
                     "with POST /api/input-bridge/capture "
                     "{screen:N,active:false} or /camwall "
                     "{zone:Z,enabled:false}."),
        },
        {
            "slug": "audit-cast",
            "title": "audit-cast runaway guard failing",
            "probe": probe_audit_cast,
            "help": ("audit-cast.timer (tony-dell) runs the cast-pipeline "
                     "runaway audit. Check: systemctl --user status "
                     "audit-cast.service; journalctl --user -u audit-cast "
                     "-n 50"),
        },
        {
            "slug": "cast-browser-proxy",
            "title": "cast-browser-proxy :8799 not answering",
            "probe": lambda: probe_http(
                "http://127.0.0.1:8799/__vcast_health_probe__",
                expect_200=False),
            "help": ("cast-browser-proxy.service proxies :8799 -> "
                     "tony-omen cast-browser. Any HTTP <500 is alive. "
                     "Check: systemctl --user status cast-browser-proxy"),
        },
        {
            "slug": "yt-live-api",
            "title": "yt-live-api :8791/status not 200",
            "probe": lambda: probe_http(
                "http://127.0.0.1:8791/status", expect_200=True),
            "help": ("yt-live REST shim for voice/agent casting. Check: "
                     "systemctl --user status yt-live-api; logs: "
                     "journalctl --user -u yt-live-api -n 50"),
        },
    ]


def card_path(slug: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)
    return CARDS / f"vcast-auto-{safe}.yml"


def load_card(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def upsert_card(path: Path, card_id: str, title: str, note: str,
                help_text: str, now: float, today: str) -> str:
    card = load_card(path)
    opened = card.get("updated") if card.get("column") == "review" \
        else today
    try:
        age_h = (now - time.mktime(
            time.strptime(str(opened), "%Y-%m-%d"))) / 3600
    except (ValueError, TypeError):
        age_h = 0
    card.update({
        "id": card_id,
        "title": title,
        "brief": (f"An automated health check flagged: {title}. "
                  "Read the note, fix it, then close the card."),
        "column": "review",
        "generated": "vcast-auto-health",
        "program": "vcast",
        "area": "monitoring",
        "priority": "high" if age_h >= ESCALATE_H else "medium",
        "note": note,
        "help": help_text,
        "updated": opened,
    })
    if path.exists() and card == load_card(path):
        return "unchanged"
    path.write_text(yaml.safe_dump(card, sort_keys=False,
                                   allow_unicode=True))
    return "updated" if path.exists() else "created"


def close_card(path: Path, slug: str, today: str) -> bool:
    card = load_card(path)
    if card.get("column") != "review" or \
            card.get("generated") != "vcast-auto-health":
        return False
    card["column"] = "done"
    card["note"] = (f"Auto-recovered {today}: `{slug}` check passing "
                    "again.")
    card["updated"] = today
    path.write_text(yaml.safe_dump(card, sort_keys=False,
                                   allow_unicode=True))
    return True


def main() -> int:
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    n_fail = n_open = n_close = 0
    known_slugs = set()
    for c in checks():
        slug = c["slug"]
        known_slugs.add(slug)
        ok, detail = c["probe"]()
        path = card_path(slug)
        if not ok:
            n_fail += 1
            rc = upsert_card(path, f"vcast-auto-{slug}", c["title"],
                             detail, c["help"], now, today)
            if rc != "unchanged":
                n_open += 1
            print(f"FAIL {slug}: {detail}", file=sys.stderr)
        else:
            if path.exists() and close_card(path, slug, today):
                n_close += 1
    # a retired check's card never gets touched by the loop above —
    # close it so renamed checks don't leave ghosts in review.
    for path in CARDS.glob("vcast-auto-*.yml"):
        slug = path.stem.removeprefix("vcast-auto-")
        if slug not in known_slugs and close_card(path, slug, today):
            n_close += 1
    print(f"vcast-auto-health: {n_fail} failing ({n_open} cards written), "
          f"{n_close} auto-recovered, {len(known_slugs)} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
