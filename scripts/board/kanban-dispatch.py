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
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch_repos as dr
import lesson_primer as lp

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
    ba = b.get("action") or {}
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
    ba = b.get("action") or {}
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
        a = card.get("action") or {}
        if a.get("status") != "running" or a.get("runner") != host:
            return "resolved itself"
        a["status"] = "queued"
        a.pop("runner", None)
        a.pop("task_id", None)
        card.setdefault("claim", {}).pop("session", None)
        comms_add(card, "chaba",
                  f"runner {host} unreachable {REQUEUE_AFTER} passes "
                  f"— requeued")
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

TASK_RAILS = """
---
Rails: you are processing kanban card '{id}' (docs/ssot/kanban/cards/{id}.yml).
- Work in the worktree devin-dispatch gave you; do NOT push unless the
  card spec explicitly says to.
- While you work, post progress to the card so the board stays live:
    curl -s -X POST {api}/comment \\
      -H 'Content-Type: application/json' \\
      -d '{{"id":"{id}","from":"devin","text":"<short status>"}}'
- When done, post a final comms entry summarizing outcome + where the
  deliverables are. The dispatcher will mark the action done and move
  the card to review.
- If you need Tony to answer something, raise a board request — do NOT
  edit the card YAML directly (that races the API's flock):
    curl -s -X POST {api}/request \\
      -H 'Content-Type: application/json' \\
      -d '{{"id":"{id}","from":"devin","ask":"<question>"}}'
- If you raised a request and kept working, the answer may arrive while
  you run: board-api appends it to $TASK_DIR/answers.jsonl (one JSON
  object per line: {{"at","card","from","kind","request_id","answer"}}).
  Check that file before finishing; newest line wins per request_id.
- answers.jsonl lines may also carry kind:"comment" — card comms pushed
  live (Tony's notes, Ada's [opinion]-tagged report takes). Treat them
  as review input to weigh; request_id/answer lines (kind:"answer")
  remain the authoritative answer channel.
- If the card opts into the CI pipeline (a `pipeline: ci` field), run
  `python3 scripts/ci/card-pipeline.py {id} --api {api}` near the end —
  it audits your worktree diff and records benchmark before/after on the
  card (docs/ssot/ssot.ci.yml).
- End your dispatch-outcome doc with a `lessons:` list — 0-5 short
  gotcha lines (one `- ` item each; `lessons: []` if none). The dispatch
  primer harvests them into the next run's KNOWN_PITFALLS block.
""".strip()

# Appended after TASK_RAILS when the card was requeued after a failed
# attempt (action.attempts > 0 or action.last_failure set) — the next
# session gets the failure evidence instead of a blind re-run.
RETRY_RAILS = """
---
This is attempt {n} for this card — the previous run did NOT merge/verify
cleanly. Prior failure: {failure}
- Read the card's comms for the full trail before starting:
    curl -s {api}/cards | python3 -c "import sys,json; print(json.dumps([c.get('comms') for c in json.load(sys.stdin).get('cards',[]) if c.get('id')=='{id}'], indent=1))"
- Fix the reported failure FIRST; do not repeat the failed approach.
""".strip()

# Design docs/design/report-session-loop.md §2b — appended after
# TASK_RAILS when the card carries `report: <cms-slug>`; the session
# keeps ada-cms-pages/<slug> updated via scripts/ada/cms-report-note.py.
REPORT_RAILS = """
This card is report-linked: ada-cms-pages/{slug}.
- Read the report FIRST: python3 scripts/ada/cms-report-note.py {slug} --read
- As you work, mirror progress into the report's session log:
    python3 scripts/ada/cms-report-note.py {slug} --note "<what changed>"
  (appends meta.timeline + the <!-- session-log:auto --> managed block;
   merges meta per the writer contract — never bare-replace a page)
- Before finishing: the report must reflect the outcome. The report is
  the long-lived artifact; this card is the tracking surface.
""".strip()


# Lesson lines injected into the most recent build_task call — read by
# start_pending so the card comms logs exactly what the primer added.
LAST_PRIMER_LINES: list = []


def build_task(card: dict) -> str:
    """The text handed to `devin-dispatch start` — card spec (or
    title+note) plus TASK_RAILS, a KNOWN_PITFALLS primer block when past
    lessons match, plus REPORT_RAILS when report-linked."""
    spec = (card.get("spec") or "").strip() \
        or f"{card.get('title','')}\n\n{card.get('note','')}"
    task = spec + "\n\n" + TASK_RAILS.format(id=card["id"], api=API)
    repo = (card.get("action") or {}).get("repo", "chaba")
    LAST_PRIMER_LINES.clear()
    if os.environ.get("KANBAN_PRIMER", "1") != "0":
        try:
            LAST_PRIMER_LINES.extend(lp.build(card, HOST, repo, REPO))
        except Exception as e:  # primer is advisory — never block a run
            print(f"warn: lesson primer failed: {e}", file=sys.stderr)
    if LAST_PRIMER_LINES:
        task += "\n\n" + lp.format_block(LAST_PRIMER_LINES, HOST, repo)
    a = card.get("action") or {}
    attempts = int(a.get("attempts") or 0)
    if attempts > 0 or a.get("last_failure"):
        task += "\n\n" + RETRY_RAILS.format(
            id=card["id"], api=API, n=attempts + 1,
            failure=str(a.get("last_failure")
                        or "(no detail — inspect the card comms)")[:400])
    slug = str(card.get("report") or "").strip()
    if slug:
        task += "\n\n" + REPORT_RAILS.format(slug=slug)
    return task


