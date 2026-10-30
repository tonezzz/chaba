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
     Claimable cards drain in the shared priority order
     (dispatch_repos.claim_sort_key — card dispatch-priority-order):
     starved (>=RUNNER_STARVE_HOURS old) first, then priority
     high > medium > absent > low, then oldest `updated`. A host whose
     chaba checkout can't resolve dispatch_repos falls back to API
     order — the queue still drains (fleet-health flags that host).
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
  RUNNER_API     board api base — default the tailnet serve route on the
                 canonical writer host (idc03) so the same value works on
                 every host
  RUNNER_HOST    hostname claim identity (default: uname nodename)
  RUNNER_CAP     max concurrent claimed tasks (default 2)
  RUNNER_MAX_LOAD_PC  stop claiming when 5-min load per core exceeds
                 this (default 1.0; 0 disables — protects the host and
                 yields the queue to idle runners)
  RUNNER_LABELS  comma-separated capability labels (e.g. "gpu,ssd";
                 "desktop" marks an interactive host and arms the
                 guards below; "push:<repo>" declares push credentials
                 for that dispatch repo — see RUNNER_PUSH_GUARD)
  RUNNER_PUSH_GUARD   0 disables the push-credential claim guard
                 (runner-push-cred-gap): a dispatch card is only
                 claimable when this host can actually push the card's
                 repo — `push:<repo>` label fast-path, else a live
                 `git push --dry-run` probe against the host checkout
                 (a git@ remote is no proof — the 2026-10-14 ADA-0673
                 failure was a chaba-only deploy key on an ssh-looking
                 ada-voice clone). Cards this host can't push stay
                 queued for a host that can, with a debounced comms
                 note.
  RUNNER_PUSH_PROBE_TTL  probe-cache seconds (default 300)
  RUNNER_STATE   state dir (default ~/.local/share/runner-agent)
  RUNNER_STARVE_HOURS  queued-card age that outranks fresh higher-
                 priority cards (default 12; 0 disables — priority is a
                 bias, not a ban)

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

