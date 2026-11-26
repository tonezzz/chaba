#!/usr/bin/env python3
"""kanban-dispatch — drain cards whose action.status is 'queued'.

Runs from kanban-dispatch.timer every 2 min on tony-dell, in the
chaba-tony-dell checkout (the web-served tree). For each queued card:

  1. builds the task text (card.spec, else title+note) with standard
     rails (worktree already handled by devin-dispatch; report back via
     the board API so the card's comms log stays live)
  2. devin-dispatch start <repo> "<task>"  -> action.task_id
  3. claims the card for this dispatch session, status -> running

Answers to a running card's requests are pushed into the session task
dir by board-api ($TASK_DIR/answers.jsonl); the rails below tell the
session to poll it.

For cards already 'running', polls `devin-dispatch status <task_id>`;
when the unit finishes, marks action.status done, moves the card to
review, writes a comms entry, and runs the close-out merge step
(dispatch_repos.close_out — card dispatch-auto-merge): leftover
worktree files are committed as a checkpoint, the session branch is
pushed to origin, the card's expected_goals gate is run, and the
branch is merged --no-ff into origin/<default_branch> in a throwaway
detached worktree — where the repo's fast test step then runs before
the merge pushes (dispatch_repos.REPO_TESTS; KANBAN_TESTGATE=0
disables). Unresolved conflicts, failed goals, or a red test suite
leave the card in review with a comms note for human resolution —
conflicts and test failures also requeue via auto-retry with the
evidence in action.last_failure (KANBAN_AUTOMERGE=0 disables the
whole step). Session-end notes report leftover dirty/unmerged state.
Tony reviews then presses Close.
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

# libyaml when present — same reason as board-api/render-board: pure
# parses of the ~1000-card corpus inside the card flock were the 2026-11
# lock-convoy tax (board-api-lock-contention).
_YAML_LOAD = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import card_io
import dispatch_repos as dr
import dispatch_task as dt
import lesson_primer as lp
import waiting_cards as wc

def _act(card: dict) -> dict:
    """card['action'] read accessor — schema says dict, but marker cards
    carry scalars ('spec-review'). Returns {} for non-dict WITHOUT
    writing, so read-only passes don't stamp action:{} onto cards."""
    a = card.get("action")
    return a if isinstance(a, dict) else {}


def _ensure_act(card: dict) -> dict:
    """Write-path twin of _act: materializes action as a dict (scalar
    marker replaced) so mutations persist."""
    a = _act(card)
    if a is not card.get("action"):
        card["action"] = a
    return a


def _ensure_claim(card: dict) -> dict:
    """Same normalization for card['claim'] — a scalar here used to
    TypeError every session-pop (2026-11-17 marker-card audit)."""
    c = card.get("claim")
    if not isinstance(c, dict):
        card["claim"] = c = {}
    return c

REPO = Path(__file__).resolve().parent.parent.parent
CARD_DIR = REPO / "docs/ssot/kanban/cards"
RENDER = REPO / "scripts/render-board.py"
LOCK = Path("/tmp/board-api.lock")
DISPATCH = os.environ.get("DEVIN_DISPATCH",
                          str(Path.home() / ".local/bin/devin-dispatch"))
# Unattended sessions die on permission rejection — 'smart' auto-rejects
# curl/systemctl and the rails ask agents to curl /comment. Worktree
# isolation + the no-push rails are the guardrail (same reasoning as
# dispatch-queue.sh's dangerous default).
os.environ.setdefault("DISPATCH_PERMISSION_MODE", "dangerous")
API = os.environ.get("BOARD_API", "http://127.0.0.1:8787")
HOST = os.uname().nodename
SESSION = f"kanban-dispatch@{HOST}"
INDEX_FILE = Path(os.environ.get(
    "KANBAN_DISPATCH_INDEX",
    f"/tmp/kanban-dispatch-index-{os.getuid()}-{HOST}.json"))
# Per-host concurrency: count of active devin-task-* units we won't exceed.
# tony-dell is RAM-tight (dispatch-queue.sh used CAP=3); other hosts raise it
# via env until a per-host table lands in ssot.kanban.yml rules.
HOST_CAP = int(os.environ.get("KANBAN_HOST_CAP", "3"))
# Load gate: stop claiming new cards when 5-min load per core exceeds this
# (a loaded host yields the queue to idle runners). 0 disables.
MAX_LOAD_PC = float(os.environ.get("KANBAN_MAX_LOAD_PC", "1.0"))
# Capability labels this host satisfies (runner-agent parity). A card with
# action.labels only runs where every label is satisfied — e.g.
# labels: [gpu] won't be grabbed by a label-less host.
MY_LABELS = {x.strip() for x in
             os.environ.get("KANBAN_HOST_LABELS", "").split(",")
             if x.strip()}
# Push-credential claim guard (runner-push-cred-gap): same rule as
# runner-agent — a dispatch card is only claimable when this host can
# actually push the card's repo. A `push:<repo>` label in
# KANBAN_HOST_LABELS is the declared fast path; otherwise
# dr.push_probe() runs a real `git push --dry-run` (a git@ remote is no
# proof — ADA-0673's chaba-only deploy key looked ssh-capable).
PUSH_GUARD = os.environ.get("KANBAN_PUSH_GUARD", "1") != "0"
# Lane -> cheapest executor mapping (jev-pilot Phase 2, 2026-10-25) —
# canonical tables live in dispatch_repos so runner-agent claims route
# identically; module aliases kept for external importers.
LANE_MODELS = dr.LANE_MODELS
LANE_EXECUTORS = dr.LANE_EXECUTORS
JEVOS = dr.JEVOS
JEV_LANE = os.environ.get("JEV_LANE", "0") == "1"

PUSH_PROBE_TTL = int(os.environ.get("KANBAN_PUSH_PROBE_TTL", "300"))
_PUSH_PROBE_CACHE: dict = {}

# Provider rate-limit claim cooldown (dispatch-runner-resilience — the
# served-side twin of runner-agent's): a devin-task unit whose journal
# shows a provider 429 arms a host-local cooldown so the NEXT claim
# doesn't burn its attempts into the same wall. The signature table is
# dr.rate_limit_hit; detection runs in the phase-A0 survey (journalctl
# stays OUT of the card flock — the 2026-11-17 convoy rule).
RATELIMIT_FILE = Path(os.environ.get(
    "KANBAN_RATELIMIT_FILE",
    f"/tmp/kanban-dispatch-ratelimit-{os.getuid()}-{HOST}.json"))
RATELIMIT_COOLDOWN_S = int(os.environ.get(
    "KANBAN_RATELIMIT_COOLDOWN_S", "1800"))

# /ready reports are debounced by payload hash; a forced refresh every
# READY_FORCE_S keeps 'stale' detection honest on quiet boards (same
# contract as runner-agent's verdict_pass — KNB-1007 follow-up: this
# lane claims on tony-dell but never posted, so GET /queue omitted the
# fleet's highest-cap claimer).
READY_REPORT = Path(os.environ.get(
    "KANBAN_DISPATCH_READY_FILE",
    str(Path.home() / ".local/state/kanban-dispatch"
        / "ready-verdicts.json")))
READY_FORCE_S = int(os.environ.get("KANBAN_DISPATCH_READY_FORCE_S",
                                   "900"))


def ratelimit_record(unit: str, sig: str) -> None:
    try:
        log = json.loads(RATELIMIT_FILE.read_text())
    except Exception:
        log = {}
    log.update(until=time.time() + RATELIMIT_COOLDOWN_S,
               hits=int(log.get("hits") or 0) + 1, last=unit, sig=sig,
               at=int(time.time()))
    try:
        RATELIMIT_FILE.write_text(json.dumps(log))
    except OSError:
        pass


