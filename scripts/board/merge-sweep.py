#!/usr/bin/env python3
"""merge-sweep — land stranded dispatch branches + flag zombie tasks.

Runs on tony-dell from merge-sweep.timer (~15min). The dispatch
close-out (dispatch_repos.close_out via kanban-dispatch / runner-agent)
merges session branches at session end — but only when the runner can
reach GitHub. Repos pin a GitHub-only SSH key (core.sshCommand), so a
runner without that credential pushes nothing and the branch strands on
the remote host (the 2026-10-08 pattern: six manual fetch-over-ssh
salvages in one night). This sweep is the remedy half of the merge
guard: it closes the loop the guard only detects.

For each card in doing/review with action.type=dispatch:

  1. resolve the session — action.task_id, else claim.session, else the
     'started devin-task-<id>' comms line, else the runner's
     runner-agent state.json
  2. locate the worktree on the recorded runner — meta.json pattern
     ($DISPATCH_DIR/tasks/<id>/meta.json on the runner host), with the
     dispatch-wt-<id> / dispatch/<id> fallbacks dispatch_repos uses
  3. verify the runner's worktree HEAD is clean — a dirty worktree is
     flagged in comms once, never auto-committed from here (checkpointing
     is the runner's close-out job)
  4. fetch the head into the served checkout:
       git -c core.sshCommand=ssh fetch <runner>:<worktree> HEAD
     (the -c override is required — the repo's configured sshCommand is
     a GitHub-only key that cannot reach tailnet hosts)
  5. merge into the served checkout's repo — dispatch_repos.merge_state
     vs origin/<default>, then --no-ff in a throwaway detached worktree
     of the served repo and push HEAD:<base> (same shape as
     close_out: the served working tree is never touched; its normal
     safe-pull path converges it). CONFLICT POLICY = stop-and-report:
     ANY conflicted path aborts and posts a card request naming the
     files. Unlike close_out this sweep never silently resolves either
     side — the branch may carry state a human already reviewed.
  6. verified gate before any verified stamp (2026-10-09 nest-mgr
     incident — the unit died 1s in, produced nothing, and was stamped
     verified anyway): verified=True requires (a) the devin-task unit
     exited 0 per the best surviving evidence (task-dir exit_code >
     meta.result > unit/journal > card finish report), (b) the branch
     changed files vs base or carries dispatch-outcome-<tid>.md, and
     (c) the card's auto_done_when checks pass (a self verified_true
     counts the a+b verdict; anything else failing defers the stamp to
     kanban-act — the work still merges). A provable failure — no
     deliverable, or a nonzero unit exit on unmerged work — marks the
     attempt failed and requeues on kanban-dispatch's retry path.
     Undecidable states hold in review with a comms flag.
  7. verified cards drain themselves (card kanban-review-auto-close —
     Tony: "if it passes the standard, close it automatically"): the
     verified stamp also flips action.status->done and, unless the
     card is human-gated (review_kind decide/triage, an open request,
     or an unanswered ask — the same contract kanban-act enforces),
     column->done with an auto_close record. Human-gated verified
     cards surface in review with a comms note. Cards verified by
     ANY writer (this stamp, close_out, a previous pass) get the
     same drain — the early-skip and the already-merged path both
     route through it, so stragglers verified before this lane
     existed close too.

Zombie lane: devin-task-* units on dell + the recorded runners +
MERGE_SWEEP_HOSTS running > ZOMBIE_AGE_H (6h) with no activity >
ZOMBIE_IDLE_MIN (60min) get one card comms flag — never auto-killed
(the 32h cue-fit case). 'Activity' = newest mtime among the unit's
cgroup processes' devin_*.log files and the task dir; transcript.json
only exists at exit, so mtime-based liveness is the only signal.

Single-writer safety: card reads hit the served checkout's card dir;
comms/requests go through board-api when reachable (notify + render),
else direct YAML under /tmp/board-api.lock; all other card mutations
(stamps) are locked YAML writes. Git merges only ever happen inside the
per-repo served checkout map (MERGE_SWEEP_TARGETS) — chaba ->
~/CascadeProjects/chaba-tony-dell, ada-pi -> ~/CascadeProjects/ada-pi,
anything else -> its repos.conf path.

Env: CHABA_REPO (cards checkout), MERGE_SWEEP_TARGETS
("chaba=/p,ada-pi=/q"), MERGE_SWEEP_HOSTS ("tony-omen,mn01"),
BOARD_API, ZOMBIE_AGE_H, ZOMBIE_IDLE_MIN.
Usage: merge-sweep.py [--dry-run]
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch_repos as dr

HOST = os.uname().nodename
LOCK = Path("/tmp/board-api.lock")
API = os.environ.get("BOARD_API", "http://127.0.0.1:8787").rstrip("/")
TZ = timezone(timedelta(hours=7))

SCRIPT_REPO = Path(__file__).resolve().parents[2]
CHABA_REPO = Path(os.environ["CHABA_REPO"]).expanduser() \
    if os.environ.get("CHABA_REPO") else (
        Path.home() / "CascadeProjects/chaba-tony-dell"
        if (Path.home() / "CascadeProjects/chaba-tony-dell").is_dir()
        else SCRIPT_REPO)
CARD_DIR = CHABA_REPO / "docs" / "ssot" / "kanban" / "cards"
RENDER = CHABA_REPO / "scripts" / "render-board.py"

# repo name -> the checkout merges land in. chaba's served tree carries
# the live board state, so merges run in a detached worktree of it and
# push to origin — the working tree converges via kanban-commit's
# safe-pull instead of being merged under its feet.
SERVED = {"chaba": "~/CascadeProjects/chaba-tony-dell",
          "ada-pi": "~/CascadeProjects/ada-pi"}
for pair in os.environ.get("MERGE_SWEEP_TARGETS", "").split(","):
    if "=" in pair:
        k, v = pair.split("=", 1)
        SERVED[k.strip()] = v.strip()

# Hosts probed for zombies in addition to the local host and runners
# recorded on cards (the dispatch lanes — card dispatch-merge-sweep).
SWEEP_HOSTS = [h.strip() for h in os.environ.get(
    "MERGE_SWEEP_HOSTS",
    os.environ.get("BOARD_REMOTE_DISPATCH_HOSTS",
                   "tony-omen,mn01")).split(",") if h.strip()]

ZOMBIE_AGE_S = float(os.environ.get("ZOMBIE_AGE_H", "6")) * 3600
ZOMBIE_IDLE_S = float(os.environ.get("ZOMBIE_IDLE_MIN", "60")) * 60
TASK_ID_RE = re.compile(r"devin-task-([0-9]{8}-[0-9]{6}[a-z0-9-]*)")


def now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def sh(cmd: list, timeout: int = 60,
       stdin: str = "") -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, input=stdin or None)
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


# ------------------------------------------------------- runner probes
# Runs on the runner host via `ssh <host> python3 - <task_id>` — returns
# meta.json, worktree presence/dirtiness/head, the repo root (from the
# worktree's git-common-dir, else the runner's own repos.conf scanned
# for the branch), and the fetch spec (<path>, <ref>) for this host's
# repo clone. Prints one JSON object.
REMOTE_SESSION_PROBE = r'''
import json, re, subprocess, sys
from pathlib import Path
tid = sys.argv[1]
home = Path.home()
tdir = home / ".local/share/devin-dispatch/tasks" / tid
meta = {}
try:
    meta = json.loads((tdir / "meta.json").read_text())
except Exception:
    pass

def g(cwd, *a):
    r = subprocess.run(["git", "-C", str(cwd), *a],
                       capture_output=True, text=True, timeout=30)
    return r.returncode, (r.stdout or "").strip()

out = {"meta": meta, "task_dir": tdir.is_dir()}
branch = meta.get("branch") or f"dispatch/{tid}"
out["branch"] = branch
wt = Path(meta.get("worktree") or home / f"CascadeProjects/dispatch-wt-{tid}")
out["worktree"] = str(wt)
out["wt_exists"] = wt.is_dir()
if out["wt_exists"]:
    rc, s = g(wt, "status", "--porcelain=v1")
    out["dirty"] = (None if rc else
                    sum(1 for l in s.splitlines() if l.strip()))
    rc, s = g(wt, "rev-parse", "HEAD")
    out["head"] = s or None
    rc, s = g(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
    out["repo_root"] = str(Path(s).parent) if rc == 0 and s else None
    out["fetch_path"], out["fetch_ref"] = str(wt), "HEAD"
if not out.get("repo_root"):
    # worktree pruned — the session branch may still live in the
    # runner's repo clone; resolve via its own dispatch repos.conf.
    conf = home / ".local/share/devin-dispatch/repos.conf"
    table = {}
    if conf.exists():
        for ln in conf.read_text().splitlines():
            ln = ln.split("#", 1)[0].strip()
            if ln:
                p = ln.split()
                table[p[0]] = str(Path(p[1]).expanduser())
    cands = ([table.get(meta.get("repo") or "")] +
             [v for v in table.values()])
    for c in cands:
        if c and Path(c).is_dir():
            rc, s = g(c, "rev-parse", "--verify", "--quiet",
                      f"refs/heads/{branch}")
            if rc == 0 and s:
                out.update(repo_root=c, head=s, fetch_path=c,
                           fetch_ref=f"refs/heads/{branch}")
                break
# exit evidence for the verified gate: the dispatch wrapper's exit_code
# survives systemd --collect GC; the unit's Result only exists while it
# is still loaded; journal Succeeded/Failed lines outlive both.
try:
    ecp = tdir / "exit_code"
    out["exit_code"] = ecp.read_text().strip() if ecp.is_file() else None
except Exception:
    out["exit_code"] = None
try:
    r = subprocess.run(["systemctl", "--user", "show",
                        f"devin-task-{tid}.service",
                        "-p", "ExecMainStatus", "-p", "Result",
                        "-p", "LoadState"],
                       capture_output=True, text=True, timeout=15)
    kv = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
    # NB: show on a never-loaded unit prints defaults
    # (Result=success/ExecMainStatus=0) — only LoadState=loaded is real.
    out["unit"] = {"exec": kv.get("ExecMainStatus", ""),
                   "result": kv.get("Result", ""),
                   "load": kv.get("LoadState", "")}
except Exception:
    out["unit"] = {}
if out["exit_code"] is None and not out["unit"].get("result"):
    try:
        j = subprocess.run(["journalctl", "--user-unit",
                            f"devin-task-{tid}.service", "--no-pager",
                            "-o", "cat"],
                           capture_output=True, text=True, timeout=20)
        hits = re.findall(r"Succeeded\.|Failed with result '[a-z-]+'",
                          j.stdout or "")
        if hits:
            out["journal_result"] = ("success" if hits[-1] == "Succeeded."
                                     else hits[-1].split("'")[1])
    except Exception:
        pass
print(json.dumps(out))
'''

# Runs on a host via `ssh <host> python3 -` — one JSON list of every
# active devin-task-* unit: {task, unit, age_s, idle_s}. idle_s is the
# newest mtime among the unit's cgroup processes' devin_<ts>_<pid>.log
# files (the `devin acp` child logs continuously while a session is
# alive) and anything in the task dir; falls back to unit start.
REMOTE_ZOMBIE_PROBE = r'''
import json, re, subprocess, time
from pathlib import Path
r = subprocess.run(
    ["systemctl", "--user", "list-units", "devin-task-*.service",
     "--state=active,activating", "--no-legend", "--plain"],
    capture_output=True, text=True, timeout=15)
units = [l.split()[0] for l in r.stdout.splitlines() if l.strip()]
logs = Path.home() / ".local/share/devin/cli/logs"
now = time.time()
out = []
for u in units:
    tid = u[len("devin-task-"):-len(".service")]
    base = re.sub(r"-fu\d+$", "", tid)
    q = subprocess.run(
        ["systemctl", "--user", "show", u,
         "-p", "ActiveEnterTimestampUSec", "-p", "ControlGroup",
         "--value"], capture_output=True, text=True, timeout=15)
    vals = q.stdout.split()
    start = int(vals[0]) / 1e6 if vals and vals[0].isdigit() else now
    latest = 0.0
    cg = vals[1] if len(vals) > 1 else ""
    try:
        pids = [int(x) for x in (Path("/sys/fs/cgroup") / cg.lstrip("/")
                                 / "cgroup.procs").read_text().split()]
    except Exception:
        pids = []
    for p in pids:
        for lf in logs.glob(f"devin_*_{p}.log"):
            try:
                latest = max(latest, lf.stat().st_mtime)
            except OSError:
                pass
    td = Path.home() / ".local/share/devin-dispatch/tasks" / base
    if td.is_dir():
        for f in td.iterdir():
            try:
                latest = max(latest, f.stat().st_mtime)
            except OSError:
                pass
    out.append({"task": base, "unit": u,
                "age_s": round(now - start),
                "idle_s": round(now - (latest or start))})
print(json.dumps(out))
'''


def _py(script: str, *argv: str) -> dict | list | None:
    # `python3 -` reads the program from stdin — pass the script
    r = sh([sys.executable, "-", *argv], timeout=60, stdin=script)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def runner_probe(host: str, script: str, *argv: str):
    """Run a probe script on a runner; None on unreachable/failed.
    The script travels over ssh's stdin into `python3 -`."""
    if not host or host == HOST:
        return _py(script, *argv)
    r = sh(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
            host, "python3", "-", *argv], timeout=60, stdin=script)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def _local_exit_evidence(tid: str, out: dict) -> None:
    """Same exit evidence the REMOTE_SESSION_PROBE collects, for a task
    on this host: task-dir exit_code (survives --collect GC), live unit
    Result, journal Succeeded/Failed lines."""
    tdir = dr.dispatch_dir() / "tasks" / tid
    try:
        ecp = tdir / "exit_code"
        out["exit_code"] = ecp.read_text().strip() \
            if ecp.is_file() else None
    except Exception:
        out["exit_code"] = None
    r = sh(["systemctl", "--user", "show", f"devin-task-{tid}.service",
            "-p", "ExecMainStatus", "-p", "Result", "-p", "LoadState"],
           timeout=15)
    kv = dict(l.split("=", 1) for l in (r.stdout or "").splitlines()
              if "=" in l)
    out["unit"] = {"exec": kv.get("ExecMainStatus", ""),
                   "result": kv.get("Result", ""),
                   "load": kv.get("LoadState", "")}
    if out["exit_code"] is None and not out["unit"]["result"]:
        j = sh(["journalctl", "--user-unit", f"devin-task-{tid}.service",
                "--no-pager", "-o", "cat"], timeout=20)
        hits = re.findall(r"Succeeded\.|Failed with result '[a-z-]+'",
                          j.stdout or "")
        if hits:
            out["journal_result"] = (
                "success" if hits[-1] == "Succeeded."
                else hits[-1].split("'")[1])