Worktree GC (card dispatch-worktree-gc): when the close-out result
leaves a session worktree whose head is provably on origin, the
worktree+branch are removed locally (dr.gc_session — never dirty trees,
never unmerged branches; KANBAN_WTGC=0 disables). Merge-sweep runs the
same cleanup on this host over ssh when it salvaged the merge from
dell's side.
"""

import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = os.environ.get(
    "RUNNER_API",
    "https://idc03.taila0626a.ts.net:10000").rstrip("/")
# dispatch_repos.board_api_base() reads BOARD_API/RUNNER_API — export the
# resolved base so the close-out patch-relay posts to the same api.
os.environ.setdefault("BOARD_API", API)
HOST = os.environ.get("RUNNER_HOST") or os.uname().nodename
CAP = int(os.environ.get("RUNNER_CAP", "2"))
MAX_LOAD_PC = float(os.environ.get("RUNNER_MAX_LOAD_PC", "1.0"))
LABELS = {x.strip() for x in os.environ.get("RUNNER_LABELS", "").split(",")
          if x.strip()}
STATE_DIR = Path(os.environ.get(
    "RUNNER_STATE", str(Path.home() / ".local/share/runner-agent")))
STATE_FILE = STATE_DIR / "state.json"
READY_REPORT = STATE_DIR / "ready-verdicts.json"
# /ready reports are debounced by payload hash; a forced refresh every
# READY_FORCE_S keeps 'stale' detection honest on quiet boards.
READY_FORCE_S = int(os.environ.get("RUNNER_READY_FORCE_S", "900"))
# Starvation guard for the shared claim order (dispatch_repos).
STARVE_HOURS = float(os.environ.get("RUNNER_STARVE_HOURS", "12"))
DISPATCH = os.environ.get(
    "DEVIN_DISPATCH", str(Path.home() / ".local/bin/devin-dispatch"))

# Lane -> cheapest model (jev-pilot Phase 2). Mirrors kanban-dispatch.
LANE_MODELS = {
    "free_lane": "litellm/gemini-3.5-flash-lite",
    "paid_frontier": "litellm/or-claude-fable-5.1",
}
OPENCODE_LANES = os.environ.get("OPENCODE_LANES", "0") == "1"
# lane -> task-scoped opencode profile (opencode-task-agent-profiles).
# The generic build agent is NEVER an unattended executor: a lane only
# reaches opencode when a profile resolves (action.profile wins, else
# this map). Unmapped lanes keep the devin path. free_lane = cheap
# single-step chores -> ops-readonly (read-only reports only; write-
# needing work stays on devin). branch-code is deliberately unmapped —
# it is disabled until its own card enables it.
LANE_PROFILES = {
    "free_lane": "ops-readonly",
}
# Executor contract (opencode-explicit-executor-routing). Mirrors
# dispatch_repos.EXECUTORS — kept local because this file deploys as a
# single file and may run where dispatch_repos isn't importable.
EXECUTORS = {"opencode", "devin", "script", "manual", "kk_mac_local"}
# kk_mac_local executor contract (kk-mac-jev-adapter-integration):
# bounded read-only LLM lane on KKs-Mac-Studio. Try-first, not strict —
# the admitted task classes mirror kk_mac_llm.ALLOWED_TASKS; a card the
# lane can't serve falls back to the next lane under the same claim.
# KK_MAC_LANES=1 marks this host as able to serve it — off by default
# until the supervised live dispatch passes.
KK_MAC_LANES = os.environ.get("KK_MAC_LANES", "0") == "1"
KK_MAC_TASK_CLASSES = {
    "summary", "operator_brief", "structured_extract", "safe_route"}
KK_MAC_FALLBACK = "__kk_mac_fallback__"


def card_profile(card: dict) -> str:
    """Declared OpenCode profile: action.agent_profile (contract name)
    wins; action.profile is the pre-contract alias."""
    a = card.get("action") or {}
    return str(a.get("agent_profile") or a.get("profile") or "").strip()


def model_provider(model: str) -> str:
    """'litellm/x' -> 'litellm'; a bare model id -> 'devin'."""
    m = (model or "").strip()
    if not m:
        return ""
    return m.split("/", 1)[0] if "/" in m else "devin"


LANE_KW = {
    "manual": ["hardware", "buy", "usb cam", "camera", "physical",
               "spend", "order the", "blocked on tony", "rotation", "rekey",
               "lease teardown", "sudo-gated", "restore.*macbook",
               "enroll.*macbook", "macbook.*restore", "macbook.*enroll"],
    "paid_frontier": ["test hook", "stagnation gate", "decision layer",
                      "construct", "register_post_type", "rename", "design a",
                      "implement a", "code fix", "op=list", "add /lesson",
                      "versus", "benchmark", "bench ", "productionize",
                      "promotion gate", "hardening", "hybrid recall",
                      "discussion board", "work bridge"],
    "codemod": ["config", "retire", "remove", "bump", "lock", "change the",
                "parallelism", "raise ", "cap", "flag", "script",
                "copies task tests", "inject", "drift", "delete old", "purge",
                "schedule", "recurring", "nest job"],
    "devin": ["shims", "wiring", "multi-repo", "backfill", "re-embed",
              "roster", "protocol", "provision", "host", "feature",
              "automation", "diagnos", "experiment", "pipeline", "end-to-end",
              "quadlet", "warm standby", "repoint", "failing", "dep fix",
              "dependency"],
    "free_lane": ["install", "try", "launch", "write the", "design doc",
                  "plan", "evaluate", "gui", "probe", "report", "fixture"],
}
LANE_COMPARE = r"(vs|versus|or)\s+(\w+\s+)?(lane|option|choice|path|approach)"


def classify_lane(card: dict) -> str:
    """Cheapest lane for this card (keyword-first, devin-safe fallback)."""
    import re as _re
    text = (card.get("title", "") + " " +
            (card.get("brief") or card.get("spec") or "")).lower()
    if any(k in text for k in LANE_KW["manual"]):
        return "manual"
    if _re.search(LANE_COMPARE, text):
        return "paid_frontier"
    for lane, kws in (("paid_frontier", LANE_KW["paid_frontier"]),
                      ("codemod", LANE_KW["codemod"]),
                      ("devin", LANE_KW["devin"]),
                      ("free_lane", LANE_KW["free_lane"])):
        if any(k in text for k in kws):
            return lane
    return "devin"

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

# --- push-credential claim guard (runner-push-cred-gap) ---------------
# A runner must only claim dispatch cards for repos it can push. The
# ADA-0673 failure (2026-10-14): tony-macbook's ada-voice clone looked
# ssh-capable but its deploy key was chaba-only — it claimed, finished,
# checkpointed, and pushed nothing, stranding the branch while the card
# read done. Declare `push:<repo>` in RUNNER_LABELS only after a real
# `git push --dry-run` passes — the label is the fast path, the probe
# is the ground truth (run once per TTL, not per card).
PUSH_GUARD = os.environ.get("RUNNER_PUSH_GUARD", "1") != "0"
PUSH_PROBE_TTL = int(os.environ.get("RUNNER_PUSH_PROBE_TTL", "300"))
PUSH_PROBE_REF = "refs/heads/__runner-push-probe"
_PUSH_PROBE_CACHE: dict = {}
REPO_ALIASES = {"ada-pi": "ada-voice"}  # one repo, one credential


def _repo_checkout(repo: str) -> Path | None:
    """This host's checkout of a dispatch repo — the same table
    devin-dispatch dispatches against ($DISPATCH_DIR/repos.conf), then
    the chaba copy of dispatch_repos when importable."""
    conf = Path(os.environ.get(
        "DISPATCH_DIR",
        str(Path.home() / ".local/share/devin-dispatch"))) / "repos.conf"
    paths = {}
    try:
        for ln in conf.read_text().splitlines():
            ln = ln.split("#", 1)[0].strip()
            p = ln.split()
            if p:
                paths[p[0]] = Path(p[1]).expanduser()
    except OSError:
        pass
    canon = REPO_ALIASES.get(repo, repo)
    p = paths.get(repo) or paths.get(canon)
    if p:
        return p
    dr = dr_module()
    if dr:
        ent = (dr.repos().get(repo) or dr.repos().get(canon) or {})
        if ent.get("path"):
            return Path(ent["path"])
    return None


def push_capable(repo: str) -> bool:
    """May this host claim dispatch cards for repo? Declared push:<repo>
    label wins; otherwise a live `git push --dry-run` probe — only the
    auth path knows whether the key actually covers the repo."""
    if not PUSH_GUARD:
        return True
    canon = REPO_ALIASES.get(repo, repo)
    if f"push:{canon}" in LABELS or f"push:{repo}" in LABELS:
        return True
    now = time.time()
    hit = _PUSH_PROBE_CACHE.get(canon)
    if hit and now - hit[0] < PUSH_PROBE_TTL:
        return hit[1]
    p = _repo_checkout(canon)
    ok = bool(p) and (p / ".git").exists() and \
        sh(["git", "-C", str(p), "push", "--dry-run", "origin",
            f"HEAD:{PUSH_PROBE_REF}"], timeout=45).returncode == 0
    _PUSH_PROBE_CACHE[canon] = (now, ok)
    return ok


def push_guard_reason(card: dict) -> str:
    """Why this host declines an otherwise-claimable dispatch card —
    "" when N/A (not dispatch, not claimable anyway, or push works)."""
    a = card.get("action") or {}
    if (a.get("type") or "dispatch") != "dispatch" \
            or a.get("status") != "queued" \
            or (a.get("runner") and a["runner"] != HOST) \
            or (a.get("host") and a["host"] != HOST) \
            or not set(a.get("labels") or []) <= LABELS \
            or not Path(DISPATCH).exists():
        return ""
    repo = str(a.get("repo") or "chaba")
    if push_capable(repo):
        return ""
    canon = REPO_ALIASES.get(repo, repo)
    return (f"push guard: no push:{canon} label and `git push --dry-run` "
            f"fails in {_repo_checkout(canon) or '(no checkout)'} — this "
            "host can't land the branch, so the card stays queued for a "
            "host with push creds (card runner-push-cred-gap)")


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

# OpenCode profile agents hold no board-api write path — the read-only
# bash allowlist denies curl/python POSTs, and a denied call counts as a
# contract violation at closeout. Their rails must not instruct the
# progress/request posts the devin executor uses; the runner itself
# writes claim/start/finish comms.
RAILS_OPENCODE = """
---
Rails: you are processing kanban card '{id}' on runner '{host}'.
- Do NOT push to git remotes unless the card spec explicitly says to.
- Do NOT call board-api or any network endpoint — the runner records
  progress and verdicts itself. Emit only what the task contract asks
  as your final message.
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
    """(ok, result-text) from the finished unit's exit evidence.

    Precedence (mirrors dispatch_repos.unit_exit_evidence and
    merge-sweep's verified gate): the task dir's exit_code file (the
    devin-dispatch wrapper writes it every run; survives systemd
    --collect) > the unit's own fields while it is still loaded (a
    --collect'ed unit reports ExecMainStatus=0/Result=success DEFAULTS
    — the 2026-10-25/26 'Failed with result exit-code' sessions that
    still reported 'finished (ok)') > journal Succeeded/Failed lines.
    No usable record -> NOT ok: an unproven exit must never report
    success, or dead sessions close as clean work again."""
    r = sh(["systemctl", "--user", "show", unit,
            "-p", "ExecMainStatus", "-p", "Result", "-p", "LoadState"],
           timeout=15)
    kv = dict(ln.split("=", 1) for ln in r.stdout.splitlines()
              if "=" in ln)
    j = sh(["journalctl", "--user", "-u", unit, "-n", "60",
            "--no-pager", "-o", "cat"], timeout=15)
    jout = j.stdout or ""
    tail = " | ".join(x for x in jout.strip().splitlines() if x)[-240:]
    # task-dir exit_code — only devin-task-* units have a task dir
    # (followups devin-task-<id>-fuN share the base task dir)
    if unit.startswith("devin-task-"):
        base = re.sub(r"-fu\d+$", "",
                      unit.removeprefix("devin-task-")
                      .removesuffix(".service"))
        try:
            ecp = (Path.home() / ".local/share/devin-dispatch/tasks"
                   / base / "exit_code")
            ec = ecp.read_text().strip() if ecp.is_file() else ""
        except Exception:
            ec = ""
        if ec:
            return ec == "0", f"exit={ec} {tail}".strip()
    if kv.get("LoadState") == "loaded":
        ok = (kv.get("ExecMainStatus") == "0"
              and kv.get("Result") == "success")
        return ok, f"exit={kv.get('ExecMainStatus', '?')} {tail}".strip()
    hits = re.findall(r"Succeeded\.|Failed with result '[a-z-]+'", jout)
    if hits:
        jr = ("success" if hits[-1] == "Succeeded."
              else hits[-1].split("'")[1])
        return jr == "success", f"journal={jr} {tail}".strip()
    return False, (f"no exit record — unit {kv.get('LoadState') or 'gone'} "
                   "reports collected defaults (unproven, not ok) "
                   + tail).strip()


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
    # card dispatch-worktree-gc — once the head is provably on origin the
    # session worktree+branch go now; dirty/unproven trees always keep.
    # getattr: dr may resolve to a stale host checkout lacking gc_session.
    gc = getattr(dr, "gc_session", None)
    if gc:
        notes += gc(res)
    if res.get("merged"):
        return True, notes
    if res.get("conflicts") or res.get("test_failures") \
            or res.get("shadows") or (
            res.get("gate") and not res["gate"]["ok"]):
        return False, notes
    return None, notes


