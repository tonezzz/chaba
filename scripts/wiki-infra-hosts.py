#!/usr/bin/env python3
"""wiki-infra-hosts.py — MediaWiki Infrastructure:Hosts rollup + leaf pages.

Canonical hierarchy (card mediawiki-infrastructure-host-hierarchy / SYS-1034):

    Infrastructure:Hosts            rollup — one row per declared host
    Infrastructure:Hosts/<host>     leaf   — one per host in the registry

Host registry is docs/ssot/infrastructure/ssot.audit.hosts.yml `hosts:` —
the same placement contract audit-hosts.py and host-loads/disk-trend-watch
already consume. No hardcoded host list: idc01 renders as `retired`,
idc03/con01/kk-mac/macbook/michael-ha are covered like every other entry,
and hosts the audit layer cannot probe still get a leaf built from
host-loads + disk-trend + SSOT last_observed.

Data sources (all read-only, all degrade gracefully when absent):

    ssot.audit.hosts.yml     declared hosts, roles, expected services,
                             retired/offline_ok, expected_resources
    reports/audit-hosts/     latest <host>-*.yml snapshot + meta.<host>.yml
                             (services, deltas, load/mem/disk — L0/L1)
    reports/host-loads/      host-loads.yml fresh 5-min load/mem/disk
    reports/disk-trend/      disk-trend.yml growth/forecast per mount
    ada-cms-pages            timer-timeline / timer-timeline-<host> CMS
                             docs (MDDB /get, optional — skipped offline)
    ssot.reports.yml         node registry -> related report links
    host-services-cms.py     services-by-host / services-<host> CMS
                             compatibility links (imported, not copied)

Privacy model (ssot.mediawiki-news.yml + Lockdown verified 2026-11-06):
Infrastructure: is a protected namespace — full pages may only publish
through board-api /wiki/page after the anonymous-deny probe passes (or
--private-ok asserts a prior verification). --surface public renders a
sanitized fleet-status derivative — host/status/freshness only, no ports,
routes, service names, or topology — and is file-only; the /wiki/page
door refuses non-allowlisted namespaces anyway.

Usage:
    wiki-infra-hosts.py                    # dry-run: render + checks, no writes
    wiki-infra-hosts.py --check            # checks only, non-zero on failure
    wiki-infra-hosts.py --apply            # publish private pages via /wiki/page
    wiki-infra-hosts.py --apply --private-ok   # skip the anon-deny probe
    wiki-infra-hosts.py --surface public --out-dir /tmp/wiki-pub
    wiki-infra-hosts.py --host idc03       # single leaf (+rollup in dry-run)
"""

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SSOT_HOSTS = REPO / "docs/ssot/infrastructure/ssot.audit.hosts.yml"
SSOT_REPORTS = REPO / "docs/ssot/infrastructure/ssot.reports.yml"
AUDIT_DIR = REPO / "reports/audit-hosts"
LOADS_YML = REPO / "reports/host-loads/host-loads.yml"
DISK_YML = REPO / "reports/disk-trend/disk-trend.yml"
HSC_PATH = REPO / "scripts/ada/host-services-cms.py"

MDDB = os.environ.get("MDDB_BASE_URL",
                      "http://100.102.134.91:11027/v1").rstrip("/")
CMS_COLLECTION = "ada-cms-pages"
ICT = timezone(timedelta(hours=7))
GENERATOR = "scripts/wiki-infra-hosts.py"
ROLLUP_TITLE = "Infrastructure:Hosts"
LEAF_PREFIX = "Infrastructure:Hosts/"

# Public derivative scrub rules — a hit means the page leaked something the
# public surface must never carry (ports, routes, service names, topology).
PUBLIC_FORBIDDEN = [
    (re.compile(r":\d{2,5}\b"), "port"),  # applied after time masking
    (re.compile(r"\b(?:https?|ssh|tailscale|100\.\d{1,3}\.\d{1,3}\.\d{1,3})",
                re.I), "route/address"),
    (re.compile(r"\.(?:service|timer|scope|socket)\b"), "unit name"),
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "ip"),
]

STATUS_ENUM = ("active", "degraded", "unreachable", "retired")


def _load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _post_json(url: str, payload: dict, timeout: int = 20):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------------------------------------------------------------- registry

def load_registry() -> dict:
    """Ordered {host: ssot entry} — the declared fleet, retired included."""
    doc = _load_yaml(SSOT_HOSTS)
    return {k: v for k, v in (doc.get("hosts") or {}).items()
            if isinstance(v, dict)}


