#!/usr/bin/env python3
"""tailscale-serve watchdog — verify the local host's serve config still
carries the mounts declared in ssot.routes.yml.

Wound (OPS-0754, 2026-10-20): `tailscale serve` on tony-dell was reset to
"No serve config" — every tailnet HTTPS route through dell died silently.
check-routes.py probes http://localhost only, so the serve layer itself
was a blind spot. This script closes it: it compares `tailscale serve
status` against the `<host>-serve` edge in the route registry and probes
the tailnet URL end-to-end.

Run as a timer on each host that owns a `<host>-serve` edge.
--alert writes one deduped focus-inbox file per host on failure.
Exit 1 when any check fails (CI/service-failure semantics).
"""
import argparse
import datetime as dt
import json
import socket
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent / "board"))
import card_io

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import inbox_door  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
ROUTES = REPO / "docs/ssot/infrastructure/ssot.routes.yml"
INBOX = REPO / "docs/ssot/focus-inbox"
# exec/readonly checkouts can't commit — --alert posts to board-api /inbox
# instead of writing local files (card
# omen-chaba-checkout-focus-inbox-writers-d993c4).
WRITES_OK = inbox_door.local_writes_ok(REPO)
ALERT_STATE = (Path.home() / ".local" / "state" / "chaba"
               / "serve-config-alerts.json")
TIMEOUT = 6


def hostname() -> str:
    return socket.gethostname().split(".")[0]


def serve_status() -> tuple[dict | None, str | None]:
    """Return (parsed json, error). `tailscale serve status --json` exits 1
    with a plain-text 'no serve config' when empty — treat that as {}."""
    try:
        r = subprocess.run(
            ["tailscale", "serve", "status", "--json"],
            capture_output=True, text=True, timeout=15)
    except Exception as e:
        return None, f"serve status failed: {e}"
    if r.returncode != 0:
        out = (r.stdout + r.stderr).strip()
        if "no serve config" in out.lower() or not out:
            return {}, None
        return None, f"serve status rc={r.returncode}: {out[:200]}"
    try:
        return json.loads(r.stdout or "{}"), None
    except json.JSONDecodeError:
        return {}, None


def declared_mounts(host: str) -> dict:
    """{mount_path_or_port_key: upstream} for the `<host>-serve` edge."""
    doc = yaml.safe_load(ROUTES.read_text()) or {}
    edge = (doc.get("edges") or {}).get(f"{host}-serve") or {}
    return edge.get("mounts") or {}


def actual_targets(status: dict) -> set[str]:
    """Flatten serve json into {'/': 'http://127.0.0.1:80', 'tcp:8447': ...}
    shape — works across tailscaled versions by scanning the JSON for
    proxy targets."""
    out = set()
    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o.startswith(("http://", "https://",
                                                  "tcp://", "tailscale-only")):
            out.add(o)
    walk(status)
    return out


def probe(url: str) -> tuple[int | None, str]:
    try:
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "serve-watchdog/1"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, "ok"
    except urllib.error.HTTPError as e:
        return e.code, "ok"          # reached a live server
    except Exception as e:
        return None, type(e).__name__


def _alert_state_load():
    try:
        return json.loads(ALERT_STATE.read_text())
    except Exception:
        return {}


def _alert_state_save(state):
    try:
        ALERT_STATE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_STATE.write_text(json.dumps(state))
    except OSError:
        pass


def write_alert(host: str, findings: list[str]) -> str:
    today = dt.date.today().isoformat()
    if not WRITES_OK:
        # /inbox has no dedup — post only when the finding set changes.
        import hashlib
        sig = hashlib.sha1("\n".join(sorted(findings)).encode()).hexdigest()[:12]
        state = _alert_state_load()
        if state.get(host) == sig:
            return f"board-api:/inbox serve-config-{host} (unchanged, deduped)"
        text = ("Serve config drifted from ssot.routes.yml "
                "`<host>-serve` mounts (OPS-0754 wound — a wiped "
                "serve config kills every tailnet HTTPS route "
                "silently). Restore per serve-restore procedure, "
                "or update the registry if the route retired.\n"
                + "\n".join(f"- {f}" for f in findings[:25]))
        if inbox_door.post_inbox({
                "label": f"Restore tailscale-serve config on {host}",
                "subtitle": f"check-serve-config.py {today}",
                "icon": "alert",
                "text": text,
                "priority": "high",
                "tags": ["ops", "tailscale-serve", "ops-0754"],
                "owner": "tony",
                "session": "check-serve-config",
        }):
            state[host] = sig
            _alert_state_save(state)
            return f"board-api:/inbox serve-config-{host}"
        return "board-api unreachable — alert dropped"
    INBOX.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"  - {f}" for f in findings[:25])
    doc = {
        "title": f"tailscale-serve drift on {host} ({len(findings)})",
        "subtitle": f"check-serve-config.py {today}",
        "icon": "alert",
        "focus": {
            "label": f"Restore tailscale-serve config on {host}",
            "text": "Serve config drifted from ssot.routes.yml "
                    "`<host>-serve` mounts (OPS-0754 wound — a wiped "
                    "serve config kills every tailnet HTTPS route "
                    "silently). Restore per serve-restore procedure, "
                    "or update the registry if the route retired.\n" + body,
            "branch": "chaba",
            "priority": "high",
            "status": "draft",
            "tags": ["ops", "tailscale-serve", "ops-0754"],
        },
        "ownership": {"owner": "tony", "locked": False, "lock_reason": ""},
        "source": {"date": today},
    }
    p = INBOX / f"serve-config-{host}.yml"
    card_io.atomic_write_text(p, yaml.safe_dump(doc, sort_keys=False,
                                               width=120))
    # clear a stale alert once healthy again is the caller's job via unlink
    return p.name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true",
                    help="write deduped focus-inbox alert on failure")
    ap.add_argument("--host", default=hostname(),
                    help="host edge to check (default: local hostname)")
    ap.add_argument("--probe", action="store_true",
                    help="also GET the tailnet root URL end-to-end")
    args = ap.parse_args()

    host = args.host
    declared = declared_mounts(host)
    if not declared:
        print(f"{host}: no <host>-serve edge declared in ssot.routes.yml "
              f"— nothing to check")
        return 0

    status, err = serve_status()
    if err:
        print(f"FAIL {host}: {err}")
        if args.alert:
            print(f"alert -> {write_alert(host, [err])}")
        return 1

    actual = actual_targets(status or {})
    findings = []
    if not (status or {}):
        findings.append(f"serve config EMPTY — {len(declared)} mount(s) "
                        f"declared, all routes dead")
    else:
        for mount, upstream in declared.items():
            if upstream not in actual:
                findings.append(f"missing mount {mount} -> {upstream}")

    if args.probe:
        url = f"https://{host}.taila0626a.ts.net/"
        st, perr = probe(url)
        if st is None:
            findings.append(f"tailnet probe {url} failed: {perr}")
        elif st >= 500:
            findings.append(f"tailnet probe {url} -> HTTP {st}")

    if findings:
        print(f"FAIL {host}:")
        for f in findings:
            print(f"  - {f}")
        if args.alert:
            print(f"alert -> {write_alert(host, findings)}")
        return 1

    alert_file = INBOX / f"serve-config-{host}.yml"
    if WRITES_OK and alert_file.exists():
        alert_file.unlink()          # self-heal: clear stale alert
        print(f"cleared stale alert {alert_file.name}")
    print(f"OK {host}: {len(declared)} declared mount(s) present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
