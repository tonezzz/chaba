#!/usr/bin/env python3
"""dispatch_repos — shared repo/session resolution for the dispatch loop.

Implements the kanban merge guard (card dispatch-merge-guard):

  * repo table: ``$DISPATCH_DIR/repos.conf`` — one ``name path
    default_branch`` triple per line (# comments, blank lines ok). This is
    the same file devin-dispatch reads; when absent the built-in table
    below applies (keep both in sync).
  * session record: ``$DISPATCH_DIR/tasks/<task_id>/meta.json`` written by
    devin-dispatch — {repo, worktree, branch, default_branch, base}.

Consumers:
  scripts/board/board-api.py       — blocks review->done while session
                                     commits are non-ancestors of the
                                     default branch
  scripts/board/kanban-dispatch.py — session-end comms (dirty worktree /
                                     unmerged commit counts)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
try:
    import goals as goallib  # scripts/lib/goals.py — expected_goals exec
except Exception:  # executor optional — a declared goal set then blocks
    goallib = None

# name -> (path, default_branch). Fallback whitelist — canonical table is
# $DISPATCH_DIR/repos.conf (repo copy: scripts/devin/dispatch-repos.conf).
BUILTIN_REPOS = {
    "chaba": ("~/CascadeProjects/chaba", "master"),
    "ada-pi": ("~/CascadeProjects/ada-pi", "main"),
    "sunsynk-card": ("~/CascadeProjects/sunsynk-power-flow-card", "main"),
    "mddb-fork": ("~/CascadeProjects/mddb-fork", "main"),
    "gods-eye-view": ("~/gods-eye-view", "main"),
}


def dispatch_dir() -> Path:
    return Path(os.environ.get(
        "DISPATCH_DIR", str(Path.home() / ".local/share/devin-dispatch")))


def repos() -> dict:
    """{name: {"path": Path, "default_branch": str}} — repos.conf wins."""
    table = {k: {"path": Path(v[0]).expanduser(), "default_branch": v[1]}
             for k, v in BUILTIN_REPOS.items()}
    conf = dispatch_dir() / "repos.conf"
    if conf.exists():
        for ln in conf.read_text().splitlines():
            ln = ln.split("#", 1)[0].strip()
            if not ln:
                continue
            parts = ln.split()
            name, path = parts[0], Path(parts[1]).expanduser()
            table[name] = {"path": path,
                           "default_branch": parts[2] if len(parts) > 2
                           else "master"}
    return table


def sh(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def task_meta(task_id: str) -> dict:
    p = dispatch_dir() / "tasks" / task_id / "meta.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _rev_parse(repo: Path, rev: str) -> str:
    r = sh(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", rev])
    return r.stdout.strip() if r.returncode == 0 else ""


def _repo_root(worktree: Path) -> Path | None:
    """Main checkout root for a linked worktree (the .git common parent)."""
    r = sh(["git", "-C", str(worktree), "rev-parse",
            "--path-format=absolute", "--git-common-dir"])
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return Path(r.stdout.strip()).parent


def _default_branch(repo_root: Path, meta: dict, repo_name: str) -> str:
    """origin/<default> selector: meta -> repos.conf -> origin/HEAD -> probe."""
    if meta.get("default_branch"):
        return meta["default_branch"]
    ent = repos().get(repo_name)
    if ent and ent.get("default_branch"):
        return ent["default_branch"]
    r = sh(["git", "-C", str(repo_root), "symbolic-ref", "--quiet",
            "--short", "refs/remotes/origin/HEAD"])
    if r.returncode == 0 and r.stdout.strip().startswith("origin/"):
        return r.stdout.strip()[len("origin/"):]
    for cand in ("master", "main"):
        if _rev_parse(repo_root, f"refs/remotes/origin/{cand}"):
            return cand
    return ""


def session(card: dict) -> dict:
    """Resolve a card's dispatch session to git refs.

    Returns {task_id, branch, worktree, repo_root, head, default_branch,
    base_ref}; fields are None when unresolvable."""
    a = card.get("action") or {}
    tid = a.get("task_id") or ""
    out = {"task_id": tid, "branch": None, "worktree": None,
           "repo_root": None, "head": None, "default_branch": None,
           "base_ref": None, "repo_name": None}
    if a.get("type") != "dispatch" or not tid:
        return out
    meta = task_meta(tid)
    out["repo_name"] = meta.get("repo") or a.get("repo") or ""
    out["branch"] = meta.get("branch") or f"dispatch/{tid}"
    wt = Path(meta.get("worktree") or
              Path.home() / f"CascadeProjects/dispatch-wt-{tid}")
    out["worktree"] = wt if wt.is_dir() else None

    root = _repo_root(wt) if out["worktree"] else None
    if root is None:
        # worktree gone — the session branch may still live in its repo
        ent = repos().get(out["repo_name"] or "")
        roots = [ent["path"]] if ent else [e["path"] for e in repos().values()]
        for cand in roots:
            if Path(cand).is_dir() and _rev_parse(
                    Path(cand), f"refs/heads/{out['branch']}"):
                root = Path(cand)
                break
    out["repo_root"] = root
    if root is None:
        return out

    if out["worktree"]:
        out["head"] = _rev_parse(out["worktree"], "HEAD") or None
    if not out["head"]:
        out["head"] = _rev_parse(root, out["branch"]) or None
    out["default_branch"] = _default_branch(
        root, meta, out["repo_name"] or "") or None
    if out["default_branch"]:
        base = f"origin/{out['default_branch']}"
        if _rev_parse(root, base):
            out["base_ref"] = base
    return out


def merge_state(repo_root: Path, head: str, base_ref: str) -> dict:
    """Ancestry of the session head vs the default-branch ref."""
    if not _rev_parse(repo_root, base_ref):
        return {"checked": False, "error": f"no {base_ref} ref in {repo_root}"}
    r = sh(["git", "-C", str(repo_root), "merge-base", "--is-ancestor",
            head, base_ref])
    if r.returncode == 0:
        return {"checked": True, "ancestor": True, "unmerged": 0}
    if r.returncode != 1:
        return {"checked": False,
                "error": (r.stderr or r.stdout).strip() or "merge-base failed"}
    n = sh(["git", "-C", str(repo_root), "rev-list", "--count",
            f"{base_ref}..{head}"])
    subs = sh(["git", "-C", str(repo_root), "log", "--format=%s",
               "--max-count=3", f"{base_ref}..{head}"])
    return {"checked": True, "ancestor": False,
            "unmerged": int(n.stdout.strip() or 0),
            "subjects": [s for s in subs.stdout.splitlines() if s][:3]}


def dirty_count(worktree: Path) -> int | None:
    """Uncommitted path count; None when the worktree can't be checked."""
    if not worktree or not Path(worktree).is_dir():
        return None
    r = sh(["git", "-C", str(worktree), "status", "--porcelain=v1",
            "--untracked-files=normal"])
    if r.returncode != 0:
        return None
    return sum(1 for ln in r.stdout.splitlines() if ln.strip())


