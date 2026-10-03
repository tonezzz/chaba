#!/usr/bin/env python3
"""Regenerate the per-host services CMS pages + services-by-host index.

Collects a fresh inventory (audit-hosts.py snapshots for linux hosts in
HOSTS, direct ssh probes for idc02/michael-ha, podman/docker ps for
containers) and rewrites the ada-cms-pages docs:

    services-tony-dell  services-tony-omen  services-idc01
    services-idc02      services-mn01       services-michael-ha
    services-by-host    (index, children = the six leaf pages)

Runs wherever ssh reachability is broadest — tony-dell reaches every
host except michael-ha; unreachable hosts render a stale-data note.

Usage:
    host-services-cms.py [--slug services-tony-dell | --all] [--dry-run]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "scripts" / "audit-hosts.py"
DUMPS = REPO / "reports" / "audit-hosts"
MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
ICT = timezone(timedelta(hours=7))
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]

# Hosts audit-hosts.py supports (linux) — fresh snapshot per run.
AUDIT_HOSTS = ["tony-dell", "tony-omen", "mn01", "idc01"]
# Probed directly (audit-hosts has no entry or ssh is one-way).
PROBE_HOSTS = ["idc02", "michael-ha"]

HOST_META = {
    "tony-dell":  {"role": "HA + apps workstation", "ts": "tony-dell.taila0626a.ts.net",
                   "ip": "100.68.142.13"},
    "tony-omen":  {"role": "dev / GPU desktop", "ts": "tony-omen.taila0626a.ts.net",
                   "ip": "100.75.102.88"},
    "idc01":      {"role": "public VPS · mddb leader · Ada", "ts": "idc01.taila0626a.ts.net",
                   "ip": "100.74.146.0", "public": "157.85.110.99"},
    "idc02":      {"role": "offload / lab VPS", "ts": "idc02.taila0626a.ts.net",
                   "ip": ""},
    "mn01":       {"role": "home node · XMEye VMS", "ts": "mn01.taila0626a.ts.net",
                   "ip": "100.106.196.22"},
    "michael-ha": {"role": "HAOS appliance", "ts": "michael-ha.taila0626a.ts.net",
                   "ip": "100.80.105.88"},
}
LEAF_SLUGS = [f"services-{h}" for h in HOST_META]
INDEX_SLUG = "services-by-host"

# Desktop/user-session noise — filtered from service lists.
NOISE = re.compile(
    r"^(dbus|dconf|pipewire|wireplumber|xdg|gpg|gnome|gsd|evolution|gvfs|"
    r"at-spi|colord|geoclue|obex|snap|tracker|app[-.]|plasma|xfce|kaccess|"
    r"kded|ksmserver|kwin|polkit|power-profiles|upower|udisks|rtkit|"
    r"bluetooth|ssh-agent|gcr|goa|flatpak|xsettings|xwayland|org\.|com\.|"
    r"pim|akonadi|baloo|kactivity|kde|kwallet|kglobalaccel|kscreen|"
    r"xsettingsd|indicator|nm-applet|pavucontrol|pulseaudio|speech|vte|"
    r"xkbcomp|xrandr|run-|init\.|ptyxis|libpod|podman-\d|rootless|"
    r"session-|user@\d|modprobe|systemd|dbus-)")
BUCKET_RULES = [
    ("HA / cameras / vision", re.compile(
        r"ha-|tony-ha|michael|camera|cam-|go2rtc|gev|gods-eye|vcast|vms|"
        r"yolo|xmeye|input-bridge|cctv|home-assistant|node-red|plug-watch", re.I)),
    ("AI / memory / assistants", re.compile(
        r"mddb|weaviate|ollama|gemini|jev|notebooklm|yomi|ada-|memory|"
        r"embed|openclaw|open-notebook|obsidian|doc-archive|google-home|"
        r"icloud|workflows|gpu-queue", re.I)),
    ("Web / apps / data", re.compile(
        r"web$|web\.|-api|api|rview|bserver|raceman|status-data|yt-|trade|"
        r"postgres|redis|secrets-console|dev-miniapp|dashboard|caddy|"
        r"dnsmasq|funnel|ghostroute|rika|sensor-reader|mcp-|playwright", re.I)),
    ("Cast / desktop", re.compile(
        r"cast|playlive|chrome|xvfb|websockify|mpris|blueman|barrier|"
        r"clip-sync|screen-timeout|audit-cast|filter-chain", re.I)),
]


def sh(cmd, timeout=90):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout, p.returncode
    except Exception:
        return "", 1


def ssh(host, remote, timeout=60):
    return sh(SSH + [host, remote], timeout)


def latest_dump(host):
    arts = sorted(DUMPS.glob(f"{host}-*.yml"),
                  key=lambda p: p.name, reverse=True)
    arts = [a for a in arts if not a.name.endswith(".meta.yml")]
    return arts[0] if arts else None


def collect_audit(host):
    """Fresh audit-hosts snapshot; returns parsed yaml dict."""
    out, rc = sh(["python3", str(AUDIT), "--host", host], timeout=180)
    art = latest_dump(host)
    if not art:
        return None
    import yaml
    try:
        d = yaml.safe_load(art.read_text()) or {}
    except Exception as e:
        print(f"warn: bad dump {art}: {e}", file=sys.stderr)
        return None
    d["_dump"] = str(art)
    return d


def containers(host):
    pod, _ = ssh(host, "podman ps --format '{{.Names}}' 2>/dev/null") if host != "tony-omen" \
        else (sh(["podman", "ps", "--format", "{{.Names}}"])[0], 0)
    doc_out, _ = ssh(host, "docker ps --format '{{.Names}}' 2>/dev/null") if host != "tony-omen" \
        else (sh(["docker", "ps", "--format", "{{.Names}}"])[0], 0)
    names = [n for n in (pod.splitlines() + doc_out.splitlines())
             if n.strip() and "cannot" not in n.lower()]
    return sorted(set(names))


def probe_host(host):
    """Manual inventory for hosts audit-hosts.py doesn't cover."""
    d = {"host": host, "unreachable": False}
    out, rc = ssh(host, "podman ps --format '{{.Names}}' 2>/dev/null; echo ';;'; "
                        "docker ps --format '{{.Names}}' 2>/dev/null; echo ';;'; "
                        "systemctl --user list-units --type=service --state=running "
                        "--no-legend 2>/dev/null | awk '{print $1}'; echo ';;'; "
                        "systemctl --user list-units --type=service --state=failed "
                        "--no-legend 2>/dev/null | awk '{print $1}'; echo ';;'; "
                        "uptime; echo ';;'; free -h | head -2; echo ';;'; df -h / | tail -1")
    if not out.strip():
        d["unreachable"] = True
        return d
    parts = out.split(";;")
    d["containers"] = sorted(set((parts[0] + parts[1]).split())) if len(parts) > 1 else []
    d["user_services"] = parts[2].split() if len(parts) > 2 else []
    d["failed_user"] = [f for f in (parts[3].split() if len(parts) > 3 else [])
                        if f not in ("●",) and f.endswith(".service")]
    d["uptime_raw"] = parts[4].strip() if len(parts) > 4 else ""
    d["mem_raw"] = parts[5].strip() if len(parts) > 5 else ""
    d["disk_raw"] = parts[6].strip() if len(parts) > 6 else ""
    return d