def session_probe(host: str, tid: str) -> dict:
    """meta.json + worktree state on the runner (local when host==HOST)."""
    if not host or host == HOST:
        # local: dispatch_repos already resolves meta/worktree/head
        meta = dr.task_meta(tid)
        wt = Path(meta.get("worktree") or
                  Path.home() / f"CascadeProjects/dispatch-wt-{tid}")
        out = {"meta": meta, "task_dir": True,
                   "branch": meta.get("branch") or f"dispatch/{tid}",
                   "worktree": str(wt), "wt_exists": wt.is_dir()}
        if out["wt_exists"]:
            out["dirty"] = dr.dirty_count(wt)
            out["head"] = dr._rev_parse(wt, "HEAD") or None
            root = dr._repo_root(wt)
            out["repo_root"] = str(root) if root else None
            out["fetch_path"], out["fetch_ref"] = str(wt), "HEAD"
        if not out.get("repo_root"):
            # worktree gone — the branch may live in a whitelisted repo
            for ent in dr.repos().values():
                p = ent["path"]
                if p.is_dir() and dr._rev_parse(
                        p, f"refs/heads/{out['branch']}"):
                    out.update(repo_root=str(p),
                               head=dr._rev_parse(p, out["branch"]),
                               fetch_path=str(p),
                               fetch_ref=f"refs/heads/{out['branch']}")
                    break
        _local_exit_evidence(tid, out)
        return out
    res = runner_probe(host, REMOTE_SESSION_PROBE, tid)
    return res if isinstance(res, dict) else {}


