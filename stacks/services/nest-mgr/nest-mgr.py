#!/usr/bin/env python3
"""nest-mgr.py — per-host Nest manager (observer-governor + gated actuation, v2).

A nest node on this host is any of:

  - a systemd user unit matching the nest patterns
    (jev|student|bankq|nest|serve-*.py|openjev — name, description, or
    ExecStart)
  - a `serves:` endpoint in ada-voice tests/bench/topologies.yml
    `models:`/`lanes:` that resolves to this host
  - a live /metrics endpoint on a known nest port

Ownership: a unit/env declaring NEST_OWNER (or a kanban card claim via a
`nest_nodes:` field) owns the node; everything else is OWNERLESS and the
manager adopts it into ~/.local/share/nest/manager-state.json. Adoption is
observational — the manager reports and health-checks, never restarts or
enforces (leash principle, ssot.nest-training.yml promotion_gate).

v2 actuation plane (card nest-mgr-v2-actuation) — modes, resolved each
tick from env/file flags; safety flags can only LOWER the effective mode:

    monitor    v1 behavior: detect + report only (default)
    recommend  compute allowlisted actions, log them to the state file
               actions[] ring + the CMS page, execute nothing
    guarded    additionally execute allowlisted restarts — requires the
               per-host opt-in flag file actuation.on

Flags under $NEST_STATE_DIR (default ~/.local/share/nest/):
    mode                 monitor|recommend|guarded (below env priority)
    actuation.off        kill switch — present => monitor, checked every tick
    actuation.on         per-host opt-in — required for guarded to execute
    host-circuit.open    host circuit breaker tripped (>5 execs/hour);
                         rm to reset
    manual-units         units an operator holds — never restarted, 1/line
    restart-allowlist    restart-eligible units, 1/line
    circuit/<unit>.open  per-unit circuit (2 failed restarts/hour);
                         rm to reset

Guarded auto-restart never touches: card-owned nodes (nest_nodes:),
NEST_OWNER=none/unmanaged units, nest-mgr itself, manual-units, or
topology prod lanes (NEST_MGR_PROD_OK=1 overrides). A restart fires only
when state==failed for FAIL_TICKS consecutive ticks, the unit is
allowlisted (NEST_RESTART_OK=1 on the unit or in restart-allowlist),
no owner lock exists, cooldown/rate limits pass, and the host budget is
green — via `systemctl --user restart` only. Every recommendation and
action appends {ts, host, unit, prior_state, action, reason, outcome} to
manager-state.json actions[] (last 200) and renders on the CMS page.

Report: publishes ada-cms-pages/nest-<host> through the MDDB writer path
report-distill uses. The page auto-surfaces on /chaba-nest because the
dashboard's `match: nest|polity|tony-ideas` already covers nest-<host>
slugs (chaba-nest-build.py --discover proposes the tile).

Refresh: the daemon ticks every TICK_S, writes manager-state.json on any
change, and republishes the CMS page every PUBLISH_S, on a state change,
or when the page's ada-cms-automation doc sets run_now (the regenerate
button queues run_now — this daemon is the worker that clears it).

Usage:
    nest-mgr.py --once        discover + adopt + probe + write state + publish
    nest-mgr.py --loop        daemon mode (service entry point)
    nest-mgr.py --discover    print discovered nodes, no writes
    nest-mgr.py --report      print the rendered page body, no publish
    nest-mgr.py --actions     print the actions[] audit tail
    nest-mgr.py --once --dry-run   full cycle, state file only, no CMS write,
                            never executes (guarded degrades to recommend)

Env:
    MDDB_BASE_URL     default http://100.102.134.91:11027/v1
    NEST_TOPOLOGIES   topologies.yml path
                      (default ~/CascadeProjects/ada-voice/tests/bench/topologies.yml)
    NEST_CARDS_DIR    kanban cards dir scanned for `nest_nodes:` claims
                      (default ~/CascadeProjects/chaba/docs/ssot/kanban/cards)
    NEST_HOST         host label override (default: short hostname)
    NEST_STATE_DIR    state/flag dir (default ~/.local/share/nest)
    NEST_MGR_MODE     monitor|recommend|guarded — overrides the mode file
    NEST_MGR_PROD_OK  set 1 to let guarded restart prod-lane nodes
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ICT = timezone(timedelta(hours=7))
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11027/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"

STATE_DIR = Path(os.environ.get(
    "NEST_STATE_DIR", str(Path.home() / ".local" / "share" / "nest")))
STATE_FILE = STATE_DIR / "manager-state.json"
DEFAULT_TOPO = (Path.home() / "CascadeProjects" / "ada-voice" / "tests" /
                "bench" / "topologies.yml")
DEFAULT_CARDS = (Path.home() / "CascadeProjects" / "chaba" / "docs" /
                 "ssot" / "kanban" / "cards")

TICK_S = 60            # discovery/probe cadence
PUBLISH_S = 900        # CMS page cadence (15 min) — plus on state change
PROBE_TIMEOUT = 3

# Discovery pattern — unit name OR description OR ExecStart. The manager's
# own unit and dispatch noise are excluded below.
NEST_RX = re.compile(r"jev|student|bankq|nest|serve-[\w./-]*\.py|openjev",
                     re.I)
EXCLUDE_RX = re.compile(
    r"^nest-mgr\.|^devin-task-|^libpod-|^podman-\d|@.*\.service$|"
    r"^run-|generated.*nest-mgr", re.I)
# Fixed probe set — NOT a port scan: only the ports the nest fleet has
# ever used, plus whatever discovered endpoints already declare.
KNOWN_PORTS = {8777, 8778, 8779, 8878, 8791}

# ---- v2 actuation plane (card nest-mgr-v2-actuation) -------------------
# Flag files under STATE_DIR — the operator's control surface. Presence
# of a flag can only lower the effective mode, never raise it.
MODE_FILE = STATE_DIR / "mode"                  # monitor|recommend|guarded
KILL_FILE = STATE_DIR / "actuation.off"         # global kill switch
OPTIN_FILE = STATE_DIR / "actuation.on"         # per-host guarded opt-in
HOST_CIRCUIT = STATE_DIR / "host-circuit.open"  # per-host breaker flag
MANUAL_FILE = STATE_DIR / "manual-units"        # operator-held units
ALLOW_FILE = STATE_DIR / "restart-allowlist"    # restart-eligible units
CIRCUIT_DIR = STATE_DIR / "circuit"             # per-unit <unit>.open flags

MODE_RANK = {"monitor": 0, "recommend": 1, "guarded": 2}

FAIL_TICKS = 3            # consecutive failed ticks before acting
RESTART_COOLDOWN_S = 300  # min seconds between restart attempts on a unit
RESTART_MAX_HOUR = 2      # max restart attempts per unit per hour
UNIT_FAILS_CIRCUIT = 2    # failed restarts/hour -> unit circuit-open
HOST_MAX_ACTIONS_HOUR = 5  # executed actions/hour -> host circuit-open
REC_RESEND_S = 900        # re-emit a standing recommendation at most /15m
HELD_RESEND_S = 3600      # re-emit a held verdict at most hourly
ACTIONS_CAP = 200         # actions[] audit ring buffer bound
UNIT_PRUNE_MISSES = 30    # ticks absent from discovery before a unit's
                          # actuation state is dropped (~30min at TICK_S=60;
                          # comfortably covers transient `systemctl show`
                          # gaps and the 5min restart cooldown)

KIND_RULES = [
    ("student", re.compile(r"student", re.I)),
    ("brain", re.compile(r"brain", re.I)),
    # non-serving nest infra (leash, bench runners) — extends the spec's
    # student/scorer/lane/brain set. Checked before scorer so a leash
    # unit whose description says "scorers" still files as ops.
    ("ops", re.compile(r"leash|bench|watch|audit", re.I)),
    ("scorer", re.compile(r"scor|router|bankq|advisory|decision", re.I)),
    ("lane", re.compile(r"lane|serve", re.I)),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sh(cmd: list[str], timeout: int = 15) -> tuple[str, int]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        return p.stdout, p.returncode
    except Exception:
        return "", 1


def _get_json(url: str, timeout: int = PROBE_TIMEOUT):
    t0 = time.monotonic()
    data = json.load(urllib.request.urlopen(url, timeout=timeout))
    return data, int((time.monotonic() - t0) * 1000)


def _post(path: str, payload: dict, timeout: int = 60):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ------------------------------------------------------------- host ident

def tailscale_ip() -> str | None:
    out, rc = _sh(["tailscale", "ip", "-4"], timeout=5)
    ip = out.strip().splitlines()[0] if rc == 0 and out.strip() else ""
    return ip or None


class HostId:
    """Resolve an endpoint host part to 'is this me?'."""

    def __init__(self):
        self.hostname = socket.gethostname().split(".")[0]
        self.ts_ip = tailscale_ip()

    def is_self(self, host: str | None) -> bool:
        if not host:
            return False
        h = host.strip().lower()
        if h in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
            return True
        if h.split(".")[0] == self.hostname:
            return True
        if self.ts_ip and h == self.ts_ip:
            return True
        return False

    def label(self) -> str:
        return self.hostname


# ------------------------------------------------------------- discovery

def discover_units() -> dict[str, dict]:
    """systemd user units matching the nest pattern. Keyed by unit name.

    Candidate pass matches unit NAME + description (free — list-units
    already prints it) plus unit-file contents on disk (ExecStart
    matches like serve-*.py with a generic unit name). Only candidates
    get a `systemctl show` — one dbus call each, not per-unit."""
    out, _ = _sh(["systemctl", "--user", "list-units", "--all",
                  "--no-legend", "--no-pager"], timeout=20)
    out2, _ = _sh(["systemctl", "--user", "list-unit-files",
                   "--no-legend", "--no-pager"], timeout=20)
    names = set()
    for line in (out + "\n" + out2).splitlines():
        m = re.match(r"\s*[●\s]*\s*([\w@.-]+\.service)\b(.*)", line)
        if m and NEST_RX.search(line) and not EXCLUDE_RX.search(m.group(1)):
            names.add(m.group(1))
    # unit-file scan — catches ExecStart=serve-*.py / openjev under a
    # generic unit name (name+desc above only sees the description)
    for d in (Path.home() / ".config" / "systemd" / "user",
              Path(f"/run/user/{os.getuid()}/systemd/generator"),
              Path(f"/run/user/{os.getuid()}/systemd/transient")):
        if not d.is_dir():
            continue
        for f in list(d.glob("*.service")) + list(d.glob("*.d/*.conf")):
            try:
                if NEST_RX.search(f.read_text()):
                    base = (f.parent.name[:-2] if f.suffix == ".conf"
                            else f.name)
                    if not EXCLUDE_RX.search(base):
                        names.add(base)
            except OSError:
                continue
    units = {}
    for name in sorted(names):
        show, rc = _sh(
            ["systemctl", "--user", "show", name, "-p", "ActiveState",
             "-p", "SubState", "-p", "Description", "-p", "ExecStart",
             "-p", "Environment", "-p", "FragmentPath",
             "-p", "Restart"], timeout=10)
        if rc != 0 or "ActiveState=" not in show:
            continue
        props = dict(l.split("=", 1) for l in show.splitlines() if "=" in l)
        units[name] = props
    # live units claim shared endpoints first — a stale sibling unit file
    # (e.g. a parked jev-bench.service on the same port) must not steal
    # the name/state of the running unit it would collide with.
    order = {"active": 0, "activating": 0, "failed": 1}
    return dict(sorted(
        units.items(),
        key=lambda kv: (order.get(kv[1].get("ActiveState"), 2), kv[0])))


def _parse_endpoint(execstart: str) -> tuple[str | None, int | None]:
    """(bind_host, port) from a unit's ExecStart argv blob."""
    if not execstart or execstart.startswith("ExecStart=(null"):
        return None, None
    host = port = None
    m = re.search(r"--publish\s+([\d.]+):(\d+):(\d+)", execstart)
    if m:  # podman --publish hostIP:hostPort:ctrPort
        return m.group(1), int(m.group(2))
    m = re.search(r"--host[=\s]+([\w.:.-]+)", execstart)
    if m:
        host = m.group(1)
    m = re.search(r"--port[=\s]+(\d+)", execstart)
    if m:
        port = int(m.group(1))
    if port is None:
        m = re.search(r":(\d{4,5})(?:\s|/|$)", execstart)
        if m:
            port = int(m.group(1))
    return host, port


