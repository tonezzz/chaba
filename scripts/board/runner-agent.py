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
  RUNNER_LABELS  comma-separated capability labels (e.g. "gpu,ssd")
  RUNNER_STATE   state dir (default ~/.local/share/runner-agent)

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
                 "--description", f"runner {cid}",
                 "podman", "run", "--rm",
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
                 "--description", f"runner {cid}"] + env +
                ["bash", "-lc",
                 f"cd {shlex.quote(workdir)} && "
                 f"exec {shlex.join(cmd)}"])
    else:  # dispatch
        spec = (card.get("spec") or "").strip() or \
            f"{card.get('title', '')}\n\n{card.get('note', '')}"
        task = spec + "\n\n" + RAILS.format(id=cid, host=HOST, api=API)
        argv = [DISPATCH, "start", a.get("repo", "chaba"), task]
    r = sh(argv, timeout=180,
           env={**os.environ,
                **({"DISPATCH_MODEL": str(a["model"])}
                   if a.get("model") else {})})
    if r.returncode != 0:
        return "", "", (r.stderr or r.stdout).strip()[:240]
    tid = ""
    if typ == "dispatch":
        # devin-dispatch prints the task id (unit is devin-task-<id>)
        tid = r.stdout.strip().splitlines()[-1].strip()
        unit = f"devin-task-{tid}"
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
                   "at": int(time.time())}
        changed = True
        print(f"{cid}: claimed + started {unit}")
    return changed


def main() -> int:
    st = load_state()
    changed = finish_pass(st) | claim_pass(st)
    if changed:
        save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
