#!/usr/bin/env python3
"""gev-auto-health — God's Eye View service probes -> kanban cards.

Probes the GEV stack on tony-dell and writes/updates `gev-auto-*` kanban
cards so a dead lane becomes tracked work instead of a silently broken
voice view. Mirrors cms-auto-health.py / logs-kanban.py's lifecycle:

  check fails    -> column=review, note = probe result (updates = incident log)
  check recovers -> column=done, note records the recovery time
  open >= 12h    -> priority bumped to high

Checks (all probe from tony-dell, where kanban-sync.timer runs):
  page        GET http://127.0.0.1/apps/gev/ via Caddy (:80) must be 200
  ws          ws handshake ws://127.0.0.1/apps/gev-live/ws?remote=1 must
              return 101 with a valid Sec-WebSocket-Accept. remote=1 is
              deliberate: bridge.py registers it as a passive remote and
              never opens a Gemini Live session, so the probe is free.
  api         GET http://127.0.0.1:4173/<bogus> — gods-eye-view-api has no
              health endpoint and its real routes proxy slow external
              calls; unknown paths 404 fast, so ANY HTTP response < 500
              proves the node server is alive and answering.
  bridge      systemctl --user is-active gev-gemini (quadlet, :8789 ws)
  api-service systemctl --user is-active gods-eye-view-api (:4173)

is-active alone is not enough — 2026-10-05 the bridge process sat in D
state for minutes with the unit "active" and nothing bound to 8789. The
ws/api probes catch that; the unit checks give the actionable pointer.

Runs anywhere on tony-dell with cards-dir access; writes into a chaba
checkout. Committing is the caller's job — runs inside kanban-sync.sh
whose `git add cards/` block commits and pushes whatever this writes.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import yaml

REPO = Path(os.environ.get(
    "CHABA_REPO",
    str(Path(__file__).resolve().parents[2])))
CARDS = REPO / "docs" / "ssot" / "kanban" / "cards"

PAGE_URL = os.environ.get("GEV_PAGE_URL", "http://127.0.0.1/apps/gev/")
WS_URL = os.environ.get("GEV_WS_URL",
                        "ws://127.0.0.1/apps/gev-live/ws?remote=1")
API_URL = os.environ.get("GEV_API_URL",
                         "http://127.0.0.1:4173/__gev_health_probe__")

TIMEOUT_S = 10
# a card open this long gets priority bumped to high — same escalation
# policy as cms-auto-health/logs-kanban.
ESCALATE_H = 12
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def probe_http(path_url: str, expect_200: bool) -> tuple[bool, str]:
    """-> (ok, detail). expect_200: require exactly 200; otherwise any
    HTTP response < 500 means the server is alive and answering."""
    try:
        req = urllib.request.Request(
            path_url, headers={"User-Agent": "gev-auto-health"})
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


def probe_ws(ws_url: str) -> tuple[bool, str]:
    """Raw-socket ws upgrade — no third-party deps, so it runs under the
    timer's plain python3. Validates status 101 + Sec-WebSocket-Accept."""
    u = urlsplit(ws_url)
    if u.scheme not in ("ws", "wss"):
        return False, f"unsupported scheme {u.scheme!r}"
    port = u.port or (443 if u.scheme == "wss" else 80)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{port}\r\n"
           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\n"
           "Sec-WebSocket-Version: 13\r\n\r\n")
    try:
        raw = socket.create_connection((u.hostname, port),
                                       timeout=TIMEOUT_S)
        with raw:
            if u.scheme == "wss":
                raw = ssl.create_default_context().wrap_socket(
                    raw, server_hostname=u.hostname)
            with raw:
                raw.sendall(req.encode())
                resp = raw.recv(4096)
    except Exception as e:
        return False, f"ws connect {ws_url} failed: {e}"
    status = resp.split(b"\r\n", 1)[0].decode(errors="replace")
    if " 101" not in status:
        return False, f"ws upgrade {ws_url} -> {status} (want 101)"
    expect = base64.b64encode(
        hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
    if expect.encode() not in resp:
        return False, "ws upgrade 101 but bad Sec-WebSocket-Accept"
    return True, "101 upgrade ok"


def probe_unit(unit: str) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True, text=True, timeout=TIMEOUT_S)
    except Exception as e:
        return False, f"systemctl --user is-active {unit} failed: {e}"
    state = p.stdout.strip() or p.stderr.strip() or f"rc={p.returncode}"
    if p.returncode == 0 and state == "active":
        return True, "active"
    return False, f"systemctl --user is-active {unit} -> {state}"