def _env_value(env_blob: str, frag: str | None, name: str) -> str | None:
    """<name>=… from `systemctl show -p Environment` or the unit
    file/drop-ins."""
    rx = re.compile(re.escape(name) + r"=([^\s\"']+)")
    m = rx.search(env_blob or "")
    if m:
        return m.group(1)
    paths = []
    if frag:
        paths.append(Path(frag))
        drop = Path(frag + ".d")
        if drop.is_dir():
            paths += sorted(drop.glob("*.conf"))
    for p in paths:
        try:
            m = rx.search(p.read_text())
            if m:
                return m.group(1)
        except OSError:
            continue
    return None


def _env_owner(env_blob: str, frag: str | None) -> str | None:
    """NEST_OWNER=… — 'none' is the explicit opt-out value."""
    return _env_value(env_blob, frag, "NEST_OWNER")


def _env_flag(env_blob: str, frag: str | None, name: str) -> bool:
    return (_env_value(env_blob, frag, name) or ""
            ).strip().lower() in ("1", "true", "yes", "on")


def card_claims(cards_dir: Path) -> dict[str, str]:
    """node name -> card id for every card declaring nest_nodes:/nest_node:.
    The board's claim convention: a card owns the nodes it lists."""
    out = {}
    if not cards_dir.is_dir():
        return out
    try:
        import yaml
    except ImportError:
        return out
    for f in sorted(cards_dir.glob("*.yml")):
        try:
            d = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        cid = d.get("id") or f.stem
        claimed = d.get("nest_nodes") or d.get("nest_node") or []
        if isinstance(claimed, str):
            claimed = [claimed]
        for n in claimed:
            out[str(n)] = cid
    return out


