#!/usr/bin/env python3
"""test-actuation.py — gate-matrix test for the nest-mgr v2 actuation plane.

Runs every mode + gate + circuit path in an isolated tempdir: flag files
and the fake `systemctl` live under a temp STATE_DIR, nothing touches the
real ~/.local/share/nest or real systemd. Exits 1 on any failure.

    python3 test-actuation.py
"""
from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("nestmgr", HERE / "nest-mgr.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

TMP = Path(tempfile.mkdtemp(prefix="nest-act-test-"))
# Point every flag-file constant at the tempdir (module globals are read
# at call time, so patching them isolates the whole control surface).
for name in ("MODE_FILE", "KILL_FILE", "OPTIN_FILE", "HOST_CIRCUIT",
             "MANUAL_FILE", "ALLOW_FILE"):
    setattr(m, name, TMP / getattr(m, name).name)
m.CIRCUIT_DIR = TMP / "circuit"

FAKEBIN = TMP / "bin"
FAKEBIN.mkdir()
os.environ["PATH"] = f"{FAKEBIN}:{os.environ['PATH']}"


def fake_systemctl(rc: int) -> None:
    p = FAKEBIN / "systemctl"
    p.write_text(f"#!/bin/sh\nexit {rc}\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class HID:
    ts_ip = "100.0.0.1"
    hostname = "testhost"

    def is_self(self, h):
        return True

    def label(self):
        return "testhost"


hid = HID()
NOW = datetime.now(timezone.utc)


def node(unit="jev-x.service", state="failed", owner="manager", **kw):
    n = {"name": unit[:-8], "unit": unit, "state": state,
         "owner": owner, "sources": ["unit"]}
    n.update(kw)
    return n


def prev_for(unit, fail_ticks=3, attempts=None):
    return {"actuation": {"mode": "monitor", "units":
                          {unit: {"fail_ticks": fail_ticks,
                                  "attempts": attempts or []}}},
            "actions": []}


results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))


def ago(s: float) -> str:
    return (NOW - timedelta(seconds=s)).isoformat()


# -- modes -----------------------------------------------------------------
m.MODE_FILE.write_text("monitor")
act, ev = m.actuation_tick({"a": node()}, hid, prev_for("jev-x.service"))
check("monitor: zero events", ev == [], str(ev))

m.MODE_FILE.write_text("recommend")
act, ev = m.actuation_tick({"a": node(restart_ok=True)}, hid,
                           prev_for("jev-x.service"))
check("recommend: recommends restart",
      any(e["outcome"] == "recommended" for e in ev), str(ev))
check("recommend: mode stayed recommend", act["mode"] == "recommend")

act, ev = m.actuation_tick({"a": node(restart_ok=True)}, hid,
                           prev_for("jev-x.service", fail_ticks=1))
check("recommend: <3 consecutive ticks -> nothing",
      not [e for e in ev if e["action"] == "restart"], str(ev))

# -- never-list gates ------------------------------------------------------
act, ev = m.actuation_tick(
    {"a": node(owner="card:foo", restart_ok=True)}, hid,
    prev_for("jev-x.service"))
check("gate: card-owned held", any(e["reason"] == "owner-card" for e in ev),
      str(ev))

act, ev = m.actuation_tick({"a": node()}, hid, prev_for("jev-x.service"))
check("gate: not-allowlisted held",
      any(e["reason"] == "not-allowlisted" for e in ev), str(ev))

act, ev = m.actuation_tick(
    {"a": node(owner="unmanaged", restart_ok=True)}, hid,
    prev_for("jev-x.service"))
check("gate: unmanaged held", any(e["reason"] == "unmanaged" for e in ev),
      str(ev))

act, ev = m.actuation_tick(
    {"a": node(unit="nest-mgr.service", restart_ok=True)}, hid,
    prev_for("nest-mgr.service"))
check("gate: nest-mgr self held", any(e["reason"] == "self" for e in ev),
      str(ev))

act, ev = m.actuation_tick(
    {"a": node(restart_ok=True, topo_status="prod")}, hid,
    prev_for("jev-x.service"))
check("gate: production lane held",
      any(e["reason"] == "production" for e in ev), str(ev))

m.MANUAL_FILE.write_text("jev-x.service\n")
act, ev = m.actuation_tick({"a": node(restart_ok=True)}, hid,
                           prev_for("jev-x.service"))
