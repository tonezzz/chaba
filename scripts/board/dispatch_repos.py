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
import subprocess
import tempfile
from pathlib import Path

# name -> (path, default_branch). Fallback whitelist — canonical table is
# $DISPATCH_DIR/repos.conf (repo copy: scripts/devin/dispatch-repos.conf).
BUILTIN_REPOS = {
    "chaba": ("~/CascadeProjects/chaba", "master"),
    "ada-pi": ("~/CascadeProjects/ada-pi", "main"),
    "sunsynk-card": ("~/CascadeProjects/sunsynk-power-flow-card", "main"),
    "mddb-fork": ("~/CascadeProjects/mddb-fork", "main"),
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


def _merge_in(wt: Path, ref: str) -> bool:
    """Merge ref inside wt. True on a clean merge; auto-resolves when the
    only conflict is the per-session dispatch-outcome.md scratch file."""
    r = sh(["git", "-C", str(wt), "merge", "--no-edit", ref], timeout=90)
    if r.returncode == 0:
        return True
    conflicted = sh(["git", "-C", str(wt), "diff", "--name-only",
                     "--diff-filter=U"]).stdout.split()
    if conflicted == ["dispatch-outcome.md"]:
        sh(["git", "-C", str(wt), "checkout", "--theirs",
            "dispatch-outcome.md"])
        sh(["git", "-C", str(wt), "add", "dispatch-outcome.md"])
        return sh(["git", "-C", str(wt), "commit", "--no-edit"],
                  timeout=30).returncode == 0
    sh(["git", "-C", str(wt), "merge", "--abort"], timeout=30)
    return False


def try_merge(card: dict) -> dict:
    """Best-effort merge of the session branch into origin/<default>.

    Runs in a throwaway detached worktree so the live checkouts are never
    touched. {"merged": bool, "skipped"|"error": str, "note": str}."""
    s = session(card)
    if not s.get("repo_root") or not s.get("branch"):
        return {"merged": False, "skipped": "no session branch"}
    if not s.get("base_ref"):
        return {"merged": False, "skipped": "no origin default branch"}
    dirty = dirty_count(s["worktree"]) if s["worktree"] else None
    if dirty:
        return {"merged": False,
                "skipped": f"worktree dirty ({dirty} file(s)) — commit first"}
    repo, branch, base = s["repo_root"], s["branch"], s["default_branch"]
    m = merge_state(repo, s["head"], s["base_ref"])
    if not m["checked"]:
        return {"merged": False, "skipped": m["error"]}
    if m["ancestor"]:
        return {"merged": True,
                "note": f"{branch} already merged into {s['base_ref']}"}
    sh(["git", "-C", str(repo), "fetch", "-q", "origin", base], timeout=45)
    wt = Path(tempfile.mkdtemp(prefix="dispatch-merge-"))
    try:
        r = sh(["git", "-C", str(repo), "worktree", "add", "--detach",
                str(wt), s["base_ref"]], timeout=60)
        if r.returncode != 0:
            return {"merged": False,
                    "error": f"worktree add: {r.stderr.strip()[:200]}"}
        if not _merge_in(wt, branch):
            return {"merged": False,
                    "error": f"conflicts merging {branch} — left unmerged"}
        r = sh(["git", "-C", str(wt), "push", "-q", "origin",
                f"HEAD:{base}"], timeout=60)
        if r.returncode != 0:
            # remote moved between fetch and push — resync once, retry
            sh(["git", "-C", str(repo), "fetch", "-q", "origin", base],
               timeout=45)
            if not _merge_in(wt, s["base_ref"]):
                return {"merged": False,
                        "error": "post-push resync conflict — left unmerged"}
            r = sh(["git", "-C", str(wt), "push", "-q", "origin",
                    f"HEAD:{base}"], timeout=60)
            if r.returncode != 0:
                return {"merged": False,
                        "error": f"push: {(r.stderr or r.stdout).strip()[:200]}"}
        return {"merged": True,
                "note": f"auto-merged {branch} → origin/{base}"}
    finally:
        sh(["git", "-C", str(repo), "worktree", "remove", "--force",
            str(wt)], timeout=30)
        sh(["git", "-C", str(repo), "worktree", "prune"], timeout=30)
