#!/usr/bin/env python3
"""runner-agent — remote kanban executor.

Runs oneshot (timer-driven, e.g. every 60s) on any tailnet host. Each
pass:
  1. poll claimed tasks (state.json: card_id -> unit) — when the systemd
     unit leaves active state, collect exit status + journal tail and
     POST /action {do:finish, host, ok, result}
  2. if under cap, GET /cards and claim queued cards matching this host:
     - action.host absent or == RUNNER_HOST
     - action.runner absent
     - every action.labels[] entry is in RUNNER_LABELS
     - an executor exists for action.type
  3. POST /action {do:claim, host} (atomic first-wins under the api
     flock), then start the task under systemd-run and record the unit.

Task types (card `action` block):
  dispatch   (default) — `devin-dispatch start <repo> <spec+rails>`;
             needs the devin CLI + repos.conf on this host.
  container  — `podman run --rm <env> <image> <cmd...>` under
             systemd-run; card supplies action.container:
             {image, cmd (str|list), env: {K: V}, pull: missing|always}
  script     — sync a git repo to a local scratch clone and run a shell
             command in it under systemd-run; card supplies
             action.script: {cmd (str|list), repo (default "chaba"),
             repo_url (override), ref (default master), workdir,
             env: {K: V}, timeout (RuntimeMaxSec, default 1800)}.
             Repo lands in <state>/repos/<name> (clone --depth 50,
             fetch+reset on each claim — always origin-fresh, host's
             own clone so local edits there are disposable).

Env:
  RUNNER_API     board api base — default the tailnet Caddy route so the
                 same value works on every host incl. tony-dell itself
  RUNNER_HOST    hostname claim identity (default: uname nodename)
  RUNNER_CAP     max concurrent claimed tasks (default 2)
  RUNNER_MAX_LOAD_PC  stop claiming when 5-min load per core exceeds
                 this (default 1.0; 0 disables — protects the host and
                 yields the queue to idle runners)
  RUNNER_LABELS  comma-separated capability labels (e.g. "gpu,ssd";
                 "desktop" marks an interactive host and arms the
                 guards below)
  RUNNER_STATE   state dir (default ~/.local/share/runner-agent)

Interactive-host guards (card omen-gpu-display-wedge — on when the host
carries the "desktop" label, or forced via RUNNER_TASK_LIMITS /
RUNNER_GPU_WATCHDOG = 1; =0 force-off):
  - task units run deprioritized + capped so benches can't starve the
    desktop: Nice/IOSchedulingClass (ionice) + CPUQuota/CPUWeight/
    MemoryMax/IOWeight on the systemd-run argv for container/script
    units; dispatch units get the same via DISPATCH_UNIT_PROPS
    (devin-dispatch splices it into its own systemd-run) plus a
    post-start set-property/renice pass covering stale dispatchers.
  - gpu-labeled cards get a VRAM pre-flight BEFORE claiming: free VRAM
    (nvidia-smi) must cover max(card need, host floor). Card need:
    action.gpu.min_free_mb (bare int or action.min_vram_mb also read).
    Shortfall defers the claim with a debounced comms note; a need that
    exceeds total VRAM is refused (fix the spec — it can never fit).
  - presentation watchdog: each pass while a gpu task runs, a
    GetVSyncParametersIfAvailable journal/Xorg-log flood (the wedge
    signature) or a hung `xrandr --verbose` deprioritizes the unit
    (strike 1) then SIGSTOPs it (strike >=2); sustained healthy probes
    SIGCONT it. Manual unstick stays `chvt 3; sleep 2; chvt 2`.

  RUNNER_TASK_LIMITS     auto|0|1 — task unit caps (default auto)
  RUNNER_TASK_NICE       nice for task units (default 10)
  RUNNER_TASK_CPU_QUOTA  e.g. "600%" (default: 75% of online CPUs)
  RUNNER_TASK_MEM_MAX    e.g. "12G" (default: 75% of MemTotal)
  RUNNER_TASK_CPU_WEIGHT / RUNNER_TASK_IO_WEIGHT (default 50)
  RUNNER_TASK_IO_CLASS   ionice class: idle|best-effort|realtime|none
                         (default best-effort)
  RUNNER_TASK_IO_PRIO    ionice priority 0-7 (default 6)
  RUNNER_GPU_MIN_FREE_MB host floor for gpu cards (default 512)
  RUNNER_GPU_WATCHDOG    auto|0|1 — presentation watchdog (default auto)
  RUNNER_WATCHDOG_CPU_QUOTA / RUNNER_WATCHDOG_NICE — stall throttle
                         (default "30%" / 19)
  RUNNER_WATCHDOG_PAUSE_STRIKES / RUNNER_WATCHDOG_RESUME_HEALTHY —
                         strike/resume hysteresis (default 2 / 2)
  RUNNER_VSYNC_FLOOD_MIN stall-signature hits per ~2min log window that
                         count as a flood (default 150)
  RUNNER_XRANDR_TIMEOUT  xrandr probe timeout s (default 8)

State is just unit names — a restart re-polls systemctl, so an agent
crash loses at most bookkeeping, not running work. All API calls are
idempotent-ish: finish on a card that was moved/reset returns 400 and
the state entry is dropped on the next pass ("not running" errors are
treated as terminal for the entry).

Close-out (card dispatch-auto-merge): a dispatch claim that finishes ok
runs dispatch_repos.close_out locally BEFORE reporting finish — commit
leftover worktree files as a checkpoint, push the session branch to
origin (always — work left local-only strands), gate on the card's
expected_goals, then merge --no-ff into origin/<default_branch>. The
merge outcome rides the finish body (verified flag) and lands in comms;
conflicts or failed goals leave the card in review for a human.
KANBAN_AUTOMERGE=0 disables. dispatch_repos.py is imported from a local
chaba checkout (this agent deploys as a single file).
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get(
    "RUNNER_API",
    "https://tony-dell.taila0626a.ts.net/apps/board-api").rstrip("/")
HOST = os.environ.get("RUNNER_HOST") or os.uname().nodename
CAP = int(os.environ.get("RUNNER_CAP", "2"))
MAX_LOAD_PC = float(os.environ.get("RUNNER_MAX_LOAD_PC", "1.0"))
LABELS = {x.strip() for x in os.environ.get("RUNNER_LABELS", "").split(",")
          if x.strip()}
STATE_DIR = Path(os.environ.get(
    "RUNNER_STATE", str(Path.home() / ".local/share/runner-agent")))
STATE_FILE = STATE_DIR / "state.json"
DISPATCH = os.environ.get(
    "DEVIN_DISPATCH", str(Path.home() / ".local/bin/devin-dispatch"))
# Parity with kanban-dispatch: unattended sessions die on permission
# rejection — 'smart' auto-rejects curl/systemctl and the rails ask
# agents to curl /comment.
os.environ.setdefault("DISPATCH_PERMISSION_MODE", "dangerous")

# script-type repo name -> clone url. Extend here or pass
# action.script.repo_url on the card for anything else.
REPO_URLS = {"chaba": "https://github.com/tonezzz/chaba.git"}

# --- interactive-host guards (omen-gpu-display-wedge) ----------------
# "desktop" in RUNNER_LABELS marks the host as interactive; both guards
# default on there and stay off on headless runners (idc*, mn01).
def _env_on(name: str, default: str = "auto") -> bool:
    v = os.environ.get(name, default).strip().lower()
    if v in ("1", "on", "true", "yes", "always"):
        return True
    if v in ("0", "off", "false", "no", "never"):
        return False
    return "desktop" in LABELS

LIMITS_ON = _env_on("RUNNER_TASK_LIMITS")
TASK_NICE = int(os.environ.get("RUNNER_TASK_NICE", "10"))
TASK_CPU_QUOTA = os.environ.get("RUNNER_TASK_CPU_QUOTA", "")
TASK_CPU_WEIGHT = os.environ.get("RUNNER_TASK_CPU_WEIGHT", "50")
TASK_MEM_MAX = os.environ.get("RUNNER_TASK_MEM_MAX", "")
TASK_IO_CLASS = os.environ.get("RUNNER_TASK_IO_CLASS", "best-effort")
TASK_IO_PRIO = os.environ.get("RUNNER_TASK_IO_PRIO", "6")
TASK_IO_WEIGHT = os.environ.get("RUNNER_TASK_IO_WEIGHT", "50")
GPU_MIN_FREE_MB = int(os.environ.get("RUNNER_GPU_MIN_FREE_MB", "512"))
GPU_DEFER_SECS = int(os.environ.get("RUNNER_GPU_DEFER_SECS", "21600"))
DEFER_FILE = STATE_DIR / "gpu-defer.json"
WD_ON = _env_on("RUNNER_GPU_WATCHDOG")
WD_NICE = int(os.environ.get("RUNNER_WATCHDOG_NICE", "19"))
WD_CPU_QUOTA = os.environ.get("RUNNER_WATCHDOG_CPU_QUOTA", "30%")
WD_STRIKES = int(os.environ.get("RUNNER_WATCHDOG_PAUSE_STRIKES", "2"))
WD_HEALTHY = int(os.environ.get("RUNNER_WATCHDOG_RESUME_HEALTHY", "2"))
VSYNC_FLOOD_MIN = int(os.environ.get("RUNNER_VSYNC_FLOOD_MIN", "150"))
XRANDR_TIMEOUT = int(os.environ.get("RUNNER_XRANDR_TIMEOUT", "8"))
# The wedge signature (2026-10-08): the nvidia presentation engine stops
# getting vblank and callers spam this failure thousands of times a
# second while the desktop picture stays frozen.
VSYNC_PAT = "GetVSyncParametersIfAvailable"
UNSTICK = ("display unstick: ssh in, `sudo chvt 3`, sleep 2, "
           "`sudo chvt 2` (modeset reset — session survives)")


def sync_repo(name: str, url: str, ref: str) -> Path:
    """Clone-or-refresh <state>/repos/<name> pinned to origin/<ref>."""
    d = STATE_DIR / "repos" / name
    if not (d / ".git").exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        r = sh(["git", "clone", "--depth", "50", "--branch", ref,
                url, str(d)], timeout=300)
        if r.returncode != 0:
            raise RuntimeError(
                f"clone {name}: {(r.stderr or r.stdout).strip()[:200]}")
        return d
    r = sh(["git", "-C", str(d), "fetch", "--depth", "50",
            "origin", ref], timeout=300)
    if r.returncode == 0:
        r = sh(["git", "-C", str(d), "reset", "--hard", "FETCH_HEAD"],
               timeout=60)
    if r.returncode != 0:
        raise RuntimeError(
            f"sync {name}: {(r.stderr or r.stdout).strip()[:200]}")
    return d

RAILS = """
---
Rails: you are processing kanban card '{id}' on runner '{host}'.
- Post progress so the board stays live:
    curl -s -X POST {api}/comment -H 'Content-Type: application/json' \\
      -d '{{"id":"{id}","from":"devin","text":"<short status>"}}'