def _norm_name(unit: str) -> str:
    n = re.sub(r"\.service$", "", unit)
    return re.sub(r"^ada-(pi-)?", "", n)


def _kind(name: str, desc: str, node: dict) -> str:
    if node.get("lane"):
        return "lane"
    blob = f"{name} {desc}"
    for kind, rx in KIND_RULES:
        if rx.search(blob):
            return kind
    # a node with no endpoint serves nothing — it's nest ops infra
    return "scorer" if node.get("endpoint") else "ops"


def merge_node(nodes: dict, key: str, **fields) -> dict:
    n = nodes.setdefault(key, {"name": key, "sources": []})
    for k, v in fields.items():
        if k == "sources":
            for s in v:
                if s not in n["sources"]:
                    n["sources"].append(s)
        elif k == "name":
            cur = n.get("name")
            if v and cur in (None, "", key):
                n["name"] = v
            elif v and v != cur:
                n.setdefault("aliases", [])
                if v not in n["aliases"]:
                    n["aliases"].append(v)
        elif k in ("unit", "endpoint"):
            # first writer wins — callers order live units first
            if v is not None and n.get(k) in (None, "", []):
                n[k] = v
        elif v is not None and (k not in n or n.get(k) in (None, "", [])):
            n[k] = v
    return n


def topo_nodes(topo_path: Path, hid: HostId) -> dict[str, dict]:
    """nodes keyed by merge key (port str or name) from topologies.yml."""
    out = {}
    try:
        import yaml
        doc = yaml.safe_load(topo_path.read_text()) or {}
    except Exception as e:
        print(f"warn: topologies unreadable ({e})", file=sys.stderr)
        return out
    for key in ("student_endpoint", "heavy_endpoint"):
        ep = doc.get(key)
        if isinstance(ep, str):
            m = re.match(r"https?://([^:/\s]+):(\d+)", ep)
            if m and hid.is_self(m.group(1)):
                merge_node(out, m.group(2), sources=["topology"],
                           endpoint=(m.group(1), int(m.group(2))),
                           topo_name=key)
    for name, mdl in (doc.get("models") or {}).items():
        serves = mdl.get("serves")
        eps = serves if isinstance(serves, list) else [serves]
        for ep in eps:
            if not isinstance(ep, str):
                continue
            m = re.match(r"https?://([^:/\s]+)(?::(\d+))?", ep)
            if not m or not hid.is_self(m.group(1)):
                continue
            port = int(m.group(2) or 80)
            task, spec = mdl.get("task"), mdl.get("specialist")
            goal = str(task or "")
            if spec:
                goal += f" ({spec})"
            bench = mdl.get("bench") or {}
            last_bench = None
            if isinstance(bench, dict):
                last_bench = ", ".join(
                    f"{k} {v}" for k, v in list(bench.items())[:3]
                    if k != "at" and v)
            merge_node(
                out, str(port), sources=["topology"],
                endpoint=(m.group(1), port), topo_name=name,
                topo_status=mdl.get("status"), topo_task=task,
                goal=goal or None, last_bench=last_bench, name=str(name))
    for name, lane in (doc.get("lanes") or {}).items():
        host = str(lane.get("host") or "")
        if host.split(".")[0] != hid.hostname:
            continue
        port = lane.get("serve_port")
        ep = (hid.ts_ip or hid.hostname, int(port)) if port else None
        goal = str(lane.get("good_for") or "").split(".")[0][:80] or None
        key = str(port) if port else name
        merge_node(out, key, sources=["topology"], lane=name,
                   endpoint=ep, topo_status=lane.get("status"),
                   runtime=lane.get("runtime"), goal=goal, name=name)
    return out


def probe_metrics(hosts: list[str], ports: set[int],
                  known: set[int]) -> dict[int, dict]:
    """GET /metrics on known nest ports. Returns port -> {metrics, ms,
    bound} for live ones not already claimed (known = claimed ports)."""
    out = {}
    for port in sorted(ports - known):
        for h in hosts:
            try:
                m, ms = _get_json(f"http://{h}:{port}/metrics", timeout=2)
                if isinstance(m, dict) and (
                        "requests_total" in m or "uptime_s" in m):
                    out[port] = {"metrics": m, "ms": ms, "bound": h}
                    break
            except Exception:
                continue
    return out


def health(endpoint: tuple[str, int] | None) -> dict:
    """Probe /health then /metrics on a node's endpoint. Loopback-bound
    services answer on 127.0.0.1; tailnet-bound on the ts IP."""
    if not endpoint:
        return {"ok": None}
    host, port = endpoint
    urls = []
    for h in dict.fromkeys([host, "127.0.0.1"]):
        urls.append(f"http://{h}:{port}")
    res = {"ok": False}
    for base in urls:
        try:
            h, ms = _get_json(base + "/health")
            res.update(ok=True, ms=ms,
                       model=(h.get("model") or "").split("/")[-1])
        except Exception:
            continue
        try:
            m, _ = _get_json(base + "/metrics")
            if isinstance(m, dict):
                res["metrics"] = m
        except Exception:
            pass
        return res
    return res


