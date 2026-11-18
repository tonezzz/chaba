#!/usr/bin/env python3
"""Fleet edge-upstream audit — dead-upstream tripwire.

Wound (2026-11-18): tony-omen `tailscale serve` :8125 proxied to dead
127.0.0.1:8125 (the tony-ha container listens on :8123); caddy-edge on
idc02 reverse-proxied ada-ha.surf-thailand.com to it and the whole vhost
502'd. Two edge layers each pointed at a dead upstream and nothing
checked the binding between an edge surface and its backend. This audit
closes that gap:

1. tailscale serve drift — `tailscale serve status --json` per host; every
   Web handler Proxy/Path target and TCP TCPForward target is verified:
   loopback targets against the host's own listener table (`ss`), remote
   targets by HTTP probe from the runner.
2. caddy reverse_proxy upstreams — Caddyfile(s) per host parsed for
   `reverse_proxy` targets per vhost; loopback targets checked against the
   host's listeners, remote targets probed (GET, expect non-5xx).

Read-only by design. Exit 1 when any upstream is dead or degraded.

Output rows: {host, surface, mount, upstream, status, evidence} —
`--write` emits per-host artifacts + report-graph metas under
reports/edge-upstreams/ (nodes edge-upstreams/<host>), `--alert` files a
deduped board-api /inbox entry per failing surface, `--ship` rsyncs the
report dir to the served checkout so the fleet report sees it.
"""

import argparse
import datetime as dt
import json
import os
import re
import shlex
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR_DEFAULT = REPO_ROOT / "reports" / "edge-upstreams"
INBOX_API = os.environ.get("CHABA_BOARD_API",
                           "https://idc03.taila0626a.ts.net:10000")
ALERT_STATE = Path(os.environ.get(
    "CHABA_EDGE_ALERT_STATE", "~/var/chaba/edge-upstream-alerts.json")
).expanduser()
SHIP_DEFAULT = os.environ.get(
    "CHABA_EDGE_SHIP", "idc03:CascadeProjects/chaba-tony-dell/reports/edge-upstreams/")

TIMEOUT = 8
SSH_TIMEOUT = 30
REPEAT_H = 24

HOSTS = {
    "tony-omen": {"tailnet": "tony-omen", "user": "tony"},
    "tony-dell": {"tailnet": "tony-dell", "user": "tony"},
    "idc02": {"tailnet": "idc02", "user": "tony"},
    "idc03": {"tailnet": "idc03", "user": "tony"},
    "mn01": {"tailnet": "mn01", "user": "tony"},
    "con01": {"tailnet": "con01", "user": "tony"},
}
DEFAULT_FLEET = ["tony-omen", "tony-dell", "idc02", "idc03", "mn01"]

# (path, loopback_scope). scope=host: the caddy instance runs with host
# networking (quadlet --network=host or a host process), so 127.0.0.1
# upstreams are host listeners. scope=container: slirp4netns netns —
# loopback upstreams live inside the container and cannot be verified via
# the host's `ss` table (the published surface is the real check).
CADDY_CANDIDATES = [
    ("~/.config/caddy/Caddyfile", "host"),
    ("~/.config/camwall-edge/Caddyfile", "container"),
    ("~/web-srv/caddy/Caddyfile", "container"),
]

# ss local addresses that accept a 127.0.0.1 client.
LOOPBACK_COVERING = ("127.0.0.1", "*", "0.0.0.0", "[::]", "[::1]")

STATUSES = ("ok", "degraded", "dead", "skipped")


# ------------------------------------------------------------ transport

def _run(cmd: list[str], timeout: int) -> tuple[str, str, int]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        return e.stdout or "", e.stderr or "", 124
    except FileNotFoundError as e:
        return "", str(e), 127