def zombie_probe(host: str) -> list:
    """[{task, unit, age_s, idle_s}] of active devin-task units on host."""
    res = runner_probe(host, REMOTE_ZOMBIE_PROBE)
    return res if isinstance(res, list) else []


def runner_task_ids(host: str) -> dict:
    """card_id -> task_id from the runner's runner-agent state.json."""
    if not host or host == HOST:
        p = Path.home() / ".local/share/runner-agent/state.json"
        try:
            st = json.loads(p.read_text())
        except Exception:
            return {}
    else:
        r = sh(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                host, "cat",
                "~/.local/share/runner-agent/state.json"], timeout=20)
        try:
            st = json.loads(r.stdout)
        except Exception:
            return {}
    return {cid: ent.get("tid") for cid, ent in st.items()
            if isinstance(ent, dict) and ent.get("tid")}


# ----------------------------------------------------------- card i/o
def load_card(path: Path) -> dict:
    try:
        card = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}
    card.setdefault("id", path.stem)
    return card


def api_post(path: str, body: dict) -> dict:
    try:
        req = urllib.request.Request(
            API + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def locked_edit(cid: str, fn) -> bool:
    """Locked card-YAML mutation — the sweep fallback/mutation channel
    (board-api holds the same flock for its own writes)."""
    p = CARD_DIR / f"{cid}.yml"
    if not p.exists():
        return False
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        card = load_card(p)
        if not card:
            return False
        if fn(card) is False:
            return False
        card["updated"] = now()
        p.write_text(yaml.safe_dump(card, allow_unicode=True,
                                    sort_keys=False, width=110))
        return True


def card_note(cid: str, text: str, dry: bool) -> None:
    """Comms entry — board-api first (notify + render), locked YAML
    fallback so a dead API never swallows a report."""
    if dry:
        print(f"  [dry] comms {cid}: {text[:120]}")
        return
    r = api_post("/comment", {"id": cid, "from": "chaba", "text": text})
    if not r.get("error"):
        return
    def add(c):
        c.setdefault("comms", []).append(
            {"at": now(), "from": "chaba", "text": text[:500]})
    locked_edit(cid, add)


def card_request(cid: str, rid: str, ask: str, dry: bool) -> None:
    """Raise a requests[] entry (merge-conflict lane)."""
    if dry:
        print(f"  [dry] request {cid}/{rid}: {ask[:120]}")
        return
    r = api_post("/request", {"id": cid, "from": "chaba",
                              "ask": ask, "request_id": rid})
    if not r.get("error"):
        return
    def add(c):
        reqs = c.setdefault("requests", [])
        if any(x.get("id") == rid for x in reqs):
            return False
        reqs.append({"id": rid, "ask": ask, "status": "open",
                     "at": now(), "from": "chaba"})
        c.setdefault("comms", []).append(
            {"at": now(), "from": "chaba",
             "text": f"raised request {rid}: {ask[:120]}"})
    locked_edit(cid, add)


def stamp(cid: str, key: str, val, dry: bool) -> None:
    """action.sweep bookkeeping stamps — once-per-condition flags."""
    if dry:
        return
    def add(c):
        a = c.setdefault("action", {})
        a.setdefault("sweep", {})[key] = val
    locked_edit(cid, add)


def open_conflict_req(card: dict) -> bool:
    """An unanswered merge-conflict* request already sits on the card."""
    for r in card.get("requests") or []:
        if str(r.get("id", "")).startswith("merge-conflict") \
                and r.get("status") != "answered":
            return True
    return False


def conflict_rid(card: dict) -> str:
    """merge-conflict, merge-conflict-2, ... — one request per distinct
    conflict event; a re-conflict after a human answered gets a new id."""
    n = sum(1 for r in card.get("requests") or []
            if str(r.get("id", "")).startswith("merge-conflict"))
    return "merge-conflict" if n == 0 else f"merge-conflict-{n + 1}"


# ------------------------------------------------------- verified gate
# action.verified means "the dispatch delivered", not "the branch
# merged" — the 2026-10-09 nest-mgr incident: the runner's unit died ~1s
# in (empty DEVIN_MODEL on a stale devin-dispatch), produced zero
# commits, and still got stamped verified because the untouched branch
# head was 'already in origin/master'. verified now requires ALL of:
#
#   (a) the devin-task unit exited 0 — evidence precedence: the task
#       dir's exit_code file (written by the dispatch wrapper, survives
#       systemd --collect GC) > meta.json result (devin-dispatch-watch
#       stamp) > systemctl unit Result / journal Succeeded-Failed lines
#       > the card's own finish report;
#   (b) the branch actually changed files vs base, or left a
#       dispatch-outcome-<tid>.md in its tree (research tasks whose only
#       deliverable is the doc);
#   (c) the card's auto_done_when checks pass — a self 'verified_true'
#       entry counts the a+b gate itself; a failing/unrunnable contract
#       defers to kanban-act rather than failing the attempt.
#
# A provable failure (nonzero exit on unmerged work, or no deliverable
# at all) marks the attempt failed and requeues it on the same path
# kanban-dispatch's merge step uses. Undecidable states (work landed but
# no usable exit record, or a merge too old to reconstruct) hold the
# card in review with a comms flag — never verified on faith.

def unit_exit(probe: dict, card: dict) -> tuple:
    """(True|False|None, detail) — did devin-task-<tid> exit 0.

    None = no usable record (unit GC'd before exit_code existed, journal
    rotated, runner never reported): callers treat it as 'unproven',
    not failed."""
    ec = str(probe.get("exit_code") or "").strip()
    if ec:
        return (ec == "0"), f"exit_code={ec}"
    mres = str((probe.get("meta") or {}).get("result") or "").strip()
    if mres and mres != "unknown":
        return (mres == "success"), f"meta.result={mres}"
    u = probe.get("unit") or {}
    if u.get("load") == "loaded":
        # only a loaded unit's fields are real — a never-loaded/collected
        # unit reports defaults (Result=success) that prove nothing
        ok = u.get("result") == "success" and str(u.get("exec")) == "0"
        return ok, (f"unit ExecMainStatus={u.get('exec') or '?'} "
                    f"Result={u.get('result') or '?'}")
    jr = str(probe.get("journal_result") or "").strip()
    if jr:
        return (jr == "success"), f"journal={jr}"
    # card-side last resort: the finish report the runner/dispatcher
    # already posted — 'finished (ok): exit=N' (runner-agent) or
    # 'run finished (<state>)' (kanban-dispatch).
    for cm in reversed(card.get("comms") or []):
        t = str(cm.get("text") or "")
        if "finished" not in t:
            continue
        ex = re.search(r"\bexit=(\d+)", t)
        if ex:
            return (ex.group(1) == "0"), f"finish report exit={ex.group(1)}"
        hit = re.search(r"finished \((\w+)\)", t)
        if hit:
            word = hit.group(1)
            return (word in ("ok", "inactive", "exited")), \
                f"finish report '{word}'"
    if (card.get("action") or {}).get("status") == "done":
        # weakest tier: the finish path only reaches done for units that
        # weren't in failed state. Pre-exit_code-era tasks have nothing
        # better; (b) still requires a real deliverable.
        return True, "card finished (no exit record survives)"
    return None, "no exit record"


def _containing_merge(repo: Path, head: str, base_tip: str) -> str:
    """First-parent sha of the newest merge on base_tip whose non-first
    parent contains head — i.e. the base tip just before the session
    branch was merged in. '' when head didn't arrive via a merge."""
    out = sh(["git", "-C", str(repo), "log", "--first-parent", "--merges",
              "--format=%H %P", "--max-count=2000", base_tip],
             timeout=60).stdout or ""
    for ln in out.splitlines():
        p = ln.split()
        if len(p) < 3:
            continue
        if any(sh(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                   head, par], timeout=30).returncode == 0
               for par in p[2:]):
            return p[1]
    return ""