# -------------------------------------------------------------- assembly

def classify_state(node: dict, hid: HostId) -> str:
    active = node.get("active_state")
    h = node.get("health") or {}
    if node.get("unit"):
        if active == "failed":
            return "failed"
        if active == "active":
            if "shadow" in (node.get("desc") or "").lower() or \
                    node.get("topo_status") == "shadow":
                return "shadow"
            if h.get("ok") is False:
                return "failed"
            return "active"
        return "parked"                     # inactive/dead units = parked
    ts = node.get("topo_status")
    if h.get("ok"):
        return "shadow" if ts == "shadow" else "active"
    if ts in ("parked", "train", "bench", "bench-only") or node.get("lane"):
        return "parked"
    return "failed" if ts == "prod" else "parked"


def fmt_progress(node: dict) -> str:
    m = ((node.get("health") or {}).get("metrics")) or {}
    bits = []
    if m:
        if m.get("requests_total") is not None:
            bits.append(f"{int(m['requests_total'])} req")
        if m.get("escalations_total"):
            bits.append(f"{int(m['escalations_total'])} esc")
        if m.get("uptime_s") is not None:
            up = int(m["uptime_s"])
            bits.append(f"up {up // 3600}h{(up % 3600) // 60}m"
                        if up >= 3600 else f"up {up // 60}m")
    else:
        bits.append("no metrics")
    if node.get("last_bench"):
        bits.append(f"bench {node['last_bench']}")
    return " · ".join(bits)


def discover(hid: HostId, topo_path: Path, cards_dir: Path) -> dict:
    """Full discovery pass -> {merge_key: node}."""
    nodes: dict[str, dict] = {}
    units = discover_units()
    for unit, props in units.items():
        host, port = _parse_endpoint(props.get("ExecStart", ""))
        name = _norm_name(unit)
        merge_node(
            nodes, str(port) if port else name,
            name=name, unit=unit, sources=["unit"],
            desc=props.get("Description", ""),
            active_state=props.get("ActiveState"),
            sub_state=props.get("SubState"),
            endpoint=(host, port) if port else None,
            restart_policy=props.get("Restart"),
            restart_ok=_env_flag(props.get("Environment", ""),
                                 props.get("FragmentPath"),
                                 "NEST_RESTART_OK"),
            nest_owner=_env_owner(props.get("Environment", ""),
                                  props.get("FragmentPath")))
    for key, tnode in topo_nodes(topo_path, hid).items():
        n = merge_node(nodes, key, **tnode)
        if not n.get("topo_name") and tnode.get("topo_name"):
            n["topo_name"] = tnode["topo_name"]
        for k in ("topo_status", "topo_task", "goal", "last_bench",
                  "lane", "runtime"):
            if tnode.get(k) and not n.get(k):
                n[k] = tnode[k]

    # ownership: NEST_OWNER > card claim > adopt
    claims = card_claims(cards_dir)
    for n in nodes.values():
        owner = n.get("nest_owner")
        if owner and owner.lower() in ("none", "unmanaged", "off"):
            n["owner"], n["adopted"] = "unmanaged", False
        elif owner:
            n["owner"], n["adopted"] = owner, False
        elif n.get("name") in claims or n.get("topo_name") in claims:
            cid = claims.get(n.get("name")) or claims.get(
                n.get("topo_name"))
            n["owner"], n["adopted"] = f"card:{cid}", False
        else:
            n["owner"], n["adopted"] = "manager", True

    # health probes (declared endpoints) then orphan /metrics discovery
    claimed_ports = set()
    for n in nodes.values():
        ep = n.get("endpoint")
        if ep:
            claimed_ports.add(ep[1])
            n["health"] = health(ep)
        n["state"] = classify_state(n, hid)
        n["kind"] = n.get("kind") or _kind(
            n.get("name") or "", n.get("desc") or "", n)
    probe_hosts = [h for h in ["127.0.0.1", hid.ts_ip] if h]
    for port, m in probe_metrics(probe_hosts, KNOWN_PORTS,
                                 claimed_ports).items():
        n = merge_node(nodes, str(port), sources=["metrics"],
                       name=f"port-{port}", endpoint=(m["bound"], port),
                       health={"ok": True, "ms": m["ms"],
                               "metrics": m["metrics"]})
        n["state"] = "active"
        n["kind"] = "scorer"
        n["owner"], n["adopted"] = "manager", True
    return nodes


# ------------------------------------------------------------- actuation
# v2 action plane — bounded, allowlisted, audited. Everything here is a
# pure function of (discovered nodes, flag files, previous state) plus —
# only in guarded mode — `systemctl --user restart`. Phase-2 rebalancing
# (re-offering broker-normalized packages to idle hosts) plugs in as a
# second planner beside _plan_restart(); it is deliberately absent until
# the restart pilot proves out (card nest-mgr-v2-actuation rollout).

def _read_list(path: Path) -> set[str]:
    """Line-delimited flag/allowlist file; '#' comments, blanks skipped."""
    try:
        return {l.strip() for l in path.read_text().splitlines()
                if l.strip() and not l.startswith("#")}
    except OSError:
        return set()