- Do NOT push to git remotes unless the card spec explicitly says to.
- If you need Tony to answer something, raise a board request instead of
  stalling:
    curl -s -X POST {api}/request -H 'Content-Type: application/json' \\
      -d '{{"id":"{id}","from":"devin","ask":"<question>"}}'
- If you raised a request and kept working, the answer may arrive while
  you run: board-api appends it to $TASK_DIR/answers.jsonl (one JSON
  object per line: {{"at","card","from","request_id","answer"}}). Check
  that file before finishing; newest line wins per request_id.
""".strip()


def sh(cmd: list, timeout: int = 60,
       **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, **kw)


def api(path: str, body: dict | None = None) -> dict:
    url = API + path
    try:
        if body is None:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.loads(r.read())
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:300] or str(e)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, indent=1))


def unit_active(unit: str) -> bool:
    r = sh(["systemctl", "--user", "is-active", unit], timeout=15)
    return r.stdout.strip() in ("active", "activating")


def collect(unit: str) -> tuple[bool, str]:
    """(ok, result-text) from the finished unit's exit status + log tail."""
    r = sh(["systemctl", "--user", "show", unit,
            "-p", "ExecMainStatus", "-p", "Result"], timeout=15)
    kv = dict(ln.split("=", 1) for ln in r.stdout.splitlines()
              if "=" in ln)
    ok = kv.get("ExecMainStatus") == "0" and kv.get("Result") == "success"
    j = sh(["journalctl", "--user", "-u", unit, "-n", "12",
            "--no-pager", "-o", "cat"], timeout=15)
    tail = " | ".join(x for x in j.stdout.strip().splitlines() if x)[-240:]
    return ok, f"exit={kv.get('ExecMainStatus', '?')} {tail}".strip()


