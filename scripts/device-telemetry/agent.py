#!/usr/bin/env python3
"""device-telemetry — tiny lost-device beacon. Linux + macOS.

Collects a small snapshot (host identity, online state, WAN IP + rough
geo, battery if any, logged-in users, uptime, top apps) and POSTs one
doc to MDDB: key <device>/<unix-ts> for history plus <device>/latest
for the always-current read. Designed to run from a systemd user timer
or launchd every few minutes — single file, stdlib only, no icon, no
tray, ~5ms when idle.

Env:
  DEVICE_TELEMETRY_MDBB   default http://100.102.134.91:11026/v1
  DEVICE_TELEMETRY_NAME   default short hostname
  DEVICE_TELEMETRY_GEO    "0" to skip WAN geo lookup (privacy/offline)
  DEVICE_TELEMETRY_PROC   max processes to list (default 8, 0=off)
  DEVICE_TELEMETRY_TEMP_CACHE_S  macOS last-good temperature TTL (default 900)
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from datetime import datetime

MDBB = os.environ.get("DEVICE_TELEMETRY_MDBB",
                      "http://100.102.134.91:11026/v1").rstrip("/")
NAME = os.environ.get("DEVICE_TELEMETRY_NAME",
                      socket.gethostname().split(".")[0])
COLLECTION = "device-telemetry"


def _run(cmd: list[str], timeout: int = 5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except Exception:
        return ""


def _tailnet() -> dict:
    out = {"online": False}
    candidates = ["tailscale"]
    if platform.system() == "Darwin":
        candidates += ["/opt/homebrew/bin/tailscale",
                       "/usr/local/bin/tailscale",
                       "/Applications/Tailscale.app/Contents/MacOS/Tailscale"]
    js = ""
    for c in candidates:
        js = _run([c, "status", "--json"])
        if js:
            break
    if js:
        try:
            st = json.loads(js)
            me = st.get("Self", {})
            out["online"] = st.get("BackendState") == "Running"
            out["ips"] = me.get("TailscaleIPs", [])
            hs = me.get("LastHandshake") or ""
            out["last_handshake"] = hs if hs.startswith("2") else None
        except Exception:
            pass
    return out


def _wan() -> dict:
    if os.environ.get("DEVICE_TELEMETRY_GEO") == "0":
        return {}
    for url in ("https://ipinfo.io/json",):
        try:
            r = json.load(urllib.request.urlopen(url, timeout=6))
            return {"ip": r.get("ip"), "city": r.get("city"),
                    "region": r.get("region"), "country": r.get("country"),
                    "loc": r.get("loc"), "org": r.get("org")}
        except Exception:
            continue
    return {}


def _battery() -> dict | None:
    if platform.system() == "Darwin":
        out = _run(["/usr/bin/pmset", "-g", "batt"])
        if "%" in out:
            return {"raw": out.splitlines()[-1][:120]}
        return None
    for bat in ("BAT0", "BAT1"):
        base = f"/sys/class/power_supply/{bat}"
        cap = _run(["cat", f"{base}/capacity"])
        st = _run(["cat", f"{base}/status"])
        if cap.isdigit():
            b = {"pct": int(cap), "status": st}
            for key, fn in (("charge_now_uah", "charge_now"),
                            ("charge_full_uah", "charge_full"),
                            ("charge_full_design_uah", "charge_full_design"),
                            ("cycle_count", "cycle_count"),
                            ("temp_dxc", "temp"),
                            ("voltage_now_uv", "voltage_now"),
                            ("current_now_ua", "current_now")):
                v = _run(["cat", f"{base}/{fn}"])
                if v.lstrip("-").isdigit():
                    b[key] = int(v)
            for fn in ("model_name", "manufacturer", "technology"):
                v = _run(["cat", f"{base}/{fn}"])
                if v:
                    b[fn] = v
            if b.get("charge_full_uah") and b.get("charge_full_design_uah"):
                b["health_pct"] = round(
                    100.0 * b["charge_full_uah"] / b["charge_full_design_uah"], 1)
            return b
    return None


def _procs() -> list[str]:
    n = int(os.environ.get("DEVICE_TELEMETRY_PROC", "8"))
    if not n:
        return []
    ps = "ps -Ao comm= -r" if platform.system() == "Darwin" \
        else "ps -eo comm --sort=-%cpu"
    return [l.strip() for l in _run(["sh", "-c", ps]).splitlines()[1:n + 1]
            if l.strip()]


def _users() -> list[str]:
    # loginctl catches GUI sessions (GDM sessions don't appear in utmp)
    out = _run(["loginctl", "list-sessions", "--no-legend"])
    if out:
        names = set()
        for l in out.splitlines():
            p = l.split()
            if len(p) >= 3 and p[1].isdigit() and p[1] != "0":
                names.add(p[2])
        if names:
            return sorted(names)
    return sorted(set(_run(["users"]).split()))


def _load() -> float | None:
    try:
        return round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        return None


def _mem_pct() -> float | None:
    if os.path.exists("/proc/meminfo"):
        kv = {}
        for l in open("/proc/meminfo"):
            k, _, v = l.partition(":")
            kv[k.strip()] = int(v.split()[0])
        total = kv.get("MemTotal")
        avail = kv.get("MemAvailable")
        if total and avail is not None:
            return round(100.0 * (total - avail) / total, 1)
        return None
    if platform.system() == "Darwin":
        out = _run(["/usr/bin/vm_stat"])
        if "page size of" not in out:
            return None
        try:
            ps = int(out.split("page size of")[1].split("bytes")[0])
            vals = {l.split(":")[0].strip(): int(l.split(":")[1].strip().rstrip("."))
                    for l in out.splitlines()
                    if l.startswith("Pages ") and ":" in l}
            total_b = int(_run(["/usr/sbin/sysctl", "-n", "hw.memsize"]))
            free = (vals.get("Pages free", 0)
                    + vals.get("Pages inactive", 0)) * ps
            return round(100.0 * (total_b - free) / total_b, 1)
        except Exception:
            return None
    return None


def _disk_pct() -> float | None:
    try:
        u = shutil.disk_usage("/")
        return round(100.0 * u.used / u.total, 1)
    except OSError:
        return None


# Last good macOS reading, reused only while younger than TTL. An SMC read
# is occasionally transient (smctemp prints 0.0 plus a hint), and a single
# null sample blanks the HA sensor until the next 5-min mirror push.
TEMP_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".temp-cache.json")
TEMP_CACHE_TTL_S = int(os.environ.get(
    "DEVICE_TELEMETRY_TEMP_CACHE_S", "900"))


def _cached_temp() -> tuple[float | None, dict]:
    """Last plausible reading, only while younger than TEMP_CACHE_TTL_S."""
    try:
        with open(TEMP_CACHE) as f:
            d = json.load(f)
        age = time.time() - float(d.get("ts") or 0)
        t = float(d.get("temp_c"))
        if 0 <= age <= TEMP_CACHE_TTL_S and 0 < t < 150:
            zones = d.get("zones") or {"cpu": round(t, 1)}
            return round(t, 1), zones
    except (OSError, ValueError, TypeError):
        pass
    return None, {}


def _remember_temp(t: float, zones: dict) -> None:
    try:
        tmp = TEMP_CACHE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"ts": time.time(), "temp_c": t, "zones": zones}, f)
        os.replace(tmp, TEMP_CACHE)
    except OSError:
        pass


def _smctemp_zones() -> dict:
    """Read every SMC zone we can (CPU, GPU) with a bounded retry each.

    A missing sensor must not hide a hot one: the caller uses max(zones).
    osx-cpu-temp is a CPU-only last resort — on kk-mac it reports 0.0C,
    which is rejected as implausible.
    """
    smctemp = os.path.expanduser("~/.local/bin/smctemp")
    zones = {}
    for name, flag in (("cpu", "-c"), ("gpu", "-g")):
        cmds = [[smctemp, flag], ["smctemp", flag]]
        if name == "cpu":
            cmds.append(["/opt/homebrew/bin/osx-cpu-temp"])
        for attempt in range(3):
            for cmd in cmds:
                out = _run(cmd).strip()
                if not out:
                    continue
                # smctemp sometimes appends a hint after the number —
                # only the first line is the reading.
                first = out.splitlines()[0].strip()
                try:
                    t = float(first.split(":")[-1].strip().rstrip("°C").strip())
                except ValueError:
                    continue
                if 0 < t < 150:
                    zones[name] = round(t, 1)
                    break
            if name in zones:
                break
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
    return zones


def _temps() -> tuple[float | None, dict, str]:
    zones = {}
    for z in sorted(__import__("glob").glob(
            "/sys/class/thermal/thermal_zone*/temp")):
        v = _run(["cat", z])
        if not v.isdigit():
            continue
        idx = z.split("thermal_zone")[1].split("/")[0]
        ztype = _run(["cat", z.replace("/temp", "/type")]).strip()
        name = (ztype or f"zone{idx}")[:24]
        zones[name] = round(int(v) / 1000.0, 1)
    if zones:
        return round(max(zones.values()), 1), zones, "live"
    if platform.system() == "Darwin":
        # No sysfs on macOS. Prefer the user-built smctemp (unprivileged
        # SMC read); launchd's minimal PATH misses ~/.local/bin, so try
        # the absolute path first. Retry briefly, then fall back to the
        # short-lived cache so one bad SMC read cannot make the overview
        # table show 'unknown'. The headline temp is always the hottest
        # zone, and all zones are kept for the per-host breakdown.
        zones = _smctemp_zones()
        if zones:
            peak = round(max(zones.values()), 1)
            _remember_temp(peak, zones)
            return peak, zones, "live"
        t, z = _cached_temp()
        return t, z, "cache" if t is not None else "none"
    return None, {}, "none"



def _thermal_pressure() -> str | None:
    # Apple Silicon exposes no die temps via powermetrics — only the
    # thermal pressure level. Needs the NOPASSWD sudoers drop-in
    # (scripts/device-telemetry/sudoers-device-telemetry).
    if platform.system() != "Darwin":
        return None
    out = _run(["sudo", "-n", "/usr/bin/powermetrics",
                "--samplers", "thermal", "-n", "1"], timeout=15)
    m = re.search(r"Current pressure level:\s*(\S+)", out)
    return m.group(1) if m else None


def _swap_pct() -> float | None:
    if os.path.exists("/proc/meminfo"):
        kv = {}
        for l in open("/proc/meminfo"):
            k, _, v = l.partition(":")
            kv[k.strip()] = int(v.split()[0])
        total, free = kv.get("SwapTotal"), kv.get("SwapFree")
        if total:
            return round(100.0 * (total - (free or 0)) / total, 1)
        return 0.0 if total == 0 else None
    if platform.system() == "Darwin":
        out = _run(["/usr/sbin/sysctl", "-n", "vm.swapusage"])
        # "total = 2048.00M  used = 512.00M  free = ..."
        try:
            tot = float(out.split("total =")[1].split("M")[0])
            used = float(out.split("used =")[1].split("M")[0])
            return round(100.0 * used / tot, 1) if tot else 0.0
        except Exception:
            return None
    return None


def _net() -> tuple[int | None, int | None]:
    rx = tx = None
    if os.path.exists("/proc/net/dev"):
        rx = tx = 0
        for l in open("/proc/net/dev").read().splitlines()[2:]:
            if ":" not in l:
                continue
            name, _, rest = l.partition(":")
            if name.strip() == "lo":
                continue
            f = rest.split()
            if len(f) >= 9:
                rx += int(f[0]); tx += int(f[8])
    return rx, tx



def _services() -> dict:
    """Chaba service probes — what our own daemons are doing.

    device-telemetry reports itself trivially; other services (nest-worker
    etc.) drop status.json into their workdir under ~/.cache/*/ which we
    pick up here. Kept small: state + a few scalar metrics."""
    svcs = {"device-telemetry": {"state": "running"}}
    for p in sorted(__import__("glob").glob(
            os.path.expanduser("~/.cache/*/status.json"))):
        try:
            with open(p) as f:
                st = json.load(f)
        except Exception:
            continue
        if not isinstance(st, dict) or "worker" not in st:
            continue
        age = int(time.time()) - int(st.get("ts") or 0)
        entry = {"state": "running" if age <= 300 else "stale",
                 "age_s": age}
        for k in ("pending", "job", "last"):
            v = (st.get("claimed") or "idle") if k == "job" else st.get(k)
            if v is not None:
                entry[k] = str(v)[:80]
        svcs["nest-worker"] = entry
    # nest-mgr (DevNest manager daemon) keeps manager-state.json —
    # summarize node counts + actuation posture so dashboards see fleet
    # state at a glance (v2: mode/actions ride svc_nest_mgr_* HA sensors)
    mgr = os.path.expanduser("~/.local/share/nest/manager-state.json")
    if os.path.exists(mgr):
        try:
            with open(mgr) as f:
                m = json.load(f)
            nodes = m.get("nodes") or {}
            counts = {}
            for n in nodes.values():
                s = n.get("state") or "unknown"
                counts[s] = counts.get(s, 0) + 1
            age = int(time.time()) - int(os.path.getmtime(mgr))
            entry = {
                "state": "running" if age <= 600 else "stale",
                "age_s": age,
                "nodes": str(len(nodes)),
                "active": str(sum(v for k, v in counts.items()
                                  if k not in ("parked", "unknown"))),
            }
            act = m.get("actuation") or {}
            if act:
                entry["mode"] = str(act.get("mode") or "monitor")
                hour_ago = time.time() - 3600
                n_1h = 0
                last_ev = None
                for a in (m.get("actions") or [])[-60:]:
                    try:
                        ts = datetime.fromisoformat(
                            str(a.get("ts")).replace("Z", "+00:00")
                        ).timestamp()
                    except Exception:
                        continue
                    if ts >= hour_ago:
                        n_1h += 1
                    last_ev = a
                entry["act_1h"] = str(n_1h)
                circs = list(act.get("unit_circuits") or [])
                if act.get("host_circuit"):
                    circs.insert(0, "HOST")
                entry["circuit"] = ",".join(circs) if circs else "closed"
                if last_ev:
                    entry["last"] = str(
                        f"{last_ev.get('action')} "
                        f"{last_ev.get('unit')} "
                        f"{last_ev.get('outcome')}")[:80]
            svcs["nest-mgr"] = entry
        except Exception:
            pass
    return svcs


