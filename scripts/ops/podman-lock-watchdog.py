#!/usr/bin/env python3
"""podman-lock-watchdog — wedged rootless-podman detector + self-heal
(card podman-lock-wedge-watchdog, OPS-0726).

Born 2026-10-16: an unclean podman kill left a stale
/dev/shm/libpod_rootless_lock_1000 + dead pause.pid + alive.lck; the
state DB wedged, every container op hung, and unbounded `docker ps`
callers piled ~700 procs into a swap-thrash collapse (runbook:
docs/ssot/jobs/infrastructure/2026-10-16-tony-dell-podman-lock-wedge.yml).
Bounded callers fixed the pile-up; this watchdog is the mid-session
self-heal for the wedge itself.

Each tick (systemd podman-lock-watchdog.timer, every 2min on tony-dell):

  1. probe  `timeout 8 podman ps`
  2. on <FAIL_THRESHOLD> consecutive failed probes AND no live podman
     CLI processes (comm podman|docker — conmon/pause/fuse-overlayfs
     are long-lived runtime, NOT lock holders), run the runbook:
       rm -f /dev/shm/libpod_rootless_lock_<uid>
       rm dead pause.pid under /run/user/<uid>/containers (live
         pause pids — comm catatonit/pause — are kept)
       rm -f /run/user/<uid>/libpod/tmp/alive.lck
       timeout 20 podman system renumber   (PODMAN_WD_RENUMBER=0 skips)
  3. re-probe `timeout 10 podman ps`
  4. alert — chaba-admin event (HA event log) + LINE via ada-line-relay
     — on BOTH auto-recovery (warn) and failure-to-recover (critical).
     One alert per wedge episode per outcome; a persistent failure
     re-alerts at most every RESEND_MIN.

Safety: locks are only removed while NO podman CLI is mid-op — a live
`podman`/`docker` client process defers the whole recovery for that
tick (the wedge signature then is someone else's problem-in-progress,
not a stale lock).

State:  ~/.local/state/podman-lock-watchdog.json (consec_fail,
        episode bookkeeping — survives timer gaps + restarts)
Output: one JSON line per tick to stdout -> journald
        (journalctl --user -u podman-lock-watchdog.service -f)

Usage:
  podman-lock-watchdog.py             # one tick (the timer path)
  podman-lock-watchdog.py --dry-run   # probe+judge, no deletes/alerts
  podman-lock-watchdog.py --self-test # synthetic run, no podman needed

Env: PODMAN_WD_STATE, PODMAN_WD_PROBE_TIMEOUT (8), PODMAN_WD_REPROBE_TIMEOUT
     (10), PODMAN_WD_FAIL_THRESHOLD (3), PODMAN_WD_COOLDOWN_S (1200 —
     min seconds between recovery attempts), PODMAN_WD_RESEND_MIN (360 —
     repeat-alert gap while a failure episode persists), PODMAN_WD_RENUMBER
     (1), PODMAN_WD_RENUMBER_TIMEOUT (20), PODMAN_WD_RELAY_SSH (idc03),
     PODMAN_WD_DEV_SHM (/dev/shm), PODMAN_WD_RUN_DIR ($XDG_RUNTIME_DIR or
     /run/user/<uid>), PODMAN_WD_PROBE_CMD (test hook — replaces the probe
     command, e.g. "true"/"false"), PODMAN_WD_EVENT_LOG
     (~/.config/home-assistant/scripts/chaba-event-log.py).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

UID = os.getuid()
STATE = Path(os.environ.get(
    "PODMAN_WD_STATE",
    "~/.local/state/podman-lock-watchdog.json")).expanduser()
PROBE_TIMEOUT = int(os.environ.get("PODMAN_WD_PROBE_TIMEOUT", "8"))
REPROBE_TIMEOUT = int(os.environ.get("PODMAN_WD_REPROBE_TIMEOUT", "10"))
FAIL_THRESHOLD = int(os.environ.get("PODMAN_WD_FAIL_THRESHOLD", "3"))
COOLDOWN_S = int(os.environ.get("PODMAN_WD_COOLDOWN_S", "1200"))
RESEND_MIN = float(os.environ.get("PODMAN_WD_RESEND_MIN", "360"))
RENUMBER = os.environ.get("PODMAN_WD_RENUMBER", "1") != "0"
RENUMBER_TIMEOUT = int(os.environ.get("PODMAN_WD_RENUMBER_TIMEOUT", "20"))
RELAY_SSH = os.environ.get("PODMAN_WD_RELAY_SSH", "idc03")
DEV_SHM = os.environ.get("PODMAN_WD_DEV_SHM", "/dev/shm")
RUN_DIR = Path(os.environ.get(
    "PODMAN_WD_RUN_DIR",
    os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{UID}"))
EVENT_LOG = Path(os.environ.get(
    "PODMAN_WD_EVENT_LOG",
    "~/.config/home-assistant/scripts/chaba-event-log.py")).expanduser()
PROBE_CMD = os.environ.get("PODMAN_WD_PROBE_CMD", "").strip()

# comm values that count as a live podman CLI op (lock may be legitimately
# held — do NOT clear). conmon/pause/catatonit/fuse-overlayfs are the
# long-lived runtime and are intentionally absent.
CLI_COMMS = {"podman", "docker"}
# comms a live pause.pid is allowed to hold — anything else with that pid
# means the pid was recycled and the file is stale.
PAUSE_COMMS = {"pause", "catatonit"}


# --- probe + process inspection ------------------------------------------------

def run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout + 5)


def probe(timeout_s: int = PROBE_TIMEOUT) -> tuple[bool, str]:
    """`timeout N podman ps` -> (ok, detail). Never raises."""
    cmd = (PROBE_CMD.split() if PROBE_CMD
           else ["timeout", str(timeout_s), "podman", "ps"])
    try:
        r = run(cmd, timeout_s)
        if r.returncode == 0:
            return True, "ok"
        return False, f"rc={r.returncode} {(r.stderr or '').strip()[:120]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def live_podman_procs() -> list[dict]:
    """Live podman/docker CLI processes (conmon/pause excluded)."""
    try:
        r = subprocess.run(
            ["ps", "-eo", "pid=,comm=,etimes=,args="],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    out = []
    me = os.getpid()
    for line in r.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid_s, comm, etimes, args = parts
        try:
            pid, et = int(pid_s), int(etimes)
        except ValueError:
            continue
        if comm in CLI_COMMS and pid != me:
            out.append({"pid": pid, "comm": comm,
                        "etimes": et, "args": args[:120]})
    return out


# --- stale-state cleanup --------------------------------------------------------

def _pid_is_pause(pid: int) -> bool | None:
    """True = alive pause-ish proc; False = dead/recycled (file stale);
    None = can't tell (keep the file)."""
    comm = Path(f"/proc/{pid}/comm")
    try:
        return comm.read_text().strip() in PAUSE_COMMS
    except FileNotFoundError:
        return False
    except OSError:
        return None