def clean_units(units):
    out = []
    for u in units:
        u = u if isinstance(u, str) else u.get("unit", "")
        if not u.endswith(".service") or NOISE.match(u.replace(".service", "")):
            continue
        out.append(u.replace(".service", ""))
    return sorted(set(out))


def bucketize(units):
    groups = {name: [] for name, _ in BUCKET_RULES}
    groups["Other / ops"] = []
    for u in units:
        for name, rx in BUCKET_RULES:
            if rx.search(u):
                groups[name].append(u)
                break
        else:
            groups["Other / ops"].append(u)
    return {k: v for k, v in groups.items() if v}


def load_str(load):
    if isinstance(load, dict):
        return f"{load.get('1m','?')}/{load.get('5m','?')}/{load.get('15m','?')}"
    m = re.search(r"load average[s]?: ([\d.]+), ([\d.]+), ([\d.]+)", load or "")
    return "/".join(m.groups()) if m else "?"


def disk_str(disk):
    if isinstance(disk, dict):
        return f"{disk.get('percent','?')}% ({disk.get('used','?')}/{disk.get('size','?')})"
    m = re.search(r"(\d+)%", disk or "")
    return f"{m.group(1)}%" if m else "?"


def mem_str(mem):
    if isinstance(mem, dict):
        return f"{mem.get('used','?')}/{mem.get('total','?')}"
    m = re.search(r"Mem:\s+(\S+)\s+(\S+)", mem or "")
    return f"{m.group(2)}/{m.group(1)}" if m else "?"