def guard(card: dict) -> dict:
    """review->done gate. {allowed, summary, note} — note is comms-worthy."""
    a = card.get("action") or {}
    if a.get("type") != "dispatch" or not a.get("task_id"):
        return {"allowed": True, "summary": "", "note": ""}
    s = session(card)
    tid = s["task_id"]
    if not s.get("head") or not s.get("repo_root"):
        return {"allowed": True, "summary": "",
                "note": f"merge guard: no session branch/worktree for {tid} "
                        f"— nothing to verify"}
    dirty = dirty_count(s["worktree"]) if s["worktree"] else None
    dirty_txt = f"; worktree still dirty: {dirty} uncommitted file(s)" \
        if dirty else ""
    if not s.get("base_ref"):
        return {"allowed": True, "summary": "",
                "note": f"merge guard: no origin default branch resolvable "
                        f"for {tid} — check skipped{dirty_txt}"}
    m = merge_state(s["repo_root"], s["head"], s["base_ref"])
    if not m["checked"]:
        return {"allowed": True, "summary": "",
                "note": f"merge guard: {m['error']} — check skipped{dirty_txt}"}
    if not m["ancestor"]:
        subs = "; ".join(m.get("subjects") or [])
        note = (f"unmerged commits remain on {s['branch']} — "
                f"{m['unmerged']} commit(s) not in {s['base_ref']}"
                f"{': ' + subs if subs else ''}{dirty_txt}")
        return {"allowed": False,
                "summary": (f"unmerged commits remain on {s['branch']} "
                            f"({m['unmerged']} not in {s['base_ref']})"),
                "note": note}
    return {"allowed": True,
            "summary": "",
            "note": f"merge guard: {s['branch']} merged into "
                    f"{s['base_ref']}{dirty_txt}"}