def clear_stale_state(uid: int = UID, dry_run: bool = False) -> dict:
    """Runbook step 2 — remove the stale lock artifacts. Returns what was
    (or would be) removed."""
    removed, kept = [], []

    shm = Path(DEV_SHM) / f"libpod_rootless_lock_{uid}"
    for p in [shm] + [Path(x) for x in glob.glob(
            str(Path(DEV_SHM) / f"libpod_rootless_lock_{uid}*")) if Path(x) != shm]:
        if p.exists() or p.is_symlink():
            removed.append(str(p))
            if not dry_run:
                try:
                    p.unlink()
                except OSError as e:
                    kept.append(f"{p} (unlink failed: {e})")

    containers = RUN_DIR / "containers"
    for p in sorted(containers.rglob("pause.pid")) if containers.is_dir() else []:
        try:
            pid = int(p.read_text().strip())
        except (OSError, ValueError):
            pid = None
        status = "dead" if pid is None else _pid_is_pause(pid)
        if status is True:
            kept.append(f"{p} (live pause pid {pid})")
            continue
        removed.append(f"{p} (pid={pid} {status})")
        if not dry_run:
            try:
                p.unlink()
            except OSError as e:
                kept.append(f"{p} (unlink failed: {e})")

    alive = RUN_DIR / "libpod" / "tmp" / "alive.lck"
    if alive.exists() or alive.is_symlink():
        removed.append(str(alive))
        if not dry_run:
            try:
                alive.unlink()
            except OSError as e:
                kept.append(f"{alive} (unlink failed: {e})")

    return {"removed": removed, "kept": kept}


def renumber() -> tuple[bool, str]:
    if not RENUMBER:
        return True, "skipped (PODMAN_WD_RENUMBER=0)"
    try:
        r = run(["timeout", str(RENUMBER_TIMEOUT),
                 "podman", "system", "renumber"], RENUMBER_TIMEOUT)
        return r.returncode == 0, f"rc={r.returncode}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# --- alert sinks (never raise) ----------------------------------------------------