def ratelimit_reason() -> str:
    """'' when claims may proceed, else the active cooldown reason."""
    try:
        log = json.loads(RATELIMIT_FILE.read_text())
    except Exception:
        return ""
    until = float(log.get("until") or 0)
    if time.time() >= until:
        return ""
    mins = max(1, int((until - time.time()) / 60))
    return (f"provider rate-limited ({log.get('sig') or '?'} on "
            f"{log.get('last') or '?'}) — claims held ~{mins}m")


def ratelimit_scan_task(tid: str) -> None:
    """Survey-side scan of a finished task's lane logs/journal for
    provider throttle signatures — runs lock-free, so the journalctl
    cost never extends the card flock. opencode/profile runs redirect
    provider errors to the taskdir (stderr.log/events.jsonl), not the
    unit journal, so those are checked first."""
    tdir = Path.home() / ".local/share/devin-dispatch/tasks" / tid
    for name in ("stderr.log", "events.jsonl", "run.json",
                 "usage.json", "verdict.json"):
        try:
            tail = (tdir / name).read_text(errors="replace")[-8000:]
        except OSError:
            continue
        sig = dr.rate_limit_hit(tail)
        if sig:
            ratelimit_record(f"devin-task-{tid}", sig)
            return
    tail = (sh(["journalctl", "--user", "-u", f"devin-task-{tid}",
                "-n", "80", "--no-pager", "-o", "cat"],
               timeout=15).stdout or "")[-8000:]
    sig = dr.rate_limit_hit(tail)
    if sig:
        ratelimit_record(f"devin-task-{tid}", sig)

# Hands-off waiting-card gate (KNB-0928,
# docs/ssot/infrastructure/ssot.devin-autonomy.yml waiting_cards):
# queue EXECUTION is gated separately from kanban-act's auto-close.
# KANBAN_WAITING_GATE=off disables; warn (default) logs verdicts but
# still claims — except declared R3/R4 cards, which are NEVER claimed
# unattended in any mode; strict defers every ineligible card. Flip to
# strict only after the readiness checklist (job
# 2026-11-08-hands-off-waiting-cards) passes.
WAITING_GATE = os.environ.get("KANBAN_WAITING_GATE", "warn")
# Board-api base for lifecycle Telegram summaries (/publish fan-out —
# noise policy lives server-side). Loopback on the writer host.
PUBLISH_API = os.environ.get(
    "KANBAN_PUBLISH_API", "http://127.0.0.1:8787").rstrip("/")


def push_capable(repo: str) -> bool:
    if not PUSH_GUARD:
        return True
    canon = dr.canon_repo(repo)
    if f"push:{canon}" in MY_LABELS or f"push:{repo}" in MY_LABELS:
        return True
    now = time.time()
    hit = _PUSH_PROBE_CACHE.get(canon)
    if hit and now - hit[0] < PUSH_PROBE_TTL:
        return hit[1]
    ok = bool(dr.push_probe(canon).get("pushable"))
    _PUSH_PROBE_CACHE[canon] = (now, ok)
    return ok


# Dead-runner sweep: a card 'running' on a remote runner-agent host that
# stops answering ssh gets requeued after this many consecutive misses
# (~2min cadence — 3 misses ≈ 6min down before requeue).
REQUEUE_AFTER = int(os.environ.get("KANBAN_REQUEUE_MISSES", "3"))
MISS_FILE = Path("/tmp/kanban-runner-misses.json")
# Starvation guard for the shared claim order (dr.claim_sort_key — card
# dispatch-priority-order): a queued card this many hours old outranks
# fresh higher-priority cards. 0 disables — priority is a bias, not a ban.
STARVE_HOURS = float(os.environ.get("KANBAN_STARVE_HOURS", "12"))

# Autonomy contract (docs/ssot/infrastructure/ssot.devin-autonomy.yml) —
# declarative envelope around claims: kill switch, quiet hours, daily
# budget, retry cap, autonomy ceiling. Tony owns this file; the
# dispatcher may read it, never edit it.
POLICY_FILE = REPO / "docs/ssot/infrastructure/ssot.devin-autonomy.yml"
TIER_ORDER = {"t0": 0, "t1": 1, "t2": 2, "t3": 3, "t4": 4}


def load_policy() -> dict:
    try:
        p = yaml.safe_load(POLICY_FILE.read_text()) or {}
        return p.get("dispatch") or {}
    except Exception:
        return {}


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def in_quiet_hours(win: str) -> bool:
    m = re.match(r"^\s*(\d\d:\d\d)\s*-\s*(\d\d:\d\d)\s*$", win or "")
    if not m:
        return False
    lo, hi = _hm(m.group(1)), _hm(m.group(2))
    cur = datetime.now(timezone(timedelta(hours=7)))
    t = cur.hour * 60 + cur.minute
    return lo <= t < hi if lo < hi else (t >= lo or t < hi)


def claims_today(state_file: Path) -> int:
    try:
        st = json.loads(state_file.read_text())
    except Exception:
        return 0
    today = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
    return int(st.get(today, 0))


def bump_claims(state_file: Path) -> None:
    try:
        st = json.loads(state_file.read_text())
    except Exception:
        st = {}
    today = datetime.now(timezone(timedelta(hours=7))).date()
    key = today.strftime("%Y-%m-%d")
    st[key] = int(st.get(key, 0)) + 1
    # prune old dates
    for k in list(st):
        if k != key:
            try:
                if (today - datetime.strptime(k, "%Y-%m-%d").date()).days > 7:
                    st.pop(k)
            except ValueError:
                st.pop(k)
    state_file.write_text(json.dumps(st))


def _blocker_released(blocker_id: str) -> bool:
    """blocked_by gate: released when the blocker card finished without
    a failed merge (dependents need its code on origin), or when a
    manual blocker was closed (column=done). Missing file = released."""
    bp = CARD_DIR / f"{blocker_id}.yml"
    if not bp.exists():
        return True
    b = load_card(bp)
    if b.get("column") == "done":
        return True
    ba = _act(b)
    return ba.get("status") == "done" and ba.get("verified") is not False


def _blocker_released(blocker_id: str) -> bool:
    """blocked_by gate: released when the blocker card finished without
    a failed merge (dependents need its code on origin), or when a
    manual blocker was closed (column=done). Missing file = released."""
    bp = CARD_DIR / f"{blocker_id}.yml"
    if not bp.exists():
        return True
    b = load_card(bp)
    if b.get("column") == "done":
        return True
    ba = _act(b)
    return ba.get("status") == "done" and ba.get("verified") is not False


def runner_reachable(host: str) -> bool:
    r = sh(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
            host, "true"], timeout=15)
    return r.returncode == 0


def requeue_dead(path: Path, host: str) -> str:
    """Locked re-check + requeue: only flip if the card is still running
    on the same (dead) runner — a fresh claim or manual move wins."""
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        card = load_card(path)
        a = _act(card)
        if a.get("status") != "running" or a.get("runner") != host:
            return "resolved itself"
        a["status"] = "queued"
        a.pop("runner", None)
        a.pop("task_id", None)
        _ensure_claim(card).pop("session", None)
        if card.get("column") == "doing":
            card["column"] = "backlog"
        comms_add(card, "chaba",
                  f"runner {host} unreachable {REQUEUE_AFTER} passes "
                  f"— requeued")
        _notify("stalled", card.get("id") or path.stem,
                f"runner {host} unreachable — requeued")
        card["updated"] = now()
        save_card(path, card)
        return "requeued"