check("gate: manual-units held", any(e["reason"] == "manual" for e in ev),
      str(ev))
m.MANUAL_FILE.unlink()

act, ev = m.actuation_tick(
    {"a": node(restart_ok=True, restart_policy="on-success")}, hid,
    prev_for("jev-x.service"))
check("gate: Restart=on-success held",
      any(e["reason"] == "restart-policy" for e in ev), str(ev))

# -- allowlist file --------------------------------------------------------
m.ALLOW_FILE.write_text("jev-x.service\n")
act, ev = m.actuation_tick({"a": node()}, hid, prev_for("jev-x.service"))
check("allowlist file: recommended",
      any(e["outcome"] == "recommended" for e in ev), str(ev))
m.ALLOW_FILE.unlink()

# -- throttles -------------------------------------------------------------
act, ev = m.actuation_tick(
    {"a": node(restart_ok=True)}, hid,
    prev_for("jev-x.service", attempts=[{"ts": ago(60), "ok": True}]))
check("throttle: cooldown held", any(e["reason"] == "cooldown" for e in ev),
      str(ev))

# -- mode resolution -------------------------------------------------------
m.MODE_FILE.write_text("guarded")
act, ev = m.actuation_tick({"a": node(restart_ok=True)}, hid,
                           prev_for("jev-x.service"))
check("guarded w/o opt-in -> recommend",
      act["mode"] == "recommend"
      and any(e["outcome"] == "recommended" for e in ev), str(ev))

m.KILL_FILE.touch()
act, ev = m.actuation_tick({"a": node(restart_ok=True)}, hid,
                           prev_for("jev-x.service"))
check("kill switch -> monitor",
      act["mode"] == "monitor"
      and not [e for e in ev if e["action"] == "restart"], str(ev))
m.KILL_FILE.unlink()

# -- guarded execution -----------------------------------------------------
m.OPTIN_FILE.touch()
fake_systemctl(0)
act, ev = m.actuation_tick({"a": node(restart_ok=True)}, hid,
                           prev_for("jev-x.service"))
check("guarded+opt-in: executes restart ok",
      any(e["outcome"] == "ok" for e in ev), str(ev))

fake_systemctl(1)
prev = prev_for("jev-x.service")
act, ev = m.actuation_tick({"a": node(restart_ok=True)}, hid, prev)
# age the first attempt past the cooldown so a second attempt can run
act["units"]["jev-x.service"]["attempts"][0]["ts"] = ago(400)
act, ev = m.actuation_tick({"a": node(restart_ok=True)}, hid,
                           {"actuation": act, "actions": ev})
check("2 failed restarts/h -> unit circuit opens",
      (m.CIRCUIT_DIR / "jev-x.service.open").exists(), str(ev))
check("circuit-open event logged",
      any(e["action"] == "circuit-open" for e in ev), str(ev))

act, ev = m.actuation_tick({"a": node(restart_ok=True)}, hid,
                           {"actuation": act, "actions": []})
check("unit circuit blocks further restarts",
      any(e["reason"] == "circuit-open" for e in ev), str(ev))
(m.CIRCUIT_DIR / "jev-x.service.open").unlink()

# -- host circuit ----------------------------------------------------------
acts5 = [{"ts": NOW.isoformat(), "unit": f"u{i}", "action": "restart",
          "outcome": "ok"} for i in range(5)]
act, ev = m.actuation_tick(
    {"a": node(restart_ok=True)}, hid,
    {"actuation": {"units": {"jev-x.service": {"fail_ticks": 3}}},
     "actions": acts5})
check(">5 execs/h -> host circuit opens", m.HOST_CIRCUIT.exists(), str(ev))

act, ev = m.actuation_tick({"a": node(restart_ok=True)}, hid,
                           {"actuation": act, "actions": acts5})
check("host circuit flag -> monitor", act["mode"] == "monitor", str(ev))
m.HOST_CIRCUIT.unlink()

# -- report ----------------------------------------------------------------
fails = [r for r in results if not r[1]]
for name, ok, extra in results:
    print(("PASS" if ok else "FAIL"), name, "" if ok else extra)
print(f"\n{len(results) - len(fails)}/{len(results)} passed")
sys.exit(1 if fails else 0)