def produced_work(repo: Path, head: str, base_tip: str,
                  m: dict, tid: str) -> tuple:
    """(True|False|None, detail) — gate (b): the session changed files
    vs base or left its outcome doc. None = can't reconstruct."""
    doc = sh(["git", "-C", str(repo), "ls-tree", "--name-only", head,
              f"dispatch-outcome-{tid}.md"], timeout=30)
    if doc.returncode == 0 and doc.stdout.strip():
        return True, f"outcome doc dispatch-outcome-{tid}.md"
    if m["ancestor"]:
        if head == base_tip:
            return False, "branch head == base tip — nothing committed"
        if m.get("on_first_parent"):
            return False, "head is an old base commit — nothing committed"
        # head entered base through a merge's non-first parent: diff the
        # branch tip against that merge's first parent (base at the time)
        pre = _containing_merge(repo, head, base_tip)
        if not pre:
            return None, ("head is merged but the merge isn't in the "
                          "first-parent window — can't diff the session")
        diff_from = pre
    else:
        r = sh(["git", "-C", str(repo), "merge-base", base_tip, head],
               timeout=30)
        diff_from = r.stdout.strip() or base_tip
    names = (sh(["git", "-C", str(repo), "diff", "--name-only",
                 diff_from, head], timeout=60).stdout or "").split()
    if names:
        return True, f"{len(names)} file(s) changed vs base"
    return False, "no changed files vs base and no outcome doc"