def sweep_dead_runners(remote: list) -> bool:
    """remote = [(path, card_id, runner)] seen running on other hosts.
    Probes each runner (lock-free); requeues cards whose runner has been
    unreachable REQUEUE_AFTER consecutive passes. True if cards changed."""
    try:
        misses = json.loads(MISS_FILE.read_text())
    except Exception:
        misses = {}
    up: dict = {}
    changed = False
    seen = set()
    for p, cid, host in remote:
        seen.add(cid)
        if host not in up:
            up[host] = runner_reachable(host)
        if up[host]:
            misses.pop(cid, None)
            continue
        misses[cid] = misses.get(cid, 0) + 1
        if misses[cid] >= REQUEUE_AFTER:
            misses.pop(cid, None)
            print(f"{cid}: runner {host} down — {requeue_dead(p, host)}")
            changed = True
        else:
            print(f"{cid}: runner {host} unreachable "
                  f"({misses[cid]}/{REQUEUE_AFTER})")
    # forget counters for cards no longer remotely running
    for cid in [c for c in misses if c not in seen]:
        misses.pop(cid, None)
    try:
        MISS_FILE.write_text(json.dumps(misses))
    except Exception:
        pass
    return changed


def active_tasks() -> int:
    r = sh(["systemctl", "--user", "list-units", "devin-task-*",
            "--state=active", "--no-legend"])
    return sum(1 for ln in r.stdout.splitlines() if ln.strip())

# The rail text + task composition live in dispatch_task.py — shared
# with runner-agent's devin path (runner-agent-primer-coverage) so a
# future rail lands in both lanes. The names stay bound here for the
# regression tests (and any reader that imported them).
TASK_RAILS = dt.TASK_RAILS
RETRY_RAILS = dt.RETRY_RAILS
REPORT_RAILS = dt.REPORT_RAILS


# Lesson/good lines injected into the most recent build_task call — read
# by start_pending so the card comms logs exactly what the primer added.
LAST_PRIMER_LINES: list = []
LAST_GOOD_LINES: list = []


def build_task(card: dict) -> str:
    """The text handed to `devin-dispatch start` — card spec (or
    title+note) plus TASK_RAILS, a KNOWN_PITFALLS primer block when past
    lessons match, a KNOWN_GOOD block when first-try-verified work
    matches, RETRY_RAILS on requeue, plus REPORT_RAILS when
    report-linked. The composition itself is dispatch_task's — the
    runner-agent devin lane renders the identical prompt."""
    task, primer, good = dt.build_task_text(card, HOST, API, root=REPO)
    LAST_PRIMER_LINES[:] = primer
    LAST_GOOD_LINES[:] = good
    return task


def now() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


# ops-event docs go to mddb-ops — ada-ha-events-* moved off the leader
# in the mddb-ops split (:11023 is pre-split residue only).
MDDB = os.environ.get(
    "MDDB_OPS_URL", "http://100.123.163.11:11025/v1").rstrip("/")


def ops_event(detail: str) -> None:
    """kanban_retry audit line — lands in the ada ops digest, same
    collection/shape kanban-act uses (ops-event kind)."""
    try:
        now = datetime.now(timezone.utc)
        req = urllib.request.Request(
            f"{MDDB}/add",
            data=json.dumps({
                "collection": "ada-ha-events-tony",
                "key": f"ops-kanban-retry-{now:%Y%m%d%H%M%S%f}",
                "lang": "en", "contentMd": detail,
                "meta": {"kind": ["ops-event"], "type": ["kanban_retry"],
                         "instance": ["tony"],
                         "ts": [now.isoformat(timespec="seconds")],
                         "written_by": ["kanban-dispatch"]}}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(f"warn: ops event failed: {e}", file=sys.stderr)


def comms_add(card: dict, frm: str, text: str) -> None:
    comms = card.get("comms")
    if not isinstance(comms, list):
        card["comms"] = comms = []
    comms.append({"at": now(), "from": frm, "text": text[:500]})


def sh(cmd: list, timeout=60, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, **kw)


def api(path: str, body: dict | None = None) -> dict:
    """Board-api call — read or write. Same shape as runner-agent's api():
    errors come back as {"error": ...} so advisory paths degrade instead
    of raising."""
    url = API + path
    try:
        if body is None:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.loads(r.read())
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=75) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:300] or str(e)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def unit_state(task_id: str) -> str:
    """devin-dispatch tasks run as devin-task-<id>.service user units."""
    r = sh(["systemctl", "--user", "is-active", f"devin-task-{task_id}.service"])
    return r.stdout.strip() or "unknown"


def overloaded() -> bool:
    """5-min load per core above MAX_LOAD_PC → don't claim new work."""
    if MAX_LOAD_PC <= 0:
        return False
    try:
        return os.getloadavg()[1] / (os.cpu_count() or 1) > MAX_LOAD_PC
    except OSError:
        return False


def load_card(path: Path) -> dict:
    card = yaml.load(path.read_text(), Loader=_YAML_LOAD) or {}
    card.setdefault("id", path.stem)
    return card


def load_dispatch_cards(card_dir: Path | None = None,
                        cache_path: Path | None = None) -> list:
    if card_dir is None:
        card_dir = CARD_DIR
    if cache_path is None:
        cache_path = INDEX_FILE
    root = str(card_dir.resolve())
    try:
        payload = json.loads(cache_path.read_text())
        previous = (payload.get("cards") if payload.get("version") == 1
                    and payload.get("root") == root else {})
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError, AttributeError):
        previous = {}
    current = {}
    loaded = []
    for path in sorted(card_dir.glob("*.yml")):
        stat = path.stat()
        signature = [stat.st_mtime_ns, stat.st_ctime_ns,
                     stat.st_ino, stat.st_size]
        cached = previous.get(path.name) or {}
        if not isinstance(cached, dict):
            cached = {}
        card = None
        if cached.get("signature") == signature and "status" in cached:
            status = cached["status"]
        else:
            card = load_card(path)
            status = _act(card).get("status")
        current[path.name] = {"signature": signature, "status": status}
        if status in ("queued", "starting", "running"):
            if card is None:
                card = load_card(path)
            loaded.append((path, card))
    if current != previous:
        temp_path = cache_path.with_name(
            f"{cache_path.name}.{os.getpid()}.tmp")
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(json.dumps(
                {"version": 1, "root": root, "cards": current},
                separators=(",", ":")))
            os.replace(temp_path, cache_path)
        except OSError as exc:
            print(f"warn: dispatch card index write failed: {exc}",
                  file=sys.stderr)
            try:
                temp_path.unlink()
            except OSError:
                pass
    return loaded


def save_card(path: Path, card: dict) -> None:
    card["updated"] = now()
    card_io.atomic_dump_card(path, card)


def mark_start(path: Path, card: dict) -> None:
    """Phase-A claim (under the lock): transient 'starting' state keeps the
    card out of other dispatchers' reach; phase B runs the slow start."""
    a = _ensure_act(card)
    card.pop("awaiting_action", None)  # being dispatched = triaged
    a["status"] = "starting"
    a["runner"] = HOST
    a["attempts"] = int(a.get("attempts") or 0) + 1
    _ensure_claim(card)["since"] = now()
    # honest columns: a live claim means doing — this dispatcher's claims
    # used to leave the card in backlog/review while the unit ran
    # (dispatch-failed-cards-park-in-doing)
    if card.get("column") not in ("doing", "done"):
        card["column"] = "doing"


def _fail_or_requeue(card: dict, why: str) -> str:
    """Stalled-claim lifecycle for a dead run (card
    dispatch-failed-cards-park-in-doing): the claim is over, so the card
    leaves doing — queued in backlog for another claim while attempts <
    max_attempts (KANBAN_AUTORETRY=0 disables), else parked there as
    failed. A manual /action do=retry resets attempts and re-arms it.
    Returns the verdict text for the caller's comms line."""
    a = _ensure_act(card)
    a["last_failure"] = why[:280]
    _ensure_claim(card).pop("session", None)
    att = int(a.get("attempts") or 0)
    max_att = dr.dispatch_attempt_cap(card)
    if os.environ.get("KANBAN_AUTORETRY", "1") != "0" and att < max_att:
        a["status"] = "queued"
        a.pop("runner", None)
        a.pop("task_id", None)
        if card.get("column") != "done":
            card["column"] = "backlog"
        return (f"auto-retry queued (attempt {att + 1}/{max_att}) "
                "(column -> backlog)")
    a["status"] = "failed"
    if card.get("column") == "doing":
        card["column"] = "backlog"
    return (f"attempt cap {max_att} reached — moved doing -> backlog; "
            "a manual retry re-arms it")