def collect() -> dict:
    boot = _run(["/usr/sbin/sysctl", "-n", "kern.boottime"]).split("{ sec = ")[-1].split(",")[0] \
        if platform.system() == "Darwin" else ""
    temps, temp_zones, temp_source = _temps()
    rx, tx = _net()
    d = {
        "device": NAME,
        "ts": int(time.time()),
        "os": f"{platform.system()} {platform.release()}",
        "uptime_s": (int(_run(["cat", "/proc/uptime"]).split()[0].split(".")[0])
                     if os.path.exists("/proc/uptime")
                     else (int(time.time()) - int(boot)
                           if boot.isdigit() else None)),
        "boot_time": int(boot) if boot.isdigit() else None,
        "users": _users(),
        "load1": _load(),
        "mem_pct": _mem_pct(),
        "disk_pct": _disk_pct(),
        "swap_pct": _swap_pct(),
        "net_rx_b": rx,
        "net_tx_b": tx,
        "temp_c": temps,
        "temp_zones": temp_zones,
        "temp_source": temp_source,
        "thermal_pressure": _thermal_pressure(),
        "top_procs": _procs(),
        "battery": _battery(),
        "tailnet": _tailnet(),
        "wan": _wan(),
        "services": _services(),
    }
    return d


def _post(key: str, doc: dict) -> bool:
    # MDDB meta values must be []string
    meta = {"device": [NAME], "ts": [str(doc["ts"])], "kind": ["telemetry"],
            "os": [doc["os"]],
            "online": [str(doc["tailnet"].get("online", False)).lower()]}
    if doc["wan"].get("ip"):
        meta["wan_ip"] = [doc["wan"]["ip"]]
        meta["city"] = [doc["wan"].get("city") or ""]
    body = {"collection": COLLECTION, "key": key, "lang": "en",
            "contentMd": json.dumps(doc, sort_keys=True)[:4000],
            "meta": meta}
    try:
        req = urllib.request.Request(
            f"{MDBB}/add", data=json.dumps(body).encode(),
            headers={"content-type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception:
        return False


def main() -> int:
    doc = collect()
    hist = _post(f"{NAME}/{doc['ts']}", doc)
    latest = _post(f"{NAME}/latest", doc)
    print(json.dumps({"hist": hist, "latest": latest,
                      "key": f"{NAME}/{doc['ts']}"}))
    return 0 if latest else 1


if __name__ == "__main__":
    raise SystemExit(main())