_KA = None
_KA_TRIED = False


def _kanban_act():
    """Import scripts/ada/kanban-act.py for its CHECKS vocabulary — the
    same bounded check kinds, evaluated here so verified can reflect the
    card's own contract instead of waiting a kanban-act pass."""
    global _KA, _KA_TRIED
    if _KA_TRIED:
        return _KA
    _KA_TRIED = True
    for cand in (CHABA_REPO / "scripts" / "ada" / "kanban-act.py",
                 SCRIPT_REPO / "scripts" / "ada" / "kanban-act.py"):
        if not cand.exists():
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                "kanban_act", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _KA = mod
            return _KA
        except Exception:
            continue
    return None


def auto_done_ok(card: dict, by_id: dict) -> tuple:
    """(c): (True, detail) when every auto_done_when check passes —
    a self 'verified_true' entry counts this gate's a+b verdict.
    (False, detail) = defer to kanban-act. No contract -> True."""
    when = card.get("auto_done_when")
    if not when:
        return True, ""
    ka = _kanban_act()
    cid = card.get("id") or ""
    results = []
    for expr in when:
        kind, _, arg = str(expr).partition(":")
        if kind == "verified_true" and (not arg or arg == cid):
            results.append(f"{expr}=gate")
            continue
        fn = ka.CHECKS.get(kind) if ka else None
        try:
            ok = bool(fn and fn(arg, by_id, card))
        except Exception:
            ok = False
        results.append(f"{expr}={'pass' if ok else 'fail'}")
        if not ok:
            return False, "; ".join(results)
    return True, "; ".join(results)


def verify_gate(card: dict, probe: dict, repo: Path, head: str,
                base_tip: str, m: dict, tid: str, by_id: dict) -> dict:
    """The (a) exit / (b) deliverable / (c) auto_done_when conjunction.
    Returns {"verify"|"fail"|"hold"|"defer": True, "why": ...}."""
    ok_b, why_b = produced_work(repo, head, base_tip, m, tid)
    ok_a, why_a = unit_exit(probe, card)
    if ok_b is False:
        return {"fail": True,
                "why": f"no delivered work — {why_b}; unit: {why_a}"}
    if ok_a is False and not m["ancestor"]:
        return {"fail": True,
                "why": f"unit did not exit 0 ({why_a}) — unmerged "
                       "partial work isn't auto-merged"}
    if ok_a is False:
        return {"hold": True,
                "why": f"branch is merged ({why_b}) but the unit did "
                       f"not exit 0 ({why_a}) — needs a human look"}
    if ok_b is None:
        return {"hold": True, "why": f"can't verify the diff — {why_b}"}
    if ok_a is None:
        return {"hold": True,
                "why": f"work present ({why_b}) but the unit exit is "
                       f"unverifiable ({why_a})"}
    ok_c, why_c = auto_done_ok(card, by_id)
    if ok_c is False:
        return {"defer": True,
                "why": f"auto_done_when not met ({why_c}) — deferred "
                       "to kanban-act"}
    return {"verify": True,
            "why": f"{why_a}; {why_b}" + (f"; {why_c}" if why_c else "")}


def fail_attempt(card: dict, why: str, dry: bool) -> bool:
    """verified-gate failure: verified=False + requeue on the same
    path kanban-dispatch's merge step uses (attempts/max_attempts cap,
    last_failure carries the evidence into the next run's RETRY_RAILS)."""
    cid = card.get("id") or "?"
    if dry:
        print(f"  [dry] {cid}: verified gate failed — {why[:110]}")
        return True

    def apply(c):
        a = c.setdefault("action", {})
        a["verified"] = False  # checked, and NOT verified
        a["last_failure"] = why[:280]
        c.setdefault("claim", {}).pop("session", None)
        # attempts is counted at claim time (mark_start) — a gate failure
        # requeues while attempts_used < max_attempts (max_attempts =
        # total dispatches incl. retries; merge_pending_one now uses the
        # same predicate — its old att+1<max variant double-counted,
        # card kanban-autoretry-off-by-one)
        att = int(a.get("attempts") or 0)
        max_att = int(a.get("max_attempts")
                      or os.environ.get("KANBAN_MAX_ATTEMPTS", "2"))
        if os.environ.get("KANBAN_AUTORETRY", "1") != "0" \
                and att < max_att:
            a["status"] = "queued"
            a.pop("runner", None)
            a.pop("task_id", None)
            text = (f"merge-sweep: verified gate failed — {why[:240]}; "
                    f"auto-retry queued (attempt {att + 1}/{max_att})")
        else:
            a["status"] = "failed"
            text = (f"merge-sweep: verified gate failed — {why[:240]}; "
                    "attempt limit reached, needs a human")
        c.setdefault("comms", []).append(
            {"at": now(), "from": "chaba", "text": text[:500]})
    return locked_edit(cid, apply)


# ------------------------------------------------------------- git ops
def served_repo(repo_name: str) -> Path | None:
    """The checkout merges land in for repo_name."""
    p = SERVED.get(repo_name)
    if p:
        p = Path(p).expanduser()
        return p if (p / ".git").exists() or (p / "HEAD").exists() else None
    ent = dr.repos().get(repo_name)
    if ent and (ent["path"] / ".git").exists():
        return ent["path"]
    return None