def finish_one(path: Path, card: dict,
               probe: tuple | None = None) -> str:
    """Phase-A finish (under the lock): cheap status flip only. A clean
    finish defers the git merge to phase B (merge_pending flag).

    `probe` = the phase-A0 survey's (task_id, unit_state, ex_ok, ex_ev,
    session_probe) for this card — systemctl/journalctl/git calls run
    BEFORE the flock so a slow systemd or fat journal never extends the
    hold (2026-11-17 convoy: these probes were the >25s lock holds,
    OPS-0725)."""
    a = _ensure_act(card)
    tid = str(a.get("task_id") or "")
    sess_probe = None
    if probe and probe[0] == tid:
        state, ex_ok, ex_ev = probe[1], probe[2], probe[3]
        sess_probe = probe[4] if len(probe) > 4 else None
    else:
        # card flipped to running between survey and lock — probe now;
        # rare enough to keep inside the lock
        state = unit_state(tid) if tid else "unknown"
        ex_ok = ex_ev = None
    if state in ("active", "activating"):
        return "still running"
    if state == "failed":
        # crashed unit — do NOT mark done or auto-merge: the branch may
        # hold partial work. The dead claim leaves doing: requeue under
        # the attempts cap, else park failed in backlog.
        why = f"{tid} FAILED — see `devin-dispatch logs {tid}`"
        a["result"] = why
        verdict = _fail_or_requeue(card, why)
        comms_add(card, "chaba", f"run failed — {verdict}")
        _notify("fail", card.get("id") or path.stem,
                f"unit failed — {verdict}")
        return "failed"
    # Executor-owned closeout (OPS-1066): tasks run by runner-agent's
    # non-devin executors (jules, opencode, kk_mac_local) own their finish
    # path — the runner's finish_pass calls finish_<executor>_lane for
    # the artifact/verified evidence. This sweeper knows none of that;
    # it used to finish the card first ("no exit record") and the real
    # closeout then bounced off status=done. Defer when the task meta
    # names a runner-owned executor so the claiming runner reports.
    taskdir = Path.home() / ".local/share/devin-dispatch/tasks" / tid
    try:
        meta_ex = str(json.loads(
            (taskdir / "meta.json").read_text()).get("executor") or "")
    except Exception:
        meta_ex = ""
    if meta_ex and meta_ex not in ("devin", "devin-dispatch"):
        return f"deferred — executor={meta_ex} closeout is the runner's"
    # Units run under systemd-run --collect: a failed unit is unloaded
    # and is-active can no longer see Result=exit-code — so 'not active'
    # alone is NOT proof of success (the 2026-10-25/26
    # dispatch-empty-closeout-verification-gap burns: 'Failed with
    # result' sessions still recorded 'finished (ok)'). Check the real
    # exit evidence before calling anything finished.
    if ex_ok is None and ex_ev is None:
        ex_ok, ex_ev = (dr.unit_exit_evidence(tid) if tid
                        else (None, "no task_id"))
    if ex_ok is False:
        why = (f"{tid} FAILED ({ex_ev}) — see "
               f"`devin-dispatch logs {tid}`")
        a["result"] = why
        verdict = _fail_or_requeue(card, why)
        comms_add(card, "chaba",
                  f"run failed ({ex_ev}) — {verdict}")
        return "failed"
    if ex_ok is None:
        # unproven exit — not 'ok', but not provably failed either:
        # finish to review and let the close-out/merge-sweep verified
        # gate weigh the deliverable (a killed session can still leave
        # real, mergeable work; verified stays withheld either way —
        # merge_pending_one requires a proven exit for the stamp).
        comms_add(card, "chaba",
                  f"run ended with no exit record ({ex_ev}) — the "
                  "verified gate decides from the deliverable")
    # unit left the active state — treat as finished
    a["status"] = "done"
    a["result"] = f"{tid} finished ({state}) — see `devin-dispatch logs {tid}`"
    card["column"] = "review"
    card.setdefault("review_kind", "verify")  # close-out contract — without it the ssot-optimize gate fails commits repo-wide
    _ensure_claim(card).pop("session", None)
    comms_add(card, "chaba", f"run finished ({state}) → review")
    _notify("finish", card.get("id") or path.stem,
            f"finished ({state}) → review")
    if os.environ.get("KANBAN_AUTOMERGE", "1") != "0":
        a["merge_pending"] = True  # merged outside the lock in phase B
    else:
        for n in session_end_notes(card, sess_probe):
            comms_add(card, "chaba", n)
    return "finished"


def session_probe(card: dict) -> dict:
    """Git-side session facts for session_end_notes — resolved OUTSIDE
    the card flock (session()/dirty_count()/merge_state() are several
    git subprocesses each; the merge_pending_one write-back used to run
    them under the lock, 2026-11-17 convoy)."""
    out = {"session": {}, "dirty": None, "merge": {}}
    try:
        s = dr.session(card)
        out["session"] = s
        if s.get("worktree"):
            out["dirty"] = dr.dirty_count(s["worktree"])
        if s.get("head") and s.get("base_ref"):
            out["merge"] = dr.merge_state(
                s["repo_root"], s["head"], s["base_ref"])
    except Exception:
        pass
    return out


def session_end_notes(card: dict, probe: dict | None = None) -> list:
    """Comms lines for leftover work at session end (merge-guard spec c):
    dirty worktree file count, plus commits not yet in the default branch
    (the same condition the board-api close gate blocks on). `probe` is
    the pre-lock session_probe() result; absent → probed inline (only
    callers already outside the flock should rely on that)."""
    notes = []
    try:
        probe = probe or session_probe(card)
        s = probe.get("session") or {}
        dirty = probe.get("dirty")
        if s.get("worktree") and dirty:
            notes.append(
                f"session end: worktree {s['worktree'].name} dirty — "
                f"{dirty} uncommitted file(s); commit or clean before "
                f"pruning")
        m = probe.get("merge") or {}
        if s.get("head") and s.get("base_ref") \
                and m.get("checked") and not m["ancestor"]:
            notes.append(
                f"session end: {m['unmerged']} commit(s) on "
                f"{s['branch']} not in {s['base_ref']} — close will "
                f"block until merged")
    except Exception:
        pass
    return notes


def _with_lock(fn):
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        return fn()


UNCLAIM_MARK = "unclaimable by the declared runner fleet"

# Lifecycle Telegram summaries (waiting_cards.reporting): collected
# under the card lock, flushed to board-api /publish in phase B — the
# server-side noise policy debounces; a dead relay never blocks a claim.
_NOTIFY: list = []


def _notify(event: str, cid: str, detail: str = "") -> None:
    _NOTIFY.append((event, cid, detail[:200]))


def _flush_notify() -> None:
    pending, _NOTIFY[:] = _NOTIFY[:], []
    for event, cid, detail in pending:
        wc.notify_lifecycle(PUBLISH_API, cid, event, detail, host=HOST)


def _last_chaba_flag(card: dict, mark: str) -> str:
    """Most recent chaba comms line containing `mark`, '' when none —
    the card's comms are the debounce store for flag/defer notes."""
    c = _last_chaba_flag_comm(card, mark)
    return str(c.get("text") or "") if c else ""


