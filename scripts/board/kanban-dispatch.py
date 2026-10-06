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
review, writes a comms entry, and best-effort merges the session branch
into origin/<default_branch> in a throwaway detached worktree (skipped
when the worktree is dirty or the merge conflicts — the board-api close
gate still blocks those until merged by hand; KANBAN_AUTOMERGE=0
disables). Session-end notes report leftover dirty/unmerged state.
Tony reviews then presses Close.
"""
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch_repos as dr

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
  object per line: {{"at","card","from","request_id","answer"}}). Check
  that file before finishing; newest line wins per request_id.
- If the card opts into the CI pipeline (a `pipeline: ci` field), run
  `python3 scripts/ci/card-pipeline.py {id} --api {api}` near the end —
  it audits your worktree diff and records benchmark before/after on the
  card (docs/ssot/ssot.ci.yml).
""".strip()


def now() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


def comms_add(card: dict, frm: str, text: str) -> None:
    card.setdefault("comms", []).append(
        {"at": now(), "from": frm, "text": text[:500]}
    )


def sh(cmd: list, timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def unit_state(task_id: str) -> str:
    """devin-dispatch tasks run as devin-task-<id>.service user units."""
    r = sh(["systemctl", "--user", "is-active", f"devin-task-{task_id}.service"])
    return r.stdout.strip() or "unknown"


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
    spec = (card.get("spec") or "").strip() \
        or f"{card.get('title','')}\n\n{card.get('note','')}"
    task = spec + "\n\n" + TASK_RAILS.format(id=card["id"], api=API)
    r = sh([DISPATCH, "start", repo, task], timeout=120)

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
        save_card(path, card)
        return f"dispatched {task_id}"
    return _with_lock(apply)


def merge_pending_one(path: Path) -> str:
    """Phase B: git auto-merge (slow, no lock), then write back."""
    try:
        res = dr.try_merge(load_card(path))
    except Exception as e:
        res = {"merged": False, "error": str(e)}

    def apply():
        card = load_card(path)
        a = card.get("action") or {}
        a.pop("merge_pending", None)
        if res.get("merged"):
            comms_add(card, "chaba",
                      res.get("note") or "session branch merged")
        else:
            why = res.get("error") or res.get("skipped") or "unknown"
            comms_add(card, "chaba",
                      f"auto-merge not done: {why} — close will block "
                      f"until merged")
        for n in session_end_notes(card):
            comms_add(card, "chaba", n)
        save_card(path, card)
        return "merged" if res.get("merged") else f"merge: {res}"
    return _with_lock(apply)


def main() -> int:
    starts, merges, remote = [], [], []
    changed = False
    # Phase A — under the lock: cheap card mutations only (no network/git).
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        claimed = 0
        for p in sorted(CARD_DIR.glob("*.yml")):
            card = load_card(p)
            a = card.get("action") or {}
            st = a.get("status")
            if st in ("queued", "starting"):  # 'starting' = crashed mid-start
                pinned = a.get("host")
                if pinned and pinned != HOST:
                    continue  # pinned to another host's dispatcher
                if a.get("type") == "container":
                    continue  # runner-agent territory — not a devin session
                needs = set(a.get("labels") or [])
                if needs and not needs <= MY_LABELS:
                    continue  # needs capabilities this host lacks
                if a.get("runner") and a["runner"] != HOST:
                    continue  # claimed/starting on another host
                if active_tasks() + claimed >= HOST_CAP:
                    print(f"{card['id']}: skipped — host cap {HOST_CAP}")
                    continue
                mark_start(p, card)
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