_DR = None
_DR_TRIED = False


def dr_module():
    """Import dispatch_repos for the close-out merge step. The module
    lives in the chaba repo (scripts/board); runner-agent deploys as a
    single file, so resolve it from a local checkout. None when the host
    has no usable copy — the merge is then reported skipped, not fatal."""
    global _DR, _DR_TRIED
    if _DR_TRIED:
        return _DR
    _DR_TRIED = True
    cands = []
    env = os.environ.get("DISPATCH_REPOS_DIR")
    if env:
        cands.append(Path(env))
    cands += [Path(__file__).resolve().parent,
              Path.home() / "CascadeProjects/chaba/scripts/board"]
    for d in cands:
        if not (d / "dispatch_repos.py").exists():
            continue
        sys.path.insert(0, str(d))
        try:
            import dispatch_repos as dr
            _DR = dr
            return _DR
        except Exception:
            continue
    return None


def close_out_merge(cid: str, ent: dict, card: dict) -> tuple:
    """Local merge step for a finished dispatch claim. Returns
    (verified: bool|None, comms notes: list[str])."""
    if os.environ.get("KANBAN_AUTOMERGE", "1") == "0":
        return None, []
    tid = ent.get("tid") or ""
    if not tid:
        unit = ent.get("unit") or ""
        tid = (unit[len("devin-task-"):]
               if unit.startswith("devin-task-") else "")
    if not tid:
        return None, []
    dr = dr_module()
    if dr is None:
        return None, ["auto-merge skipped: dispatch_repos module not "
                      "found on this host — merge by hand"]
    a = card.get("action") or {}
    pseudo = {"id": cid,
              "expected_goals": card.get("expected_goals"),
              "action": {"type": "dispatch", "task_id": tid,
                         "repo": a.get("repo") or "chaba"}}
    try:
        res = dr.close_out(pseudo)
    except Exception as e:
        res = {"merged": False, "error": f"{type(e).__name__}: {e}"}
    notes = dr.close_out_notes(res)
    if res.get("merged"):
        return True, notes
    if res.get("conflicts") or res.get("test_failures") or (
            res.get("gate") and not res["gate"]["ok"]):
        return False, notes
    return None, notes