def _last_chaba_flag_comm(card: dict, mark: str) -> dict | None:
    """Most recent chaba comms entry containing `mark` — callers that
    need the `at` age (defer debounce) use this; text-only callers keep
    _last_chaba_flag."""
    for c in reversed(card.get("comms") or []):
        if c.get("from") == "chaba" and mark in (c.get("text") or ""):
            return c
    return None


DEFER_NOTE_SECS = int(os.environ.get("KANBAN_DEFER_NOTE_SECS", "21600"))


def _defer_norm(text: str) -> str:
    """Volatile metrics stripped for defer debounce — 'load/core 1.38'
    vs '2.76' is the same defer (OPS-1314)."""
    return re.sub(r"\d+(?:\.\d+)?", "#", text)


def _defer_note(path: Path, card: dict, reason: str) -> bool:
    """Per-host defer comms — the served-side twin of runner-agent's
    note_defer: 'this host saw it and declined' lands on the card, not
    just in the unit journal (the 2026-11-07 ops0790 starve was
    invisible for ~3h because skips lived only in logs). Debounced on
    the card's own comms: an unchanged reason is not re-logged. Comms
    only — one host's refusal is not a fleet verdict, so no
    awaiting_action."""
    text = f"{HOST} defers: {reason}"[:500]
    last = _last_chaba_flag_comm(card, f"{HOST} defers:")
    if last:
        try:
            age = (datetime.now() - datetime.strptime(
                str(last.get("at") or ""),
                "%Y-%m-%d %H:%M")).total_seconds()
        except Exception:
            age = DEFER_NOTE_SECS + 1
        if _defer_norm(str(last.get("text") or "")) == _defer_norm(text) \
                and age < DEFER_NOTE_SECS:
            return False
    comms_add(card, "chaba", text)
    save_card(path, card)
    return True


def _flag_unclaimable(path: Path, card: dict, fleet: dict) -> str:
    """Fleet-level starvation flag (dispatch-claim-eligibility-
    visibility): a queued card no declared runner can serve writes WHY
    to the card — chaba comms + awaiting_action — so Ada/triage sees
    it and fixes labels or re-routes instead of the queue starving
    silently. -> 'new' (flag written this pass), 'present' (same flag
    already on the card — debounced), '' (declared fleet may serve it).
    A cleared flag with unchanged reasons stays cleared (triage
    dismissed it)."""
    reasons = dr.unsatisfiable_reasons(card, fleet=fleet,
                                       local_host=HOST,
                                       push_probe=push_capable)
    if not reasons:
        return ""
    text = (f"{UNCLAIM_MARK}: " + "; ".join(reasons)
            + " — fix action.labels/host pins or teach a runner the "
              "capability (card dispatch-claim-eligibility-visibility)"
            )[:500]
    if _last_chaba_flag(card, UNCLAIM_MARK) == text:
        return "present"
    comms_add(card, "chaba", text)
    card["awaiting_action"] = True
    save_card(path, card)
    print(f"{card['id']}: UNCLAIMABLE — {'; '.join(reasons)}")
    return "new"


# Keyword lane classifier (jev-pilot Phase 2, 2026-10-25). Deterministic,
# validated 23/23 on corpus + held-out cards (evals/results/jev/).
# Canonical copy lives in dispatch_repos — aliases kept for importlib
# consumers (tests, evals scripts).
LANE_KW = dr.LANE_KW
LANE_COMPARE = dr.LANE_COMPARE
classify_lane = dr.classify_lane

def start_pending(path: Path) -> str:
    """Phase B: devin-dispatch start (slow, no lock), then write back."""
    card = load_card(path)  # read-only peek for spec/task build
    a = _ensure_act(card)
    repo = a.get("repo", "chaba")
    task = build_task(card)
    ex = str(a.get("executor") or "").strip()
    lane = str(a.get("lane") or "")
    # An explicit executor is itself the routing decision — lane
    # classification stays out (executor=devin pins the devin path and
    # keeps action.model as the native devin id it declared).
    if not lane and JEV_LANE and not ex:
        lane, lsrc, _conf = classify_lane(card, with_detail=True)
        if lane:
            a["lane"] = lane
            # classifier output carries provenance so a re-queue
            # re-evaluates it — a bare stamp reads as an author pin
            # forever (devin-lane-cheap-ops-reroute)
            a["lane_source"] = str(lsrc or "").split(":", 1)[0] or "claim"
            # Persist the executor-aware cheapest model too, so ANY
            # claimer (runner-agent reads action.model) routes to the
            # right lane — the env-only path never reached remote
            # runner-agents (model-chain probe OPS-0836, 2026-10-25).
            # This dispatcher only launches devin, so the pick is the
            # devin-native id — litellm/* aliases belong to the
            # opencode/proxy executor and never reach action.model here
            # (devin-executor-model-routing; paid_frontier has no devin
            # pick -> stays gated, executor default).
            pick = dr.lane_model(lane, "devin")
            if pick:
                a["model"] = pick
            save_card(path, card)
    if lane == "manual":
        return "manual lane — not dispatched (Tony's hands)"
    env = dict(os.environ)
    # Provider/executor namespaces must match
    # (dispatch-model-pick-executor-mismatch + devin-executor-model-
    # routing): a litellm/* model id on the devin CLI is a guaranteed
    # 'Unknown model' exit — drop it to the executor default rather
    # than launch a dead session. This dispatcher only serves devin.
    exr = ex or "devin"
    model = str(a.get("model") or "")
    if model and not dr.model_valid_for_executor(model, exr):
        model = ""
    if not model:
        model = dr.lane_model(lane, exr)  # cheapest lane, ns-aware
    if model:
        env["DISPATCH_MODEL"] = model  # -> devin --model
    # Executor-contract context for the launcher's task meta + usage:
    # the card that declared it, the resolved executor/provider, and the
    # profile id — devin-dispatch._meta_write persists them.
    env["DISPATCH_CARD"] = card.get("id") or path.stem
    env["DISPATCH_EXECUTOR"] = exr
    env["DISPATCH_PROVIDER"] = dr.model_provider(model) or "devin"
    if dr.card_profile(card):
        env["DISPATCH_PROFILE"] = dr.card_profile(card)
    if a.get("target_host"):
        env["DISPATCH_TARGET_HOST"] = str(a["target_host"])
    r = sh([DISPATCH, "start", repo, task], timeout=120, env=env)

    def apply():
        card = load_card(path)  # re-read — API may have touched the card
        a = _ensure_act(card)
        if r.returncode != 0:
            why = f"dispatch failed: {(r.stderr or r.stdout).strip()[:300]}"
            a["result"] = why
            verdict = _fail_or_requeue(card, why)
            comms_add(card, "chaba",
                      f"dispatch failed — {verdict}: {why[:160]}")
            save_card(path, card)
            return "dispatch failed"
        task_id = r.stdout.strip().splitlines()[-1].strip()
        a["status"] = "running"
        a["task_id"] = task_id
        a["runner"] = HOST
        _ensure_claim(card)["session"] = task_id
        card["claim"]["since"] = now()
        blurb = dr.executor_blurb(card)
        comms_add(card, "chaba",
                  f"dispatched {task_id} on {repo}"
                  + (f" ({blurb})" if blurb else ""))
        _notify("start", card.get("id") or path.stem,
                f"dispatched {task_id} on {repo}")
        if LAST_PRIMER_LINES or LAST_GOOD_LINES:
            msg = f"primer injected {len(LAST_PRIMER_LINES)} lesson(s)"
            if LAST_PRIMER_LINES:
                msg += ": " + "; ".join(
                    l[:80] for l in LAST_PRIMER_LINES)
            if LAST_GOOD_LINES:
                msg += (" | good: " + "; ".join(
                    l[:80] for l in LAST_GOOD_LINES))
            comms_add(card, "chaba", msg)
        save_card(path, card)
        return f"dispatched {task_id}"
    return _with_lock(apply)