def fetch_session(repo: Path, host: str, probe: dict) -> str:
    """git fetch <runner>:<worktree> HEAD into the served repo; returns
    the fetched sha ("" on failure). The -c core.sshCommand=ssh override
    is the whole point: repos pin a GitHub-only key that can't reach
    tailnet runners — plain ssh uses ~/.ssh/config."""
    path, ref = probe.get("fetch_path"), probe.get("fetch_ref", "HEAD")
    if not path:
        return ""
    if host and host != HOST:
        spec = f"{host}:{path}"
        cmd = ["git", "-C", str(repo), "-c", "core.sshCommand=ssh",
               "fetch", "-q", spec, ref]
    else:
        cmd = ["git", "-C", str(repo), "fetch", "-q", path, ref]
    if sh(cmd, timeout=120).returncode != 0:
        return ""
    return dr._rev_parse(repo, "FETCH_HEAD")


def merge_strict(repo: Path, sha: str, base_ref: str,
                 base: str) -> dict:
    """--no-ff merge of sha into origin/<base> inside a throwaway
    detached worktree of the served repo — NEVER silently resolves a
    side: any conflicted path aborts and is reported.
    {merged, sha, conflicts, error}."""
    mwt = Path(tempfile.mkdtemp(prefix="merge-sweep-"))
    try:
        r = sh(["git", "-C", str(repo), "worktree", "add", "--detach",
                str(mwt), base_ref], timeout=60)
        if r.returncode != 0:
            return {"merged": False,
                    "error": f"worktree add: {r.stderr.strip()[:200]}"}
        for attempt in (1, 2):
            r = sh(["git", "-C", str(mwt), "merge", "--no-ff",
                    "--no-edit", sha], timeout=90)
            if r.returncode != 0:
                conflicts = sh(
                    ["git", "-C", str(mwt), "diff", "--name-only",
                     "--diff-filter=U"]).stdout.split()
                if not conflicts:
                    # merge refused outright (dirty state can't exist in
                    # a fresh worktree — this is a real refusal)
                    conflicts = [(r.stderr or r.stdout).strip()[:200]]
                sh(["git", "-C", str(mwt), "merge", "--abort"],
                   timeout=30)
                return {"merged": False, "conflicts": conflicts}
            push = sh(["git", "-C", str(mwt), "push", "-q", "origin",
                       f"HEAD:{base}"], timeout=90)
            if push.returncode == 0:
                return {"merged": True,
                        "sha": dr._rev_parse(mwt, "HEAD")}
            if attempt == 2:
                return {"merged": False,
                        "error": (f"push: "
                                  f"{(push.stderr or push.stdout).strip()[:200]}")}
            # remote moved between fetch and push — resync once, retry
            sh(["git", "-C", str(repo), "fetch", "-q", "origin", base],
               timeout=60)
            sh(["git", "-C", str(mwt), "reset", "-q", "--hard",
                base_ref], timeout=30)
        return {"merged": False, "error": "unreachable"}
    finally:
        sh(["git", "-C", str(repo), "worktree", "remove", "--force",
            str(mwt)], timeout=30)
        sh(["git", "-C", str(repo), "worktree", "prune"], timeout=30)


# ------------------------------------------------------------- sweep
def task_id_for(card: dict, runner: str) -> str:
    """action.task_id -> claim.session -> comms 'devin-task-<id>' line ->
    runner-agent state.json on the runner host."""
    a = card.get("action") or {}
    tid = str(a.get("task_id") or "").strip()
    if tid:
        return tid
    tid = str((card.get("claim") or {}).get("session") or "").strip()
    if tid:
        return tid
    for m in card.get("comms") or []:
        hit = TASK_ID_RE.search(str(m.get("text") or ""))
        if hit:
            return hit.group(1)
    return runner_task_ids(runner).get(card.get("id") or "", "")


def runner_for(card: dict, tid: str) -> str:
    a = card.get("action") or {}
    r = str(a.get("runner") or "").strip()
    if r:
        return r
    for m in card.get("comms") or []:
        text = str(m.get("text") or "")
        hit = re.search(
            rf"started devin-task-{re.escape(tid)} on (\S+)", text)
        if hit:
            return hit.group(1).rstrip("()")
    return ""


def flag_once(card: dict, key: str, text: str, dry: bool,
              val=None) -> bool:
    """Post comms only the first time a condition is seen (action.sweep
    stamp); returns True when it fired."""
    a = card.get("action") or {}
    if (a.get("sweep") or {}).get(key):
        return False
    card_note(card["id"], text, dry)
    stamp(card["id"], key, val if val is not None else now(), dry)
    return True


# ----------------------------------------------------- verified drain
def close_hold_reason(card: dict) -> str:
    """Why a verified card stays in review instead of closing itself —
    "" when it may auto-close. Absent review_kind defaults to verify
    (card_schema); decide/triage are human calls. Open requests and
    unanswered asks block — the same contract kanban-act's
    gate_hold_reason enforces for t2 cards."""
    kind = str(card.get("review_kind") or "verify").strip().lower()
    if kind != "verify":
        return f"review_kind={kind} — human-gated"
    blockers = [
        str(r.get("id") or r.get("ask", "?"))[:30]
        for r in card.get("requests") or []
        if isinstance(r, dict)
        and (r.get("status") or "open") != "answered"]
    ask = card.get("ask") or {}
    if (isinstance(ask, dict) and ask.get("question")
            and (ask.get("status") or "open") != "answered"):
        blockers.append("ask")
    if blockers:
        return f"open request(s) {blockers} block close"
    return ""