def load_reports_nodes() -> dict:
    """ssot.reports.yml nodes -> per-host related report node ids."""
    doc = _load_yaml(SSOT_REPORTS)
    out = {}
    for node in doc.get("nodes") or []:
        nid = str(node.get("id") or "")
        for host in load_registry():
            variants = {host, host.replace("-", "_"),
                        host.replace("_", "-")}
            if any(nid == f"{p}/{v}" for p in
                   ("audit-hosts", "edge-upstreams", "mcp-inventory")
                   for v in variants):
                out.setdefault(host, []).append(nid)
    return out


def services_cms_hosts() -> set:
    """Hosts covered by the services-by-host / services-<host> CMS pages —
    imported from host-services-cms.py so the compatibility map can't drift."""
    try:
        spec = importlib.util.spec_from_file_location(
            "host_services_cms", HSC_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return set(mod.HOST_META)
    except Exception as e:
        print(f"warn: host-services-cms import failed ({e}) — "
              "compat links degraded", file=sys.stderr)
        return set()


_FAILED_NOISE = None


def _failed_noise_re():
    """audit-hosts.py FAILED_NOISE — generic desktop flakiness that is
    never a fleet signal; filtered out of leaf failed-unit lists."""
    global _FAILED_NOISE
    if _FAILED_NOISE is None:
        try:
            spec = importlib.util.spec_from_file_location(
                "audit_hosts", REPO / "scripts/audit-hosts.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _FAILED_NOISE = mod.FAILED_NOISE
        except Exception:
            _FAILED_NOISE = re.compile(r"(?!x)x")  # match nothing
    return _FAILED_NOISE


# ------------------------------------------------------------------ sources

def latest_audit(host: str):
    arts = sorted(AUDIT_DIR.glob(f"{host}-*.yml"),
                  key=lambda p: p.name, reverse=True)
    arts = [a for a in arts if not a.name.startswith("meta.")]
    if not arts:
        return None, None
    dump = _load_yaml(arts[0])
    meta = _load_yaml(AUDIT_DIR / f"meta.{host}.yml")
    return dump, meta


def load_host_loads() -> dict:
    doc = _load_yaml(LOADS_YML)
    return {r.get("host"): r for r in doc.get("hosts") or []
            if isinstance(r, dict)}


def load_disk_trend() -> dict:
    doc = _load_yaml(DISK_YML)
    return {h.get("host"): h for h in doc.get("hosts") or []
            if isinstance(h, dict)}


def timer_timeline_doc(host: str, timeout: int = 8):
    """Best-effort MDDB read of the timer-timeline-<host> CMS leaf.
    Returns {updated, timers, reachable} — never raises."""
    try:
        doc = _post_json(f"{MDDB}/get",
                         {"collection": CMS_COLLECTION,
                          "key": f"timer-timeline-{host}", "lang": "en"},
                         timeout=timeout)
    except Exception:
        return {"reachable": False}
    if not isinstance(doc, dict) or not doc.get("key"):
        return {"reachable": False}
    meta = doc.get("meta") or {}
    body = doc.get("contentMd") or doc.get("content") or ""
    timers = len(re.findall(r"^\| `[^`]+` \|", body, flags=re.M))
    upd = meta.get("updated") or meta.get("last_verified") or []
    return {"reachable": True,
            "updated": upd[0] if isinstance(upd, list) and upd else upd,
            "timers": timers}


# ------------------------------------------------------------------ gather

def gather(host: str, registry: dict, loads: dict, disks: dict,
           nodes: dict, want_timers: bool) -> dict:
    ent = registry[host]
    dump, meta = latest_audit(host)
    row = loads.get(host) or {}
    disk = disks.get(host) or {}
    tt = timer_timeline_doc(host) if want_timers else {"reachable": False}

    deltas = []
    if dump:
        deltas = list(dump.get("deltas") or [])
    elif meta:
        deltas = list((meta.get("extra") or {}).get("deltas") or [])

    failed = []
    if dump:
        known = {str(f.get("name", "")) if isinstance(f, dict) else str(f)
                 for f in ent.get("known_failed") or []}
        noise = _failed_noise_re()
        for f in (dump.get("failed_user_services") or []) + \
                (dump.get("failed_system_services") or []):
            name = str(f)
            base = name[:-8] if name.endswith(".service") else name
            if base in known or name in known or \
                    noise.match(base) or base.startswith("session-"):
                continue
            failed.append(name)

    obs = ent.get("last_observed") or {}
    d = {
        "host": host,
        "entry": ent,
        "retired": bool(ent.get("retired")),
        "offline_ok": bool(ent.get("offline_ok")),
        "role": ent.get("role") or "-",
        "description": ent.get("description") or "",
        "tailscale_ip": ent.get("tailscale_ip") or
                        dump.get("tailscale_ip") or
                        (obs.get("tailscale_ip") if isinstance(obs, dict) else None),
        "expected_services": ent.get("expected_services") or [],
        "expected_absent": ent.get("expected_absent") or [],
        "known_failed": ent.get("known_failed") or [],
        "allowed_running": ent.get("allowed_running") or [],
        "expected_resources": ent.get("expected_resources") or {},
        "audit": dump,
        "audit_meta": meta,
        "audit_path": None,
        "load_row": row,
        "disk_trend": disk,
        "timer_timeline": tt,
        "deltas": deltas,
        "failed_units": failed,
        "obs": obs if isinstance(obs, dict) else {},
        "nodes": nodes.get(host, []),
    }
    arts = sorted(AUDIT_DIR.glob(f"{host}-*.yml"),
                  key=lambda p: p.name, reverse=True)
    arts = [a for a in arts if not a.name.startswith("meta.")]
    if arts:
        d["audit_path"] = str(arts[0].relative_to(REPO))
    return d


def _parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def last_verified(d: dict):
    """Freshest observed timestamp across the sources we consumed."""
    cands = []
    if d["audit"]:
        cands.append(_parse_ts(d["audit"].get("timestamp")))
    if d["audit_meta"]:
        cands.append(_parse_ts(d["audit_meta"].get("generated_at")))
    if d["load_row"].get("ts"):
        cands.append(_parse_ts(d["load_row"]["ts"]))
    if d.get("obs", {}).get("observed_at"):
        cands.append(_parse_ts(d["obs"]["observed_at"]))
    if d.get("timer_timeline", {}).get("updated"):
        cands.append(_parse_ts(d["timer_timeline"]["updated"]))
    cands += [t for t in cands if t]
    if d.get("_dt_gen"):
        cands.append(d["_dt_gen"])
    return max(cands) if cands else None


def disk_trend_generated() -> datetime:
    doc = _load_yaml(DISK_YML)
    return _parse_ts(doc.get("generated_at"))


def _unreachable(d: dict) -> bool:
    if d["retired"]:
        return False
    if d["audit"] and d["audit"].get("unreachable"):
        return True
    if d["audit_meta"] and d["audit_meta"].get("status") == "unreachable":
        return True
    if d["load_row"] and d["load_row"].get("unreachable"):
        return True
    if d["disk_trend"] and d["disk_trend"].get("unreachable"):
        return True
    return False


def _has_signal(d: dict) -> bool:
    return bool(d["audit"] or d["load_row"] or d["obs"])


def status_for(d: dict, dt_gen: datetime = None) -> str:
    if d["retired"]:
        return "retired"
    if _unreachable(d):
        return "unreachable"
    if d["deltas"] or d["failed_units"]:
        return "degraded"
    for m in (d["disk_trend"].get("mounts") or []):
        if m.get("alert") in ("warn", "fill", "critical"):
            return "degraded"
    # No live signal at all (laptop asleep, probe-less host, or the report
    # layer never ran here) is not 'active' — we simply could not verify.
    if not _has_signal(d):
        return "unreachable"
    return "active"


def key_warning(d: dict) -> str:
    bits = []
    if d["retired"]:
        return "retired — out of the placement contract"
    if d["deltas"]:
        bits.append(f"{len(d['deltas'])} audit delta(s)")
    if d["failed_units"]:
        bits.append(f"{len(d['failed_units'])} failed unit(s)")
    for m in (d["disk_trend"].get("mounts") or []):
        if m.get("alert") in ("fill", "critical"):
            bits.append(f"disk {m.get('mount')} fills "
                        f"({m.get('days_to_full')}d)")
        elif m.get("alert") == "warn":
            bits.append(f"disk {m.get('mount')} over limit")
    if _unreachable(d):
        bits.append("unreachable" + (" (offline_ok)" if d["offline_ok"]
                                     else ""))
    elif not _has_signal(d):
        bits.append("no live data this run")
    return "; ".join(bits) if bits else "—"


# ------------------------------------------------------------------ render

def _meta_table(pairs):
    rows = "\n".join(f"| {k} || {v}" for k, v in pairs)
    return ("{| class=\"wikitable\" style=\"font-size:90%\"\n"
            "! field !! value\n|-\n" + rows + "\n|}")


def _svc_name(u):
    u = u if isinstance(u, str) else str(u)
    return u[:-8] if u.endswith(".service") else u


def leaf_wikitext(d: dict, now: datetime, cms_hosts: set,
                  surface: str = "private") -> str:
    host = d["host"]
    st = status_for(d)
    lv = last_verified(d)
    lv_s = lv.astimezone(ICT).strftime("%Y-%m-%d %H:%M %Z") if lv else "unknown"
    warn = key_warning(d)

    pairs = [
        ("report_role", "leaf"),
        ("parent", ROLLUP_TITLE),
        ("status", st),
        ("role", d["role"]),
        ("last_verified", lv_s),
        ("generated_by", GENERATOR),
        ("sources", "ssot.audit.hosts.yml; reports/audit-hosts; "
                    "reports/host-loads; reports/disk-trend; "
                    "ada-cms-pages/timer-timeline"),
    ]
    if d["offline_ok"]:
        pairs.insert(4, ("offline_ok", "true — sleeps/off-net is normal"))
    if surface == "public":
        pairs = [(k, v) for k, v in pairs
                 if k not in ("role", "sources")] + \
                [("surface", "public-sanitized")]

    L = [f"# Infrastructure host — {host}\n",
         _meta_table(pairs), ""]

    # Quick summary
    exp_n = len(d["expected_services"])
    L.append("== Quick summary ==\n")
    if d["retired"]:
        L.append(f"**{host}** is retired — out of the placement contract "
                 f"(ssot.audit.hosts.yml `retired: true`). No services are "
                 f"expected; kept here so rollups and history stay whole.\n")
    else:
        L.append(f"**{host}** — {d['role']}. Status **{st}**; "
                 f"last verified {lv_s}. "
                 f"{exp_n} expected service(s) declared; "
                 f"{len(d['deltas'])} audit delta(s); "
                 f"key warning: {warn}.\n")

    if d["description"] and surface == "private":
        L.append(f"> {d['description']}\n")

    # Services
    L.append("== Services ==\n")
    if d["retired"]:
        L.append("Retired — `expected_services` is empty by contract.\n")
    elif not (d["expected_services"] or d["audit"]):
        L.append("No audit coverage and no declared services — leaf is "
                 "registry + reachability only.\n")
    else:
        svc_exp, timers_exp = [], 0
        for e in d["expected_services"]:
            name = str(e.get("name", ""))
            if name.endswith(".timer"):
                timers_exp += 1
            elif name.endswith(".service"):
                svc_exp.append(_svc_name(name))
        if surface == "private":
            shown = svc_exp[:40]
            L.append(f"- Expected services declared: **{len(svc_exp)}** "
                     f"(+{timers_exp} timers)\n")
            if shown:
                L.append("- Declared: " + ", ".join(f"`{n}`" for n in shown)
                         + (f" … +{len(svc_exp)-len(shown)} more"
                            if len(svc_exp) > len(shown) else "") + "\n")
        else:
            L.append(f"- Expected services declared: **{len(svc_exp)}** "
                     f"(+{timers_exp} timers — names withheld on the public "
                     "surface)\n")
        if d["audit"]:
            au = d["audit"]
            if au.get("unreachable"):
                L.append("- Audit snapshot: **unreachable** at collection "
                         "time\n")
            else:
                act = [s for s in au.get("active_user_services") or []
                       if isinstance(s, dict) and s.get("state") == "active"]
                n_timer = sum(1 for s in act
                              if str(s.get("unit", "")).endswith(".timer"))
                n_svc = len(act) - n_timer
                L.append(f"- Observed active user units: **{n_svc}** "
                         f"services + {n_timer} timers\n")
        tt = d["timer_timeline"]
        if tt.get("reachable"):
            L.append(f"- Timer timeline (CMS `timer-timeline-{host}`): "
                     f"{tt.get('timers', '?')} timers observed, page "
                     f"updated {tt.get('updated') or '?'}\n")
        elif surface == "private":
            L.append("- Timer timeline: CMS doc unreachable this run\n")
        if d["failed_units"] and surface == "private":
            L.append("- Failed units: " + ", ".join(
                f"`{_svc_name(f)}`" for f in d["failed_units"][:20]) + "\n")

    # Capacity / load / disk
    L.append("== Capacity / load / disk ==\n")
    if d["retired"]:
        L.append("n/a — retired\n")
    else:
        au = d["audit"] or {}
        lr = d["load_row"] or {}
        mem = au.get("memory") or {}
        disk_a = au.get("disk") or {}
        load = au.get("load") or lr.get("load") or {}
        up = au.get("uptime") or ""
        if surface == "private":
            bits = []
            if up:
                bits.append(f"uptime `{up}`")
            if load:
                bits.append("load " + "/".join(
                    str(load.get(k, "?")) for k in ("1m", "5m", "15m")))
            if mem:
                bits.append(f"mem {mem.get('used','?')}/"
                            f"{mem.get('total','?')} "
                            f"(avail {mem.get('available','?')})")
            elif lr.get("mem_total_mb"):
                bits.append(f"mem {lr.get('mem_used_mb','?')}MiB/"
                            f"{lr['mem_total_mb']}MiB used")
            if disk_a:
                bits.append(f"disk / {disk_a.get('percent','?')}% "
                            f"({disk_a.get('used','?')}/"
                            f"{disk_a.get('size','?')})")
            elif lr.get("disk_pct") is not None:
                bits.append(f"disk / {lr['disk_pct']}%")
            L.append(("- " + " · ".join(bits) + "\n") if bits
                     else "- no capacity data this run\n")
            max_root = (d["expected_resources"] or {}).get(
                "max_root_disk_percent")
            if max_root:
                L.append(f"- Declared `/` ceiling: {max_root}% "
                         "(ssot.audit.hosts.yml expected_resources)\n")
            for m in (d["disk_trend"].get("mounts") or []):
                if m.get("mount") != "/":
                    continue
                rate = (f"{m['growth_gib_day']:+.2f} GiB/d"
                        if m.get("growth_gib_day") is not None else "n/a")
                fill = (f"full in {m['days_to_full']:.1f}d"
                        if m.get("days_to_full") is not None else "-")
                L.append(f"- Disk trend: {m.get('pct','?')}%, {rate}, {fill}"
                         + (f" — alert `{m['alert']}`"
                            if m.get("alert") != "ok" else "") + "\n")
        else:
            L.append("- capacity detail withheld on the public surface "
                     "(see the private leaf)\n")

    # Expected-service delta
    L.append("== Expected-service delta ==\n")
    if d["retired"]:
        L.append("n/a — retired\n")
    elif not d["deltas"]:
        L.append("No deltas — observed matches the SSOT placement "
                 "contract (or no audit ran this cycle).\n")
    else:
        L.append(f"**{len(d['deltas'])} delta(s)** vs "
                 "ssot.audit.hosts.yml:\n")
        for x in d["deltas"][:15]:
            L.append(f"- {x}\n")
        if len(d["deltas"]) > 15:
            L.append(f"- … +{len(d['deltas'])-15} more\n")

    # Sources & generators
    L.append("== Sources & generators ==\n")
    srcs = []
    if d["audit_path"]:
        srcs.append(f"`{d['audit_path']}` (scripts/audit-hosts.py)")
    if d["audit_meta"]:
        srcs.append("`reports/audit-hosts/meta.%s.yml`" % host)
    srcs.append("`reports/host-loads/host-loads.yml` (scripts/host-loads.py)")
    srcs.append("`reports/disk-trend/disk-trend.yml` "
                "(scripts/ada/disk-trend-watch.py)")
    srcs.append(f"CMS `timer-timeline-{host}` "
                "(scripts/ada/timer-timeline-update.py)")
    srcs.append("`docs/ssot/infrastructure/ssot.audit.hosts.yml`")
    srcs.append(f"`docs/ssot/infrastructure/ssot.reports.yml`")
    L.append("\n".join(f"- {s}" for s in srcs) + "\n")

    # Related reports
    L.append("== Related reports ==\n")
    rel = []
    for nid in d["nodes"]:
        rel.append(f"- report node `{nid}`")
    rel.append("- report node `host-loads`, `disk-trend`, `fleet`, "
               "`system-report`")
    rel.append("- CMS pages: `services-by-host`, "
               f"`timer-timeline-{host}`")
    if surface == "private":
        rel.append("- wiki rollup: [[Infrastructure:Hosts]]")
    L += rel
    L.append("")

    # Compatibility links — services-by-host / services-<host> CMS pages.
    L.append("== Compatibility ==\n")
    if host in cms_hosts:
        L.append(f"- CMS index `services-by-host` and leaf "
                 f"`services-{host}` (ada-cms-pages, generated by "
                 "scripts/ada/host-services-cms.py) cover the same host — "
                 "this wiki leaf is the canonical Infrastructure: view; "
                 "the CMS pages remain the services-inventory surface.\n")
    else:
        L.append("- no `services-%s` CMS page — host joined the registry "
                 "after host-services-cms coverage; wiki leaf is the only "
                 "Infrastructure: page.\n" % host)
    L.append(f"*Generated {now.astimezone(ICT).isoformat(timespec='seconds')} "
             f"by {GENERATOR} — private Infrastructure: page; do not "
             "copy to public surfaces.*\n")
    return "\n".join(L)


def rollup_wikitext(datas: dict, now: datetime, cms_hosts: set,
                    surface: str = "private") -> str:
    rows = []
    watch = []
    counts = {s: 0 for s in STATUS_ENUM}
    for host in datas:
        d = datas[host]
        st = status_for(d)
        counts[st] += 1
        lv = last_verified(d)
        lv_s = (lv.astimezone(ICT).strftime("%m-%d %H:%M")
                if lv else "never")
        warn = key_warning(d)
        if surface == "public":
            role_cell = "fleet node" if st != "retired" else "retired"
            warn_cell = ("degraded" if st == "degraded" else
                         "unreachable" if st == "unreachable" else "—")
        else:
            role_cell = d["role"]
            warn_cell = warn
        link = (f"[[{LEAF_PREFIX}{host}|{host}]]"
                if surface == "private" else host)
        rows.append(f"| {host} || {st} || {lv_s} || {role_cell} "
                    f"|| {warn_cell} || {link} |")
        if st in ("degraded", "unreachable") and st != "retired":
            watch.append(f"**{host}** — {st}: {warn}")

    children = "\n".join(
        f"* [[{LEAF_PREFIX}{h}|{h}]]" if surface == "private"
        else f"* {h}" for h in datas)
    pairs = [
        ("report_role", "rollup"),
        ("parent", "Infrastructure"),
        ("children", str(len(datas)) + " leaves — see below"),
        ("status", ", ".join(f"{k}={counts[k]}" for k in STATUS_ENUM)),
        ("last_verified", now.astimezone(ICT)
         .strftime("%Y-%m-%d %H:%M %Z")),
        ("generated_by", GENERATOR),
        ("sources", "ssot.audit.hosts.yml; reports/audit-hosts; "
                    "reports/host-loads; reports/disk-trend; "
                    "ada-cms-pages/timer-timeline; ssot.reports.yml"),
    ]
    if surface == "public":
        pairs = [(k, v) for k, v in pairs if k != "sources"] + \
                [("surface", "public-sanitized")]

    L = ["# Infrastructure — Hosts\n",
         _meta_table(pairs), "",
         f"Fleet rollup generated {now.astimezone(ICT):%Y-%m-%d %H:%M %Z} "
         f"— {sum(counts.values())} declared hosts: "
         + ", ".join(f"{k} {counts[k]}" for k in STATUS_ENUM) + ".\n",
         "== Hosts ==\n",
         "{| class=\"wikitable\"\n"
         "! host !! status !! freshness !! role !! key warning !! report\n|-",
         "\n".join(rows),
         "|}\n",
         "== Children ==\n", children, ""]
    if watch:
        L.append("== Watch list ==\n")
        L += [f"{i+1}. {w}" for i, w in enumerate(watch)]
        L.append("")
    L.append("== Compatibility ==\n")
    L.append("- CMS index `services-by-host` + `services-<host>` leaves "
             "(ada-cms-pages, scripts/ada/host-services-cms.py) remain the "
             "services-inventory surface; this tree is the canonical "
             "Infrastructure: host registry view.\n")
    if surface == "private":
        L.append("- Report graph: `fleet` L2 node in ssot.reports.yml; "
                 "wiki reports under Reports: where published.\n")
    L.append(f"*Generated {now.astimezone(ICT).isoformat(timespec='seconds')} "
             f"by {GENERATOR}.*\n")
    return "\n".join(L)


# ------------------------------------------------------------------ checks

def public_scrub(text: str) -> list:
    """Return list of (pattern-name, match) privacy violations.
    style="..." attributes are stripped first — `font-size:90%` is not a
    port."""
    text = re.sub(r'style="[^"]*"', "", text)
    # mask timestamps/clock times so `19:16` isn't read as a port
    text = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?"
                  r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})?", " ", text)
    text = re.sub(r"\b\d{1,2}:\d{2}(:\d{2})?\b", " ", text)
    bad = []
    for rx, name in PUBLIC_FORBIDDEN:
        m = rx.search(text)
        if m:
            bad.append((name, m.group(0)))
    return bad