def _ts(s: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _ago(s: str | None) -> float:
    """Seconds since an iso ts; a missing/unparseable ts is 'long ago'."""
    d = _ts(s)
    return (_now() - d).total_seconds() if d else 1e18


def requested_mode() -> str:
    m = (os.environ.get("NEST_MGR_MODE") or "").strip().lower()
    if not m:
        try:
            m = MODE_FILE.read_text().strip().lower()
        except OSError:
            m = ""
    return m if m in MODE_RANK else "monitor"


def effective_mode(requested: str) -> tuple[str, list[str]]:
    """Safety flags can only degrade the requested mode, never raise it."""
    if KILL_FILE.exists():
        return "monitor", ["kill switch: actuation.off present"]
    if HOST_CIRCUIT.exists():
        return "monitor", [f"host circuit open — rm {HOST_CIRCUIT} "
                           "to reset"]
    if requested == "guarded" and not OPTIN_FILE.exists():
        return "recommend", ["guarded requested but the per-host opt-in "
                             "flag actuation.on is absent"]
    return requested, []


def restart_gate(n: dict, allow: set[str], manual: set[str]) -> str | None:
    """First blocking gate for auto-restart, or None when the node is a
    restart candidate. The never-list is checked before the allowlist —
    an allowlisted unit that is card-owned, unmanaged, manual, or prod
    still never restarts."""
    unit = n.get("unit") or ""
    if not unit:
        return "no-unit"
    if unit.startswith("nest-mgr") or EXCLUDE_RX.match(unit):
        return "self"
    owner = n.get("owner") or ""
    if owner.startswith("card:"):
        return "owner-card"
    if owner == "unmanaged":
        return "unmanaged"
    if unit in manual or (n.get("name") or "") in manual:
        return "manual"
    if n.get("topo_status") == "prod" and \
            not os.environ.get("NEST_MGR_PROD_OK"):
        return "production"
    if not (n.get("restart_ok") or unit in allow
            or (n.get("name") or "") in allow):
        return "not-allowlisted"
    if n.get("restart_policy") == "on-success":
        # failed + Restart=on-success means the unit is deliberately
        # parked on failure — a timer/oneshot, not a crashed daemon
        return "restart-policy"
    if (CIRCUIT_DIR / f"{unit}.open").exists():
        return "circuit-open"
    return None


def throttle_gate(u: dict) -> str | None:
    """Cooldown + per-unit hourly rate limit on restart attempts."""
    atts = u.get("attempts") or []
    if atts and _ago(atts[-1].get("ts")) < RESTART_COOLDOWN_S:
        return "cooldown"
    if sum(1 for a in atts if _ago(a.get("ts")) < 3600) >= RESTART_MAX_HOUR:
        return "rate-limit"
    return None


def _execs_1h(actions: list[dict]) -> int:
    """Executed restarts in the last hour — the host circuit budget."""
    return sum(
        1 for a in actions
        if a.get("action") == "restart"
        and str(a.get("outcome") or "").startswith(("ok", "error"))
        and _ago(a.get("ts")) < 3600)


def actuation_tick(nodes: dict, hid: HostId, prev: dict,
                   plan_only: bool = False) -> tuple[dict, list[dict]]:
    """One actuation tick. Returns (actuation_state, new_events).

    monitor   — counters only; zero decisions (v1 behavior, unchanged).
    recommend — plan allowlisted actions, log them, execute nothing.
    guarded   — additionally execute allowlisted restarts; requires the
                actuation.on opt-in flag plus all per-unit gates.
    plan_only — dry-run/report callers: guarded degrades to recommend so
                a preview can never execute."""
    prev_act = prev.get("actuation") or {}
    units = {k: dict(v) for k, v in (prev_act.get("units") or {}).items()}
    metrics = dict(prev_act.get("metrics") or {})
    prev_actions = list(prev.get("actions") or [])
    req = requested_mode()
    eff, notes = effective_mode(req)
    if plan_only and eff == "guarded":
        eff = "recommend"
        notes.append("plan-only tick — guarded degraded to recommend")
    now = _now()
    events: list[dict] = []

    def record(unit: str, action: str, reason: str, outcome: str,
               prior_state: str | None = None) -> None:
        events.append({"ts": now.isoformat(timespec="seconds"),
                       "host": hid.label(), "unit": unit,
                       "prior_state": prior_state, "action": action,
                       "reason": reason, "outcome": outcome})

    def bump(key: str, n: int = 1) -> None:
        metrics[key] = int(metrics.get(key) or 0) + n

    # fail_ticks bookkeeping runs in every mode — pure observation; a
    # monitor -> recommend mode flip must not inherit a stale streak.
    for n in nodes.values():
        unit = n.get("unit")
        if not unit:
            continue
        u = units.setdefault(unit, {})
        u["fail_ticks"] = (int(u.get("fail_ticks") or 0) + 1
                           if n.get("state") == "failed" else 0)
        u["attempts"] = [a for a in (u.get("attempts") or [])
                         if _ago(a.get("ts")) < 2 * 3600]

    # ghost prune — a unit that leaves discovery (unit file removed,
    # renamed, transient show failure) must not keep stale fail_ticks /
    # held / attempts forever; seen live on idc02 (ada-code.service
    # outlived its unit file). `missed` counts consecutive absent ticks
    # so a one-tick discovery gap can't wipe throttle memory.
    seen_units = {n.get("unit") for n in nodes.values() if n.get("unit")}
    for unit in list(units):
        u = units[unit]
        if unit in seen_units:
            u["missed"] = 0
        else:
            u["missed"] = int(u.get("missed") or 0) + 1
            if u["missed"] >= UNIT_PRUNE_MISSES:
                del units[unit]

    prev_mode = prev_act.get("mode") or "monitor"
    if prev_mode != eff:
        record("-", "mode-change", f"{prev_mode} -> {eff}", eff)

    if eff != "monitor":
        allow = _read_list(ALLOW_FILE)
        manual = _read_list(MANUAL_FILE)
        for key in sorted(nodes, key=lambda k: nodes[k].get("name") or k):
            n = nodes[key]
            unit = n.get("unit")
            if not unit:
                continue
            u = units[unit]
            if (u.get("fail_ticks") or 0) < FAIL_TICKS:
                # recovered / never reached threshold — drop any stale
                # held verdict so the audit trail doesn't claim a gate
                # that no longer applies
                u.pop("held", None)
                continue
            u = units[unit]
            gate = restart_gate(n, allow, manual) or throttle_gate(u)
            if gate:
                held = u.get("held") or {}
                if held.get("gate") != gate or \
                        _ago(held.get("ts")) > HELD_RESEND_S:
                    u["held"] = {"gate": gate,
                                 "ts": now.isoformat(timespec="seconds")}
                    record(unit, "restart", gate, "held",
                           prior_state=n.get("state"))
                    bump("held")
                continue
            u.pop("held", None)
            acted = False
            if eff == "guarded":
                if _execs_1h(prev_actions) + _execs_1h(events) \
                        >= HOST_MAX_ACTIONS_HOUR:
                    if not HOST_CIRCUIT.exists():
                        HOST_CIRCUIT.write_text(
                            now.isoformat(timespec="seconds"))
                        record("-", "circuit-open",
                               f"more than {HOST_MAX_ACTIONS_HOUR} "
                               "restart actions in 1h", "open")
                        bump("circuits")
                    eff = "recommend"
                    notes.append("host circuit opened this tick — "
                                 "degraded to recommend")
                else:
                    acted = True
                    _, rc = _sh(["systemctl", "--user", "restart", unit],
                                timeout=30)
                    att = {"ts": now.isoformat(timespec="seconds"),
                           "ok": rc == 0}
                    u.setdefault("attempts", []).append(att)
                    if rc == 0:
                        u["fail_ticks"] = 0
                        record(unit, "restart",
                               f"failed {FAIL_TICKS}+ ticks; allowlisted",
                               "ok", prior_state=n.get("state"))
                        bump("executed"); bump("exec_ok")
                    else:
                        record(unit, "restart",
                               f"systemctl --user restart rc={rc}",
                               "error", prior_state=n.get("state"))
                        bump("executed"); bump("exec_fail")
                        fails = sum(1 for a in u["attempts"]
                                    if not a.get("ok")
                                    and _ago(a.get("ts")) < 3600)
                        if fails >= UNIT_FAILS_CIRCUIT:
                            CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
                            (CIRCUIT_DIR / f"{unit}.open").write_text(
                                now.isoformat(timespec="seconds"))
                            record(unit, "circuit-open",
                                   f"{fails} failed restarts in 1h",
                                   "open", prior_state=n.get("state"))
                            bump("circuits")
            if not acted and _ago(u.get("last_rec")) > REC_RESEND_S:
                u["last_rec"] = now.isoformat(timespec="seconds")
                record(unit, "restart",
                       f"state=failed {u['fail_ticks']} consecutive "
                       "ticks; eligible, gates green",
                       "recommended", prior_state=n.get("state"))
                bump("recommended")

    act = {
        "requested_mode": req, "mode": eff,
        "notes": notes or None,
        "opted_in": OPTIN_FILE.exists(),
        "kill_switch": KILL_FILE.exists(),
        "host_circuit": HOST_CIRCUIT.exists(),
        "unit_circuits": (sorted(p.name[:-5]
                                 for p in CIRCUIT_DIR.glob("*.open"))
                          if CIRCUIT_DIR.is_dir() else []),
        "units": units, "metrics": metrics,
    }
    return act, events


# ----------------------------------------------------------------- state

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def fingerprint(nodes: dict, act: dict | None = None,
                actions: list[dict] | None = None) -> str:
    """State-change detector: publish when any node's state/health, the
    node set, the actuation posture, or the audit tail changes."""
    parts = []
    for k in sorted(nodes):
        n = nodes[k]
        h = n.get("health") or {}
        parts.append(f"{n.get('name') or k}:{n.get('state')}:{h.get('ok')}")
    if act:
        parts.append(f"~mode:{act.get('mode')}")
        # count + last ts: at the ACTIONS_CAP ring bound a new event must
        # still shift the fingerprint
        last = (actions or [{}])[-1].get("ts") or "-"
        parts.append(f"~actions:{len(actions or [])}:{last}")
        for c in act.get("unit_circuits") or []:
            parts.append(f"~circuit:{c}")
    return "|".join(parts)


def update_state_file(nodes: dict, hid: HostId, act: dict,
                      events: list[dict],
                      prev: dict | None = None) -> tuple[bool, list[dict]]:
    """Merge into manager-state.json (first_seen/adopted_at persist).
    State file is keyed by node NAME (jev-student, bankq-student, …).
    Actuation state + the actions[] audit ring (last ACTIONS_CAP) ride
    the same doc. Returns (fingerprint_changed, full actions list)."""
    prev = prev if prev is not None else load_state()
    prev_nodes = prev.get("nodes") or {}
    now = _now().isoformat(timespec="seconds")
    out_nodes = {}
    for key, n in nodes.items():
        skey = n.get("name") or key
        old = prev_nodes.get(skey) or {}
        out_nodes[skey] = {
            "name": n.get("name"), "kind": n.get("kind"),
            "endpoint": (f"{n['endpoint'][0]}:{n['endpoint'][1]}"
                         if n.get("endpoint") else None),
            "unit": n.get("unit"), "lane": n.get("lane"),
            "aliases": n.get("aliases") or None,
            "topology_model": n.get("topo_name"),
            "sources": n.get("sources"),
            "state": n.get("state"), "owner": n.get("owner"),
            "adopted": bool(n.get("adopted")),
            "restart_ok": bool(n.get("restart_ok")),
            "restart_policy": n.get("restart_policy"),
            "goal": n.get("goal") or n.get("desc"),
            "progress": fmt_progress(n),
            "health": {k2: v for k2, v in (n.get("health") or {}).items()
                       if k2 != "metrics"},
            "metrics": (n.get("health") or {}).get("metrics"),
            "first_seen": old.get("first_seen") or now,
            "last_seen": now,
            "adopted_at": (old.get("adopted_at")
                           or (now if n.get("adopted") else None)),
        }
    actions = (list(prev.get("actions") or []) + events)[-ACTIONS_CAP:]
    fp = fingerprint(nodes, act, actions)
    doc = {"host": hid.label(), "manager": "nest-mgr v2",
           "updated": now, "fingerprint": fp,
           "leash": "actuation monitor<recommend<guarded — gated, "
                    "allowlisted, audited; production lanes stay "
                    "leashed (card nest-mgr-v2-actuation)",
           "actuation": act, "actions": actions,
           "nodes": out_nodes}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE_DIR, prefix=".state-")
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, STATE_FILE)
    return (fp != prev.get("fingerprint") or
            set(out_nodes) != set(prev_nodes)), actions