def claimable(card: dict) -> str:
    """task type the card wants if this host may claim it, else ""."""
    a = card.get("action") or {}
    if a.get("status") != "queued":
        return ""
    if a.get("runner") and a["runner"] != HOST:
        return ""  # queued but tagged with another host's runner
    pinned = a.get("host")
    if pinned and pinned != HOST:
        return ""
    needs = set(a.get("labels") or [])
    if not needs <= LABELS:
        return ""
    typ = a.get("type") or "dispatch"
    if typ == "dispatch" and not Path(DISPATCH).exists():
        return ""
    if typ == "container":
        c = a.get("container") or {}
        if not c.get("image") or not shutil_which("podman"):
            return ""
    elif typ == "script":
        c = a.get("script") or {}
        url = c.get("repo_url") or REPO_URLS.get(c.get("repo", "chaba"))
        if not c.get("cmd") or not url or not shutil_which("git"):
            return ""
    elif typ != "dispatch":
        return ""
    return typ


def shutil_which(name: str) -> bool:
    return any((Path(p) / name).exists()
               for p in os.environ.get("PATH", "").split(":"))


# --- task unit resource limits ---------------------------------------

def _mem_total_gb() -> float:
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            if ln.startswith("MemTotal:"):
                return float(ln.split()[1]) / 1048576
    except (OSError, ValueError):
        pass
    return 0.0


def task_cpu_quota() -> str:
    """Explicit env wins; default leaves ~25% of CPU for the desktop."""
    if TASK_CPU_QUOTA:
        return TASK_CPU_QUOTA
    return f"{max(100, (os.cpu_count() or 2) * 75)}%"


def task_mem_max() -> str:
    if TASK_MEM_MAX:
        return TASK_MEM_MAX
    gb = _mem_total_gb()
    return f"{max(1, int(gb * 0.75))}G" if gb else ""


def task_run_props() -> list:
    """--property= args for systemd-run when task limits are armed."""
    if not LIMITS_ON:
        return []
    props = [f"--property=Nice={TASK_NICE}",
             f"--property=CPUWeight={TASK_CPU_WEIGHT}",
             f"--property=CPUQuota={task_cpu_quota()}"]
    mm = task_mem_max()
    if mm:
        props.append(f"--property=MemoryMax={mm}")
    if TASK_IO_CLASS.lower() not in ("", "none"):
        props += [f"--property=IOSchedulingClass={TASK_IO_CLASS}",
                  f"--property=IOSchedulingPriority={TASK_IO_PRIO}"]
    if TASK_IO_WEIGHT:
        props.append(f"--property=IOWeight={TASK_IO_WEIGHT}")
    return props