def drain_verified(card: dict, dry: bool) -> bool:
    """The close decision for a card already stamped verified — the
    work is merged, so only the column remains. review_kind verify
    (or absent) closes itself: status->done, column->done, an
    auto_close record. Human-gated cards (close_hold_reason) move
    to/stay in review with one comms note. Idempotent: no card
    change, no output — a held card doesn't re-report every pass."""
    cid = card.get("id") or "?"
    if card.get("column") == "done":
        return False
    if dry:
        hold = close_hold_reason(card)
        print(f"  [dry] {cid}: verified — "
              + (f"held in review ({hold})" if hold
                 else "auto-close (column -> done)"))
        return True
    out = {}

    def apply(c):
        a = c.setdefault("action", {})
        changed = a.get("status") != "done"
        a["status"] = "done"
        c.setdefault("claim", {}).pop("session", None)
        hold = close_hold_reason(c)
        out["hold"] = hold
        if hold:
            if c.get("column") != "review":
                c["column"] = "review"
                changed = True
        elif c.get("column") != "done":
            c["column"] = "done"
            c["auto_close"] = {
                "by": "merge-sweep", "at": now(),
                "note": "verified — evidence checks green, "
                        "closing itself"}
            changed = True
        return changed

    changed = locked_edit(cid, apply)
    if out.get("hold"):
        # the request/kind is the visible gate — explain once (sweep
        # stamp), even when the card itself needed no field change
        flagged = flag_once(
            card, "close_held",
            f"merge-sweep: verified — held in review ({out['hold']})",
            dry)
        return bool(changed or flagged)
    if not changed:
        return False
    card_note(cid, "merge-sweep: verified — auto-closed "
                   "(column -> done)", dry)
    return True


def sweep_card(card: dict, active: dict, dry: bool,
               by_id: dict | None = None) -> bool:
    """One dispatch card through the merge lane. `active` = {task:
    info} of devin-task units still active on any probed host — used to
    skip in-flight sessions. `by_id` = all cards for auto_done_when
    checks (card_done/verified_true:<id>). True when the board
    changed."""
    a = card.get("action") or {}
    cid = card.get("id") or "?"
    st = a.get("status")
    if st in ("queued", "starting"):
        return False
    if st == "done" and a.get("verified") is True:
        # already landed — drain the column decision without git work
        # (verified implies merged; covers close_out-stamped cards and
        # stragglers from before the drain existed)
        return drain_verified(card, dry)
    tid = task_id_for(card, str(a.get("runner") or ""))
    if not tid:
        return False
    runner = runner_for(card, tid)
    if st == "running" and tid in active:
        return False  # in-flight — zombie lane watches it, not merge
    if st == "running":
        flag_once(card, "stale_running",
                  f"merge-sweep: devin-task-{tid} no longer active on "
                  f"{runner or HOST} but card still says running — "
                  "sweeping its branch", dry)
    if st == "failed":
        flag_once(card, "failed_noted",
                  f"merge-sweep: devin-task-{tid} failed — its branch "
                  f"isn't auto-merged (unverified partial work). Retry "
                  "the card or merge dispatch/" + tid + " by hand.", dry)
        return False

    probe = session_probe(runner, tid)
    if not probe or (not probe.get("head") and not probe.get("wt_exists")):
        flag_once(card, "session_gone",
                  f"merge-sweep: no session/worktree found for "
                  f"devin-task-{tid} on {runner or HOST} — if the work "
                  "was never pushed it may be gone", dry)
        return False
    repo_name = (probe.get("meta") or {}).get("repo") \
        or a.get("repo") or ""
    repo = served_repo(repo_name)
    if repo is None:
        flag_once(card, "no_repo",
                  f"merge-sweep: no served checkout for repo "
                  f"'{repo_name or '?'}' — can't land devin-task-{tid}",
                  dry)
        return False
    dirty = probe.get("dirty")
    if dirty:
        flag_once(card, "dirty",
                  f"merge-sweep: worktree {Path(probe['worktree']).name} "
                  f"on {runner or HOST} still dirty — {dirty} "
                  "uncommitted file(s); not fetching (checkpoint is the "
                  "runner's job)", dry, val=dirty)
        return False

    base = (probe.get("meta") or {}).get("default_branch") \
        or (dr.repos().get(repo_name) or {}).get("default_branch") \
        or "master"
    sh(["git", "-C", str(repo), "fetch", "-q", "origin", base],
       timeout=60)
    base_ref = f"origin/{base}"
    if not dr._rev_parse(repo, base_ref):
        flag_once(card, "no_base",
                  f"merge-sweep: no {base_ref} in {repo} — can't "
                  f"land devin-task-{tid}", dry)
        return False
    head = fetch_session(repo, runner, probe)
    if not head:
        flag_once(card, "fetch_failed",
                  f"merge-sweep: fetch {runner or 'local'}:"
                  f"{probe.get('fetch_path')} {probe.get('fetch_ref')} "
                  "failed — runner down or worktree gone?", dry)
        return False
    m = dr.merge_state(repo, head, base_ref)
    if not m.get("checked"):
        flag_once(card, "state_err",
                  f"merge-sweep: {m.get('error')} for devin-task-{tid}",
                  dry)
        return False

    # A card already stamped verified never re-gates — re-evaluating
    # stale evidence can flip a proven card back to queued and
    # re-dispatch it (the 2026-10-09 verified-merge re-dispatch).
    # ancestor head = the work is in base: run the close decision.
    # Non-ancestor = anomalous (commits landed after verification the
    # stamp never covered): flag once for a human, never auto-merge
    # or requeue on a proven card.
    if a.get("verified") is True:
        if not m["ancestor"]:
            return flag_once(
                card, "verified_unmerged",
                f"merge-sweep: {cid} is verified but "
                f"{probe.get('branch')} has {m['unmerged']} commit(s) "
                f"not in {base_ref} — not re-gating a proven card; "
                "check by hand", dry)
        return drain_verified(card, dry)

    # verified gate — verified means "the dispatch delivered", not "the
    # branch merged" (2026-10-09 nest-mgr false-verify). A provable
    # failure requeues before any merge; undecidable states hold with a
    # comms flag; auto_done_when gaps defer to kanban-act.
    base_tip = dr._rev_parse(repo, base_ref)
    g = verify_gate(card, probe, repo, head, base_tip, m, tid,
                    by_id or {cid: card})
    if g.get("fail"):
        return fail_attempt(card, g["why"], dry)

    def stamp_gate_result(merged_txt: str) -> bool:
        """Apply the gate verdict after a merge/already-merged check."""
        if g.get("verify"):
            held = {}

            def mark(c):
                a = c.setdefault("action", {})
                a["verified"] = True
                a["status"] = "done"
                c.setdefault("claim", {}).pop("session", None)
                hold = close_hold_reason(c)
                if hold:
                    held["why"] = hold
                    # human-gated — surface in review, don't close
                    c["column"] = "review"
                else:
                    c["column"] = "done"
                    c["auto_close"] = {
                        "by": "merge-sweep", "at": now(),
                        "note": f"verified — {g['why'][:200]}"}
            if dry:
                held["why"] = close_hold_reason(card)
                print(f"  [dry] {cid}: {merged_txt} — stamp verified "
                      f"({g['why'][:80]})")
            else:
                locked_edit(cid, mark)
            tail = (f" — held in review ({held['why']})"
                    if held.get("why") else " — auto-closed")
            card_note(cid, f"merge-sweep: {merged_txt} — marked "
                           f"verified ({g['why'][:160]}){tail}", dry)
            return True
        key = "verify_deferred" if g.get("defer") else "verify_hold"
        return flag_once(card, key,
                         f"merge-sweep: {merged_txt} but verified "
                         f"withheld — {g['why'][:200]}", dry)

    if m["ancestor"]:
        return stamp_gate_result(
            f"{probe.get('branch')} already in {base_ref}")
    if dry:
        verdict = ("verify" if g.get("verify") else
                   "defer" if g.get("defer") else "hold")
        print(f"  [dry] {cid}: would merge {head[:8]} "
              f"({m['unmerged']} commits) -> {base_ref} in {repo} "
              f"[gate: {verdict}]")
        return True
    res = merge_strict(repo, head, base_ref, base)
    if res.get("merged"):
        stamp_gate_result(
            f"merged {res['sha'][:8]} ({probe.get('branch')} from "
            f"{runner or HOST}) -> origin/{base}")
        return True
    if res.get("conflicts"):
        files = ", ".join(str(f) for f in res["conflicts"][:10])
        # comms rides the request — without it, every 15min pass would
        # repost the same conflict line while it waits on a human
        if not open_conflict_req(card):
            card_note(cid, f"merge-sweep: {probe.get('branch')} "
                           f"conflicts with {base_ref}: {files} — "
                           "merge aborted, card stays for human "
                           "resolution", dry)
            card_request(cid, conflict_rid(card),
                         f"merge-sweep can't land dispatch/{tid}: "
                         f"{m['unmerged']} commit(s) conflict with "
                         f"{base_ref} in {repo_name or 'repo'} — "
                         f"conflicted paths: {files}. Merge "
                         f"{runner or 'local'}:{probe.get('worktree')} "
                         "by hand, or retry/abandon the card.", dry)
        return True
    flag_once(card, "merge_err",
              f"merge-sweep: landing devin-task-{tid} failed: "
              f"{res.get('error') or 'unknown'}", dry)
    return False