# ------------------------------------------------------------- close-out
#
# Dispatch merge step (card dispatch-auto-merge). Pipeline at session end:
#   checkpoint leftover worktree files -> push the session branch to origin
#   (always — a branch left local-only is how work strands) -> merge
#   --no-ff into origin/<default_branch> behind an expected_goals gate.
# Conflict policy follows scripts/git-safe-pull.sh conventions: paths under
# SAFE_PULL_GENERATED_RE (default ^docs/ssot/) resolve upstream-wins — the
# default branch carries the served/generated state; the per-session
# dispatch-outcome*.md scratch resolves session-wins; anything else aborts
# and is reported for a human (not everything merges — that is correct).

GENERATED_RE = re.compile(
    os.environ.get("SAFE_PULL_GENERATED_RE", r"^docs/ssot/"))
SESSION_SCRATCH_RE = re.compile(r"^dispatch-outcome.*\.md$")


def checkpoint(worktree: Path, label: str = "") -> dict:
    """Commit uncommitted leftovers in the session worktree as a
    checkpoint commit. {"committed", "files", "sha", "skipped"|"error"}."""
    if not worktree or not Path(worktree).is_dir():
        return {"committed": False, "skipped": "no worktree"}
    dirty = dirty_count(worktree)
    if not dirty:
        return {"committed": False}
    r = sh(["git", "-C", str(worktree), "add", "-A"], timeout=60)
    if r.returncode != 0:
        return {"committed": False, "error":
                f"add: {(r.stderr or r.stdout).strip()[:160]}"}
    msg = (f"dispatch checkpoint: {dirty} leftover file(s) at session end"
           + (f" [{label}]" if label else ""))
    r = sh(["git", "-C", str(worktree), "commit", "-q", "-m", msg],
           timeout=60)
    if r.returncode != 0:
        return {"committed": False, "error":
                f"commit: {(r.stderr or r.stdout).strip()[:160]}"}
    return {"committed": True, "files": dirty,
            "sha": _rev_parse(Path(worktree), "HEAD")}


def push_branch(repo: Path, branch: str) -> dict:
    """Push the session branch to origin. {"pushed": bool, "error"?}."""
    r = sh(["git", "-C", str(repo), "push", "-q", "-u", "origin", branch],
           timeout=90)
    if r.returncode == 0:
        return {"pushed": True}
    return {"pushed": False,
            "error": (r.stderr or r.stdout).strip()[:200]}


def goals_gate(card: dict, worktree: Path | None) -> dict:
    """expected_goals executor for the merge precondition.

    {"ran", "ok", "results", "bad", "errors"}. A declared-but-unverifiable
    goal set (parse errors, missing executor, gone worktree) blocks the
    merge — the plan gate rejects prose, so a bad goal here means a
    hand-edited card a human should look at."""
    declared = bool(card.get("expected_goals"))
    if goallib is None:
        return {"ran": False, "ok": not declared,
                "errors": ["goals executor unavailable on this host"]
                if declared else []}
    goals, errors = goallib.validate_goals(card)
    if errors:
        return {"ran": False, "ok": False, "errors": errors}
    if not goals:
        return {"ran": False, "ok": True, "results": []}
    if not worktree or not Path(worktree).is_dir():
        return {"ran": False, "ok": False,
                "errors": [f"{len(goals)} goal(s) declared but the "
                           "worktree is gone — cannot verify"]}
    results = goallib.run_goals(goals, worktree)
    bad = [r for r in results if r["ok"] is not True]
    return {"ran": True, "ok": not bad, "results": results,
            "bad": [r["id"] for r in bad]}


