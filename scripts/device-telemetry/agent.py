#!/usr/bin/env python3
"""device-telemetry — tiny lost-device beacon. Linux + macOS.

Collects a small snapshot (host identity, online state, WAN IP + rough
geo, battery if any, logged-in users, uptime, top apps) and POSTs one
doc to MDDB: key <device>/<unix-ts> for history plus <device>/latest
for the always-current read. Designed to run from a systemd user timer
or launchd every few minutes — single file, stdlib only, no icon, no
tray, ~5ms when idle.

Env:
  DEVICE_TELEMETRY_MDBB   default http://100.102.134.91:11023/v1
  DEVICE_TELEMETRY_NAME   default short hostname
  DEVICE_TELEMETRY_GEO    "0" to skip WAN geo lookup (privacy/offline)
  DEVICE_TELEMETRY_PROC   max processes to list (default 8, 0=off)
"""
import json
import os
import platform
import socket
import subprocess
import time
import urllib.request

MDBB = os.environ.get("DEVICE_TELEMETRY_MDBB",
                      "http://100.102.134.91:11023/v1").rstrip("/")
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
    js = _run(["tailscale", "status", "--json"])
    if js:
        try:
            st = json.loads(js)
            me = st.get("Self", {})
            out["online"] = st.get("BackendState") == "Running"
            out["ips"] = me.get("TailscaleIPs", [])
            out["last_handshake"] = me.get("LastHandshake")
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
        out = _run(["pmset", "-g", "batt"])
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


def collect() -> dict:
    boot = _run(["sysctl", "-n", "kern.boottime"]).split("{ sec = ")[-1].split(",")[0] \
        if platform.system() == "Darwin" else ""
    d = {
        "device": NAME,
        "ts": int(time.time()),
        "os": f"{platform.system()} {platform.release()}",
        "uptime_s": int(_run(["cat", "/proc/uptime"]).split()[0].split(".")[0])
        if os.path.exists("/proc/uptime") else None,
        "boot_time": int(boot) if boot.isdigit() else None,
        "users": _users(),
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