def run_checks(pages: dict, datas: dict, registry: dict,
               cms_hosts: set, surface: str, full: bool = True) -> list:
    """pages: {title: wikitext}. Returns list of failure strings.
    full=False (single --host) skips registry-wide missing/orphan checks."""
    fails = []
    leaf_titles = {f"{LEAF_PREFIX}{h}" for h in datas}
    rollup_title = ROLLUP_TITLE

    if full:
        # missing-host: every declared host has a leaf + rollup row
        for h in registry:
            t = f"{LEAF_PREFIX}{h}"
            if t not in pages:
                fails.append(f"missing leaf page for declared host {h}")
        # orphan: no page for an undeclared host; rollup children == leaf set
        for t in pages:
            if t.startswith(LEAF_PREFIX) and t not in leaf_titles:
                fails.append(f"orphan leaf {t} — host not in registry")
        rb = pages.get(rollup_title, "")
        for t in leaf_titles:
            # public surface links hosts by name, not leaf title
            token = t if surface == "private" else t.rsplit("/", 1)[-1]
            if token not in rb:
                fails.append(f"rollup missing row/link for {t}")
    # required leaf fields
    required = ["report_role", "leaf", "parent", ROLLUP_TITLE,
                "status", "last_verified", "Services",
                "Capacity / load / disk", "Expected-service delta",
                "Sources & generators", "Related reports"]
    for h, text in ((h, pages.get(f"{LEAF_PREFIX}{h}", ""))
                    for h in datas):
        for marker in required:
            if marker not in text:
                fails.append(f"{LEAF_PREFIX}{h}: missing '{marker}'")
        if "report_role" in text and "|| leaf" not in text \
                and "leaf" not in text.split("report_role", 1)[-1][:40]:
            fails.append(f"{LEAF_PREFIX}{h}: report_role not leaf")
    # rollup role
    rb = pages.get(rollup_title, "")
    if "rollup" not in rb.split("report_role", 1)[-1][:60]:
        fails.append("rollup: report_role not rollup")
    # compatibility links
    for h in datas:
        text = pages.get(f"{LEAF_PREFIX}{h}", "")
        if "services-by-host" not in text:
            fails.append(f"{LEAF_PREFIX}{h}: missing services-by-host "
                         "compat link")
        if h in cms_hosts and f"services-{h}" not in text:
            fails.append(f"{LEAF_PREFIX}{h}: missing services-{h} "
                         "compat link")
    if "services-by-host" not in rb:
        fails.append("rollup: missing services-by-host compat link")
    # privacy gates
    if surface == "public":
        for t, text in pages.items():
            for name, hit in public_scrub(text):
                fails.append(f"public surface leak [{name}] in {t}: "
                             f"{hit!r}")
        for h in datas:
            if "Infrastructure:" in str(pages.get(
                    f"{LEAF_PREFIX}{h}", "")):
                pass  # internal links fine; scrub already ran
    return fails


