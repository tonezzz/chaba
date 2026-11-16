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
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import time
import urllib.request

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


def _temps() -> tuple[float | None, dict]:
    zones = {}
    for z in sorted(__import__("glob").glob(
            "/sys/class/thermal/thermal_zone*/temp")):
        v = _run(["cat", z])
        if v.isdigit():
            name = z.split("thermal_zone")[1].split("/")[0]
            zones[f"zone{name}"] = round(int(v) / 1000.0, 1)
    if not zones:
        return None, {}
    return round(max(zones.values()), 1), zones



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



def collect() -> dict:
    boot = _run(["/usr/sbin/sysctl", "-n", "kern.boottime"]).split("{ sec = ")[-1].split(",")[0] \
        if platform.system() == "Darwin" else ""
    temps = _temps()
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
        "temp_c": temps[0],
        "temp_zones": temps[1],
        "top_procs": _procs(),
        "battery": _battery(),
        "tailnet": _tailnet(),
        "wan": _wan(),
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