def _resolve_side(wt: Path, path: str, side: str) -> bool:
    """checkout --ours/--theirs + stage; `git rm` when the side deleted
    the file."""
    if sh(["git", "-C", str(wt), "checkout", f"--{side}", "--", path],
          timeout=30).returncode == 0:
        return sh(["git", "-C", str(wt), "add", "--", path],
                  timeout=30).returncode == 0
    return sh(["git", "-C", str(wt), "rm", "-qf", "--", path],
              timeout=30).returncode == 0


def _merge_in(wt: Path, ref: str) -> tuple:
    """merge --no-ff ref inside wt -> (ok, unresolved_conflict_paths, err).

    Generated paths resolve --ours (default branch = served state, the
    safe-pull upstream-wins convention); dispatch-outcome*.md resolves
    --theirs (session scratch). Any other conflict aborts. A merge that
    fails without conflicted paths (e.g. missing git identity) surfaces
    as err, not an empty conflict list."""
    r = sh(["git", "-C", str(wt), "merge", "--no-ff", "--no-edit", ref],
           timeout=90)
    if r.returncode == 0:
        return True, [], ""
    conflicted = sh(["git", "-C", str(wt), "diff", "--name-only",
                     "--diff-filter=U"]).stdout.split()
    if not conflicted:
        # merge died before conflict stage (missing ident, bad ref, ...)
        err = (r.stderr or r.stdout).strip()[:200] or "merge failed"
        sh(["git", "-C", str(wt), "merge", "--abort"], timeout=30)
        return False, [], err
    unresolved = []
    for p in conflicted:
        if SESSION_SCRATCH_RE.match(p):
            _resolve_side(wt, p, "theirs")
        elif GENERATED_RE.search(p):
            _resolve_side(wt, p, "ours")
        else:
            unresolved.append(p)
    if unresolved:
        sh(["git", "-C", str(wt), "merge", "--abort"], timeout=30)
        return False, unresolved, ""
    if sh(["git", "-C", str(wt), "commit", "--no-edit"],
          timeout=30).returncode == 0:
        return True, [], ""
    sh(["git", "-C", str(wt), "merge", "--abort"], timeout=30)
    return False, [], "commit after conflict resolution failed"