def now() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")


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
    card.setdefault("comms", []).append(
        {"at": now(), "from": frm, "text": text[:500]}
    )


def sh(cmd: list, timeout=60, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, **kw)


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
    card = yaml.safe_load(path.read_text()) or {}
    card.setdefault("id", path.stem)
    return card


def save_card(path: Path, card: dict) -> None:
    card["updated"] = now()
    path.write_text(
        yaml.safe_dump(card, allow_unicode=True, sort_keys=False, width=110))


def mark_start(path: Path, card: dict) -> None:
    """Phase-A claim (under the lock): transient 'starting' state keeps the
    card out of other dispatchers' reach; phase B runs the slow start."""
    a = card["action"]
    card.pop("awaiting_action", None)  # being dispatched = triaged
    a["status"] = "starting"
    a["runner"] = HOST
    a["attempts"] = int(a.get("attempts") or 0) + 1


def finish_one(path: Path, card: dict) -> str:
    """Phase-A finish (under the lock): cheap status flip only. A clean
    finish defers the git merge to phase B (merge_pending flag)."""
    a = card["action"]
    tid = a.get("task_id") or ""
    state = unit_state(tid) if tid else "unknown"
    if state in ("active", "activating"):
        return "still running"
    if state == "failed":
        # crashed unit — do NOT mark done or auto-merge: the branch may
        # hold partial work; card stays in doing with a retry affordance
        a["status"] = "failed"
        a["result"] = f"{tid} FAILED — see `devin-dispatch logs {tid}`"
        card.setdefault("claim", {}).pop("session", None)
        comms_add(card, "chaba", "run failed — check logs, then retry")
        return "failed"
    # unit left the active state — treat as finished
    a["status"] = "done"
    a["result"] = f"{tid} finished ({state}) — see `devin-dispatch logs {tid}`"
    card["column"] = "review"
    card.setdefault("review_kind", "verify")  # close-out contract — without it the ssot-optimize gate fails commits repo-wide
    card.setdefault("claim", {}).pop("session", None)
    comms_add(card, "chaba", f"run finished ({state}) → review")
    if os.environ.get("KANBAN_AUTOMERGE", "1") != "0":
        a["merge_pending"] = True  # merged outside the lock in phase B
    else:
        for n in session_end_notes(card):
            comms_add(card, "chaba", n)
    return "finished"


def session_end_notes(card: dict) -> list:
    """Comms lines for leftover work at session end (merge-guard spec c):
    dirty worktree file count, plus commits not yet in the default branch
    (the same condition the board-api close gate blocks on)."""
    notes = []
    try:
        s = dr.session(card)
        if s["worktree"]:
            dirty = dr.dirty_count(s["worktree"])
            if dirty:
                notes.append(
                    f"session end: worktree {s['worktree'].name} dirty — "
                    f"{dirty} uncommitted file(s); commit or clean before "
                    f"pruning")
        if s["head"] and s["base_ref"]:
            m = dr.merge_state(s["repo_root"], s["head"], s["base_ref"])
            if m.get("checked") and not m["ancestor"]:
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