# ------------------------------------------------------------------ publish

def board_api_base() -> str:
    try:
        spec = importlib.util.spec_from_file_location(
            "dispatch_repos", REPO / "scripts/board/dispatch_repos.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.board_api_base()
    except Exception:
        return os.environ.get(
            "BOARD_API", "https://idc03.taila0626a.ts.net:10000")


def publish_page(api: str, title: str, wikitext: str, summary: str):
    body = {"title": title, "wikitext": wikitext, "summary": summary,
            "from": "devin"}
    req = urllib.request.Request(
        f"{api}/wiki/page", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def anon_privacy_probe(api_url: str) -> tuple:
    """Anonymous read of Infrastructure:Hosts must be denied. Returns
    (ok, detail)."""
    q = {"action": "query", "prop": "revisions", "rvprop": "content",
         "titles": ROLLUP_TITLE, "format": "json", "formatversion": "2"}
    url = api_url + "?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            doc = json.load(r)
    except Exception as e:
        return False, f"probe failed: {e}"
    if doc.get("error"):
        code = str(doc["error"].get("code", ""))
        if "denied" in code or "permission" in code:
            return True, f"anonymous read denied ({code})"
        return False, f"unexpected api error {code}"
    pages = (doc.get("query") or {}).get("pages") or []
    for p in pages:
        revs = p.get("revisions") or []
        if revs and (revs[0].get("slots", {}).get("main", {})
                     .get("content") or "").strip():
            return False, "anonymous read returned page content!"
    return True, "anonymous read returned no content"


# ------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", help="render a single leaf (+rollup)")
    ap.add_argument("--surface", choices=["private", "public"],
                    default="private",
                    help="public = sanitized fleet-status derivative "
                         "(file-only, no topology)")
    ap.add_argument("--apply", action="store_true",
                    help="publish via board-api /wiki/page "
                         "(private surface only)")
    ap.add_argument("--private-ok", action="store_true",
                    help="assert Lockdown anonymous-deny already verified "
                         "(skips the live probe)")
    ap.add_argument("--wiki-api",
                    default=os.environ.get(
                        "WIKI_API_URL",
                        "https://wiki.h3.gizmo-thailand.com/api.php"),
                    help="MediaWiki api.php for the anon-deny probe")
    ap.add_argument("--api", default=None,
                    help="board-api base (default: dispatch_repos / env)")
    ap.add_argument("--check", action="store_true",
                    help="run orphan/missing/compat/privacy checks only")
    ap.add_argument("--out-dir", default=None,
                    help="write rendered wikitext files here instead of "
                         "stdout (dry-run)")
    ap.add_argument("--no-timers", action="store_true",
                    help="skip MDDB timer-timeline lookups")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    registry = load_registry()
    nodes = load_reports_nodes()
    cms_hosts = services_cms_hosts()
    loads = load_host_loads()
    disks = load_disk_trend()
    dt_gen = disk_trend_generated()

    hosts = [args.host] if args.host else list(registry)
    datas = {h: gather(h, registry, loads, disks, nodes,
                       want_timers=not args.no_timers)
             for h in hosts}
    # last_verified also considers the disk-trend report timestamp
    for d in datas.values():
        d["_dt_gen"] = dt_gen

    pages = {}
    for h in hosts:
        pages[f"{LEAF_PREFIX}{h}"] = leaf_wikitext(
            datas[h], now, cms_hosts, surface=args.surface)
    pages[ROLLUP_TITLE] = rollup_wikitext(
        {h: datas[h] for h in hosts}, now, cms_hosts,
        surface=args.surface)

    fails = run_checks(pages, datas, registry, cms_hosts, args.surface,
                       full=not args.host)

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for title, text in pages.items():
            fn = title.replace(":", "_").replace("/", "_") + ".wiki"
            (out / fn).write_text(text)
        print(f"wrote {len(pages)} pages -> {out}")
    elif not (args.apply or args.check):
        for title, text in pages.items():
            print(f"===== {title} =====\n{text}\n")

    if fails:
        print("CHECK FAILURES:", file=sys.stderr)
        for f in fails:
            print(f"  - {f}", file=sys.stderr)

    if args.check:
        return 1 if fails else 0

    if args.apply:
        if args.surface != "private":
            print("refusing --apply on public surface — the sanitized "
                  "derivative is file-only (no public write path through "
                  "/wiki/page)", file=sys.stderr)
            return 2
        if fails:
            print("refusing --apply with failed checks", file=sys.stderr)
            return 1
        if not args.private_ok:
            ok, detail = anon_privacy_probe(args.wiki_api)
            print(f"anon-deny probe: {detail}")
            if not ok:
                print("refusing --apply — anonymous read is NOT denied; "
                      "pass --private-ok only after verifying Lockdown",
                      file=sys.stderr)
                return 2
        api = args.api or board_api_base()
        rc = 0
        for title, text in pages.items():
            try:
                r = publish_page(api, title, text,
                                 f"infra hosts hierarchy refresh "
                                 f"({now:%Y-%m-%d})")
                print(f"{title}: {r.get('action')} rev={r.get('revid')}")
            except Exception as e:
                print(f"{title}: PUBLISH FAIL {e}", file=sys.stderr)
                rc = 1
        return rc

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