def sweep_zombies(host_units: dict, cards_by_tid: dict,
                  dry: bool) -> int:
    """devin-task-* active >ZOMBIE_AGE_S with no activity >ZOMBIE_IDLE_S
    -> one card comms flag. Never kills (the 32h cue-fit case).
    host_units = {host: zombie_probe(host)} — probed once in main."""
    flagged = 0
    for host, units in host_units.items():
        for z in units:
            if z["age_s"] < ZOMBIE_AGE_S or z["idle_s"] < ZOMBIE_IDLE_S:
                continue
            tid = z["task"]
            card = cards_by_tid.get(tid)
            msg = (f"merge-sweep: devin-task-{tid} zombie? — active "
                   f"{z['age_s'] / 3600:.0f}h on {host}, no session "
                   f"activity for {z['idle_s'] / 60:.0f}min. Not "
                   f"killed — check `ssh {host} systemctl --user status "
                   f"devin-task-{tid}`")
            if card:
                if flag_once(card, "zombie", msg, dry, val=tid):
                    flagged += 1
            else:
                print(f"  zombie (no card): devin-task-{tid} on {host} "
                      f"— {msg.split('—', 1)[-1].strip()}")
                flagged += 1
    return flagged


def main() -> int:
    dry = "--dry-run" in sys.argv
    card_files = sorted(CARD_DIR.glob("*.yml"))
    if not card_files:
        print(f"merge-sweep: no cards in {CARD_DIR}")
        return 0

    cards = [load_card(p) for p in card_files]
    cards = [c for c in cards if c]
    by_tid = {}
    runners = set()
    for c in cards:
        a = c.get("action") or {}
        tid = str(a.get("task_id") or (c.get("claim") or {})
                  .get("session") or "")
        if not tid:
            for m in c.get("comms") or []:
                hit = TASK_ID_RE.search(str(m.get("text") or ""))
                if hit:
                    tid = hit.group(1)
                    break
        if tid:
            by_tid[tid] = c
        r = str(a.get("runner") or "").strip()
        if not r and tid:
            r = runner_for(c, tid)  # comms 'on <host>' fallback
        if r and r != HOST:
            runners.add(r)

    # one zombie probe per host doubles as the "still active?" set for
    # running cards — don't probe a host twice
    hosts = []
    for h in [HOST] + sorted(runners) + SWEEP_HOSTS:
        if h and h not in hosts:
            hosts.append(h)
    active = {}
    host_units = {}
    for h in hosts:
        units = zombie_probe(h)
        host_units[h] = units
        for z in units:
            active[z["task"]] = {**z, "host": h}

    changed = False
    by_id = {c.get("id"): c for c in cards if c.get("id")}
    in_scope = [c for c in cards
                if c.get("column") in ("doing", "review")
                and (c.get("action") or {}).get("type") == "dispatch"]
    for c in in_scope:
        try:
            changed |= sweep_card(c, active, dry, by_id)
        except Exception as e:
            print(f"{c.get('id')}: sweep error {type(e).__name__}: {e}")
    zombies = sweep_zombies(host_units, by_tid, dry)
    changed |= bool(zombies)

    if changed and not dry and RENDER.exists():
        subprocess.run([sys.executable, str(RENDER)], cwd=CHABA_REPO,
                       check=False, timeout=120,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    print(f"merge-sweep: {len(in_scope)} dispatch cards in scope, "
          f"{sum(len(u) for u in host_units.values())} active units "
          f"across {len(hosts)} host(s)"
          + (", board updated" if changed else ", nothing to do")
          + (" (dry-run)" if dry else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