def unit_pids(unit: str) -> list:
    """PIDs in the unit's cgroup (cgroup v2), MainPID fallback."""
    r = sh(["systemctl", "--user", "show", unit,
            "-p", "ControlGroup", "--value"], timeout=15)
    cg = r.stdout.strip()
    if cg:
        try:
            pids = ((Path("/sys/fs/cgroup") / cg.lstrip("/"))
                    / "cgroup.procs").read_text().split()
            if pids:
                return pids
        except OSError:
            pass
    r = sh(["systemctl", "--user", "show", unit,
            "-p", "MainPID", "--value"], timeout=15)
    pid = r.stdout.strip()
    return [pid] if pid.isdigit() and pid != "0" else []


def renice_unit(unit: str, nice: int) -> None:
    """nice + ionice a running unit's processes; children inherit."""
    pids = unit_pids(unit)
    if not pids:
        return
    sh(["renice", "-n", str(nice), "-p"] + pids, timeout=15)
    cls = TASK_IO_CLASS.lower()
    if shutil_which("ionice") and cls not in ("", "none"):
        cid = {"realtime": "1", "best-effort": "2", "idle": "3"}.get(cls)
        if cid:
            sh(["ionice", "-c", cid, "-n", str(TASK_IO_PRIO),
                "-p"] + pids, timeout=15)


def enforce_task_limits(unit: str) -> None:
    """Apply the cgroup props to a RUNNING unit — the dispatch path's
    unit is created inside devin-dispatch, so this covers hosts whose
    devin-dispatch predates DISPATCH_UNIT_PROPS. Nice isn't a cgroup
    property, hence the renice."""
    if not LIMITS_ON:
        return
    props = [f"CPUQuota={task_cpu_quota()}",
             f"CPUWeight={TASK_CPU_WEIGHT}"]
    if TASK_IO_WEIGHT:
        props.append(f"IOWeight={TASK_IO_WEIGHT}")
    mm = task_mem_max()
    if mm:
        props.append(f"MemoryMax={mm}")
    sh(["systemctl", "--user", "set-property", unit] + props, timeout=20)
    renice_unit(unit, TASK_NICE)


# --- gpu card pre-flight ----------------------------------------------

def card_gpu_need_mb(card: dict) -> int:
    """VRAM the card wants free before claiming: action.gpu.min_free_mb
    (bare int accepted), action.min_vram_mb / gpu_min_free_mb / vram_mb."""
    a = card.get("action") or {}
    g = a.get("gpu")
    need = 0
    if isinstance(g, dict):
        need = g.get("min_free_mb") or g.get("vram_mb") or 0
    elif isinstance(g, (int, float)):
        need = g
    for k in ("min_vram_mb", "gpu_min_free_mb", "vram_mb"):
        need = need or a.get(k) or 0
    try:
        return int(need)
    except (TypeError, ValueError):
        return 0


_GPU_PROBE = [0.0, None]  # [ts, result] — nvidia-smi per card per pass
                         # is wasteful; cache for a minute


def gpu_free_mb() -> tuple:
    """(free_mb, total_mb) of the emptiest NVIDIA GPU, or None when
    nvidia-smi is missing/failed. Cached 60s — preflight calls it once
    per queued gpu card."""
    now = time.time()
    if now - _GPU_PROBE[0] < 60:
        return _GPU_PROBE[1]
    best = None
    if shutil_which("nvidia-smi"):
        try:
            r = sh(["nvidia-smi",
                    "--query-gpu=memory.free,memory.total",
                    "--format=csv,noheader,nounits"], timeout=20)
            if r.returncode == 0:
                for ln in r.stdout.splitlines():
                    parts = [p.strip() for p in ln.split(",")]
                    if len(parts) >= 2 and parts[0].isdigit() \
                            and parts[1].isdigit():
                        free, tot = int(parts[0]), int(parts[1])
                        if best is None or free > best[0]:
                            best = (free, tot)
        except subprocess.TimeoutExpired:
            pass
    _GPU_PROBE[0], _GPU_PROBE[1] = now, best
    return best


def gpu_preflight(card: dict) -> str:
    """'' when a card may be claimed, else the defer/refuse reason —
    evaluated BEFORE the claim POST so a deferred card stays queued."""
    labels = set((card.get("action") or {}).get("labels") or [])
    if "gpu" not in labels:
        return ""
    need = max(card_gpu_need_mb(card), GPU_MIN_FREE_MB)
    if need <= 0:
        return ""
    probe = gpu_free_mb()
    if probe is None:
        return ("nvidia-smi unavailable — can't verify VRAM for a "
                "gpu-labeled card")
    free, total = probe
    if need > total:
        return (f"needs {need}MB free VRAM but the GPU only has "
                f"{total}MB total — it can never fit; fix the spec "
                f"(smaller model) or drop the gpu label")
    if free < need:
        return f"free VRAM {free}MB < need {need}MB — deferred"
    return ""