# ---------------------------------------------------------------- report

STATE_MARK = {"active": "active", "shadow": "shadow", "failed": "FAILED",
              "parked": "parked"}


def render_page(nodes: dict, hid: HostId, now: datetime,
                act: dict | None = None,
                actions: list[dict] | None = None) -> tuple[str, str]:
    stamp = now.astimezone(ICT).strftime("%Y-%m-%d %H:%M")
    rows = []
    counts = {"active": 0, "shadow": 0, "failed": 0, "parked": 0}
    adopted = 0
    for key in sorted(nodes, key=lambda k: nodes[k].get("name") or k):
        n = nodes[key]
        st = n.get("state") or "parked"
        counts[st] = counts.get(st, 0) + 1
        adopted += 1 if n.get("adopted") else 0
        ep = n.get("endpoint")
        ep_s = (f"{ep[0]}:{ep[1]}" if ep else "—")
        if hid.ts_ip:
            ep_s = ep_s.replace(hid.ts_ip, hid.hostname)
        ep_s = ep_s.replace(".taila0626a.ts.net", "")
        mark = {"active": "🟢", "shadow": "🟡", "failed": "🔴",
                "parked": "⚪"}.get(st, "")
        goal = n.get("goal") or n.get("desc") or "—"
        ok = " ✅restart-ok" if n.get("restart_ok") else ""
        rows.append(
            f"| **{n.get('name')}** | {n.get('kind') or 'node'} | "
            f"`{ep_s}` | {mark} {st} | {goal} — {fmt_progress(n)} | "
            f"{n.get('owner')}{ok} |")
    n_nodes = len(nodes)
    act = act or {}
    mode = act.get("mode") or "monitor"
    req = act.get("requested_mode") or mode
    req_note = f" (requested `{req}`)" if req != mode else ""
    summary = (f"{n_nodes} nest nodes on {hid.label()}: "
               f"{counts['active']} active, {counts['shadow']} shadow, "
               f"{counts['failed']} failed, {counts['parked']} parked — "
               f"{adopted} adopted · actuation mode {mode}")
    if not rows:
        rows.append("| _none_ | — | — | — | no nest nodes discovered on "
                    "this host | — |")

    arows = []
    for a in (actions or [])[-8:]:
        arows.append(
            f"| `{a.get('ts', '?')[5:19].replace('T', ' ')}Z` | "
            f"{a.get('unit')} | {a.get('action')} | {a.get('reason')} | "
            f"{a.get('outcome')} |")
    if not arows:
        arows.append("| — | _no actuation events recorded yet_ | — | — |"
                     " — |")
    m = act.get("metrics") or {}
    met_bits = []
    for k in ("recommended", "executed", "exec_ok", "exec_fail", "held",
              "circuits"):
        if m.get(k):
            met_bits.append(f"{k} {m[k]}")
    flags = []
    flags.append("opt-in `actuation.on` ✅" if act.get("opted_in")
                 else "opt-in `actuation.on` —")
    flags.append("kill `actuation.off` 🔴SET" if act.get("kill_switch")
                 else "kill `actuation.off` —")
    flags.append("host circuit 🔴OPEN" if act.get("host_circuit")
                 else "host circuit —")
    ucirc = act.get("unit_circuits") or []
    flags.append(f"unit circuits 🔴{','.join(ucirc)}" if ucirc
                 else "unit circuits —")
    posture = " · ".join(flags)
    met_line = (f"lifetime: {' · '.join(met_bits)}"
                if met_bits else "no actions recorded")
    notes = act.get("notes") or []
    notes_line = ("  \n".join(f"> {x}" for x in notes) + "  \n") \
        if notes else ""
    body = f"""# Nest nodes — {hid.label()}

**{summary}**
_Updated {stamp} ICT · `nest-mgr.service` v2 — observer-governor + gated
actuation plane. `monitor` reports only · `recommend` plans and audits ·
`guarded` executes allowlisted restarts under per-host opt-in + circuit
breakers (card `nest-mgr-v2-actuation`; prod lanes stay leashed)._

| node | kind | endpoint | state | goal · progress | owner |
|---|---|---|---|---|---|
{chr(10).join(rows)}

## Actuation — mode `{mode}`{req_note}

{notes_line}{posture}
_{met_line}_

| ts (utc) | unit | action | reason | outcome |
|---|---|---|---|---|
{chr(10).join(arows)}

**Owner** — `manager` = adopted ownerless node · `card:<id>` = kanban claim
(`nest_nodes:` on the card) · `unmanaged` = NEST_OWNER opt-out · any other
value = that unit's declared NEST_OWNER · `✅restart-ok` = the unit opts in
to guarded auto-restart (`NEST_RESTART_OK=1` or `restart-allowlist`).

**Discovery** — systemd user units matching `jev|student|bankq|nest|serve-*.py|openjev` ·
`serves:`/`lanes:` entries in ada-voice `tests/bench/topologies.yml` resolving
here · live `/metrics` on known nest ports.

*Generated by nest-mgr.py · {stamp} ICT · state:
`~/.local/share/nest/manager-state.json` · hub: [chaba-nest](#/chaba-nest)*
"""
    return body, summary[:240]