def start_pending(path: Path) -> str:
    """Phase B: devin-dispatch start (slow, no lock), then write back."""
    card = load_card(path)  # read-only peek for spec/task build
    a = card["action"]
    repo = a.get("repo", "chaba")
    task = build_task(card)
    env = dict(os.environ)
    if a.get("model"):
        env["DISPATCH_MODEL"] = str(a["model"])  # -> devin --model
    r = sh([DISPATCH, "start", repo, task], timeout=120, env=env)

    def apply():
        card = load_card(path)  # re-read — API may have touched the card
        a = card.setdefault("action", {})
        if r.returncode != 0:
            a["status"] = "failed"
            a["result"] = f"dispatch failed: {(r.stderr or r.stdout).strip()[:300]}"
            comms_add(card, "chaba", f"dispatch failed: {a['result'][:120]}")
            save_card(path, card)
            return "dispatch failed"
        task_id = r.stdout.strip().splitlines()[-1].strip()
        a["status"] = "running"
        a["task_id"] = task_id
        a["runner"] = HOST
        card.setdefault("claim", {})["session"] = task_id
        card["claim"]["since"] = now()
        comms_add(card, "chaba", f"dispatched {task_id} on {repo}")
        if LAST_PRIMER_LINES:
            comms_add(
                card, "chaba",
                f"primer injected {len(LAST_PRIMER_LINES)} lesson(s): "
                + "; ".join(l[:80] for l in LAST_PRIMER_LINES))
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

    def apply():
        card = load_card(path)
        a = card.get("action") or {}
        a.pop("merge_pending", None)
        if res.get("merged"):
            a["verified"] = True
        elif res.get("conflicts") or res.get("test_failures") or (
                res.get("gate") and not res["gate"]["ok"]):
            a["verified"] = False  # checked and NOT verified
            # Review feedback loop: conflicts/goal-failures requeue the
            # card with the failure evidence (RETRY_RAILS carries it into
            # the next session) until action.max_attempts is reached.
            # attempts is counted at claim time (mark_start) — requeue
            # while attempts_used < max_attempts (max_attempts = total
            # dispatches incl. retries; mirrors merge-sweep fail_attempt).
            att = int(a.get("attempts") or 0)
            max_att = int(a.get("max_attempts")
                          or os.environ.get("KANBAN_MAX_ATTEMPTS", "2"))
            if (os.environ.get("KANBAN_AUTORETRY", "1") != "0"
                    and att < max_att):
                why = ("; ".join(dr.close_out_notes(res)) or
                       "merge/goals failed")[:280]
                a["last_failure"] = why
                a["status"] = "queued"
                a.pop("runner", None)
                a.pop("task_id", None)
                comms_add(card, "chaba",
                          f"auto-retry queued (attempt {att + 1}/"
                          f"{max_att}): {why}")
                ops_event(
                    f"kanban-dispatch auto-retry `{card.get('id') or path.stem}` "
                    f"(attempt {att + 1}/{max_att}) on {HOST}: {why}")
        for n in dr.close_out_notes(res):
            comms_add(card, "chaba", n)
        for n in session_end_notes(card):
            comms_add(card, "chaba", n)
        save_card(path, card)
        if res.get("noop"):
            return "noop"
        return ("merged" if res.get("merged")
                else f"merge: {res.get('error') or res.get('skipped') or res}")
    return _with_lock(apply)


def main() -> int:
    starts, merges, remote = [], [], []
    changed = False
    # Phase A — under the lock: cheap card mutations only (no network/git).
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        claimed = 0
        pol = load_policy()
        kill = Path(pol.get("kill_switch") or "/tmp/no-kanban-dispatch")
        budget = int(pol.get("sessions_per_day") or 0)
        state_file = Path(pol.get("state_file")
                          or "/tmp/kanban-dispatch-state.json")
        max_tier = TIER_ORDER.get(str(pol.get("max_autonomy") or "t3"), 3)
        retry_cap = int(pol.get("retries_per_card") or 2)
        can_claim = not overloaded()
        if not can_claim:
            print(f"load gate: load5/cpu > {MAX_LOAD_PC} — not claiming")
        if kill.exists():
            can_claim = False
            print(f"kill switch {kill} present — not claiming")
        if in_quiet_hours(pol.get("quiet_hours") or ""):
            can_claim = False
            print(f"quiet hours {pol['quiet_hours']} — not claiming")
        # Priority-aware drain (card dispatch-priority-order): claimable
        # queued cards are visited starved-first -> priority rank ->
        # oldest `updated`; all other cards keep filename order. The
        # gates below still filter per card — order never overrides
        # eligibility.
        loaded = [(p, load_card(p))
                  for p in sorted(CARD_DIR.glob("*.yml"))]
        queued = [pc for pc in loaded if (
            (pc[1].get("action") or {}).get("status")
            in ("queued", "starting"))]
        queued.sort(key=lambda pc: dr.claim_sort_key(
            pc[1], starve_hours=STARVE_HOURS))
        rest = [pc for pc in loaded if (
            (pc[1].get("action") or {}).get("status")
            not in ("queued", "starting"))]
        for p, card in queued + rest:
            a = card.get("action") or {}
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
                if int(a.get("attempts") or 0) >= retry_cap:
                    a["status"] = "held"
                    comms_add(card, "chaba",
                              f"dispatch parked after {a['attempts']} attempts "
                              f"(policy retries_per_card={retry_cap}) — "
                              "re-queue to retry")
                    save_card(p, card)
                    changed = True
                    print(f"{card['id']}: parked (retry cap)")
                    continue
                pinned = a.get("host")
                if pinned and pinned != HOST:
                    continue  # pinned to another host's dispatcher
                blocker_id = card.get("blocked_by")
                if blocker_id and not _blocker_released(blocker_id):
                    continue  # dependency not done yet
                if (a.get("type") or "dispatch") != "dispatch":
                    continue  # container/script = runner-agent territory
                needs = set(a.get("labels") or [])
                if needs and not needs <= MY_LABELS:
                    continue  # needs capabilities this host lacks
                if a.get("runner") and a["runner"] != HOST:
                    continue  # claimed/starting on another host
                if active_tasks() + claimed >= HOST_CAP:
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
                msg = finish_one(p, card)
                if msg == "still running":
                    continue
                save_card(p, card)
                changed = True
                if (card.get("action") or {}).get("merge_pending"):
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
    if changed or starts or merges:
        subprocess.run([sys.executable, str(RENDER)], cwd=REPO, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