def note_gpu_defer(card: dict, reason: str) -> None:
    """Comment a gpu defer/refuse — at most once per GPU_DEFER_SECS per
    distinct reason."""
    cid = card.get("id") or ""
    try:
        log = json.loads(DEFER_FILE.read_text())
    except Exception:
        log = {}
    ent = log.get(cid) or {}
    now = int(time.time())
    if ent.get("reason") == reason and \
            now - int(ent.get("at", 0)) < GPU_DEFER_SECS:
        return
    api("/comment", {"id": cid, "from": "chaba",
                     "text": f"gpu preflight: {reason}"})
    log[cid] = {"at": now, "reason": reason}
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        DEFER_FILE.write_text(json.dumps(log, indent=1))
    except OSError:
        pass


# --- presentation watchdog --------------------------------------------

def _x_displays() -> list:
    """':N' for each live X socket."""
    try:
        return [f":{s.name[1:]}"
                for s in sorted(Path("/tmp/.X11-unix").glob("X*"))
                if s.name[1:].isdigit()]
    except OSError:
        return []


def _xauthority() -> str:
    for p in (os.environ.get("XAUTHORITY"),
              f"/run/user/{os.getuid()}/gdm/Xauthority",
              str(Path.home() / ".Xauthority")):
        if p and Path(p).exists():
            return p
    return ""


def vsync_flood_hits() -> int:
    """Stall-signature count in the last ~2min of journal + Xorg logs.
    A healthy desktop logs this never; the wedge floods it."""
    hits = 0
    try:
        r = sh(["journalctl", "-o", "cat",
                "--since", f"@{int(time.time()) - 120}",
                "-n", "4000", "--no-pager"], timeout=25)
        if r.returncode == 0:
            hits += sum(1 for ln in r.stdout.splitlines()
                        if VSYNC_PAT in ln)
    except subprocess.TimeoutExpired:
        pass
    for name in (Path.home() / ".local/share/xorg/Xorg.0.log",
                 Path("/var/log/Xorg.0.log")):
        try:
            r = sh(["tail", "-c", "1048576", str(name)], timeout=10)
            if r.returncode == 0:
                hits += sum(1 for ln in r.stdout.splitlines()
                            if VSYNC_PAT in ln)
        except subprocess.TimeoutExpired:
            pass
    return hits


def xrandr_probe() -> str:
    """'' when every live X display answers `xrandr --verbose` quickly —
    a wedged presentation path stalls or fails the query. Only failures
    count: a plain answer doesn't prove vblank flows."""
    if not shutil_which("xrandr"):
        return ""
    xa = _xauthority()
    for disp in _x_displays():
        env = dict(os.environ, DISPLAY=disp)
        if xa:
            env["XAUTHORITY"] = xa
        try:
            r = sh(["xrandr", "--verbose"], timeout=XRANDR_TIMEOUT,
                   env=env)
        except subprocess.TimeoutExpired:
            return f"xrandr {disp} timed out ({XRANDR_TIMEOUT}s)"
        if r.returncode != 0:
            err = (r.stderr or "") + (r.stdout or "")
            if "Can't open display" in err or "uthorization" in err:
                continue  # auth/perm issue — not a wedge signal
            return f"xrandr {disp} rc={r.returncode}"
    return ""


def display_stalled() -> tuple:
    """(stalled, detail) — either signal alone is enough."""
    hits = vsync_flood_hits()
    if hits >= VSYNC_FLOOD_MIN:
        return True, f"vsync stall signature x{hits} in ~2min of logs"
    xr = xrandr_probe()
    if xr:
        return True, xr
    return False, ""