def get_page(slug: str) -> dict | None:
    try:
        return _post("get", {"collection": COLLECTION, "key": slug,
                             "lang": "en"})
    except Exception:
        return None


def get_registry(slug: str) -> tuple[dict, dict | None]:
    """-> (cfg, raw_doc). cfg={} when missing/unparseable."""
    try:
        d = _post("get", {"collection": REGISTRY, "key": slug,
                          "lang": "en"})
        if d:
            return json.loads(d.get("contentMd") or "{}"), d
    except Exception:
        pass
    return {}, None


def save_registry(slug: str, cfg: dict) -> None:
    now = _now()
    meta = {"kind": ["automation-config"], "bank": ["cms"],
            "scope": ["tony"], "status": ["active"], "source": ["api"],
            "written_by": ["nest-mgr"], "subject": [slug],
            "attribute": ["automation"], "slug": [slug],
            "title": [f"CMS automation: {slug}"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    _post("add", {"collection": REGISTRY, "key": slug, "lang": "en",
                  "contentMd": json.dumps(cfg, ensure_ascii=False,
                                          indent=2), "meta": meta},
          timeout=60)


TIMELINE_CAP = 40


def publish(nodes: dict, hid: HostId, now: datetime,
            act: dict | None = None, actions: list[dict] | None = None,
            dry_run: bool = False) -> str:
    slug = f"nest-{hid.label()}"
    body, summary = render_page(nodes, hid, now, act, actions)
    if dry_run:
        return body
    old = get_page(slug) or {}
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (old.get("meta") or {}).items()}
    tl = [x for x in meta.get("timeline", []) if isinstance(x, str)]
    n_active = sum(1 for n in nodes.values()
                   if n.get("state") in ("active", "shadow"))
    tl.append(f"{now.isoformat(timespec='minutes')}: refresh — "
              f"{len(nodes)} nodes, {n_active} up")
    meta.update({
        "kind": ["report"], "attribute": ["report"],
        "report_role": ["leaf"], "parent": ["chaba-nest"],
        "domain": ["bench"], "bank": ["cms"], "scope": ["tony"],
        "status": ["active"], "source": ["api"],
        "slug": [slug], "subject": [slug],
        "title": [f"Nest nodes — {hid.label()}"],
        "format": ["markdown"], "lang": ["en"],
        "summary": [summary], "fresh_for": ["30m"],
        "confidence": ["high"],
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "valid_from": meta.get("valid_from")
                      or [now.date().isoformat()],
        "written_by": ["nest-mgr"],
        "generated_by": ["nest-mgr.py (nest-mgr.service)"],
        "sources": ["systemctl --user", "ada-voice topologies.yml",
                    "GET /metrics"],
        "links": ["chaba-nest", "nest-bench",
                  f"services-{hid.label()}"],
        "timeline": tl[-TIMELINE_CAP:],
    })
    _post("add", {"collection": COLLECTION, "key": slug, "lang": "en",
                  "contentMd": body, "meta": meta}, timeout=120)

    # registry doc — seed on first sight, always write last_run; run_now
    # is consumed (cleared) by the publish itself.
    cfg, _ = get_registry(slug)
    cfg.update({
        "enabled": cfg.get("enabled", True),
        "interval_min": int(cfg.get("interval_min") or PUBLISH_S // 60),
        "run_now": False,
        "page": slug,
        # generator host — cms-auto-health gates staleness on tailnet
        # reachability so a powered-off host doesn't card as broken
        "host": hid.label(),
        "generator": {"kind": "service", "name": "nest-mgr",
                      "unit": "nest-mgr.service",
                      "note": "per-host daemon — publishes every 15 min + "
                              "on state change; regenerate queues run_now "
                              "and the daemon clears it next tick"},
        "note": "per-host nest node report — observer-governor "
                "(card nest-manager-node)",
        "last_run": now.isoformat(timespec="seconds"),
        "last_status": "ok",
    })
    save_registry(slug, cfg)
    return body


# ------------------------------------------------------------------ main

def cycle(hid: HostId, topo: Path, cards: Path, publish_now: bool,
          dry_run: bool) -> tuple[bool, dict]:
    """One tick. Returns (published?, nodes)."""
    nodes = discover(hid, topo, cards)
    prev = load_state()
    act, events = actuation_tick(nodes, hid, prev, plan_only=dry_run)
    changed, actions = update_state_file(nodes, hid, act, events, prev)
    cfg, _ = get_registry(f"nest-{hid.label()}") if not dry_run \
        else ({}, None)
    due = publish_now or changed or cfg.get("run_now") or \
        _publish_due(cfg)
    if due:
        if cfg.get("enabled", True) or publish_now:
            publish(nodes, hid, _now(), act, actions, dry_run=dry_run)
            return True, nodes
    return False, nodes


def _publish_due(cfg: dict) -> bool:
    interval = int(cfg.get("interval_min") or PUBLISH_S // 60)
    last = cfg.get("last_run")
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return _now() >= dt + timedelta(minutes=interval)
    except ValueError:
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                    help="one full cycle, publish now")
    ap.add_argument("--loop", action="store_true",
                    help=f"daemon: tick {TICK_S}s, publish {PUBLISH_S}s"
                         " / on change / on run_now")
    ap.add_argument("--discover", action="store_true",
                    help="print discovered nodes only")
    ap.add_argument("--report", action="store_true",
                    help="print rendered page only")
    ap.add_argument("--actions", action="store_true",
                    help="print the actions[] audit tail")
    ap.add_argument("--dry-run", action="store_true",
                    help="state file yes, CMS/registry no, never executes")
    ap.add_argument("--topologies", default=os.environ.get(
        "NEST_TOPOLOGIES", str(DEFAULT_TOPO)))
    ap.add_argument("--cards", default=os.environ.get(
        "NEST_CARDS_DIR", str(DEFAULT_CARDS)))
    ap.add_argument("--host", default=os.environ.get("NEST_HOST"))
    a = ap.parse_args()

    hid = HostId()
    if a.host:
        hid.hostname = a.host
    topo, cards = Path(a.topologies), Path(a.cards)

    if a.discover:
        nodes = discover(hid, topo, cards)
        print(f"{len(nodes)} node(s) on {hid.label()}:")
        for k in sorted(nodes, key=lambda k: nodes[k].get("name") or k):
            n = nodes[k]
            ep = n.get("endpoint")
            print(f"  {n.get('name'):24} {n.get('state') or '?':7} "
                  f"{(ep[0] + ':' + str(ep[1])) if ep else '—':24} "
                  f"owner={n.get('owner'):10} src={'+'.join(n['sources'])}")
        return 0
    if a.report:
        nodes = discover(hid, topo, cards)
        prev = load_state()
        act, events = actuation_tick(nodes, hid, prev, plan_only=True)
        print(render_page(nodes, hid, _now(), act,
                          list(prev.get("actions") or []) + events)[0])
        return 0
    if a.actions:
        st = load_state()
        acts = st.get("actions") or []
        act = st.get("actuation") or {}
        print(f"{hid.label()}: mode={act.get('mode') or 'monitor'} "
              f"(requested {act.get('requested_mode') or '?'}) — "
              f"{len(acts)} audit record(s):")
        for ev in acts[-25:]:
            print(f"  {ev.get('ts')}  {ev.get('unit') or '-':28} "
                  f"{ev.get('action'):12} {ev.get('outcome'):12} "
                  f"{ev.get('reason')}")
        return 0
    if a.loop:
        print(f"nest-mgr: host={hid.label()} tick={TICK_S}s "
              f"publish={PUBLISH_S}s state={STATE_FILE}")
        while True:
            try:
                did, nodes = cycle(hid, topo, cards,
                                   publish_now=False, dry_run=a.dry_run)
                if did:
                    print(f"{_now().isoformat(timespec='seconds')} "
                          f"published nest-{hid.label()} "
                          f"({len(nodes)} nodes)")
            except Exception as e:
                print(f"tick error: {e}", file=sys.stderr)
            time.sleep(TICK_S)
    # default / --once
    did, nodes = cycle(hid, topo, cards, publish_now=True,
                       dry_run=a.dry_run)
    print(f"{'would publish' if a.dry_run else 'published'} "
          f"nest-{hid.label()} — {len(nodes)} nodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