def finish_opencode_lane(cid: str, ent: dict, card: dict) -> tuple:
    """Executor-contract closeout for OpenCode lanes — runs BEFORE
    close_out_merge so a landed artifact is checkpointed into the
    session branch by the normal merge gate.

    Returns (ok_to_merge: bool, notes). True when this isn't an OpenCode
    task (nothing to do) or when the declared artifact landed AND the
    held-out verifier passed; False holds the merge — the card fails
    verified=False with the evidence in comms and the worktree kept.
    A card with no declared action.artifact skips landing/verify and
    only gets the usage/audit enrichment (contract evidence is still
    durable: exit_code + events.jsonl + usage.json + manifest)."""
    tid = ent.get("tid") or ""
    if not tid:
        unit = ent.get("unit") or ""
        tid = (unit[len("devin-task-"):]
               if unit.startswith("devin-task-") else "")
    if not tid:
        return True, []
    taskdir = Path.home() / ".local/share/devin-dispatch/tasks" / tid
    try:
        meta = json.loads((taskdir / "meta.json").read_text())
    except Exception:
        return True, []  # no meta -> not an opencode task
    if not str(meta.get("executor") or "").startswith("opencode"):
        return True, []
    ocp = oc_profiles_module()
    if ocp is None:
        return False, ["opencode closeout: opencode_profiles missing — "
                       "artifact/verifier can't run, merge held"]
    try:
        prof = ocp.load_profile(str(meta.get("profile") or ""))
    except Exception as e:
        return False, [f"opencode closeout: profile load failed: {e}"]
    ev = taskdir / "events.jsonl"
    env = {"id": tid, "card": cid,
           "mcp_allowlist": list((prof.get("mcp") or {}).get("allowed")
                                 or [])}
    audit = ocp.audit_events(ev, env, prof) if ev.is_file() else \
        {"tokens": {}, "tool_calls": [], "denials": [],
         "mutating_commands": [], "verifier_peeks": [],
         "write_attempts": []}
    try:
        usage = json.loads((taskdir / "usage.json").read_text())
    except Exception:
        usage = {}
    tok = audit["tokens"]
    try:
        usage["exit_code"] = int(
            (taskdir / "exit_code").read_text().strip())
    except Exception:
        usage["exit_code"] = None
    usage.update({
                  "input_tokens": tok.get("input") or 0,
                  "output_tokens": tok.get("output") or 0,
                  "cache_read_tokens": tok.get("cache_read") or 0,
                  "cache_write_tokens": tok.get("cache_write") or 0,
                  "tool_calls": len(audit["tool_calls"]),
                  "denials": audit["denials"],
                  "write_attempts": audit["write_attempts"],
                  "mutating": audit["mutating_commands"],
                  "verifier_peeks": audit["verifier_peeks"]})
    notes, verdict, landed = [], {"verdict": "skip", "checks": {}}, False
    a = card.get("action") or {}
    art_path = str(a.get("artifact") or "").strip()
    wt = Path(str(meta.get("worktree") or ""))
    if art_path:
        dirs = [str(d) for d in
                (prof.get("artifact") or {}).get("dirs") or []]
        if not any(art_path.startswith(d) for d in dirs):
            verdict = {"verdict": "fail",
                       "checks": {"artifact path under profile dirs":
                                  False}}
            notes.append(f"artifact {art_path!r} outside profile dirs "
                         f"{dirs}")
        else:
            amode = (prof.get("artifact") or {}).get("mode", "message")
            afmt = (prof.get("artifact") or {}).get("format", "json")
            content = None
            if amode == "message":
                text = ocp.final_text(ev) if ev.is_file() else ""
                content = ocp.extract_artifact(text, afmt) \
                    if text else None
                src = None
            else:
                src = wt / art_path
                if src.is_file():
                    content = src.read_text()
            if content:
                (taskdir / "artifact.out").write_text(content)
                dest = wt / art_path
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(
                        content + ("" if content.endswith("\n") else "\n"))
                    landed = True
                    notes.append(f"opencode artifact landed {art_path}")
                except OSError as e:
                    verdict = {"verdict": "fail",
                               "checks": {"artifact write": str(e)}}
            if not landed and verdict["verdict"] == "skip":
                verdict = {"verdict": "fail",
                           "checks": {"artifact landed": False}}
        # manifest + held-out verifier — the verifier never trusts the
        # agent's narrative (same contract as opencode_profiles._verify)
        man = {"at": datetime.now(timezone.utc).isoformat(),
               "job": tid,
               "envelope": {"id": tid, "card": cid, "target_host": HOST,
                            "model": meta.get("model"),
                            "executor": meta.get("executor"),
                            "profile": meta.get("profile"),
                            "artifact": {"path": art_path}},
               "profile": {k: v for k, v in prof.items()
                           if k != "_path"},
               "agent": ocp.agent_name(prof.get("id") or "")}
        (taskdir / "manifest.json").write_text(json.dumps(man, indent=1))
        if landed:
            vref = str((prof.get("verifier") or {}).get("ref") or "")
            vpath = Path("")
            for base in (wt, Path(str(meta.get("repo_root") or "."))):
                cand = base / vref
                if cand.is_file():
                    vpath = cand
                    break
            if not str(vpath) or not vpath.is_file():
                verdict = {"verdict": "fail",
                           "checks": {"verifier missing": vref}}
            else:
                try:
                    spec = importlib.util.spec_from_file_location(
                        f"pverify_{re.sub('[^a-zA-Z0-9]', '_', tid)}",
                        vpath)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    verdict = mod.verify(str(taskdir)) or {}
                    verdict.setdefault("checks", {})
                    verdict["verified_at"] = \
                        datetime.now(timezone.utc).isoformat()
                except Exception as e:
                    verdict = {"verdict": "fail",
                               "checks": {"verifier_error":
                                          f"{type(e).__name__}: {e}"[:300]}}
        # denials/mutating from the event audit are contract violations —
        # they fail the closeout even when the verifier itself passed
        if verdict.get("verdict") == "pass" and \
                (audit["denials"] or audit["mutating_commands"]):
            verdict = {"verdict": "fail",
                       "checks": {**verdict.get("checks", {}),
                                  "denials": audit["denials"][:5],
                                  "mutating":
                                  audit["mutating_commands"][:5]}}
        (taskdir / "verdict.json").write_text(json.dumps(verdict,
                                                        indent=1))
        notes.append(f"opencode verifier: {verdict.get('verdict')}")
    else:
        notes.append("no action.artifact declared — closeout evidence is "
                     "exit code + event audit only")
    usage["verdict"] = verdict.get("verdict")
    usage["artifact_landed"] = landed
    (taskdir / "usage.json").write_text(json.dumps(usage, indent=1))
    # lane_gate metric ledger — the durable accounting row for the run
    lg = getattr(ocp, "lane_gate", None)
    if lg:
        try:
            menv = {"id": tid, "card": cid, "profile": prof.get("id"),
                    "model": meta.get("model") or "",
                    "provider": meta.get("provider") or "",
                    "stage": "", "task_class": ""}
            m = lg.new_metric(menv, "opencode")
            m["input_tokens"] = tok.get("input") or 0
            m["output_tokens"] = tok.get("output") or 0
            m["cache_read_tokens"] = tok.get("cache_read") or 0
            m["cache_write_tokens"] = tok.get("cache_write") or 0
            m["verifier_pass"] = verdict.get("verdict") == "pass"
            m["artifact_landed"] = landed
            m["tool_denials"] = len(audit["denials"]) + \
                len(audit["write_attempts"])
            m["failure_reason"] = None if m["verifier_pass"] else \
                ("mutating_command" if audit["mutating_commands"]
                 else "tool_denial" if audit["denials"]
                 else "missing_artifact" if art_path and not landed
                 else "unverified_exit" if art_path
                 else "no_artifact_declared")
            lg.record_metric(m)
        except Exception:
            pass  # ledger is best-effort; usage.json is the contract copy
    if art_path and verdict.get("verdict") != "pass":
        checks = "; ".join(f"{k}={v}" for k, v in
                           list(verdict.get("checks", {}).items())[:4])
        notes.append("merge held — executor contract requires declared "
                     f"artifact + verifier pass ({checks})")
        return False, notes
    return True, notes