def watchdog_pass(st: dict) -> bool:
    """Guard the desktop while a gpu task runs. Stall strikes: 1 =
    deprioritize (renice + tight CPUQuota), >=WD_STRIKES = SIGSTOP the
    unit. WD_HEALTHY consecutive healthy probes SIGCONT a task we
    paused. State lives in the entry's `wd` dict."""
    if not WD_ON:
        return False
    entries = {cid: e for cid, e in st.items()
               if e.get("gpu") and e.get("unit")}
    if not entries:
        return False
    if not any(unit_active(e["unit"]) for e in entries.values()):
        return False
    stalled, detail = display_stalled()
    changed = False
    for cid, e in entries.items():
        unit = e["unit"]
        wd = e.setdefault("wd", {})
        if stalled:
            if not unit_active(unit):
                continue  # exited mid-stall — finish_pass reports it
            wd["healthy"] = 0
            wd["strikes"] = wd.get("strikes", 0) + 1
            changed = True
            if wd["strikes"] == 1:
                sh(["systemctl", "--user", "set-property", unit,
                    f"CPUQuota={WD_CPU_QUOTA}"], timeout=15)
                renice_unit(unit, WD_NICE)
                api("/comment", {"id": cid, "from": "chaba",
                    "text": f"display watchdog: {detail} — deprioritized "
                            f"{unit} (nice {WD_NICE}, CPUQuota "
                            f"{WD_CPU_QUOTA}); will pause if the stall "
                            f"persists"})
            elif wd["strikes"] >= WD_STRIKES and not wd.get("paused"):
                sh(["systemctl", "--user", "kill", "--kill-whom=all",
                    "--signal", "SIGSTOP", unit], timeout=15)
                wd["paused"] = True
                api("/comment", {"id": cid, "from": "chaba",
                    "text": f"display watchdog: still stalled ({detail}) "
                            f"— PAUSED {unit} (SIGSTOP). " + UNSTICK +
                            f"; resume the task with `systemctl --user "
                            f"kill -s SIGCONT {unit}` (or wait — the "
                            f"watchdog auto-resumes on healthy probes)"})
            elif wd.get("paused") and wd["strikes"] == WD_STRIKES + 8:
                api("/comment", {"id": cid, "from": "chaba",
                    "text": f"display watchdog: {unit} still paused, "
                            f"display still stalled ~10min on — "
                            + UNSTICK})
        else:
            wd["strikes"] = 0
            if wd.get("paused"):
                wd["healthy"] = wd.get("healthy", 0) + 1
                changed = True
                if wd["healthy"] >= WD_HEALTHY:
                    sh(["systemctl", "--user", "kill", "--kill-whom=all",
                        "--signal", "SIGCONT", unit], timeout=15)
                    wd["paused"] = False
                    wd["healthy"] = 0
                    enforce_task_limits(unit)  # undo the throttle
                    api("/comment", {"id": cid, "from": "chaba",
                        "text": f"display watchdog: probes healthy — "
                                f"resumed {unit} (SIGCONT)"})
    return changed


def start_task(card: dict, typ: str) -> tuple:
    """Kick off the claimed card; returns (unit_name, task_id, error)."""
    cid = card["id"]
    a = card.get("action") or {}
    unit = re.sub(r"[^a-zA-Z0-9_-]", "-",
                  f"runner-{cid}-{int(time.time())}")[:60]
    if typ == "container":
        c = a.get("container") or {}
        cmd = c.get("cmd")
        cmd = (["sh", "-c", cmd] if isinstance(cmd, str)
               else [str(x) for x in (cmd or [])])
        env = []
        for k, v in (c.get("env") or {}).items():
            env += ["-e", f"{k}={v}"]
        argv = (["systemd-run", "--user", f"--unit={unit}", "--collect",
                 "--description", f"runner {cid}"] + task_run_props() +
                ["podman", "run", "--rm",
                 f"--pull={c.get('pull', 'missing')}",
                 f"--name={unit}"] + env +
                [str(c["image"])] + cmd)
    elif typ == "script":
        c = a.get("script") or {}
        url = c.get("repo_url") or REPO_URLS.get(c.get("repo", "chaba"))
        try:
            path = sync_repo(c.get("repo", "chaba"), url,
                             c.get("ref") or "master")
        except RuntimeError as e:
            return "", "", str(e)[:240]
        workdir = str(path / (c.get("workdir") or "."))
        cmd = c.get("cmd")
        cmd = (["bash", "-lc", cmd] if isinstance(cmd, str)
               else [str(x) for x in cmd])
        env = []
        for k, v in (c.get("env") or {}).items():
            env += ["--setenv", f"{k}={v}"]
        argv = (["systemd-run", "--user", f"--unit={unit}", "--collect",
                 f"--property=RuntimeMaxSec={int(c.get('timeout', 1800))}",
                 "--description", f"runner {cid}"] + task_run_props() +
                env +
                ["bash", "-lc",
                 f"cd {shlex.quote(workdir)} && "
                 f"exec {shlex.join(cmd)}"])
    else:  # dispatch
        spec = (card.get("spec") or "").strip() or \
            f"{card.get('title', '')}\n\n{card.get('note', '')}"
        task = spec + "\n\n" + RAILS.format(id=cid, host=HOST, api=API)
        argv = [DISPATCH, "start", a.get("repo", "chaba"), task]
    env = dict(os.environ)
    if a.get("model"):
        env["DISPATCH_MODEL"] = str(a["model"])
    if typ == "dispatch" and LIMITS_ON:
        # devin-dispatch splices this into its systemd-run call;
        # enforce_task_limits below re-applies the cgroup props on the
        # live unit for hosts with a stale devin-dispatch.
        env["DISPATCH_UNIT_PROPS"] = " ".join(task_run_props())
    r = sh(argv, timeout=180, env=env)
    if r.returncode != 0:
        return "", "", (r.stderr or r.stdout).strip()[:240]
    tid = ""
    if typ == "dispatch":
        # devin-dispatch prints the task id (unit is devin-task-<id>)
        tid = r.stdout.strip().splitlines()[-1].strip()
        unit = f"devin-task-{tid}"
        enforce_task_limits(unit)
    return unit, tid, ""