def checks() -> list[dict]:
    return [
        {
            "slug": "page",
            "title": "GEV page /apps/gev/ not 200",
            "probe": lambda: probe_http(PAGE_URL, expect_200=True),
            "help": ("Static bundle is Caddy (`web` container, :80) serving "
                     "stacks/web/public/apps/gev/. If Caddy answers but 404s, "
                     "the staged bundle is missing — rebuild + repatch + "
                     "re-stage per AGENTS.md 'GEV Gemini Live voice "
                     "deployment'. Check: podman ps | grep web; "
                     "curl -s -o /dev/null -w '%{http_code}' "
                     "http://127.0.0.1/apps/gev/"),
        },
        {
            "slug": "ws",
            "title": "GEV ws /apps/gev-live/ws upgrade fails",
            "probe": lambda: probe_ws(WS_URL),
            "help": ("Caddy proxies /apps/gev-live/ws -> 127.0.0.1:8789 "
                     "(gev-gemini bridge). Page ok + ws fail usually means "
                     "the bridge is down or stuck (unit can read 'active' "
                     "while the process hangs — check the port): "
                     "systemctl --user status gev-gemini; "
                     "ss -tln | grep 8789; "
                     "systemctl --user restart gev-gemini"),
        },
        {
            "slug": "api",
            "title": "GEV api 127.0.0.1:4173 not answering",
            "probe": lambda: probe_http(API_URL, expect_200=False),
            "help": ("gods-eye-view-api (/home/tony/gods-eye-view/server.mjs) "
                     "listens on 4173; Caddy routes /apps/gev/api/* to it. "
                     "The probe GETs a bogus path — 404 counts as alive. "
                     "systemctl --user status gods-eye-view-api; "
                     "restart: systemctl --user restart gods-eye-view-api"),
        },
        {
            "slug": "bridge",
            "title": "gev-gemini service not active",
            "probe": lambda: probe_unit("gev-gemini"),
            "help": ("Quadlet ~/.config/containers/systemd/gev-gemini."
                     "container runs the Gemini Live bridge (image "
                     "localhost/gev-gemini, Network=host, :8789 ws + :8790 "
                     "cmd). Fix: systemctl --user start gev-gemini. If the "
                     "image is stale: podman build -t localhost/gev-gemini:"
                     "latest ~/CascadeProjects/chaba-tony-dell/stacks/"
                     "tony-dell/gev-gemini && systemctl --user restart "
                     "gev-gemini"),
        },
        {
            "slug": "api-service",
            "title": "gods-eye-view-api service not active",
            "probe": lambda: probe_unit("gods-eye-view-api"),
            "help": ("User unit ~/.config/systemd/user/gods-eye-view-api."
                     "service runs server.mjs on 4173. Fix: systemctl "
                     "--user enable --now gods-eye-view-api; logs: "
                     "journalctl --user -u gods-eye-view-api -n 50"),
        },
    ]


def card_path(slug: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)
    return CARDS / f"gev-auto-{safe}.yml"


def load_card(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def upsert_card(path: Path, card_id: str, title: str, note: str,
                help_text: str, now: float, today: str) -> str:
    """Write a review card. -> 'created'|'updated'|'unchanged'."""
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
        "generated": "gev-auto-health",
        "program": "gev",
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
            card.get("generated") != "gev-auto-health":
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
            rc = upsert_card(path, f"gev-auto-{slug}", c["title"],
                             detail, c["help"], now, today)
            if rc != "unchanged":
                n_open += 1
            print(f"FAIL {slug}: {detail}", file=sys.stderr)
        else:
            if path.exists() and close_card(path, slug, today):
                n_close += 1
    # a retired check's card never gets touched by the loop above —
    # close it so renamed checks don't leave ghosts in review.
    for path in CARDS.glob("gev-auto-*.yml"):
        slug = path.stem.removeprefix("gev-auto-")
        if slug not in known_slugs and close_card(path, slug, today):
            n_close += 1
    print(f"gev-auto-health: {n_fail} failing ({n_open} cards written), "
          f"{n_close} auto-recovered, {len(known_slugs)} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
