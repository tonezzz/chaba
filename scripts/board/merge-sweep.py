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
  6. on clean merge: push + card comms + action.verified=True.
     Already-merged branches are silent no-ops (verified is still
     stamped when missing).

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
import json, subprocess, sys
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


def sweep_card(card: dict, active: dict, dry: bool) -> bool:
    """One dispatch card through the merge lane. `active` = {task:
    info} of devin-task units still active on any probed host — used to
    skip in-flight sessions. True when the board changed."""
    a = card.get("action") or {}
    cid = card.get("id") or "?"
    st = a.get("status")
    if st in ("queued", "starting"):
        return False
    if st == "done" and a.get("verified") is True:
        return False  # already landed — the cheap skip
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
    if m["ancestor"]:
        changed = False
        if a.get("verified") is not True:
            def mark(c):
                c.setdefault("action", {})["verified"] = True
            if dry:
                print(f"  [dry] {cid}: already merged — stamp verified")
            else:
                locked_edit(cid, mark)
            card_note(cid, f"merge-sweep: {probe.get('branch')} already "
                           f"in {base_ref} — marked verified", dry)
            changed = True
        return changed
    if dry:
        print(f"  [dry] {cid}: would merge {head[:8]} "
              f"({m['unmerged']} commits) -> {base_ref} in {repo}")
        return True
    res = merge_strict(repo, head, base_ref, base)
    if res.get("merged"):
        def mark(c):
            c.setdefault("action", {})["verified"] = True
        locked_edit(cid, mark)
        card_note(cid, f"merge-sweep: merged {res['sha'][:8]} "
                       f"({probe.get('branch')} from {runner or HOST}) "
                       f"-> origin/{base}", dry)
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
    in_scope = [c for c in cards
                if c.get("column") in ("doing", "review")
                and (c.get("action") or {}).get("type") == "dispatch"]
    for c in in_scope:
        try:
            changed |= sweep_card(c, active, dry)
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