def _claimable(card: dict) -> tuple:
    """(task type, block reason) — typ ""/reason text when unclaimable.
    The gate order IS claimable(); the reason feeds /ready verdicts so
    the board can say *why* a card waits instead of silently starving."""
    a = card.get("action") or {}
    if a.get("status") != "queued":
        return "", "not queued"
    if a.get("runner") and a["runner"] != HOST:
        # queued but tagged with another host's runner
        return "", f"pinned to runner {a['runner']}"
    pinned = a.get("host")
    if pinned and pinned != HOST:
        return "", f"host-pinned to {pinned}"
    # executor contract host pin (action.target_host) — independent of
    # action.host; both must be satisfied.
    th = str(a.get("target_host") or "").strip()
    if th and th != HOST:
        return "", f"target_host {th}"
    needs = set(a.get("labels") or [])
    if not needs <= LABELS:
        return "", f"missing labels {sorted(needs - LABELS)}"
    ex = str(a.get("executor") or "").strip()
    # executor contract (opencode-explicit-executor-routing):
    # manual = Tony's hands — never claimed; an unrecognised executor is
    # an unintelligible contract — fail closed, don't guess a route.
    if ex == "manual":
        return "", "manual executor (Tony's hands)"
    if ex and ex not in EXECUTORS:
        return "", f"unknown executor {ex!r}"
    typ = a.get("type") or "dispatch"
    if ex and typ != "dispatch" and not (ex == "script" and typ == "script"):
        # executor contract routes dispatch-typed cards; on a
        # script/container card only a matching script executor is a
        # consistent declaration — anything else fails closed
        return "", f"executor={ex} cannot serve type={typ}"
    if ex == "script" and typ == "dispatch":
        # the contract routes a dispatch-typed card to the script
        # executor — it must carry a usable action.script block
        c = a.get("script") or {}
        url = c.get("repo_url") or REPO_URLS.get(c.get("repo", "chaba"))
        if c.get("cmd") and url and shutil_which("git"):
            return "script", ""
        return "", "executor=script needs action.script.cmd+repo+git"
    if typ == "dispatch":
        if a.get("lane") == "manual":
            # lane routing: manual = Tony's hands, never claimed
            return "", "manual lane"
        if ex == "kk_mac_local" and not a.get("kk_mac_tried"):
            # Try-first executor contract: a fresh kk_mac_local card is
            # claimed here only when this host can serve the lane —
            # otherwise it waits for a capable runner. The exception:
            # when the lane is currently INELIGIBLE the card just needs
            # its next lane, so any dispatch-capable host may claim it
            # (the run skips straight to the fallback path).
            if not kk_mac_contract_ok(a):
                return "", ("executor=kk_mac_local: task_class "
                            f"{a.get('task_class') or '(missing)'!r} not "
                            "admitted or artifact outside lane roots")
            if not kk_mac_servable() and \
                    kk_mac_probe().get("eligible"):
                # lane is live elsewhere — leave for it
                return "", ("kk_mac lane is live but this host can't "
                            "serve it")
        if ex == "opencode":
            # Declared OpenCode executor: this host may claim ONLY when
            # it is a compatible runner — OPENCODE_LANES=1 AND a real
            # opencode binary. Anything less leaves the card queued for
            # a host that qualifies (the defer note says why) — claiming
            # it for a devin run would silently break the contract.
            if not OPENCODE_LANES:
                return "", "executor=opencode but OPENCODE_LANES=0"
            if not opencode_bin():
                return "", "executor=opencode but no opencode binary"
        elif not Path(DISPATCH).exists():
            return "", "no devin-dispatch on host"
        # runner-push-cred-gap: never claim a repo this host can't push
        # — finishing here strands the branch (ADA-0673). Applies to the
        # OpenCode lane too: its close-out pushes the session branch.
        if not push_capable(str(a.get("repo") or "chaba")):
            return "", push_guard_reason(card) or "cannot push repo"
    if typ == "container":
        c = a.get("container") or {}
        if not c.get("image") or not shutil_which("podman"):
            return "", "container task needs image+podman"
    elif typ == "script":
        c = a.get("script") or {}
        url = c.get("repo_url") or REPO_URLS.get(c.get("repo", "chaba"))
        if not c.get("cmd") or not url or not shutil_which("git"):
            return "", "script task needs cmd+repo+git"
    elif typ != "dispatch":
        return "", f"unknown type {typ!r}"
    return typ, ""


def claimable(card: dict) -> str:
    """task type the card wants if this host may claim it, else ""."""
    return _claimable(card)[0]


def executor_defer_reason(card: dict) -> str:
    """Why this host declines an executor=opencode card it otherwise
    could claim — "" when N/A. The note goes to the board so the card
    visibly waits for an OpenCode-capable runner instead of silently
    starving (or worse, silently falling back to devin)."""
    a = card.get("action") or {}
    ex = str(a.get("executor") or "").strip()
    if a.get("status") != "queued" \
            or (a.get("runner") and a["runner"] != HOST) \
            or (a.get("host") and a["host"] != HOST) \
            or (a.get("target_host") and a["target_host"] != HOST) \
            or not set(a.get("labels") or []) <= LABELS:
        return ""
    if ex == "opencode":
        missing = []
        if not OPENCODE_LANES:
            missing.append("OPENCODE_LANES=0")
        if not opencode_bin():
            missing.append("no opencode binary")
        if missing:
            return (f"executor=opencode declared but this runner can't "
                    f"serve it ({', '.join(missing)}) — the card stays "
                    "queued for an OpenCode-capable runner; it will "
                    "never silently fall back to devin")
    if ex == "kk_mac_local" and not a.get("kk_mac_tried"):
        if not kk_mac_contract_ok(a):
            return (f"executor=kk_mac_local but action.task_class "
                    f"{a.get('task_class') or '(missing)'!r} is not "
                    f"admitted ({', '.join(sorted(KK_MAC_TASK_CLASSES))}"
                    ") or action.artifact is outside the lane roots — "
                    "fix the card; fail closed rather than guess")
        if not kk_mac_servable():
            missing = []
            if not KK_MAC_LANES:
                missing.append("KK_MAC_LANES=0")
            if kk_mac_module() is None:
                missing.append("no kk_mac_executor.py")
            gate = kk_mac_probe()
            if gate.get("eligible"):
                return (f"executor=kk_mac_local declared and the lane is "
                        f"live, but this runner can't serve it "
                        f"({', '.join(missing)}) — the card stays queued "
                        "for a kk_mac-capable runner")
            # lane ineligible — this host claims it as a next-lane run,
            # so no defer note (nothing is actually waiting on kk_mac)
    if ex and ex not in EXECUTORS:
        return (f"executor={ex!r} is not a known executor "
                f"({', '.join(sorted(EXECUTORS))}) — fix the card; "
                "fail closed rather than guess a route")
    if ex == "script" and (a.get("type") or "dispatch") == "dispatch" \
            and not (a.get("script") or {}).get("cmd"):
        return ("executor=script declared but action.script.cmd is "
                "missing — the card can't be served; fix the card")
    return ""


def shutil_which(name: str) -> bool:
    return any((Path(p) / name).exists()
               for p in os.environ.get("PATH", "").split(":"))


def opencode_bin() -> str:
    """Resolve the opencode binary — $OPENCODE_BIN, PATH, then the two
    install locations the systemd user manager PATH never carries
    (~/.opencode/bin only enters PATH via ~/.bashrc, so shutil_which
    alone misses it under the timer unit)."""
    env = os.environ.get("OPENCODE_BIN") or ""
    if env and Path(env).is_file():
        return env
    for p in os.environ.get("PATH", "").split(":"):
        c = Path(p) / "opencode"
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    for c in (Path.home() / ".opencode/bin/opencode",
              Path.home() / ".local/bin/opencode"):
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return ""


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


def note_defer(card: dict, kind: str, reason: str) -> None:
    """Comment a defer/refuse — at most once per GPU_DEFER_SECS per
    distinct reason per kind (gpu preflight, push guard)."""
    cid = card.get("id") or ""
    key = f"{cid}:{kind}"
    try:
        log = json.loads(DEFER_FILE.read_text())
    except Exception:
        log = {}
    ent = log.get(key) or {}
    now = int(time.time())
    if ent.get("reason") == reason and \
            now - int(ent.get("at", 0)) < GPU_DEFER_SECS:
        return
    api("/comment", {"id": cid, "from": "chaba",
                     "text": f"{HOST} defers: {reason}"})
    log[key] = {"at": now, "reason": reason}
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        DEFER_FILE.write_text(json.dumps(log, indent=1))
    except OSError:
        pass


def note_gpu_defer(card: dict, reason: str) -> None:
    note_defer(card, "gpu", f"gpu preflight: {reason}")


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