def merge_pending_one(path: Path) -> str:
    """Phase B: close-out (checkpoint + push + goals gate + auto-merge;
    slow, no lock), then write back."""
    try:
        res = dr.close_out(load_card(path))
    except Exception as e:
        res = {"merged": False, "error": str(e)}
    # card dispatch-worktree-gc — remove the session worktree+branch once
    # the head is provably on origin (never dirty/unmerged; runs outside
    # the card lock like the merge itself)
    gc_notes = dr.gc_session(res)
    # exit evidence for the verified stamp — probed OUTSIDE the lock
    # (systemctl/journalctl are the slow part, same rule as the merge).
    ex_ok, ex_ev = dr.unit_exit_evidence(
        str(((res.get("session") or {}).get("task_id")) or ""))
    # session_end_notes' git probes — likewise surveyed before the
    # write-back lock, not inside it.
    sess_probe = session_probe(load_card(path))

    def apply():
        card = load_card(path)
        a = _act(card)
        a.pop("merge_pending", None)
        if res.get("merged"):
            # verified = "the dispatch delivered": a merge whose session
            # FAILED or left no exit record still withholds the stamp —
            # merge-sweep's gate then holds it for a human instead of
            # auto-closing (dispatch-empty-closeout-verification-gap).
            if ex_ok is True:
                a["verified"] = True
                # close-the-loop (ada-dispatch-approve-button): the
                # verdict Tony approved for must reach him — milestone
                # routes to Telegram via /publish
                _notify("verified", card.get("id") or path.stem,
                        "merged + verified — auto-close follows")
            else:
                comms_add(
                    card, "chaba",
                    f"merged but verified withheld — unit exit "
                    f"{'failed' if ex_ok is False else 'unproven'} "
                    f"({ex_ev}); merge-sweep's gate will review")
                _notify("unverified", card.get("id") or path.stem,
                        f"merged but verified withheld "
                        f"({'failed' if ex_ok is False else 'unproven'} "
                        f"exit) — held for review")
        elif res.get("conflicts") or res.get("test_failures") \
                or res.get("shadows") or (
                res.get("gate") and not res["gate"]["ok"]):
            a["verified"] = False  # checked and NOT verified
            # Review feedback loop: conflicts/goal-failures requeue the
            # card with the failure evidence (RETRY_RAILS carries it into
            # the next session) until action.max_attempts is reached.
            # attempts is counted at claim time (mark_start) — requeue
            # while attempts_used < max_attempts (max_attempts = total
            # dispatches incl. retries; mirrors merge-sweep fail_attempt).
            att = int(a.get("attempts") or 0)
            max_att = dr.dispatch_attempt_cap(card)
            if (os.environ.get("KANBAN_AUTORETRY", "1") != "0"
                    and att < max_att):
                why = ("; ".join(dr.close_out_notes(res)) or
                       "merge/goals failed")[:280]
                a["last_failure"] = why
                a["status"] = "queued"
                a.pop("runner", None)
                a.pop("task_id", None)
                # requeued = claimable, not in-flight — the card goes
                # back to backlog, not sitting in doing/review
                if card.get("column") in ("doing", "review"):
                    card["column"] = "backlog"
                comms_add(card, "chaba",
                          f"auto-retry queued (attempt {att + 1}/"
                          f"{max_att}): {why} (column -> backlog)")
                _notify("fail", card.get("id") or path.stem,
                        f"merge/goals failed — auto-retry "
                        f"{att + 1}/{max_att}")
                ops_event(
                    f"kanban-dispatch auto-retry `{card.get('id') or path.stem}` "
                    f"(attempt {att + 1}/{max_att}) on {HOST}: {why}")
        for n in dr.close_out_notes(res):
            comms_add(card, "chaba", n)
        for n in gc_notes:
            comms_add(card, "chaba", n)
        for n in session_end_notes(card, sess_probe):
            comms_add(card, "chaba", n)
        if not res.get("merged") and not res.get("noop"):
            _notify("fail", card.get("id") or path.stem,
                    f"close-out merge failed: "
                    f"{str(res.get('error') or res.get('skipped') or '')[:120]}")
        save_card(path, card)
        if res.get("noop"):
            return "noop"
        return ("merged" if res.get("merged")
                else f"merge: {res.get('error') or res.get('skipped') or res}")
    return _with_lock(apply)


def claim_pass_gate(pol: dict, pf_env: dict) -> str:
    """'' when this pass may claim, else the blocking gate's reason —
    load, kill switch, quiet hours, waiting-cards preflight, provider
    rate-limit cooldown, in main()'s order. Shared with verdict_pass()
    so /ready reports the same pass-level reason a claim would hit."""
    if overloaded():
        return f"load gate: load5/cpu > {MAX_LOAD_PC}"
    kill = Path(pol.get("kill_switch") or "/tmp/no-kanban-dispatch")
    if kill.exists():
        return f"kill switch {kill} present"
    if in_quiet_hours(pol.get("quiet_hours") or ""):
        return f"quiet hours {pol.get('quiet_hours') or ''}"
    pf_fails = wc.preflight({"recoverability": "R0"}, pf_env)
    if pf_fails:
        return "waiting-cards preflight: " + "; ".join(pf_fails)
    return ratelimit_reason()


def _claim_epoch(card: dict) -> int:
    """claim.since ('%Y-%m-%d %H:%M' ICT) -> epoch for the /ready active
    list; 0 when absent/unparseable (board-api stamps receipt time)."""
    c = card.get("claim")
    s = str(c.get("since") or "") if isinstance(c, dict) else ""
    try:
        return int(datetime.strptime(
            s, "%Y-%m-%d %H:%M")
            .replace(tzinfo=timezone(timedelta(hours=7))).timestamp())
    except Exception:
        return 0


def _verdict_reason(card: dict, ctx: dict) -> str:
    """'' when this dispatcher would claim `card` now, else the gate that
    stops it. Mirrors the queued-card gate order in main() (pass gates
    -> autonomy -> retry cap -> pins -> type/lane/executor -> labels ->
    push guard -> waiting-cards -> foreign claim -> host cap) so /queue's
    blocked projection matches what a pass would do. Read-only: none of
    the claim loop's flag/defer/save side effects run here."""
    a = _act(card)
    # mirrors the claim loop's column scope (KNB-0036): a stale queued
    # flag on a done/review card is off-queue, whatever else passes
    if card.get("column") not in ("backlog", "doing"):
        return (f"column {card.get('column') or '(unset)'} — "
                "off the claim queue")
    if ctx["pass_reason"]:
        return ctx["pass_reason"]
    ctier = TIER_ORDER.get(str(card.get("autonomy") or ""), -1)
    if ctier > ctx["max_tier"]:
        return f"autonomy t{ctier} > policy max t{ctx['max_tier']}"
    attempt_cap = min(ctx["retry_cap"], dr.dispatch_attempt_cap(card))
    if int(a.get("attempts") or 0) >= attempt_cap:
        return f"retry cap {attempt_cap} reached"
    pinned = a.get("host")
    if pinned and dr.canon_host(pinned) != dr.canon_host(HOST):
        return f"host-pinned to {pinned}"
    blocker_id = card.get("blocked_by")
    if blocker_id and not _blocker_released(blocker_id):
        return f"blocked_by {blocker_id}"
    if (a.get("type") or "dispatch") != "dispatch":
        return f"action.type {a.get('type')!r} not dispatchable"
    lane = str(a.get("lane") or "").strip()
    if lane == "manual":
        return "lane=manual (Tony's hands)"
    if lane in ("jules", "nlm_batch"):
        return f"remote lane {lane} — not a devin claim"
    ex = str(a.get("executor") or "").strip()
    if ex and ex != "devin":
        why = ("not a known executor" if ex not in dr.EXECUTORS
               else "Tony's hands — never claimed" if ex == "manual"
               else f"routes to the {ex} executor, not devin")
        return f"executor={ex} ({why})"
    th = str(a.get("target_host") or "").strip()
    if th and th != HOST:
        return f"target_host={th}"
    needs = set(a.get("labels") or [])
    if needs and not needs <= MY_LABELS:
        return f"missing labels {sorted(needs - MY_LABELS)}"
    repo = str(a.get("repo") or "chaba")
    if not push_capable(repo):
        return (f"push guard: cannot push {dr.canon_repo(repo)} "
                "from this host")
    env = dict(ctx["pf_env"], claimed=ctx["inflight"], cap=HOST_CAP)
    wv = wc.evaluate(card, env=env, push_probe=push_capable)
    if wv["never"] or (WAITING_GATE == "strict" and not wv["eligible"]):
        return ("waiting-cards gate: "
                + ("; ".join(wv["reasons"])[:200] or "ineligible"))
    if a.get("runner") and a["runner"] != HOST:
        return f"claimed on {a['runner']}"
    if ctx["inflight"] >= HOST_CAP:
        return f"host cap {HOST_CAP} ({ctx['inflight']} in flight)"
    return ""