def uptime_str(d):
    up = d.get("uptime") or ""
    if isinstance(up, str) and up.strip():
        return up.strip()
    m = re.search(r"up\s+(.+?),\s+\d+ user", d.get("uptime_raw", ""))
    return m.group(1) if m else "?"


def page_for(host, d, now_07):
    meta = HOST_META[host]
    slug = f"services-{host}"
    title = f"Services — {host} ({meta['role']})"
    if d.get("unreachable"):
        status = (f"unreachable from the collector at {now_07:%Y-%m-%d %H:%M} +07 — "
                  "page shows last known layout; verify manually.")
        body = ""
    else:
        up = uptime_str(d)
        load = load_str(d.get("load") or d.get("uptime_raw", ""))
        disk = disk_str(d.get("disk") or d.get("disk_raw", ""))
        mem = mem_str(d.get("memory") or d.get("mem_raw", ""))
        failed = d.get("failed_user_services") or d.get("failed_user") or []
        failed = [f.replace(".service", "") for f in failed]
        failed_sys = [f.replace(".service", "") for f in
                      d.get("failed_system_services", [])]
        conts = d.get("containers") or containers(host)
        services = clean_units(d.get("active_user_services") or
                               d.get("user_services") or [])
        timers = [u["unit"] if isinstance(u, dict) else u
                  for u in d.get("active_user_services", []) if ".timer" in
                  str(u)]
        groups = bucketize(services)
        warn = " ⚠" if re.match(r"\d+", disk) and int(re.match(r"\d+", disk).group()) >= 85 else ""
        status = (f"up {up.strip()}, load {load}, mem {mem}, disk {disk}{warn}. "
                  f"{len(failed)} failed user units."
                  if failed else
                  f"up {up.strip()}, load {load}, mem {mem}, disk {disk}{warn}. "
                  "No failed units.")
        secs = []
        secs.append("## Resources\n\n"
                    f"- Uptime {up.strip()} · load {load} · mem {mem} · disk {disk}\n"
                    f"- Tailscale: `{meta['ts']}` ({meta['ip']})"
                    + (f" · public {meta['public']}" if meta.get("public") else ""))
        if conts:
            secs.append(f"## Containers ({len(conts)})\n\n" + ", ".join(conts))
        if groups:
            lines = []
            for name, units in groups.items():
                lines.append(f"- **{name}:** " + ", ".join(units))
            secs.append(f"## User services (running, {len(services)})\n\n"
                        + "\n".join(lines))
        if timers:
            t = [x.replace(".timer", "") for x in timers]
            secs.append(f"## Timers ({len(t)})\n\n" + ", ".join(sorted(t)))
        if failed or failed_sys:
            fl = []
            if failed:
                fl.append("- **User:** " + ", ".join(failed))
            if failed_sys:
                fl.append("- **System:** " + ", ".join(failed_sys))
            secs.append("## Failed units\n\n" + "\n".join(fl))
        else:
            secs.append("## Failed units\n\nNone.")
        body = "\n\n".join(secs)
    content = (f"# {title}\n\n**Status: {status}**\n\n"
               f"Parent index: [services-by-host](#/services-by-host)\n\n"
               f"## Latest\n\n- **{now_07:%Y-%m-%d}** — regenerated from live "
               f"inventory (`audit-hosts` + ssh/podman probes).\n\n{body}\n\n"
               f"*Generated by host-services-cms.py · "
               f"{now_07.isoformat(timespec='seconds')} · sources: audit-hosts "
               "dumps, systemctl, podman/docker ps, ssot.services.yml*")
    return slug, title, content