def oc_profiles_module():
    """Import scripts/devnest/opencode_profiles.py from this checkout —
    same lazy pattern as dr_module(); None when unavailable."""
    p = Path(__file__).resolve().parents[2] / "scripts" / "devnest" / \
        "opencode_profiles.py"
    if not p.is_file():
        return None
    spec = importlib.util.spec_from_file_location("opencode_profiles", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_KK_MAC = None
_KK_MAC_TRIED = False


def kk_mac_module():
    """Import scripts/devnest/kk_mac_executor.py from this checkout —
    same lazy pattern as dr_module()/oc_profiles_module(); None when
    unavailable."""
    global _KK_MAC, _KK_MAC_TRIED
    if _KK_MAC_TRIED:
        return _KK_MAC
    _KK_MAC_TRIED = True
    p = Path(__file__).resolve().parents[2] / "scripts" / "devnest" / \
        "kk_mac_executor.py"
    if not p.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "kk_mac_executor", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _KK_MAC = m
    except Exception:
        _KK_MAC = None
    return _KK_MAC


def kk_mac_servable() -> bool:
    """May this host RUN the kk_mac_local executor — the env gate plus a
    resolvable executor module."""
    return bool(KK_MAC_LANES) and kk_mac_module() is not None


_KK_PROBE = [0.0, None]


def kk_mac_probe() -> dict:
    """Heartbeat liveness for the KK-Mac lane, cached ~60s — used at
    claim time by hosts that can't serve the lane themselves: a live
    eligible lane means leave the card for a capable runner; anything
    else means the card just needs its next lane. Probe failure reads
    as ineligible (the lane is effectively unavailable)."""
    now = time.time()
    if now - _KK_PROBE[0] < 60 and _KK_PROBE[1] is not None:
        return _KK_PROBE[1]
    kme = kk_mac_module()
    try:
        res = (kme.probe() if kme is not None
               else {"eligible": False, "reasons": ["executor_missing"]})
    except Exception:
        res = {"eligible": False, "reasons": ["probe_failed"]}
    _KK_PROBE[0], _KK_PROBE[1] = now, res
    return res


def kk_mac_contract_ok(a: dict) -> bool:
    """Is the action block a servable kk_mac_local contract — admitted
    task class and (when declared) an artifact path inside the lane's
    roots. Prompt size is an admission question, checked at start."""
    if str(a.get("task_class") or "").strip() not in KK_MAC_TASK_CLASSES:
        return False
    kme = kk_mac_module()
    art = str(a.get("artifact") or "").strip()
    if art and kme is not None and not kme.artifact_allowed(art):
        return False
    return True


def start_kk_mac_lane(card: dict, unit: str) -> tuple:
    """Run the bounded kk_mac_local executor in a dispatch worktree.

    Same lifecycle as start_opencode_lane: worktree + taskdir meta/
    usage, a devin-task-<tid> unit running kk_mac_executor.py, and the
    finish pass gates the merge on the verdict. Admission is probed
    HERE (fresh, right before the unit launches): an ineligible lane
    returns (KK_MAC_FALLBACK, "", reason) so the caller continues the
    card on the next lane under the same claim — never a silent devin
    run and never a starved card."""
    a = card.get("action") or {}
    kme = kk_mac_module()
    if kme is None:
        return "", "", ("kk_mac_executor.py missing in this checkout — "
                        "can't serve the contract")
    cid = card["id"]
    task_class = str(a.get("task_class") or "").strip()
    if task_class not in KK_MAC_TASK_CLASSES:
        return "", "", (f"executor=kk_mac_local needs action.task_class "
                        f"in {sorted(KK_MAC_TASK_CLASSES)} — fail closed")
    prompt = str(a.get("prompt") or "").strip() or \
        (card.get("spec") or "").strip() or \
        f"{card.get('title', '')}\n\n{card.get('note', '')}".strip()
    expect = a.get("expect") if isinstance(a.get("expect"), dict) else {}
    art = str(a.get("artifact") or "").strip() or \
        f"evals/kk-mac-lane/out/{cid}.json"
    if not kme.artifact_allowed(art):
        return "", "", (f"artifact {art!r} outside the kk_mac roots — "
                        "fail closed")
    # Fresh admission probe BEFORE the worktree spend — the contract
    # says a stale/unavailable/overloaded KK-Mac falls back, and the
    # fallback is cheaper than an isolated worktree.
    try:
        gate = kme.admission_gate(task_class, prompt)
    except Exception as e:
        return KK_MAC_FALLBACK, "", \
            f"admission probe failed: {type(e).__name__}"
    if not gate.get("eligible"):
        return KK_MAC_FALLBACK, "", \
            "ineligible: " + ",".join(gate.get("reasons") or ["?"])
    repo_name = str(a.get("repo") or "chaba")
    dr = dr_module()
    ent = (dr.repos().get(repo_name) if dr else None) or {}
    root = Path(ent.get("path") or "")
    if not root.is_dir():
        return "", "", f"no dispatch repo checkout for {repo_name}"
    tid = unit.removeprefix("runner-")
    branch = f"dispatch/{tid}"
    worktree = Path.home() / f"CascadeProjects/dispatch-wt-{tid}"
    taskdir = Path.home() / ".local/share/devin-dispatch/tasks" / tid
    try:
        taskdir.mkdir(parents=True, exist_ok=True)
        if worktree.exists():
            return "", "", f"worktree already exists: {worktree}"
        base = f"origin/{ent.get('default_branch') or 'master'}"
        sh(["git", "-C", str(root), "fetch", "-q", "origin",
            ent.get('default_branch') or 'master'], timeout=60)
        r = sh(["git", "-C", str(root), "worktree", "add", "-B", branch,
                str(worktree), base], timeout=120)
        if r.returncode:
            return "", "", (r.stderr or r.stdout).strip()[:240]
        dbranch = ent.get('default_branch') or 'master'
        started = datetime.now(timezone.utc).isoformat()
        model = os.environ.get("KK_MAC_MODEL", "qwen3:8b")
        meta = {"repo": repo_name, "branch": branch,
                "worktree": str(worktree), "repo_root": str(root),
                "default_branch": dbranch,
                "base": f"origin/{dbranch}",
                "executor": "kk_mac_local", "card": cid,
                "provider": "ollama", "model": model,
                "task_class": task_class, "unit": unit,
                "task_id": tid, "started_at": started}
        (taskdir / "meta.json").write_text(json.dumps(meta, indent=1))
        usage = {"task_id": tid, "card": cid, "unit": unit,
                 "host": HOST, "executor": "kk_mac_local",
                 "provider": "ollama", "model": model,
                 "task_class": task_class, "artifact": art,
                 "started_at": started}
        (taskdir / "usage.json").write_text(json.dumps(usage, indent=1))
        (taskdir / "prompt.txt").write_text(prompt)
        (taskdir / "expect.json").write_text(json.dumps(expect, indent=1))
    except Exception as e:
        return "", "", f"kk_mac worktree setup: {e}"
    shell = (
        f"cd {shlex.quote(str(worktree))} && "
        f"python3 scripts/devnest/kk_mac_executor.py run "
        f"--card {shlex.quote(cid)} --task-id {shlex.quote(tid)} "
        f"--task-class {shlex.quote(task_class)} "
        f"--worktree {shlex.quote(str(worktree))} "
        f"--taskdir {shlex.quote(str(taskdir))} "
        f"--artifact {shlex.quote(art)} "
        f"--model {shlex.quote(model)} "
        f"--prompt-file {shlex.quote(str(taskdir / 'prompt.txt'))} "
        f"--expect-file {shlex.quote(str(taskdir / 'expect.json'))} "
        f"2>&1 | tee {shlex.quote(str(taskdir / 'kk_mac.log'))}; "
        "rc=$${PIPESTATUS[0]}; "
        f"echo \"$$rc\" > {shlex.quote(str(taskdir / 'exit_code'))}; "
        "exit $$rc"
    )
    argv = (["systemd-run", "--user", f"--unit=devin-task-{tid}",
             "--collect",
             "--description", f"runner {cid} kk_mac {task_class}"]
            + task_run_props() + ["bash", "-lc", shell])
    r = sh(argv, timeout=180)
    if r.returncode:
        return "", "", (r.stderr or r.stdout).strip()[:240]
    return f"devin-task-{tid}", tid, ""


def finish_kk_mac_lane(cid: str, ent: dict, card: dict) -> tuple:
    """kk_mac_local closeout — runs BEFORE close_out_merge like
    finish_opencode_lane. Returns (may_merge, notes, fallback_reason):

    - verdict pass AND the declared artifact landed in the worktree ->
      may_merge=True; the merge gate stamps verified.
    - verdict fallback (lane declined mid-run or invalid output) ->
      may_merge=False + fallback_reason set; the caller runs the next
      lane under the same claim and the stale worktree is cleaned up.
    - verdict fail/missing (contract violation, crashed unit) ->
      may_merge=False, no fallback — the card is held for a human."""
    tid = ent.get("tid") or ""
    if not tid:
        unit = ent.get("unit") or ""
        tid = (unit[len("devin-task-"):]
               if unit.startswith("devin-task-") else "")
    if not tid:
        return True, [], ""
    taskdir = Path.home() / ".local/share/devin-dispatch/tasks" / tid
    try:
        meta = json.loads((taskdir / "meta.json").read_text())
    except Exception:
        return True, [], ""  # no meta -> not a kk_mac task
    if str(meta.get("executor") or "") != "kk_mac_local":
        return True, [], ""
    notes = []
    try:
        usage = json.loads((taskdir / "usage.json").read_text())
    except Exception:
        usage = {}
    try:
        verdict = json.loads((taskdir / "verdict.json").read_text())
    except Exception:
        verdict = {}
    try:
        result = json.loads(
            (taskdir / "kk_mac_result.json").read_text())
    except Exception:
        result = {}
    art = str(verdict.get("artifact")
              or (card.get("action") or {}).get("artifact") or "")
    wt = Path(str(meta.get("worktree") or ""))
    landed = bool(art) and (wt / art).is_file()
    if landed:
        try:  # durable copy for the task record
            (taskdir / "artifact.out").write_text(
                (wt / art).read_text())
        except OSError:
            pass
    v = str(verdict.get("verdict") or "")
    usage.update({"verdict": v or "missing",
                  "artifact_landed": landed,
                  "checks": verdict.get("checks") or {},
                  "reasons": verdict.get("reasons") or [],
                  "usage": result.get("usage") or {}})
    try:
        (taskdir / "usage.json").write_text(json.dumps(usage, indent=1))
    except OSError:
        pass
    if v == "pass" and landed:
        u = result.get("usage") or {}
        notes.append(f"kk_mac_local artifact landed {art} — verifier "
                     f"pass (eval_tokens={u.get('eval_count')})")
        return True, notes, ""
    fb = ""
    if v == "fallback" or (not v and result):
        reasons = ";".join(verdict.get("reasons")
                           or result.get("reasons") or ["unknown"])
        fb = reasons[:240]
        notes.append(f"kk_mac_local fell back: {fb}")
        # the declared artifact evidence stays in the taskdir; the
        # stale kk_mac worktree/branch is cleaned up so the next lane's
        # dispatch worktree machinery runs clean
        root = Path(str(meta.get("repo_root") or ""))
        if wt.is_dir() and root.is_dir():
            sh(["git", "-C", str(root), "worktree", "remove", "--force",
                str(wt)], timeout=60)
            sh(["git", "-C", str(root), "branch", "-D",
                str(meta.get("branch") or "")], timeout=30)
    elif v == "pass" and not landed:
        notes.append("merge held — verifier passed but the declared "
                     f"artifact {art or '(none)'} did not land")
    else:
        checks = "; ".join(f"{k}={x}" for k, x in
                           list((verdict.get("checks") or {}).items())[:4])
        detail = checks or v or "no verdict"
        notes.append("merge held — kk_mac_local contract requires "
                     f"artifact + verifier pass ({detail})")
    return False, notes, fb


def start_opencode_lane(card: dict, lane: str, unit: str) -> tuple:
    """Run a profile-scoped opencode lane in a dispatch worktree.

    The generic build agent is kept out of unattended routing
    (opencode-task-agent-profiles): the lane must resolve a task-scoped
    profile (action.agent_profile — action.profile as the pre-contract
    alias — else LANE_PROFILES), which is rendered into a worktree-local
    opencode config — custom agent + builtin agents disabled + minimal
    MCP + permission rules — and the run addresses it via --agent.

    Executor contract (opencode-explicit-executor-routing): this path
    requires OPENCODE_LANES=1 AND a real opencode binary — the caller
    normally gates on both at claim time, but the check repeats here so
    no route reaches devin-free OpenCode execution silently. The run
    stamps executor/provider/model/profile into taskdir meta.json AND
    usage.json, and tees the opencode event stream to events.jsonl so
    the finish pass can land the declared artifact and the close-out
    can prove who ran the work."""
    if not OPENCODE_LANES:
        return "", "", ("OPENCODE_LANES=0 on this runner — the opencode "
                        "executor is disabled; the card needs an "
                        "OpenCode-capable runner, not a devin run")
    oc_bin = opencode_bin()
    if not oc_bin:
        return "", "", "opencode is not installed on this runner"
    a = card.get("action") or {}
    prof_id = str(card_profile(card) or LANE_PROFILES.get(lane) or "")
    if not prof_id:
        return "", "", f"no task profile for lane {lane or '(none)'} — " \
                       "the opencode executor requires " \
                       "action.agent_profile or a mapped lane (generic " \
                       "build agent is not an unattended executor)"
    ocp = oc_profiles_module()
    if ocp is None:
        return "", "", "opencode_profiles.py missing in this " \
                       "checkout — profile render impossible"
    try:
        prof = ocp.load_profile(prof_id)
    except SystemExit as e:
        return "", "", f"profile {prof_id}: {e}"
    # model precedence: explicit action.model > lane table > the
    # profile's declared default — the contract's model always wins.
    model = str(a.get("model") or "").strip() or \
        str(LANE_MODELS.get(lane) or "") or \
        str(((prof.get("model") or {}).get("default")) or "")
    if not model:
        return "", "", (f"no model resolvable for profile {prof_id} — "
                        "set action.model or a lane")
    provider = model_provider(model)
    repo_name = str(a.get("repo") or "chaba")
    dr = dr_module()
    ent = (dr.repos().get(repo_name) if dr else None) or {}
    root = Path(ent.get("path") or "")
    if not root.is_dir():
        return "", "", f"no dispatch repo checkout for {repo_name}"
    tid = unit.removeprefix("runner-")
    branch = f"dispatch/{tid}"
    worktree = Path.home() / f"CascadeProjects/dispatch-wt-{tid}"
    # Match devin-dispatch's task metadata so the existing closeout/merge
    # gate can discover this OpenCode session after the unit exits —
    # plus the executor contract fields (provider/model/profile/card)
    # and usage.json so the trail proves who ran the work.
    taskdir = Path.home() / ".local/share/devin-dispatch/tasks" / tid
    try:
        taskdir.mkdir(parents=True, exist_ok=True)
        if worktree.exists():
            return "", "", f"worktree already exists: {worktree}"
        base = f"origin/{ent.get('default_branch') or 'master'}"
        sh(["git", "-C", str(root), "fetch", "-q", "origin",
            ent.get('default_branch') or 'master'], timeout=60)
        r = sh(["git", "-C", str(root), "worktree", "add", "-B", branch,
                str(worktree), base], timeout=120)
        if r.returncode:
            return "", "", (r.stderr or r.stdout).strip()[:240]
        dbranch = ent.get('default_branch') or 'master'
        started = datetime.now(timezone.utc).isoformat()
        meta = {"repo": repo_name, "branch": branch,
                "worktree": str(worktree), "repo_root": str(root),
                "default_branch": dbranch,
                "base": f"origin/{dbranch}",
                "executor": f"opencode:{lane or prof_id}",
                "card": card["id"], "provider": provider,
                "model": model, "profile": prof_id, "lane": lane,
                "unit": unit, "task_id": tid,
                "started_at": started}
        (taskdir / "meta.json").write_text(json.dumps(meta, indent=1))
        usage = {"task_id": tid, "card": card["id"], "unit": unit,
                 "host": HOST, "executor": "opencode",
                 "provider": provider, "model": model,
                 "profile": prof_id, "lane": lane,
                 "artifact": str(a.get("artifact") or ""),
                 "started_at": started}
        (taskdir / "usage.json").write_text(json.dumps(usage, indent=1))
    except Exception as e:
        return "", "", f"OpenCode worktree setup: {e}"
    spec = (card.get("spec") or "").strip() or \
        f"{card.get('title', '')}\n\n{card.get('note', '')}"
    task = spec + "\n\n" + RAILS_OPENCODE.format(
        id=card["id"], host=HOST, api=API)
    # Render the task-scoped profile into a worktree-local opencode
    # config: profile agent only, builtin agents disabled, MCP surface
    # minimal (proxy-only, only when present), permission rules from
    # the profile. Render failure = the lane can't start.
    confdir = worktree / ".opencode-profile"
    try:
        synth = {"id": tid, "card": card["id"], "target_host": HOST,
                 "model": model, "mcp_allowlist":
                     list((prof.get("mcp") or {}).get("allowed") or []),
                 "artifact": {"path": str(a.get("artifact") or ""),
                              "schema": ""}}
        cfg = ocp.render_config(synth, prof)
        cfg.pop("_allowfile", None)
        confdir.mkdir(parents=True, exist_ok=True)
        (confdir / "opencode.json").write_text(json.dumps(cfg, indent=1))
    except SystemExit as e:
        return "", "", f"profile {prof_id}: {e}"
    except Exception as e:
        return "", "", f"profile render: {e}"
    # The event stream tees to events.jsonl — durable proof for the
    # finish pass (artifact extraction, tool-call audit) that also
    # survives journal rotation.
    shell = (
        "set -a; if [ -f $$HOME/.config/secrets/litellm-keys.env ]; then "
        ". $$HOME/.config/secrets/litellm-keys.env; export LITELLM_KEY=$${LITELLM_KEY_ADA:-}; "
        "else . $$HOME/.config/secrets/litellm-chaba.env; fi; "
        f"export OPENCODE_CONFIG={shlex.quote(str(confdir / 'opencode.json'))}; "
        f"cd {shlex.quote(str(worktree))} && "
        f"{shlex.quote(oc_bin)} run --format json "
        f"--dir {shlex.quote(str(worktree))} --model {shlex.quote(model)} "
        f"--agent {shlex.quote(ocp.agent_name(prof_id))} "
        f"{shlex.quote(task)} 2>&1 | "
        f"tee {shlex.quote(str(taskdir / 'events.jsonl'))}; "
        "rc=$${PIPESTATUS[0]}; "
        f"echo \"$$rc\" > {shlex.quote(str(taskdir / 'exit_code'))}; "
        "exit $$rc"
    )
    argv = (["systemd-run", "--user", f"--unit=devin-task-{tid}", "--collect",
             "--description", f"runner {card['id']} OpenCode "
                              f"{lane or prof_id}"]
            + task_run_props() + ["bash", "-lc", shell])
    r = sh(argv, timeout=180)
    if r.returncode:
        return "", "", (r.stderr or r.stdout).strip()[:240]
    return f"devin-task-{tid}", tid, ""


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
        # Executor contract (opencode-explicit-executor-routing): an
        # explicit action.executor decides the route BEFORE any lane
        # classification, and never silently re-routes to a different
        # executor.
        ex = str(a.get("executor") or "").strip()
        if ex == "kk_mac_local":
            # Try-first contract (kk-mac-jev-adapter-integration): the
            # bounded lane gets one shot; every decline falls back to
            # the normal lane cascade under THIS claim — the card never
            # starves and never silently skips the contract.
            if not a.get("kk_mac_tried") and kk_mac_servable():
                kunit, ktid, kerr = start_kk_mac_lane(card, unit)
                if kunit != KK_MAC_FALLBACK:
                    return kunit, ktid, kerr
                api("/comment", {"id": cid, "from": "chaba",
                                 "text": f"kk_mac_local declined "
                                         f"({kerr or 'ineligible'}) — "
                                         "running the next lane"})
            elif not a.get("kk_mac_tried"):
                api("/comment", {"id": cid, "from": "chaba",
                                 "text": "kk_mac_local not servable on "
                                         "this host — running the next "
                                         "lane"})
            a["kk_mac_tried"] = True   # consumed for this claim (local
            ex = ""                    # copy — the board keeps the
        if ex == "opencode":
            try:
                # an explicit action.lane maps through LANE_PROFILES
                # (executor=opencode + lane=free_lane -> ops-readonly);
                # the error below promised this route but the lane was
                # blinded here (OPS-1021 first claim, 2026-10-30)
                return start_opencode_lane(card, str(a.get("lane") or ""), unit)
            except Exception as e:
                # contract failures fail the task — never a devin fallback
                return "", "", f"opencode executor: {e}"
        if ex == "manual" or (ex and ex not in EXECUTORS):
            return "", "", (f"action.executor={ex or '?'!r} cannot be "
                            "auto-claimed — fail closed")
        if ex == "script":
            # claimable() routes dispatch-typed executor=script cards to
            # typ=script; reaching the dispatch branch means the card is
            # inconsistent — fail closed rather than improvise a route.
            return "", "", ("executor=script on a dispatch card needs "
                            "action.script — fail closed")
        if ex == "devin":
            # pinned to the devin path — lane classification stays out;
            # action.model (a native devin id) maps via DISPATCH_MODEL
            lane = ""
        else:
            # Claim-time lane routing (jev-pilot Phase 2): classify when the
            # card has no lane yet, persist it, map to the cheapest model.
            # `lane` must be bound even when the card already carries
            # action.lane (explicit lane or the JEV_LANE claim-classify that
            # persisted it) — reading it unbound crashed every such claim
            # with UnboundLocalError (OPS-0846 review 2026-10-25).
            lane = str(a.get("lane") or "")
            if not lane:
                lane = classify_lane(card)
                if lane and lane != "manual":
                    a["lane"] = lane
                    if lane in LANE_MODELS and not a.get("model"):
                        a["model"] = LANE_MODELS[lane]
        if lane == "manual":
            return "", "", "manual lane — not dispatched (Tony's hands)"
        if lane in LANE_MODELS and OPENCODE_LANES and \
                (card_profile(card) or LANE_PROFILES.get(lane)):
            return start_opencode_lane(card, lane, unit)
        # no resolvable task profile -> generic build agent stays out
        # of unattended routing; the card takes the devin path
        spec = (card.get("spec") or "").strip() or \
            f"{card.get('title', '')}\n\n{card.get('note', '')}"
        task = spec + "\n\n" + RAILS.format(id=cid, host=HOST, api=API)
        argv = [DISPATCH, "start", a.get("repo", "chaba"), task]
    env = dict(os.environ)
    if typ == "dispatch":
        # executor contract context — devin-dispatch._meta_write stamps
        # it into meta.json + usage.json so the close-out can prove who
        # ran the work.
        env["DISPATCH_CARD"] = cid
        env["DISPATCH_EXECUTOR"] = ex or "devin"
        if card_profile(card):
            env["DISPATCH_PROFILE"] = card_profile(card)
        if a.get("target_host"):
            env["DISPATCH_TARGET_HOST"] = str(a["target_host"])
    if a.get("model"):
        env["DISPATCH_MODEL"] = str(a["model"])
    elif typ == "dispatch":
        # lane -> cheapest model (jev-pilot Phase 2). Parity with
        # kanban-dispatch start_pending — whichever claimer wins applies
        # the same routing: an explicit action.lane always maps through
        # LANE_MODELS, and JEV_LANE=1 additionally classifies unset lanes.
        # jev-model-chain-probe found this missing here: runner claims
        # silently launched on the devin default model.
        lane = str(a.get("lane") or "")
        dr = dr_module()
        lane_models = getattr(dr, "LANE_MODELS", {}) if dr else {}
        if not lane and dr and getattr(dr, "classify_lane", None) \
                and os.environ.get("JEV_LANE", "0") == "1":
            lane = dr.classify_lane(card) or ""
        if lane == "manual":
            return "", "", "manual lane — not dispatched (Tony's hands)"
        if lane in lane_models:
            env["DISPATCH_MODEL"] = str(lane_models[lane])
    if typ == "dispatch":
        # provider follows the RESOLVED model (action.model or the lane
        # mapping) — computed after both so litellm lane ids report
        # provider=litellm, not devin.
        env["DISPATCH_PROVIDER"] = model_provider(
            env.get("DISPATCH_MODEL") or "") or "devin"
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
        # `systemd-run --collect` can remove the transient unit before the
        # next runner pass observes it. The kk_mac executor persists its
        # exit code and verifier evidence in the task directory, so use that
        # durable evidence instead of treating a missing collected unit as
        # an execution failure.
        if not ok and ent.get("type") == "dispatch":
            tid = ent.get("tid") or ""
            taskdir = (Path.home() / ".local/share/devin-dispatch/tasks"
                       / tid)
            # A legacy runner state can lose tid while the executor's
            # durable task directory remains. Recover by card id before
            # treating a reaped unit as an execution failure.
            if not taskdir.is_dir():
                tasks_root = Path.home() / ".local/share/devin-dispatch/tasks"
                for candidate in tasks_root.glob("*/meta.json"):
                    try:
                        meta_probe = json.loads(candidate.read_text())
                    except (OSError, json.JSONDecodeError):
                        continue
                    if (meta_probe.get("card") == cid and
                            meta_probe.get("executor") == "kk_mac_local"):
                        taskdir = candidate.parent
                        break
            try:
                meta = json.loads((taskdir / "meta.json").read_text())
                exit_code = int((taskdir / "exit_code").read_text().strip())
            except (OSError, ValueError, json.JSONDecodeError):
                meta, exit_code = {}, None
            if meta.get("executor") == "kk_mac_local" and exit_code == 0:
                ok = True
                result = ("kk_mac executor exited 0; collected unit was "
                          "already reaped; using durable verdict evidence")
        verified, notes = None, []
        if ok and ent.get("type") == "dispatch":
            if cards is None:
                cards = {c.get("id"): c for c in
                         (api("/cards") or {}).get("cards") or []}
            card = cards.get(cid) or {}
            # Executor contract: the OpenCode closeout lands the declared
            # artifact + runs the verifier BEFORE the merge gate; a
            # contract failure holds the merge (verified=False) with the
            # evidence in comms — never merges on exit code alone.
            may_merge, oc_notes = finish_opencode_lane(cid, ent, card)
            notes = oc_notes
            kk_fb = ""
            if may_merge:
                # kk_mac_local closeout: verdict pass + landed artifact
                # or the merge is held; a fallback verdict hands the
                # card to the next lane under the same claim.
                may_merge, kk_notes, kk_fb = \
                    finish_kk_mac_lane(cid, ent, card)
                notes += kk_notes
            if kk_fb:
                # In-claim fallback (kk-mac-jev-adapter-integration):
                # the bounded lane declined after starting — mark the
                # executor consumed on the local copy and run the next
                # lane now; the card never requeues for it.
                (card.setdefault("action", {}))["kk_mac_tried"] = True
                u2, t2, e2 = start_task(card, "dispatch")
                if e2 or not u2:
                    notes.append(f"kk_mac_local fell back ({kk_fb}) but "
                                 f"the next lane failed to start: "
                                 f"{e2 or 'no unit'}")
                    verified = False
                else:
                    st[cid].update({"unit": u2, "tid": t2})
                    notes.append(f"kk_mac_local fell back ({kk_fb}) — "
                                 f"next lane running as {u2}")
                    for n in notes:
                        api("/comment", {"id": cid, "from": "chaba",
                                         "text": n})
                    changed = True
                    continue  # still claimed — no finish post yet
            elif may_merge:
                verified, merge_notes = close_out_merge(cid, ent, card)
                notes += merge_notes
            else:
                verified = False
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


_CLAIM_ORDER_WARNED = False


def _claim_order(cards: list) -> list:
    """Shared priority drain order (dispatch_repos.claim_sort_key, card
    dispatch-priority-order). The module is resolved like the close-out
    import; a host that can't resolve it keeps API order — the queue
    still drains, and runner-fleet-health already flags the drift."""
    global _CLAIM_ORDER_WARNED
    dr = dr_module()
    sorter = getattr(dr, "sort_claimable", None) if dr else None
    if sorter is None:
        if not _CLAIM_ORDER_WARNED:
            _CLAIM_ORDER_WARNED = True
            print("warn: dispatch_repos.sort_claimable unavailable — "
                  "claiming in API order (stale/missing host checkout)")
        return cards
    return sorter(cards, starve_hours=STARVE_HOURS)


def claim_pass(st: dict) -> bool:
    if len(st) >= CAP:
        return False
    if overloaded():
        return False
    cards = _claim_order((api("/cards") or {}).get("cards") or [])
    by_id = {c.get("id"): c for c in cards}
    changed = False
    for card in cards:
        if len(st) >= CAP:
            break
        cid = card.get("id") or ""
        typ = claimable(card)
        if not typ:
            # distinguish "not for me" from "would claim but can't push"
            # — the latter wants a board note so the gap is visible
            pg = push_guard_reason(card)
            if pg:
                note_defer(card, "push", pg)
            # executor-contract defer: an executor=opencode card this
            # host can't serve, or an unrecognised executor, gets a
            # visible reason instead of silently starving
            xr = executor_defer_reason(card)
            if xr:
                note_defer(card, "executor", xr)
            continue
        if card.get("blocked_by"):
            blocker = by_id.get(card["blocked_by"]) or {}
            if not blocker_released(blocker):
                continue  # gate holds — try again next pass
        if not cid:
            continue
        reason = gpu_preflight(card)
        if reason:
            note_gpu_defer(card, reason)
            continue  # stays queued — a later pass or spec fix picks it up
        claim_body = {"id": cid, "do": "claim", "host": HOST}
        a0 = card.get("action") or {}
        ex_decl = str(a0.get("executor") or "").strip()
        if ex_decl:
            # The declared executor rides the atomic claim so the board
            # record carries the contract that served it.
            claim_body["executor"] = ex_decl
            if card_profile(card):
                claim_body["agent_profile"] = card_profile(card)
        # Classify BEFORE the atomic claim and persist the lane/model in the
        # claim request. The previous start_task-only classification could
        # not write action fields back to the board and remote runners lost
        # the model chain (OPS-0836..0844). An explicit executor is itself
        # the routing decision — classification stays out of it.
        if typ == "dispatch" and not ex_decl \
                and os.environ.get("JEV_LANE", "0") == "1":
            a = card.setdefault("action", {})
            # An explicit action.lane (pinned in the card YAML, e.g. the
            # OPS-0885 pilot cards) wins over claim-time classification —
            # re-classifying here clobbered pinned free_lane cards into
            # codemod/paid_frontier lanes (OPS-0885 miss class).
            lane = str(a.get("lane") or "")
            if not lane:
                lane = classify_lane(card)
            if lane == "manual":
                continue
            a["lane"] = lane
            if lane in LANE_MODELS and not a.get("model"):
                a["model"] = LANE_MODELS[lane]
            claim_body["lane"] = lane
            claim_body["model"] = a.get("model", "")
        resp = api("/action", claim_body)
        if resp.get("error"):
            continue  # lost the race or rejected — next card
        unit, tid, err = start_task(card, typ)
        if err:
            api("/action", {"id": cid, "do": "finish", "host": HOST,
                            "ok": False, "result": f"start failed: {err}"})
            continue
        detail = typ
        if ex_decl:
            # comms carry the executor contract that ran the card
            detail += f" executor={ex_decl}"
            if card_profile(card):
                detail += f" profile={card_profile(card)}"
            if a0.get("model"):
                detail += f" model={a0['model']}"
        api("/comment", {"id": cid, "from": "chaba",
                         "text": f"started {unit} on {HOST} ({detail})"})
        st[cid] = {"unit": unit, "type": typ, "tid": tid,
                   "at": int(time.time()),
                   "gpu": "gpu" in set((card.get("action") or {})
                                      .get("labels") or [])}
        changed = True
        print(f"{cid}: claimed + started {unit}")
    return changed


def verdict_pass(st: dict) -> None:
    """/ready report — runner-observed claimability for every queued card
    plus this host's in-flight claims (KNB-1007). Runs every pass, even
    at cap/overload: the projection needs 'why waiting' exactly when the
    host is busiest. Debounced by payload hash, forced every
    READY_FORCE_S; never fails the claim pass."""
    try:
        cards = (api("/cards") or {}).get("cards") or []
        by_id = {c.get("id"): c for c in cards}
        verdicts = {}
        for c in cards:
            cid = c.get("id")
            if not cid or (c.get("action") or {}).get("status") != "queued":
                continue
            typ, reason = _claimable(c)
            if typ:
                g = gpu_preflight(c)
                verdicts[cid] = {"ok": not g, "reason": g or ""}
                if not g:
                    continue
                blocker = by_id.get(c.get("blocked_by") or "") or {}
                if c.get("blocked_by") and not blocker_released(blocker):
                    verdicts[cid] = {
                        "ok": False,
                        "reason": f"blocked_by {c['blocked_by']}"}
            else:
                verdicts[cid] = {"ok": False, "reason": reason}
        active = [{"id": cid, "unit": v.get("unit", ""),
                   "at": v.get("at", 0)} for cid, v in st.items()]
        h = hashlib.sha1(json.dumps(
            {"v": verdicts, "a": sorted(x["id"] for x in active)},
            sort_keys=True).encode()).hexdigest()
        last = {}
        try:
            last = json.loads(READY_REPORT.read_text())
        except Exception:
            pass
        if last.get("hash") == h and \
                time.time() - (last.get("at") or 0) < READY_FORCE_S:
            return
        resp = api("/ready",
                   {"host": HOST, "verdicts": verdicts, "active": active})
        if resp.get("error"):
            print(f"warn: /ready report failed: {resp['error']}")
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        READY_REPORT.write_text(
            json.dumps({"hash": h, "at": time.time()}))
    except Exception as e:
        print(f"warn: verdict_pass failed: {e}")


def main() -> int:
    st = load_state()
    changed = finish_pass(st) | watchdog_pass(st) | claim_pass(st)
    verdict_pass(st)
    if changed:
        save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