def run_ssh(host: str, cmd: str, timeout: int = SSH_TIMEOUT) -> tuple[str, str, int]:
    """Same reachability pattern as audit-hosts.py: tailnet name first
    (known_hosts keys on names; raw IPs can fail host-key checks), then
    the tailscale IP."""
    cfg = HOSTS[host]
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
               f"{cfg['user']}@{cfg['tailnet']}", cmd]
    out, err, rc = _run(ssh_cmd, timeout)
    if rc == 0 or out.strip():
        return out, err, rc
    try:
        ip = subprocess.run(
            ["tailscale", "ip", "-4", cfg["tailnet"]],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        ip = cfg["tailnet"]
    if ip == cfg["tailnet"]:
        return out, err, rc
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
               f"{cfg['user']}@{ip}", cmd]
    return _run(ssh_cmd, timeout)


def host_cmd(host: str, cmd: str, timeout: int = SSH_TIMEOUT) -> tuple[str, str, int]:
    if host == local_hostname():
        return _run(["bash", "-c", cmd], timeout)
    return run_ssh(host, cmd, timeout)


def local_hostname() -> str:
    try:
        return socket.gethostname().split(".")[0]
    except Exception:
        return ""


# ------------------------------------------------------------- probing

def probe_http(url: str, insecure: bool = False) -> tuple[str, str]:
    """GET url; classify (status, evidence). Any HTTP response <500 is ok
    (auth/404 still prove the upstream is alive); >=500 degraded; TLS or
    protocol errors mean something answered but can't serve the edge —
    degraded; connect refused/timeout/DNS dead."""
    ctx = ssl._create_unverified_context() if insecure else None
    req = urllib.request.Request(url, method="GET",
                                 headers={"User-Agent": "edge-upstream-audit/1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            st = r.status
    except urllib.error.HTTPError as e:
        st = e.code
    except urllib.error.URLError as e:
        return _classify_url_error(e, url)
    except ssl.SSLError as e:
        return "degraded", f"{url} tls-error {e}"
    except Exception as e:
        return "dead", f"{url} {type(e).__name__}: {e}"
    if st >= 500:
        return "degraded", f"{url} HTTP {st}"
    return "ok", f"{url} HTTP {st}"


def _classify_url_error(e: urllib.error.URLError, url: str) -> tuple[str, str]:
    reason = e.reason
    if isinstance(reason, ssl.SSLError):
        return "degraded", f"{url} tls-error {reason}"
    if isinstance(reason, (ConnectionRefusedError, TimeoutError,
                         socket.timeout, socket.gaierror)):
        return "dead", f"{url} {type(reason).__name__}"
    if isinstance(reason, OSError):
        # ECONNREFUSED/EHOSTUNREACH/ENETUNREACH arrive wrapped
        return "dead", f"{url} {reason}"
    if isinstance(reason, Exception) and "RemoteDisconnected" in type(reason).__name__:
        return "degraded", f"{url} remote-disconnected"
    return "dead", f"{url} {reason}"


def probe_tcp(addr: str, port: int) -> tuple[str, str]:
    try:
        with socket.create_connection((addr, port), timeout=TIMEOUT):
            return "ok", f"tcp {addr}:{port} connect ok"
    except ssl.SSLError as e:
        return "degraded", f"tcp {addr}:{port} tls {e}"
    except Exception as e:
        return "dead", f"tcp {addr}:{port} {type(e).__name__}: {e}"


# ---------------------------------------------------- host-side checks

def host_listeners(host: str) -> tuple[dict[int, set[str]], set[str], str | None]:
    """({port: {bind_addrs}}, {unix_socket_paths}, error) from ss."""
    out, err, rc = host_cmd(host, "ss -ltnH; echo '--X--'; ss -lxnH")
    if rc != 0 and not out.strip():
        return {}, set(), f"ss failed rc={rc}: {err.strip()[:160]}"
    tcp_part, _, unix_part = out.partition("--X--")
    ports: dict[int, set[str]] = {}
    for line in tcp_part.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3].split("%")[0]     # strip %iface
        addr, _, p = local.rpartition(":")
        try:
            port = int(p)
        except ValueError:
            continue
        ports.setdefault(port, set()).add(addr)
    unix = set()
    for line in unix_part.splitlines():
        parts = line.split()
        for tok in parts:
            if tok.startswith("/"):
                unix.add(tok.split("%")[0])
                break
    return ports, unix, None


def check_loopback(port: int, listeners: dict[int, set[str]]) -> tuple[str, str]:
    """Does 127.0.0.1:port accept connections on this host?"""
    addrs = listeners.get(port)
    if not addrs:
        return "dead", f"127.0.0.1:{port} — nothing listening"
    if addrs & set(LOOPBACK_COVERING):
        return "ok", f"127.0.0.1:{port} listening ({', '.join(sorted(addrs))})"
    return "dead", (f"127.0.0.1:{port} bound only on {sorted(addrs)} "
                    "— loopback clients refused")


# -------------------------------------------------------- serve parsing

def parse_serve_status(status: dict) -> list[dict]:
    """Flatten `tailscale serve status --json` into check targets:
    [{surface, mount, kind, target}]. Handles the background Web/TCP
    sections plus Foreground sessions (own TCP/Web trees)."""
    out: list[dict] = []
    sections = [("", status)]
    for sess, sub in (status.get("Foreground") or {}).items():
        sections.append((f"fg:{sess}", sub))
    for scope, sub in sections:
        for surface, site in (sub.get("Web") or {}).items():
            handlers = (site or {}).get("Handlers") or {}
            for mount, h in handlers.items():
                if not isinstance(h, dict):
                    continue
                if "Proxy" in h:
                    out.append({"surface": f"serve:{surface}" + (f" ({scope})" if scope else ""),
                                "mount": mount, "kind": "proxy",
                                "target": h["Proxy"]})
                elif "Path" in h:
                    out.append({"surface": f"serve:{surface}" + (f" ({scope})" if scope else ""),
                                "mount": mount, "kind": "fs",
                                "target": h["Path"]})
                elif "Text" in h:
                    out.append({"surface": f"serve:{surface}" + (f" ({scope})" if scope else ""),
                                "mount": mount, "kind": "text",
                                "target": "inline"})
        for tport, spec in (sub.get("TCP") or {}).items():
            if isinstance(spec, dict) and "TCPForward" in spec:
                out.append({"surface": f"serve-tcp:{tport}" + (f" ({scope})" if scope else ""),
                            "mount": "-", "kind": "tcpforward",
                            "target": spec["TCPForward"]})
    return out


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def split_hostport(hp: str) -> tuple[str, int | None]:
    hp = hp.strip()
    if hp.startswith("["):
        m = re.match(r"^\[([^\]]+)\](?::(\d+))?$", hp)
        if m:
            return m.group(1), int(m.group(2)) if m.group(2) else None
        return hp, None
    if ":" in hp:
        host, _, p = hp.rpartition(":")
        try:
            return host, int(p)
        except ValueError:
            return hp, None
    return hp, None


def classify_target(target: str) -> dict:
    """Classify a serve/caddy upstream target into a checkable form."""
    t = target.strip()
    low = t.lower()
    if low == "tailscale-only":
        return {"kind": "skip", "why": "tailscale-only control target"}
    if low.startswith("http+unix://") or low.startswith("unix/"):
        path = urllib.parse.unquote(
            t.split("://", 1)[-1] if "://" in t else t[len("unix"):])
        return {"kind": "unix", "path": path}
    insecure = "+insecure" in low
    m = re.match(r"^(https?)(?:\+insecure)?://", low)
    if m:
        scheme = m.group(1)
        rest = t.split("://", 1)[1]
        host, port = split_hostport(rest.split("/")[0])
        if host in _LOOPBACK_HOSTS:
            return {"kind": "loopback", "port": port}
        return {"kind": "http",
                "url": f"{scheme}://{rest}", "insecure": insecure,
                "host": host, "port": port}
    if low.startswith("tcp://"):
        host, port = split_hostport(t[6:])
        if host in _LOOPBACK_HOSTS:
            return {"kind": "loopback", "port": port}
        return {"kind": "tcp", "host": host, "port": port}
    # scheme-less: caddy treats it as plain HTTP upstream
    host, port = split_hostport(t)
    if host in _LOOPBACK_HOSTS:
        return {"kind": "loopback", "port": port}
    if re.fullmatch(r"[A-Za-z0-9_-]+", host or ""):
        return {"kind": "container", "name": host, "port": port}
    if host:
        return {"kind": "http", "url": f"http://{t}/",
                "insecure": False, "host": host, "port": port}
    return {"kind": "skip", "why": f"unparseable target {t!r}"}


def check_target(host: str, cls: dict, listeners, unix_socks,
                 file_ok: dict[str, bool], container_ok: dict[str, bool],
                 loopback_scope: str = "host") -> tuple[str, str]:
    kind = cls["kind"]
    if kind == "skip":
        return "skipped", cls["why"]
    if kind == "loopback":
        if cls.get("port") is None:
            return "skipped", "loopback target with no port"
        if loopback_scope == "container":
            return "skipped", ("127.0.0.1 inside container netns — "
                               "host ss cannot see it; published surface is the check")
        return check_loopback(cls["port"], listeners)
    if kind == "unix":
        if cls["path"] in unix_socks:
            return "ok", f"unix socket {cls['path']} listening"
        return "dead", f"unix socket {cls['path']} not in ss -lxn"
    if kind == "fs":
        ok = file_ok.get(cls["path"])
        if ok is True:
            return "ok", f"root {cls['path']} exists"
        if ok is False:
            return "dead", f"static root {cls['path']} missing on host"
        return "skipped", f"fs check failed for {cls['path']}"
    if kind == "container":
        ok = container_ok.get(cls["name"])
        if ok is True:
            return "ok", f"container {cls['name']} running"
        if ok is False:
            return "dead", f"container-net upstream {cls['name']} not running"
        return "skipped", (f"container-net name {cls['name']} — resolves "
                           "inside the edge network, not verifiable from host")
    if kind == "http":
        return probe_http(cls["url"], insecure=cls.get("insecure", False))
    if kind == "tcp":
        if cls.get("port") is None:
            return "skipped", f"tcp target without port: {cls}"
        return probe_tcp(cls["host"], cls["port"])
    return "skipped", f"unknown kind {kind}"


def audit_serve(host: str) -> tuple[list[dict], str | None]:
    out, err, rc = host_cmd(host, "tailscale serve status --json")
    if rc != 0:
        blob = (out + err).strip().lower()
        if "no serve config" in blob or not blob:
            return [], "empty-serve"     # not an error — nothing declared
        return [], f"serve status rc={rc}: {(out + err).strip()[:160]}"
    try:
        status = json.loads(out or "{}")
    except json.JSONDecodeError as e:
        return [], f"serve status json parse: {e}"
    targets = parse_serve_status(status)
    if not targets:
        return [], None
    listeners, unix_socks, lerr = host_listeners(host)
    fs_paths = [t["target"] for t in targets if t["kind"] == "fs"]
    file_ok = check_paths(host, fs_paths, "-d")
    rows = []
    for t in targets:
        cls = classify_target(t["target"]) if t["kind"] in ("proxy", "tcpforward") \
            else {"kind": t["kind"], "path": t["target"]}
        if lerr and cls["kind"] in ("loopback", "unix"):
            status_s, ev = "skipped", f"listeners unavailable: {lerr}"
        else:
            status_s, ev = check_target(host, cls, listeners, unix_socks,
                                        file_ok, {})
        rows.append({"host": host, "surface": t["surface"],
                     "mount": t["mount"], "upstream": t["target"],
                     "status": status_s, "evidence": ev})
    return rows, None


def check_paths(host: str, paths: list[str], flag: str) -> dict[str, bool]:
    if not paths:
        return {}
    quoted = " ".join(shlex.quote(p) for p in paths)
    out, _e, _rc = host_cmd(
        host, f'for p in {quoted}; do [ {flag} "$p" ] && echo "ok $p" || echo "no $p"; done')
    res = {}
    for line in out.splitlines():
        mark, _, p = line.partition(" ")
        res[p] = mark == "ok"
    return res


def check_containers(host: str, names: list[str]) -> dict[str, bool]:
    if not names:
        return {}
    quoted = " ".join(shlex.quote(n) for n in names)
    cmd = ("for n in " + quoted + "; do "
           "if podman inspect -f '{{.State.Running}}' \"$n\" 2>/dev/null | grep -q true; "
           "then echo \"ok $n\"; "
           "elif docker inspect -f '{{.State.Running}}' \"$n\" 2>/dev/null | grep -q true; "
           "then echo \"ok $n\"; else echo \"no $n\"; fi; done")
    out, _e, _rc = host_cmd(host, cmd)
    res = {}
    for line in out.splitlines():
        mark, _, n = line.partition(" ")
        res[n] = mark == "ok"
    return res


# -------------------------------------------------------- caddy parsing

def parse_caddyfile(text: str, site_hint: str = "?") -> list[dict]:
    """Extract reverse_proxy upstreams per vhost. Returns rows
    {vhost, line, upstream}. Handles nested handle/route blocks; site
    blocks are the depth-0 `address {` forms."""
    rows: list[dict] = []
    depth = 0
    site = site_hint
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        s = line.strip()
        if s:
            if depth == 0 and s.endswith("{"):
                site = s[:-1].strip() or site_hint
            if s.startswith("reverse_proxy") or s == "reverse_proxy":
                for ups in _reverse_proxy_upstreams(s):
                    rows.append({"vhost": site, "line": lineno, "upstream": ups})
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            depth = 0
            site = site_hint
    return rows


def _reverse_proxy_upstreams(line: str) -> list[str]:
    try:
        toks = shlex.split(line, comments=False)
    except ValueError:
        toks = line.split()
    toks = toks[1:]                       # drop 'reverse_proxy'
    ups = []
    for i, tok in enumerate(toks):
        if tok == "{":
            break
        if i == 0 and (tok.startswith("@") or tok == "*" or tok.startswith("/")):
            continue                      # matcher token, not an upstream
        ups.append(tok)
    return ups


def fetch_caddy(host: str, path: str, scope: str, depth: int = 0) -> list[dict]:
    """cat a Caddyfile on the host and expand `import` lines one level."""
    if depth > 3:
        return []
    remote = "$HOME" + path[1:] if path.startswith("~") else path
    out, _e, rc = host_cmd(host, f'cat "{remote}" 2>/dev/null')
    if rc != 0 or not out.strip():
        return []
    rows = parse_caddyfile(out, site_hint=Path(path).name)
    for m in re.finditer(r"^\s*import\s+(\S+)", out, re.M):
        imp = m.group(1)
        if "*" in imp:
            continue                    # glob imports — rare; skipped
        imp_path = imp if imp.startswith("/") else str(Path(path).parent / imp)
        rows.extend(fetch_caddy(host, imp_path, scope, depth + 1))
    return rows


def audit_caddy(host: str) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    notes: list[str] = []
    listeners, unix_socks, lerr = host_listeners(host)
    all_targets: list[dict] = []
    for path, scope in CADDY_CANDIDATES:
        for r in fetch_caddy(host, path, scope):
            r["caddyfile"] = path
            r["scope"] = scope
            all_targets.append(r)
    if not all_targets:
        return rows, notes
    cont_names = set()
    for r in all_targets:
        cls = classify_target(r["upstream"])
        r["cls"] = cls
        if cls["kind"] == "container":
            cont_names.add(cls["name"])
    container_ok = check_containers(host, sorted(cont_names))
    for r in all_targets:
        cls = r["cls"]
        if lerr and cls["kind"] in ("loopback", "unix"):
            status_s, ev = "skipped", f"listeners unavailable: {lerr}"
        else:
            status_s, ev = check_target(host, cls, listeners, unix_socks,
                                        {}, container_ok,
                                        loopback_scope=r["scope"])
        rows.append({"host": host, "surface": f"caddy:{r['vhost']}",
                     "mount": f"{r['caddyfile']}:{r['line']}",
                     "upstream": r["upstream"],
                     "status": status_s, "evidence": ev})
    return rows, notes


# ------------------------------------------------------------- audit

def audit_host(host: str) -> dict:
    result = {"host": host, "checked_at": now_iso(), "rows": [],
              "errors": [], "unreachable": False}
    ping_out, ping_err, ping_rc = host_cmd(host, "echo ok")
    if ping_rc != 0 or "ok" not in ping_out:
        result["unreachable"] = True
        result["errors"].append(
            f"unreachable via {'local' if host == local_hostname() else 'ssh'}: "
            f"{(ping_err or ping_out).strip()[:160]}")
        return result
    rows, serr = audit_serve(host)
    result["rows"].extend(rows)
    if serr and serr != "empty-serve":
        result["errors"].append(f"serve: {serr}")
    crows, cnotes = audit_caddy(host)
    result["rows"].extend(crows)
    result["errors"].extend(cnotes)
    return result


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def worst(statuses: list[str]) -> str:
    for s in ("dead", "degraded", "skipped"):
        if s in statuses:
            return s
    return "ok"


# ---------------------------------------------------------- reporting

def print_report(results: list[dict]) -> None:
    n_dead = n_deg = n_skip = n_ok = 0
    for r in results:
        statuses = [row["status"] for row in r["rows"]]
        n_dead += statuses.count("dead")
        n_deg += statuses.count("degraded")
        n_skip += statuses.count("skipped")
        n_ok += statuses.count("ok")
        tag = "FAIL" if r["unreachable"] or any(
            s in ("dead", "degraded") for s in statuses) else "ok"
        print(f"\n== {r['host']} — {tag} ==")
        for e in r["errors"]:
            print(f"   ! {e}")
        for row in r["rows"]:
            mark = {"ok": "✓", "dead": "✗", "degraded": "!", "skipped": "·"}[row["status"]]
            print(f"   {mark} {row['surface']} {row['mount']} -> "
                  f"{row['upstream']}  [{row['status']}] {row['evidence']}")
    print(f"\n{len(results)} hosts: {n_ok} ok, {n_deg} degraded, "
          f"{n_dead} dead, {n_skip} skipped")


def write_reports(results: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from lib.report import append_timeline, write_meta
    except Exception as e:
        print(f"meta emit skipped (lib.report unavailable): {e}")
        write_meta = append_timeline = None
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for r in results:
        statuses = [row["status"] for row in r["rows"]]
        bad = [row for row in r["rows"] if row["status"] in ("dead", "degraded")]
        if r["unreachable"]:
            status, summary = "unreachable", "unreachable — ssh failed"
        elif bad:
            status = "delta"
            summary = (f"{len(bad)} dead/degraded upstream(s): "
                       + "; ".join(f"{b['surface']}->{b['upstream']}" for b in bad[:5]))
        else:
            status, summary = "ok", f"{len(r['rows'])} upstreams clean"
        doc = {**r, "status": status, "summary": summary}
        art = out_dir / f"{r['host']}-{ts}.yml"
        art.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
        if write_meta:
            try:
                write_meta(
                    out_dir / f"meta.{r['host']}.yml",
                    node=f"edge-upstreams/{r['host']}",
                    layer="L1-producer",
                    purpose="Edge upstream audit — tailscale serve mounts + caddy reverse_proxy targets",
                    generated_by="scripts/audit-edge-upstreams.py",
                    status=status, summary=summary,
                    sources=[art.name],
                    extra={"counts": {s: statuses.count(s) for s in set(statuses)},
                           "errors": r["errors"]},
                )
                append_timeline(f"edge-upstreams/{r['host']}", "L1",
                                status, summary, ref=art)
            except Exception as e:
                print(f"meta/timeline emit failed for {r['host']}: {e}")
        print(f"wrote {art}")


# -------------------------------------------------------------- alerts

def _load_alert_state() -> dict:
    try:
        return json.loads(ALERT_STATE.read_text())
    except Exception:
        return {}


def _save_alert_state(st: dict) -> None:
    ALERT_STATE.parent.mkdir(parents=True, exist_ok=True)
    ALERT_STATE.write_text(json.dumps(st))


def alert(results: list[dict]) -> None:
    st = _load_alert_state()
    now = dt.datetime.now(dt.timezone.utc)
    for r in results:
        for row in r["rows"]:
            if row["status"] not in ("dead", "degraded"):
                continue
            key = f"{r['host']}|{row['surface']}|{row['upstream']}"
            last = st.get(key)
            if last:
                try:
                    if (now - dt.datetime.fromisoformat(last)).total_seconds() \
                            < REPEAT_H * 3600:
                        continue
                except ValueError:
                    pass
            text = (f"edge-upstream audit: {r['host']} {row['surface']} "
                    f"{row['mount']} -> {row['upstream']} is {row['status']} "
                    f"({row['evidence']}). Verify: "
                    "scripts/audit-edge-upstreams.py --host "
                    f"{r['host']} --json; fix the upstream or drop the "
                    "stale serve/caddy binding.")
            body = {"text": text,
                    "label": f"Dead edge upstream on {r['host']}",
                    "priority": "high",
                    "tags": ["ops", "edge", "dead-upstream"],
                    "owner": "tony"}
            try:
                req = urllib.request.Request(
                    f"{INBOX_API}/inbox", data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    ok = 200 <= resp.status < 300
            except Exception as e:
                sys.stderr.write(f"inbox post failed for {key}: {e}\n")
                ok = False
            if ok:
                st[key] = now.isoformat()


def ship(out_dir: Path, target: str) -> None:
    rc = subprocess.run(
        ["rsync", "-a", str(out_dir) + "/", target],
        capture_output=True, text=True, timeout=120).returncode
    if rc:
        print(f"ship to {target} failed rc={rc} (non-fatal)")


# ----------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Audit tailscale-serve + caddy reverse_proxy upstreams "
                    "across the fleet (dead-upstream tripwire).")
    ap.add_argument("--host", choices=list(HOSTS), action="append",
                    help="audit one host (repeatable)")
    ap.add_argument("--all", action="store_true",
                    help="audit the default fleet: " + ",".join(DEFAULT_FLEET))
    ap.add_argument("--json", action="store_true", help="print rows as JSON")
    ap.add_argument("--write", action="store_true",
                    help="write reports/edge-upstreams artifacts + metas")
    ap.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT)
    ap.add_argument("--alert", action="store_true",
                    help="file deduped board-api /inbox entries on failures")
    ap.add_argument("--ship", nargs="?", const=SHIP_DEFAULT, default=None,
                    metavar="USER@HOST:PATH",
                    help="rsync reports/edge-upstreams to the served checkout")
    args = ap.parse_args()

    hosts = args.host or (DEFAULT_FLEET if args.all else None)
    if not hosts:
        ap.error("give --host or --all")

    results = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(audit_host, hosts))

    if args.json:
        print(json.dumps({"generated": now_iso(), "hosts": results},
                         ensure_ascii=False, indent=2))
    else:
        print_report(results)

    if args.write:
        write_reports(results, args.output_dir)
    if args.ship:
        ship(args.output_dir, args.ship)
    if args.alert:
        alert(results)

    failing = any(
        r["unreachable"] or
        any(row["status"] in ("dead", "degraded") for row in r["rows"])
        for r in results)
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