def send_event(severity: str, body: str) -> tuple[bool, str]:
    """chaba-admin event via the HA event-log script — local path first
    (we run on tony-dell), ssh-self fallback."""
    payload = json.dumps({
        "title": "podman lock watchdog", "category": "ops-canary",
        "source": "podman-lock-watchdog", "severity": severity,
        "requires_response": severity != "info", "body": body})
    if EVENT_LOG.exists():
        try:
            r = subprocess.run(
                ["python3", str(EVENT_LOG), "add", "-"],
                input=payload, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return True, "event-log"
        except Exception:
            pass
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             "tony-dell", "python3",
             "~/.config/home-assistant/scripts/chaba-event-log.py", "add", "-"],
            input=payload, capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            return True, "ssh:tony-dell"
    except Exception:
        pass
    return False, "no event transport"


def send_line(text: str) -> tuple[bool, str]:
    """LINE push via ada-line-relay :8912/send — direct loopback first,
    then the chaba-nag `ssh idc03 curl` fallback."""
    payload = json.dumps({"text": text, "class": "critical"})
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:8912/send", data=payload.encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            if '"ok":true' in r.read().decode().replace(" ", ""):
                return True, "relay-url"
    except Exception:
        pass
    try:
        p = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             RELAY_SSH, "curl", "-s", "-m", "8", "-X", "POST",
             "http://127.0.0.1:8912/send",
             "-H", "Content-Type: application/json", "-d", "@-"],
            input=payload, capture_output=True, text=True, timeout=30)
        if '"ok":true' in (p.stdout or "").replace(" ", ""):
            return True, f"ssh:{RELAY_SSH}"
        return False, (p.stdout or p.stderr or "")[:160]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def recent_event(text: str) -> None:
    """Hot-tier chaba memory line (staleness-sentinel pattern)."""
    for d in ("~/CascadeProjects/chaba", "~/CascadeProjects/chaba-tony-dell"):
        rp = Path(d).expanduser() / "scripts/chaba/recent-event.py"
        if rp.exists():
            try:
                subprocess.run(
                    ["python3", str(rp), "--text", text,
                     "--ref", "podman-lock-watchdog", "--ttl-hours", "24"],
                    capture_output=True, timeout=15)
            except Exception:
                pass
            return


def alert(kind: str, body: str, dry_run: bool) -> dict:
    """kind: recovered|failed — chaba-admin event + LINE."""
    severity = "warn" if kind == "recovered" else "critical"
    line = ("✅ podman-lock-watchdog tony-dell: "
            if kind == "recovered" else
            "🚨 podman-lock-watchdog tony-dell: ") + body
    if dry_run:
        return {"event": "dry-run", "line": "dry-run", "severity": severity}
    ev, ev_via = send_event(severity, body)
    ln, ln_via = send_line(line)
    recent_event(f"podman-lock-watchdog {kind}: {body}")
    return {"event": f"{ev}:{ev_via}", "line": f"{ln}:{ln_via}",
            "severity": severity}


# --- state ------------------------------------------------------------------------

def load_state() -> dict:
    try:
        s = json.loads(STATE.read_text())
        if isinstance(s, dict):
            return s
    except (OSError, ValueError):
        pass
    return {"consec_fail": 0, "episode_open": False, "episode_since": None,
            "last_action_ts": 0, "last_alert_ts": 0}


def save_state(s: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(s, indent=1))
    except OSError:
        pass


# --- tick -------------------------------------------------------------------------