def verdict_pass() -> None:
    """/ready report — this dispatcher's claimability verdict for every
    queued card plus its in-flight claims (KNB-1007 follow-up: tony-dell
    claims via kanban-dispatch, which never posted, so GET /queue's
    hosts map omitted the fleet's highest-cap claimer and queued cards
    showed 'unreported'). Runs every pass, even when gates block
    claiming — the projection needs 'why waiting' exactly then.
    Debounced by payload hash, forced every READY_FORCE_S; never fails
    the claim pass."""
    try:
        pol = load_policy()
        pf_env = wc.local_env(host=HOST, path=REPO)
        pass_reason = claim_pass_gate(pol, pf_env)
        loaded = load_dispatch_cards()
        # verdicts cover every queued card — a foreign-runner claim gets
        # its 'claimed on <host>' reason, matching the claim loop; only
        # the active list is host-scoped.
        queued = [(p, c) for p, c in loaded
                  if _act(c).get("status") == "queued"]
        active_cards = [(p, c) for p, c in loaded
                        if _act(c).get("status") in ("starting",
                                                     "running")
                        and _act(c).get("runner") in (None, "", HOST)]
        # fresh unit count — phase A0's active_base predates this pass's
        # own starts, so it would undercount inflight at verdict time
        inflight = active_tasks() + sum(
            1 for _p, c in active_cards
            if _act(c).get("status") == "starting")
        ctx = {"pass_reason": pass_reason,
               "max_tier": TIER_ORDER.get(
                   str(pol.get("max_autonomy") or "t3"), 3),
               "retry_cap": int(pol.get("retries_per_card") or 2),
               "pf_env": pf_env, "inflight": inflight}
        verdicts = {}
        for _p, c in queued:
            cid = c.get("id")
            if not cid:
                continue
            reason = _verdict_reason(c, ctx)
            verdicts[cid] = {"ok": not reason, "reason": reason}
        active = [{"id": c.get("id") or p.stem,
                   "unit": str(_act(c).get("task_id") or ""),
                   "at": _claim_epoch(c)}
                  for p, c in active_cards]
        h = hashlib.sha1(json.dumps(
            {"v": verdicts,
             "a": sorted(x["id"] for x in active)},
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
                   {"host": HOST, "verdicts": verdicts,
                    "active": active})
        if resp.get("error"):
            print(f"warn: /ready report failed: {resp['error']}")
            return
        READY_REPORT.parent.mkdir(parents=True, exist_ok=True)
        READY_REPORT.write_text(
            json.dumps({"hash": h, "at": time.time()}))
    except Exception as e:
        print(f"warn: verdict_pass failed: {e}")


def main() -> int:
    starts, merges, remote = [], [], []
    changed = False
    # Phase A0 — lock-free: every probe that used to run under the card
    # flock (systemctl/journalctl per running card, git push --dry-run,
    # SSOT fleet parse, env preflight). Stacked across cards they were
    # the >25s holds that 503'd board-api writes (2026-11-17 convoy,
    # OPS-0725). Everything below is read-only on shared state.
    pol = load_policy()
    budget = int(pol.get("sessions_per_day") or 0)
    state_file = Path(pol.get("state_file")
                      or "/tmp/kanban-dispatch-state.json")
    max_tier = TIER_ORDER.get(str(pol.get("max_autonomy") or "t3"), 3)
    retry_cap = int(pol.get("retries_per_card") or 2)
    # Pass-level claim gates (load, kill switch, quiet hours,
    # waiting-cards preflight, provider rate-limit) — shared with
    # verdict_pass() so /ready reports the same reason.
    pf_env = wc.local_env(host=HOST, path=REPO)
    pass_reason = claim_pass_gate(pol, pf_env)
    can_claim = not pass_reason
    if pass_reason:
        print(f"{pass_reason} — not claiming")
    # Declared fleet claim surface for the unclaimable flag — parsed
    # once per pass; {} when the SSOT is unreadable (never flags).
    try:
        fleet = dr.fleet_capabilities()
    except Exception:
        fleet = {}
    active_base = active_tasks()
    # Probe survey for cards currently 'running' on THIS host:
    # unit_state (systemctl is-active), exit evidence (systemctl show /
    # journalctl) and the git session probe — finish_one consumes them
    # inside the flock instead of spawning under it. Cards that flip to
    # running between survey and lock take the inline fallback.
    prescan = load_dispatch_cards()
    unit_survey = {}
    for _p, _c in prescan:
        _a = _act(_c)
        if _a.get("status") != "running" \
                or (_a.get("runner") and _a["runner"] != HOST):
            continue
        _tid = str(_a.get("task_id") or "")
        _st = unit_state(_tid) if _tid else "unknown"
        _ex = (dr.unit_exit_evidence(_tid)
               if _tid and _st not in ("active", "activating")
               else (None, "not surveyed"))
        # rate-limit survey (dispatch-runner-resilience): a unit that
        # just died on a provider 429 arms the claim cooldown — lock-
        # free here, never inside the card flock.
        if _tid and _st not in ("active", "activating") \
                and _ex[0] is not True:
            try:
                ratelimit_scan_task(_tid)
            except Exception:
                pass  # a journal hiccup must not break the survey
        # session_end_notes git probes — only needed on the no-automerge
        # finish path (merge_pending_one surveys its own)
        _sess = session_probe(_c) \
            if os.environ.get("KANBAN_AUTOMERGE", "1") == "0" else None
        unit_survey[_tid] = (_tid, _st, _ex[0], _ex[1], _sess)
    # Warm the push-probe cache for every repo in play — the claim gates
    # inside the lock then read cache, never the 45s network probe.
    for _p, _c in prescan:
        push_capable(str((_act(_c)).get("repo") or "chaba"))
    # Phase A — under the lock: cheap card mutations only (no network/git).
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        claimed = 0
        # Priority-aware drain (card dispatch-priority-order): claimable
        # queued cards are visited starved-first -> priority rank ->
        # oldest `updated`; all other cards keep filename order. The
        # gates below still filter per card — order never overrides
        # eligibility.
        loaded = load_dispatch_cards()
        # KNB-0036 follow-through: the claim queue is column-scoped — a
        # stale queued/starting flag on a done/review card is off-queue
        # (no claim, no fleet-gap flag, no defer note). 'doing' stays
        # in: a re-queued card can sit there between claim and finish.
        queued = [pc for pc in loaded if (
            (_act(pc[1])).get("status") in ("queued", "starting")
            and pc[1].get("column") in ("backlog", "doing"))]
        queued.sort(key=lambda pc: dr.claim_sort_key(
            pc[1], starve_hours=STARVE_HOURS))
        rest = [pc for pc in loaded if (
            (_act(pc[1])).get("status")
            not in ("queued", "starting"))]
        for p, card in queued + rest:
            a = _act(card)
            st = a.get("status")
            if st in ("queued", "starting"):  # 'starting' = crashed mid-start
                if not can_claim:
                    continue
                ctier = TIER_ORDER.get(str(card.get("autonomy") or ""), -1)
                if ctier > max_tier:
                    print(f"{card['id']}: autonomy t{ctier} > policy max "
                          f"t{max_tier} — never claimed")
                    continue
                if budget and claims_today(state_file) + claimed >= budget:
                    print(f"{card['id']}: daily session budget {budget} hit")
                    continue
                attempt_cap = min(retry_cap, dr.dispatch_attempt_cap(card))
                if int(a.get("attempts") or 0) >= attempt_cap:
                    a["status"] = "held"
                    if card.get("column") == "doing":
                        card["column"] = "backlog"
                    comms_add(card, "chaba",
                              f"dispatch parked after {a['attempts']} attempts "
                              f"(cap {attempt_cap}) — "
                              "/action do=retry re-arms it")
                    save_card(p, card)
                    changed = True
                    print(f"{card['id']}: parked (retry cap)")
                    continue
                pinned = a.get("host")
                if pinned and dr.canon_host(pinned) != dr.canon_host(HOST):
                    if _flag_unclaimable(p, card, fleet) == "new":
                        changed = True
                    else:
                        print(f"{card['id']}: skipped — host-pinned to "
                              f"{pinned}")
                    continue  # pinned to another host's dispatcher
                blocker_id = card.get("blocked_by")
                if blocker_id and not _blocker_released(blocker_id):
                    continue  # dependency not done yet
                if (a.get("type") or "dispatch") != "dispatch":
                    # queue-type-starvation-guard: a queued card we can
                    # never claim must say so in the log — the 2026-10-13
                    # zombie-sweep found 6 of these silently starved for
                    # days (board-invariants Q1 alerts the persistent ones)
                    if _flag_unclaimable(p, card, fleet) == "new":
                        changed = True
                    print(f"{card['id']}: skipped — action.type "
                          f"{a.get('type')!r} is not dispatchable "
                          "(claims are type=dispatch only)")
                    continue
                # Executor contract (opencode-explicit-executor-routing):
                # this dispatcher's only executor is devin. A declared
                # executor other than devin routes elsewhere — opencode/
                # script cards are runner-agent territory, manual is
                # Tony's hands, anything unknown fails closed. Never
                # silently run them on devin.
                ex = str(a.get("executor") or "").strip()
                if str(a.get("lane") or "").strip() == "manual":
                    # lane=manual is Tony's hands even when a classifier
                    # stamped it — never a devin claim, never a fleet gap
                    print(f"{card['id']}: skipped — lane=manual "
                          "(Tony's hands — never claimed)")
                    continue
                if str(a.get("lane") or "").strip() in ("jules", "nlm_batch"):
                    # stale jules pins (lane retired 2026-11-20) and
                    # nlm_batch pins route to a remote runner —
                    # this dispatcher only runs devin claims
                    print(f"{card['id']}: skipped — remote lane "
                          "(jules retired / nlm_batch)")
                    continue
                if ex and ex != "devin":
                    why = ("not a known executor"
                           if ex not in dr.EXECUTORS
                           else "Tony's hands — never claimed"
                           if ex == "manual"
                           else f"routes to the {ex} executor, not devin")
                    if _flag_unclaimable(p, card, fleet) == "new":
                        changed = True
                    print(f"{card['id']}: skipped — executor={ex} "
                          f"({why})")
                    continue
                th = str(a.get("target_host") or "").strip()
                if th and th != HOST:
                    if _flag_unclaimable(p, card, fleet) == "new":
                        changed = True
                    print(f"{card['id']}: skipped — target_host={th}")
                    continue
                needs = set(a.get("labels") or [])
                if needs and not needs <= MY_LABELS:
                    # label skips used to be log-silent — the exact
                    # ops0790 starve. Per-host defer lands on the card;
                    # fleet-unclaimable additionally raises the flag
                    # (and suppresses the noisier per-host note).
                    miss = sorted(needs - MY_LABELS)
                    fl = _flag_unclaimable(p, card, fleet)
                    if fl == "new":
                        changed = True
                    elif not fl:
                        changed |= _defer_note(
                            p, card, f"missing labels {miss}")
                    print(f"{card['id']}: skipped — missing labels "
                          f"{miss}")
                    continue  # needs capabilities this host lacks
                # runner-push-cred-gap: claiming a repo this host can't
                # push strands the finished branch (ADA-0673, idc03
                # daa0e0a) — leave it queued for a host that can
                repo = str(a.get("repo") or "chaba")
                if not push_capable(repo):
                    fl = _flag_unclaimable(p, card, fleet)
                    if fl == "new":
                        changed = True
                    elif not fl:
                        changed |= _defer_note(
                            p, card,
                            f"push guard: no push:{dr.canon_repo(repo)} "
                            "label and `git push --dry-run` fails — "
                            "this host can't land the branch")
                    print(f"{card['id']}: skipped — cannot push "
                          f"{dr.canon_repo(repo)} (no push: label and "
                          "`git push --dry-run` fails)")
                    continue
                # waiting_cards eligibility gate (KNB-0928): R3/R4
                # declared cards are NEVER claimed unattended; other
                # ineligible cards defer only in strict mode (warn mode
                # logs the verdict — the undeclared backlog predates
                # the contract).
                if WAITING_GATE != "off":
                    env = dict(pf_env, claimed=active_base + claimed,
                               cap=HOST_CAP)
                    verdict = wc.evaluate(card, env=env,
                                          push_probe=push_capable)
                    if verdict["never"] or (
                            WAITING_GATE == "strict"
                            and not verdict["eligible"]):
                        why = "; ".join(verdict["reasons"])[:200] \
                            or "ineligible"
                        changed |= _defer_note(
                            p, card, f"waiting-cards gate: {why}")
                        print(f"{card['id']}: deferred — waiting-cards "
                              f"gate ({why})")
                        continue
                    if not verdict["eligible"]:
                        print(f"{card['id']}: waiting-cards warn — "
                              f"{'; '.join(verdict['reasons'])[:160]}")
                if a.get("runner") and a["runner"] != HOST:
                    if _flag_unclaimable(p, card, fleet) == "new":
                        changed = True
                    continue  # claimed/starting on another host
                if active_base + claimed >= HOST_CAP:
                    print(f"{card['id']}: skipped — host cap {HOST_CAP}")
                    continue
                mark_start(p, card)
                bump_claims(state_file)
                save_card(p, card)
                starts.append(p)
                claimed += 1
                changed = True
                print(f"{card['id']}: claimed")
            elif st == "running":
                if a.get("runner") and a["runner"] != HOST:
                    remote.append((p, card.get("id") or p.stem,
                                   a["runner"]))
                    continue  # runs on another host — don't touch its unit
                msg = finish_one(
                    p, card,
                    probe=unit_survey.get(str(a.get("task_id") or "")))
                if msg == "still running":
                    continue
                save_card(p, card)
                changed = True
                if (_act(card)).get("merge_pending"):
                    merges.append(p)
                print(f"{card['id']}: {msg}")
    # Phase B — lock released: slow ops (devin-dispatch start, git merge,
    # runner liveness probes).
    if remote:
        changed |= sweep_dead_runners(remote)
    for p in starts:
        print(f"{p.stem}: {start_pending(p)}")
    for p in merges:
        print(f"{p.stem}: {merge_pending_one(p)}")
    verdict_pass()
    _flush_notify()
    if changed or starts or merges:
        subprocess.run([sys.executable, str(RENDER)], cwd=REPO, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