def finish_pass(st: dict) -> bool:
    """Report claimed tasks whose units exited. Returns state changed."""
    changed = False
    cards = None  # lazy /cards fetch — only the close-out needs it
    for cid, ent in list(st.items()):
        unit = ent.get("unit") or ""
        if not unit or unit_active(unit):
            continue
        ok, result = collect(unit)
        verified, notes = None, []
        if ok and ent.get("type") == "dispatch":
            if cards is None:
                cards = {c.get("id"): c for c in
                         (api("/cards") or {}).get("cards") or []}
            verified, notes = close_out_merge(cid, ent,
                                              cards.get(cid) or {})
        body = {"id": cid, "do": "finish", "host": HOST,
                "ok": ok, "result": result}
        if verified is not None:
            body["verified"] = verified
        resp = api("/action", body)
        for n in notes:
            api("/comment", {"id": cid, "from": "chaba", "text": n})
        err = resp.get("error") or ""
        if not err or "not running" in err or "claimed by" in err \
                or "no card" in err:
            del st[cid]  # reported, or card moved on — stop tracking
            changed = True
            print(f"{cid}: finish {'ok' if ok else 'failed'} — {err or 'reported'}")
    return changed


def overloaded() -> bool:
    """5-min load per core above MAX_LOAD_PC → don't claim new work."""
    if MAX_LOAD_PC <= 0:
        return False
    try:
        return os.getloadavg()[1] / (os.cpu_count() or 1) > MAX_LOAD_PC
    except OSError:
        return False


def blocker_released(blocker: dict) -> bool:
    """blocked_by releases when the blocker finished AND its merge
    didn't fail verification (dependents need its code on origin).
    Manual blockers release on column=done (closed by a human)."""
    ba = blocker.get("action") or {}
    if blocker.get("column") == "done":
        return True
    return ba.get("status") == "done" and ba.get("verified") is not False


def claim_pass(st: dict) -> bool:
    if len(st) >= CAP:
        return False
    if overloaded():
        return False
    cards = (api("/cards") or {}).get("cards") or []
    by_id = {c.get("id"): c for c in cards}
    changed = False
    for card in cards:
        if len(st) >= CAP:
            break
        cid = card.get("id") or ""
        typ = claimable(card)
        if typ and card.get("blocked_by"):
            blocker = by_id.get(card["blocked_by"]) or {}
            if not blocker_released(blocker):
                continue  # gate holds — try again next pass
        if not cid or not typ:
            continue
        reason = gpu_preflight(card)
        if reason:
            note_gpu_defer(card, reason)
            continue  # stays queued — a later pass or spec fix picks it up
        resp = api("/action", {"id": cid, "do": "claim", "host": HOST})
        if resp.get("error"):
            continue  # lost the race or rejected — next card
        unit, tid, err = start_task(card, typ)
        if err:
            api("/action", {"id": cid, "do": "finish", "host": HOST,
                            "ok": False, "result": f"start failed: {err}"})
            continue
        api("/comment", {"id": cid, "from": "chaba",
                         "text": f"started {unit} on {HOST} ({typ})"})
        st[cid] = {"unit": unit, "type": typ, "tid": tid,
                   "at": int(time.time()),
                   "gpu": "gpu" in set((card.get("action") or {})
                                      .get("labels") or [])}
        changed = True
        print(f"{cid}: claimed + started {unit}")
    return changed


def main() -> int:
    st = load_state()
    changed = finish_pass(st) | watchdog_pass(st) | claim_pass(st)
    if changed:
        save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