def index_page(datas, now_07):
    title = "Running services by host"
    rows = []
    watch = []
    for host, d in datas.items():
        meta = HOST_META[host]
        slug = f"services-{host}"
        if d.get("unreachable"):
            rows.append(f"| {host} | {meta['role']} | unreachable | — | — | — "
                        f"| [services-{host}](#/{slug}) |")
            watch.append(f"**{host} unreachable** from collector — page stale.")
            continue
        load = load_str(d.get("load") or d.get("uptime_raw", "")).split("/")[0]
        disk = disk_str(d.get("disk") or d.get("disk_raw", ""))
        conts = len(d.get("containers") or []) or "?"
        failed = len(d.get("failed_user_services") or d.get("failed_user") or [])
        rows.append(f"| {host} | {meta['role']} | {load} | {disk} | {conts} "
                    f"| {failed} | [{slug}](#/{slug}) |")
        pct = re.match(r"(\d+)%", disk)
        if pct and int(pct.group(1)) >= 85:
            watch.append(f"**{host} disk {disk}** — prune images/logs soon.")
        if failed:
            watch.append(f"**{host}: {failed} failed user units** — see "
                         f"[its page](#/{slug}).")
    wl = "\n".join(f"{i+1}. {w}" for i, w in enumerate(watch)) or "1. Nothing flagged."
    content = (f"# {title} — overview ({now_07:%Y-%m-%d %H:%M} +07)\n\n"
               f"**Status: {len(datas)} hosts checked — "
               f"{sum(1 for d in datas.values() if d.get('unreachable'))} unreachable.**\n\n"
               "## Latest\n\n"
               f"- **{now_07:%Y-%m-%d}** — regenerated from live inventory; "
               "per-host detail on the linked pages.\n\n"
               "## Host reports\n\n"
               "| host | role | load | disk | containers | failed | report |\n"
               "|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n\n"
               "## Watch list\n\n" + wl + "\n\n"
               "## History\n\n"
               "- [services-by-host-2026-09-30](#/services-by-host-2026-09-30) — "
               "previous dated snapshot\n\n"
               f"*Generated by host-services-cms.py · "
               f"{now_07.isoformat(timespec='seconds')} · sources: audit-hosts "
               "dumps, systemctl, podman/docker ps*")
    return INDEX_SLUG, title, content


def publish(slug, title, content, extra_meta, now):
    meta = {
        "attribute": ["page"], "bank": ["cms"], "domain": ["infra"],
        "format": ["markdown"], "instance": ["ada"], "kind": ["page"],
        "lang": ["en"], "scope": ["tony"], "slug": [slug], "source": ["api"],
        "status": ["active"], "subject": [slug], "title": [title],
        "updated": [now.isoformat(timespec="seconds")],
        "valid_from": [now.date().isoformat()],
        "last_verified": [now.date().isoformat()],
        "written_by": ["host-services-cms"],
        "generated_by": ["host-services-cms.py"],
        "sources": ["reports/audit-hosts", "systemctl --user list-units",
                    "podman/docker ps", "ssot.services.yml"],
    }
    meta.update(extra_meta)
    body = json.dumps({"collection": COLLECTION, "key": slug, "lang": "en",
                       "contentMd": content, "meta": meta}).encode()
    req = urllib.request.Request(f"{MDDB}/add", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", help="regenerate a single leaf page")
    ap.add_argument("--all", action="store_true",
                    help="regenerate all pages (default)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    targets = HOST_META.keys() if (args.all or not args.slug) else \
        [args.slug.replace("services-", "", 1)]

    now_utc = datetime.now(timezone.utc)
    now_07 = now_utc.astimezone(ICT)
    started = time.monotonic()
    datas = {}
    for host in HOST_META:
        if host not in targets:
            datas[host] = {"unreachable": False, "_skip": True}
            continue
        print(f"== {host}: collecting…", file=sys.stderr)
        if host in AUDIT_HOSTS:
            d = collect_audit(host) or {"unreachable": True}
            d["containers"] = containers(host) if not d.get("unreachable") else []
        else:
            d = probe_host(host)
        datas[host] = d

    pages = {}
    for host in targets:
        slug, title, content = page_for(host, datas[host], now_07)
        pages[slug] = (title, content)
    # Index is a rollup — only re-render it on a full (--all) run.
    if not args.slug:
        slug, title, content = index_page(datas, now_07)
        pages[INDEX_SLUG] = (title, content)

    for slug, (title, content) in pages.items():
        extra = {"report_role": ["index" if slug == INDEX_SLUG else "leaf"]}
        extra["children"] = LEAF_SLUGS if slug == INDEX_SLUG else []
        if slug != INDEX_SLUG:
            extra["parent"] = [INDEX_SLUG]
        if args.dry_run:
            print(f"--- {slug} ({len(content)} chars) ---\n{content}\n")
        else:
            try:
                code = publish(slug, title, content, extra, now_utc)
                print(f"{slug}: HTTP {code} ({len(content)} chars)")
            except Exception as e:
                print(f"{slug}: PUBLISH FAIL {e}", file=sys.stderr)
    print(f"done in {time.monotonic()-started:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