def close_out(card: dict) -> dict:
    """Dispatch close-out merge step. Consumed by close_out_notes().

    Result keys: merged, noop (silent skip — no commits produced),
    checkpoint, pushed/push_error, gate, conflicts, merged_sha,
    skipped|error, note, session."""
    out: dict = {"merged": False}
    s = session(card)
    out["session"] = s
    if not s.get("task_id") and not s.get("branch"):
        out.update(noop=True, skipped="not a dispatch session")
        return out
    if not s.get("repo_root"):
        out.update(skipped=f"no session repo for {s['task_id'] or '?'}")
        return out
    # 1. checkpoint — enforce the session-end commit sessions half-do
    wt = s["worktree"]
    cp = checkpoint(wt, s["task_id"])
    out["checkpoint"] = cp
    if cp.get("committed"):
        s["head"] = _rev_parse(wt, "HEAD") or s["head"]
    if not s.get("base_ref"):
        out.update(skipped="no origin default branch")
        return out
    repo, branch, base = s["repo_root"], s["branch"], s["default_branch"]
    # 2. push the branch always — strand-proof even if the merge bails
    if s.get("head"):
        out.update(push_branch(wt or repo, branch))
    # 3. nothing produced → silent no-op
    if not s.get("head"):
        out.update(noop=True, skipped="no session head")
        return out
    m = merge_state(repo, s["head"], s["base_ref"])
    if not m["checked"]:
        out.update(skipped=m["error"])
        return out
    if m["ancestor"]:
        if s["head"] == _rev_parse(repo, s["base_ref"]):
            # head == base tip: the session produced no commits — that is
            # NOT merged work; verify would stamp a false positive.
            out.update(noop=True,
                       skipped="session produced no commits")
            return out
        out.update(merged=True, noop=True,
                   note=f"{branch} already in {s['base_ref']}")
        return out
    # 4. expected_goals gate (merge precondition)
    gate = goals_gate(card, wt)
    out["gate"] = gate
    if not gate["ok"]:
        return out
    # 5. merge into origin/<default> in a throwaway detached worktree
    sh(["git", "-C", str(repo), "fetch", "-q", "origin", base], timeout=45)
    mwt = Path(tempfile.mkdtemp(prefix="dispatch-merge-"))
    try:
        r = sh(["git", "-C", str(repo), "worktree", "add", "--detach",
                str(mwt), s["base_ref"]], timeout=60)
        if r.returncode != 0:
            out["error"] = f"worktree add: {r.stderr.strip()[:200]}"
            return out
        mref = branch if _rev_parse(repo, f"refs/heads/{branch}") \
            else s["head"]
        ok, conflicts, merr = _merge_in(mwt, mref)
        if not ok:
            if merr:
                out["error"] = f"merge: {merr}"
            else:
                out["conflicts"] = conflicts
            return out
        out["merged_sha"] = _rev_parse(mwt, "HEAD")
        r = sh(["git", "-C", str(mwt), "push", "-q", "origin",
                f"HEAD:{base}"], timeout=60)
        if r.returncode != 0:
            # remote moved between fetch and push — resync once, retry
            sh(["git", "-C", str(repo), "fetch", "-q", "origin", base],
               timeout=45)
            sh(["git", "-C", str(mwt), "reset", "-q", "--hard",
                s["base_ref"]], timeout=30)
            ok, conflicts, merr = _merge_in(mwt, mref)
            if not ok:
                if merr:
                    out["error"] = f"merge: {merr}"
                else:
                    out["conflicts"] = conflicts or ["<post-push resync>"]
                return out
            out["merged_sha"] = _rev_parse(mwt, "HEAD")
            r = sh(["git", "-C", str(mwt), "push", "-q", "origin",
                    f"HEAD:{base}"], timeout=60)
            if r.returncode != 0:
                out["error"] = f"push: {(r.stderr or r.stdout).strip()[:200]}"
                return out
        out.update(merged=True,
                   note=f"auto-merged {out['merged_sha'][:8]} "
                        f"({branch}) → origin/{base}")
        return out
    finally:
        sh(["git", "-C", str(repo), "worktree", "remove", "--force",
            str(mwt)], timeout=30)
        sh(["git", "-C", str(repo), "worktree", "prune"], timeout=30)


def close_out_notes(res: dict) -> list:
    """Comms lines for a close_out() result — shared by kanban-dispatch
    (local cards) and runner-agent (remote cards)."""
    notes = []
    cp = res.get("checkpoint") or {}
    if cp.get("committed"):
        notes.append(f"session-end checkpoint {cp['sha'][:8]}: "
                     f"{cp['files']} leftover file(s) committed")
    elif cp.get("error"):
        notes.append(f"checkpoint failed: {cp['error']}")
    if res.get("push_error"):
        notes.append(f"branch push failed: {res['push_error']}")
    elif res.get("pushed") and (res.get("session") or {}).get("branch"):
        notes.append(f"pushed {res['session']['branch']} to origin")
    if res.get("noop"):
        return notes  # no commits to merge — silent per spec
    gate = res.get("gate") or {}
    if not res.get("merged") and gate and not gate["ok"]:
        bad = gate.get("bad") or gate.get("errors") or ["?"]
        notes.append("auto-merge held — expected_goals not met: "
                     + "; ".join(str(b)[:80] for b in bad[:4]))
        return notes
    if res.get("conflicts"):
        notes.append("auto-merge conflicts: "
                     + ", ".join(res["conflicts"][:8])
                     + " — card stays in review for manual resolution")
        return notes
    if res.get("merged"):
        notes.append(res.get("note") or "auto-merged")
    elif res.get("error") or res.get("skipped"):
        why = res.get("error") or res.get("skipped")
        notes.append(f"auto-merge not done: {why} — close will block "
                     "until merged")
    return notes


def try_merge(card: dict) -> dict:
    """Back-compat shim — close_out() subsumes the old best-effort merge."""
    return close_out(card)
