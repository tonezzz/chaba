#!/usr/bin/env python3
"""Render ssot.jobs.yml -> systemd user units.

dispatch: systemd     -> generated/<host>/<id>.timer + <id>.service
dispatch: dispatcher  -> no per-job units; emits chaba-jobs.{timer,service}
                         on hosts that have >=1 dispatcher job

Usage:
  render-jobs.py [--host tony_dell]            # write generated/<host>/
  render-jobs.py --check                       # validate manifest only (CI)
  render-jobs.py --host idc02 --install        # install units + daemon-reload
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs/ssot/infrastructure/ssot.jobs.yml"

DUR_RE = re.compile(r"^(\d+)(min|s|m|h|d)?$")
UNIT_S = {"s": 1, "m": 60, "min": 60, "h": 3600, "d": 86400}


def dur_s(v) -> int:
    """'90'|90|'90s'|'15m'|'1min'|'2h'|'1d' -> seconds."""
    m = DUR_RE.match(str(v).strip())
    if not m:
        raise ValueError(f"bad duration: {v!r}")
    return int(m.group(1)) * UNIT_S.get(m.group(2) or "s", 1)


def systemd_dur(v) -> str:
    s = dur_s(v)
    return f"{s}s" if s < 60 else f"{s // 60}min" if s % 60 == 0 else f"{s}s"


def load_manifest():
    return yaml.safe_load(MANIFEST.read_text())


def validate(man):
    errs = []
    cfg = man.get("config", {})
    hosts = set(cfg.get("repo", {}))
    tick = dur_s(cfg.get("dispatcher_min_interval", "60s"))
    for j in man.get("jobs", []):
        jid = j.get("id", "?")
        for f in ("id", "name", "host", "dispatch", "exec"):
            if f not in j:
                errs.append(f"{jid}: missing {f}")
        if j.get("host") not in hosts:
            errs.append(f"{jid}: host {j.get('host')!r} not in config.repo")
        if j.get("dispatch") not in ("systemd", "dispatcher"):
            errs.append(f"{jid}: dispatch must be systemd|dispatcher")
        if j.get("dispatch") == "dispatcher":
            if "every" not in j:
                errs.append(f"{jid}: dispatcher jobs need every: (no on_calendar)")
            elif dur_s(j["every"]) < tick:
                errs.append(
                    f"{jid}: every={j['every']} < dispatcher tick {tick}s — use dispatch: systemd"
                )
        if j.get("dispatch") == "systemd" and "on_calendar" not in j and "every" not in j:
            errs.append(f"{jid}: systemd jobs need on_calendar: or every:")
    return errs


def esc(v: str) -> str:
    # Escape only bare '%' — keep real systemd specifiers (%h, %u, ...) intact.
    return re.sub(r"%(?![a-zA-Z])", "%%", v)


def render_service(j, man):
    cfg = man["config"]
    lines = [
        "[Unit]",
        f"Description={j['name']} (job:{j['id']}, rendered from ssot.jobs.yml — do not edit)",
        "",
        "[Service]",
        "Type=oneshot",
        f"TimeoutStartSec={dur_s(j.get('timeout', '5m'))}",
        f"ExecStart={esc(j['exec'])}",
    ]
    cwd = j.get("cwd")
    if cwd:
        lines.append(f"WorkingDirectory={cwd}")
    for k, v in (j.get("env") or {}).items():
        lines.append(f'Environment="{k}={v}"')
    return "\n".join(lines) + "\n"


def render_timer(j):
    lines = [
        "[Unit]",
        f"Description={j['name']} (job:{j['id']}, rendered from ssot.jobs.yml — do not edit)",
        "",
        "[Timer]",
    ]
    if "on_calendar" in j:
        lines.append(f"OnCalendar={j['on_calendar']}")
    else:
        lines += ["OnBootSec=1min", f"OnUnitActiveSec={systemd_dur(j['every'])}"]
    if j.get("persistent"):
        lines.append("Persistent=true")
    lines += ["", "[Install]", "WantedBy=timers.target"]
    return "\n".join(lines) + "\n"


def render_dispatcher_units(host, man):
    repo = man["config"]["repo"][host]
    tick = systemd_dur(man["config"].get("dispatcher_tick", "1min"))
    svc = (
        "[Unit]\n"
        "Description=Chaba job dispatcher (runs dispatch:dispatcher jobs from ssot.jobs.yml)\n\n"
        "[Service]\nType=oneshot\nTimeoutStartSec=55\n"
        f"ExecStart=/usr/bin/python3 {repo}/scripts/job-dispatcher.py --host {host}\n"
    )
    tim = (
        "[Unit]\n"
        "Description=Chaba job dispatcher tick\n\n"
        "[Timer]\nOnBootSec=1min\n"
        f"OnUnitActiveSec={tick}\nPersistent=true\n\n"
        "[Install]\nWantedBy=timers.target\n"
    )
    return {"chaba-jobs.service": svc, "chaba-jobs.timer": tim}


def render_host(man, host):
    out = {}
    for j in man["jobs"]:
        if j["host"] != host or not j.get("enabled", True):
            continue
        if j["dispatch"] == "systemd":
            out[f"{j['id']}.service"] = render_service(j, man)
            out[f"{j['id']}.timer"] = render_timer(j)
    if any(
        j["host"] == host and j["dispatch"] == "dispatcher" and j.get("enabled", True)
        for j in man["jobs"]
    ):
        out.update(render_dispatcher_units(host, man))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--manifest", default=str(MANIFEST))
    args = ap.parse_args()

    man = load_manifest()
    errs = validate(man)
    if errs:
        for e in errs:
            print(f"ERR {e}")
        return 2
    if args.check:
        print(f"OK {len(man['jobs'])} jobs, {len(man['config']['repo'])} hosts")
        return 0

    hosts = [args.host] if args.host else list(man["config"]["repo"])
    rc = 0
    for host in hosts:
        units = render_host(man, host)
        if not units:
            continue
        dest = (
            Path.home() / ".config/systemd/user"
            if args.install
            else REPO / man["config"]["generated_dir"] / host
        )
        dest.mkdir(parents=True, exist_ok=True)
        for name, body in units.items():
            p = dest / name
            if p.exists() and p.read_text() == body:
                continue
            p.write_text(body)
            print(f"wrote {p}")
        if args.install:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
            timers = [n[:-6] for n in units if n.endswith(".timer")]
            if timers:
                r = subprocess.run(
                    ["systemctl", "--user", "enable", "--now", *timers]
                )
                rc = rc or r.returncode
            print(json.dumps({"host": host, "units": sorted(units), "timers": timers}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