def tick(dry_run: bool = False, probe_fn=probe,
         live_fn=live_podman_procs, alert_fn=alert,
         clear_fn=clear_stale_state, renumber_fn=renumber) -> dict:
    """One watchdog cycle. All externals injectable for tests."""
    now = time.time()
    st = load_state()
    ok, detail = probe_fn(PROBE_TIMEOUT)
    res = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": os.uname().nodename,
           "probe_ok": ok, "probe": detail, "consec_fail": st["consec_fail"],
           "signature": False, "action": "none", "outcome": None,
           "alerts": None}

    if ok:
        if st["consec_fail"] or st.get("episode_open"):
            res["action"] = "recovered-external"
            res["outcome"] = f"probe ok again after {st['consec_fail']} fail(s)"
        st.update(consec_fail=0, episode_open=False, episode_since=None,
                  last_action_ts=0, last_alert_ts=0)
        save_state(st)
        return res

    st["consec_fail"] += 1
    res["consec_fail"] = st["consec_fail"]
    if st["consec_fail"] < FAIL_THRESHOLD:
        save_state(st)
        return res

    live = live_fn()
    res["live_podman"] = live
    if live:
        res["action"] = "deferred-live-cli"
        save_state(st)
        return res

    # wedge signature confirmed: >=N dead probes, no podman CLI running
    res["signature"] = True
    if not st.get("episode_open"):
        st["episode_open"] = True
        st["episode_since"] = now

    if st.get("last_action_ts") and now - st["last_action_ts"] < COOLDOWN_S:
        res["action"] = "suppressed-cooldown"
        res["outcome"] = (f"last recovery attempt "
                          f"{int(now - st['last_action_ts'])}s ago")
        save_state(st)
        return res

    # recover: clear stale locks, renumber, re-probe
    cleared = clear_fn(dry_run=dry_run)
    ren_ok, ren_detail = (True, "dry-run") if dry_run else renumber_fn()
    ok2, detail2 = probe_fn(REPROBE_TIMEOUT)
    st["last_action_ts"] = now
    res.update(action="recover", cleared=cleared,
               renumber=f"{ren_ok}:{ren_detail}",
               reprobe_ok=ok2, reprobe=detail2)

    if ok2:
        res["outcome"] = "recovered"
        body = (f"wedge self-healed — {st['consec_fail']} failed probes, "
                f"cleared {len(cleared['removed'])} stale file(s): "
                f"{', '.join(cleared['removed']) or 'none'}; "
                f"renumber {ren_detail}; re-probe ok")
        res["alerts"] = alert_fn("recovered", body, dry_run)
        st.update(consec_fail=0, episode_open=False, episode_since=None,
                  last_alert_ts=now)
    else:
        res["outcome"] = "still-wedged"
        due = now - st.get("last_alert_ts", 0) >= RESEND_MIN * 60
        if due:
            body = (f"wedge NOT recovered — {st['consec_fail']} failed "
                    f"probes, no live podman CLI; cleared "
                    f"{len(cleared['removed'])} file(s), renumber "
                    f"{ren_detail}, re-probe still fails ({detail2}). "
                    f"Manual runbook: docs/ssot/jobs/infrastructure/"
                    f"2026-10-16-tony-dell-podman-lock-wedge.yml — if the "
                    f"box is thrashing, reboot clears /dev/shm.")
            res["alerts"] = alert_fn("failed", body, dry_run)
            st["last_alert_ts"] = now
        else:
            res["alerts"] = {"suppressed": "resend window"}

    save_state(st)
    return res


def self_test() -> int:
    """Synthetic exercise — no podman, no filesystem locks, no alerts."""
    import tempfile
    global STATE
    checks = []

    with tempfile.TemporaryDirectory() as td:
        STATE = Path(td) / "state.json"
        import itertools
        seq = itertools.chain([False, False, False],
                              itertools.repeat(True))   # 3 fails then ok
        calls = {"alert": []}
        rs = [
            tick(probe_fn=lambda t: (next(seq), "x"),
                 live_fn=lambda: [],
                 clear_fn=lambda dry_run=False: {"removed": ["x"], "kept": []},
                 renumber_fn=lambda: (True, "rc=0"),
                 alert_fn=lambda k, b, d: calls["alert"].append(k) or {"ok": 1})
            for _ in range(4)]
        checks.append(("3 fails -> signature + recover", rs[2]["signature"]))
        checks.append(("recover outcome", rs[2]["outcome"] == "recovered"))
        checks.append(("alert fired once", calls["alert"] == ["recovered"]))

    with tempfile.TemporaryDirectory() as td:
        STATE = Path(td) / "state.json"
        live = [{"pid": 9, "comm": "podman", "etimes": 3, "args": "podman ps"}]
        for _ in range(3):
            r = tick(probe_fn=lambda t: (False, "rc=124"),
                     live_fn=lambda: live,
                     alert_fn=lambda *a: {"x": 1})
        checks.append(("live CLI defers", r["action"] == "deferred-live-cli"))
        checks.append(("no signature while CLI live", not r["signature"]))

    with tempfile.TemporaryDirectory() as td:
        STATE = Path(td) / "state.json"
        alerts = []
        rs = [
            tick(probe_fn=lambda t: (False, "rc=124"),
                 live_fn=lambda: [],
                 clear_fn=lambda dry_run=False: {"removed": [], "kept": []},
                 renumber_fn=lambda: (True, "rc=0"),
                 alert_fn=lambda k, b, d: alerts.append(k) or {"ok": 1})
            for _ in range(4)]
        checks.append(("failed recovery -> still-wedged",
                       rs[2]["outcome"] == "still-wedged"))
        checks.append(("one critical alert", alerts == ["failed"]))
        checks.append(("cooldown suppresses re-action",
                       rs[3]["action"] == "suppressed-cooldown"))

    for name, okc in checks:
        print(f"{'PASS' if okc else 'FAIL'} {name}")
    return 0 if all(c for _, c in checks) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    res = tick(dry_run=args.dry_run)
    if args.dry_run:
        res["dry_run"] = True
    print(json.dumps(res, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
