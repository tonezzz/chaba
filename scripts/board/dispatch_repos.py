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
                                     unmerged commit counts), claim
                                     order, close-out worktree GC
  scripts/board/runner-agent.py    — close_out merge + worktree GC at
                                     card close + the same claim order
                                     via dr_module()
"""
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
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
    "ada-voice": ("~/CascadeProjects/ada-voice", "main"),
    # legacy alias for cards/dispatches still naming the pre-rename repo
    # (kanban ada-pi-rename-ada-voice, 2026-10-14) — retire once no card
    # carries action.repo: ada-pi
    "ada-pi": ("~/CascadeProjects/ada-voice", "main"),
    "sunsynk-card": ("~/CascadeProjects/sunsynk-power-flow-card", "main"),
    "mddb-fork": ("~/CascadeProjects/mddb-fork", "main"),
    "gods-eye-view": ("~/gods-eye-view", "main"),
}

# repo name -> canonical name, for surfaces that name capabilities
# (the push:<repo> runner label) — aliased repos share one credential.
REPO_ALIASES = {"ada-pi": "ada-voice"}


def canon_repo(name: str) -> str:
    return REPO_ALIASES.get(name or "", name or "")


DEFAULT_BOARD_API = "https://idc03.taila0626a.ts.net:10000"


def board_api_base() -> str:
    """Where relay/patch posts go — BOARD_API (kanban-dispatch,
    merge-sweep) or RUNNER_API (runner-agent); the tailnet route is the
    same default both use."""
    return (os.environ.get("BOARD_API") or os.environ.get("RUNNER_API")
            or DEFAULT_BOARD_API).rstrip("/")


def dispatch_dir() -> Path:
    return Path(os.environ.get(
        "DISPATCH_DIR", str(Path.home() / ".local/share/devin-dispatch")))


# --- lane -> cheapest-executor routing (jev-pilot Phase 2, 2026-10-25) --
# Canonical home for the lane tables + classifier so a queued card's lane
# resolves to DISPATCH_MODEL identically whichever claimer wins the race —
# kanban-dispatch (served host) or runner-agent (a remote host). Model
# lanes map to `devin --model` ids; codemod -> script executor, manual ->
# Tony's hands (never dispatched). jev-model-chain-probe found this gap:
# the wiring originally lived only in kanban-dispatch, so cards claimed
# by runner-agent always launched on the devin default model.
LANE_MODELS = {
    "free_lane": "litellm/gemini-3.5-flash-lite",
    "paid_frontier": "litellm/or-claude-fable-5.1",
}
LANE_EXECUTORS = {"codemod": "script", "manual": None}
JEVOS = os.environ.get("JEVOS_URL", "http://127.0.0.1:8017")

# Keyword lane classifier — deterministic, validated on the lane corpus
# (evals/results/jev/). Keyword hits run first; jevos is the fallback.
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
    """Cheapest lane for this card: keyword-first, jevos gated fallback."""
    text = (card.get("title", "") + " " +
            (card.get("brief") or card.get("spec") or "")).lower()
    if any(k in text for k in LANE_KW["manual"]):
        return "manual"
    if re.search(LANE_COMPARE, text):
        return "paid_frontier"
    for lane, kws in (("paid_frontier", LANE_KW["paid_frontier"]),
                      ("codemod", LANE_KW["codemod"]),
                      ("devin", LANE_KW["devin"]),
                      ("free_lane", LANE_KW["free_lane"])):
        if any(k in text for k in kws):
            return lane
    state = {"card": card.get("id"), "title": card.get("title", ""),
             "brief": (card.get("brief") or card.get("spec") or "")[:250]}
    q = {"lane": {"type": "choice",
                  "instructions": "Choose the cheapest lane that can complete this card's work class.",
                  "criteria": {"codemod": "deterministic pattern change, known transform, no judgment",
                               "free_lane": "single-step chore, verification exists, no long horizon",
                               "paid_frontier": "contained code task needing strong reasoning",
                               "devin": "multi-step, remote diagnosis, ambiguous, or no-gate work",
                               "manual": "needs Tony's hands (hardware, accounts, physical)"}}}
    payload = {"model": "jev-latest", "state": state, "questions": q}
    try:
        req = urllib.request.Request(
            JEVOS + "/v1/systemone",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        ans = (r.get("answers") or {}).get("lane") or {}
        lane = ans.get("choice")
        conf = float(ans.get("confidence") or 0.0)
        if conf < float(os.environ.get("JEV_LANE_MIN_CONF", "0.5")):
            return "devin"  # safe multi-step default when unsure
        return lane if lane in LANE_MODELS or lane in LANE_EXECUTORS else "devin"
    except Exception:
        return "devin"  # jevos down -> safe default, not None


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
    base_tip = _rev_parse(repo_root, base_ref)
    if not base_tip:
        return {"checked": False, "error": f"no {base_ref} ref in {repo_root}"}
    r = sh(["git", "-C", str(repo_root), "merge-base", "--is-ancestor",
            head, base_ref])
    if r.returncode == 0:
        # head is an ancestor of base — but so is the tip of an EMPTY
        # session branch (the task died before committing; its head is
        # just an old base commit). Real merged work reaches base through
        # the --no-ff merge's second parent, i.e. it is NOT on base's
        # first-parent chain; an old base commit IS. Flag that so the
        # caller can refuse to stamp "verified" on work that never
        # happened (idc01 hollow-dispatch incident 2026-10-09).
        fp = sh(["git", "-C", str(repo_root), "rev-list", "--first-parent",
                 "--max-count=5000", base_ref])
        on_fp = head in (fp.stdout or "").splitlines()
        return {"checked": True, "ancestor": True, "unmerged": 0,
                "on_first_parent": on_fp, "empty_session": on_fp and head != base_tip}
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
        try:
            shad = shadow_paths(s["repo_root"], s["base_ref"], s["head"],
                                cwd=s["worktree"] or s["repo_root"])
            if shad:
                note += ("; gitignored-dir shadow path(s): "
                         + ", ".join(shad[:5]))
        except Exception:
            pass
        return {"allowed": False,
                "summary": (f"unmerged commits remain on {s['branch']} "
                            f"({m['unmerged']} not in {s['base_ref']})"),
                "note": note}
    return {"allowed": True,
            "summary": "",
            "note": f"merge guard: {s['branch']} merged into "
                    f"{s['base_ref']}{dirty_txt}"}


# -------------------------------------------------------- claim ordering
#
# Priority-aware drain order for queued cards (card
# dispatch-priority-order). Shared by BOTH claim paths —
# kanban-dispatch's local drain and runner-agent's remote claim — so a
# card's position doesn't depend on which host picks it up:
#
#   1. starvation tier — a card whose `updated` is >= starve_hours old
#      claims ahead of every fresh card regardless of priority
#      (priority is a bias, not a ban; starve_hours <= 0 disables)
#   2. priority rank — high > medium > absent/unknown > low (the map
#      render-board.py uses for the board's "next-up" column order)
#   3. `updated` oldest-first
#
# Pure ordering — no preemption and no eligibility relaxation: labels,
# caps, blocked_by, autonomy tier and the load gate still run per card.

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 3}  # absent/unknown -> 2
CARD_TZ = timezone(timedelta(hours=7))  # card `updated` stamps this zone


def card_updated_ts(card: dict) -> float:
    """epoch of card['updated'] ('YYYY-MM-DD[ HH:MM]' in CARD_TZ); 0 when
    absent/unparseable — sorts oldest inside its rank rather than
    sinking forever."""
    s = str(card.get("updated") or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(
                tzinfo=CARD_TZ).timestamp()
        except ValueError:
            pass
    return 0.0


def claim_sort_key(card: dict, starve_hours: float = 12.0,
                   now_ts: float | None = None) -> tuple:
    """(starved?, priority rank, updated) — smaller claims first. A card
    with no readable `updated` can't prove its age, so it never takes
    the starvation tier (it still wins its own rank's oldest-first)."""
    upd = card_updated_ts(card)
    starved = (starve_hours > 0 and upd > 0 and
               (time.time() if now_ts is None else now_ts) - upd
               >= starve_hours * 3600)
    rank = PRIORITY_RANK.get(
        str(card.get("priority") or "").strip().lower(), 2)
    return (0 if starved else 1, rank, upd)


def sort_claimable(cards: list, starve_hours: float = 12.0,
                   now_ts: float | None = None) -> list:
    """Cards in claim-drain order. Stable — equal keys keep input order
    (API order for runner-agent, filename order for kanban-dispatch)."""
    now = time.time() if now_ts is None else now_ts
    return sorted(cards,
                  key=lambda c: claim_sort_key(c, starve_hours, now))


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


# ----------------------------------------------------- push credential
#
# Card runner-push-cred-gap (the 2026-10-14 ADA-0673 incident): a runner
# whose repo creds are fetch-only or scoped to a different repo finishes
# a dispatch, commits the checkpoint, and pushes nothing — the branch
# strands on the remote host while the card still read done+verified.
# The URL shape cannot detect this (macbook's ada-voice clone had a
# git@ remote AND core.sshCommand — the deploy key was chaba-only), so
# the capability is probed for real: `git push --dry-run` exercises the
# auth path without touching a ref.
#
# Two mechanisms share it:
#   * claim guard — runner-agent/kanban-dispatch only claim dispatch
#     cards for repos the host can push (declared `push:<repo>` label
#     fast-path, live probe otherwise; RUNNER_/KANBAN_PUSH_GUARD=0 off)
#   * bundle relay — when a push still fails at close-out, the session
#     head is exported as a `git bundle` (shas preserved, unlike
#     format-patch) and POSTed to board-api /patch-relay; merge-sweep
#     fetches it from $DISPATCH_DIR/patch-inbox like any other head.

PUSH_PROBE_REF = "refs/heads/__runner-push-probe"


def push_probe(repo_name: str) -> dict:
    """{"pushable": bool, "detail"} — dry-run push against this host's
    checkout of repo_name. False also when the checkout is absent —
    such a host can't run the dispatch at all."""
    ent = repos().get(repo_name) or repos().get(canon_repo(repo_name))
    if not ent:
        return {"pushable": False, "detail": f"no repo '{repo_name}'"}
    p = Path(ent["path"])
    if not (p / ".git").exists():
        return {"pushable": False, "detail": f"no checkout at {p}"}
    r = sh(["git", "-C", str(p), "push", "--dry-run", "origin",
            f"HEAD:{PUSH_PROBE_REF}"], timeout=45)
    if r.returncode == 0:
        return {"pushable": True, "detail": "dry-run push ok"}
    return {"pushable": False,
            "detail": (r.stderr or r.stdout).strip()[:200]
            or "push --dry-run failed"}


def branch_on_origin(repo: Path, branch: str, head: str) -> bool:
    """ls-remote truth: origin's refs/heads/<branch> == head."""
    if not branch or not head:
        return False
    r = sh(["git", "-C", str(repo), "ls-remote", "origin",
            f"refs/heads/{branch}"], timeout=45)
    if r.returncode != 0:
        return False
    got = (r.stdout.split() or [""])[0]
    return bool(got) and got == head


def head_on_origin(repo: Path, head: str, base_ref: str,
                   branch: str = "") -> tuple:
    """(bool, how) — is the session head provably on origin? Either an
    ancestor of the fetched origin/<base> ref (work merged/landed), or
    the session branch ref itself resolves to head. 'verified' may only
    be stamped when this holds — a head that lives only on the runner
    is stranded, not delivered (runner-push-cred-gap)."""
    if not head:
        return False, "no head"
    if base_ref and sh(["git", "-C", str(repo), "merge-base",
                        "--is-ancestor", head, base_ref],
                       timeout=30).returncode == 0:
        return True, f"ancestor of {base_ref}"
    if branch_on_origin(repo, branch, head):
        return True, f"origin refs/heads/{branch}"
    return False, f"not in {base_ref or 'origin/<base>'} and " \
                  f"{('refs/heads/' + branch) if branch else 'no branch'} " \
                  "not at head on origin"


RELAY_MAX_BYTES = int(os.environ.get(
    "PATCH_RELAY_MAX_BYTES", str(8 * 1024 * 1024)))


def export_bundle(repo: Path, base_ref: str | None, head: str,
                  ref: str = "",
                  out_dir: Path | None = None) -> dict:
    """git bundle of base_ref..head (whole history when base_ref is
    unresolvable) -> {"path", "bytes", "head"} or {"error"}.
    A bundle preserves commit shas — the receiver fetches it like the
    runner's own remote and every downstream check (ancestry, verify
    gate, GC) works unchanged. `ref` names the positive rev recorded in
    the bundle (HEAD in a session worktree, refs/heads/<branch> when
    only the repo survives) — a bare sha records no ref and git refuses
    the bundle; when nothing resolves to head a transient ref is pinned
    for the duration."""
    if not head:
        return {"error": "no head"}
    repo = Path(repo)
    tmpref = ""
    if not ref or _rev_parse(repo, ref) != head:
        tmpref = f"refs/dispatch-relay/{head[:12]}"
        if sh(["git", "-C", str(repo), "update-ref", tmpref, head],
              timeout=30).returncode != 0:
            return {"error": "cannot pin session head to a ref"}
        ref = tmpref
    try:
        d = out_dir or Path(tempfile.mkdtemp(prefix="dispatch-bundle-"))
        f = d / f"dispatch-{head[:10]}.bundle"
        r = None
        if base_ref and _rev_parse(repo, base_ref):
            r = sh(["git", "-C", str(repo), "bundle", "create", str(f),
                    ref, f"^{base_ref}"], timeout=120)
        if r is None or r.returncode != 0:
            r = sh(["git", "-C", str(repo), "bundle", "create", str(f),
                    ref], timeout=300)
        if r.returncode != 0:
            return {"error": (r.stderr or r.stdout).strip()[:200]}
        size = f.stat().st_size
        if size > RELAY_MAX_BYTES:
            try:
                f.unlink()
            except OSError:
                pass
            return {"error": f"bundle too large ({size}B > "
                             f"{RELAY_MAX_BYTES}B)"}
        return {"path": f, "bytes": size, "head": head}
    finally:
        if tmpref:
            sh(["git", "-C", str(repo), "update-ref", "-d", tmpref],
               timeout=30)


def relay_session(card: dict, s: dict, api_base: str = "") -> dict:
    """Close-out safety net: the push failed, so export the session head
    as a bundle and POST it to board-api /patch-relay — dell-side
    merge-sweep lands it. {relayed, file|bytes|error}."""
    head = s.get("head") or ""
    repo = s.get("repo_root")
    if not repo or not head:
        return {"relayed": False, "error": "no repo/head to relay"}
    # the ref recorded in the bundle: HEAD inside the session worktree,
    # the branch ref when only the repo survives
    wt = s.get("worktree")
    b = export_bundle(Path(wt or repo), s.get("base_ref"), head,
                      ref=("HEAD" if wt else
                           f"refs/heads/{s.get('branch') or ''}"))
    if b.get("error"):
        return {"relayed": False, "error": f"bundle: {b['error']}"}
    tid = s.get("task_id") or ""
    exit_code = None
    try:
        ecp = dispatch_dir() / "tasks" / tid / "exit_code"
        exit_code = ecp.read_text().strip() if ecp.is_file() else None
    except Exception:
        pass
    body = {"id": card.get("id"), "host": os.uname().nodename,
            "repo": s.get("repo_name"), "branch": s.get("branch"),
            "base": s.get("default_branch"), "head": head,
            "task_id": tid, "exit_code": exit_code,
            "bundle": base64.b64encode(b["path"].read_bytes()).decode()}
    try:
        req = urllib.request.Request(
            (api_base or board_api_base()) + "/patch-relay",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            resp = json.loads(r.read())
    except Exception as e:
        return {"relayed": False,
                "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            b["path"].unlink()
        except (OSError, KeyError):
            pass
    if resp.get("error"):
        return {"relayed": False, "error": str(resp["error"])[:200]}
    return {"relayed": True, "file": resp.get("file"),
            "bytes": b["bytes"]}


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


# ---------------------------------------------------------- test gate
#
# Per-repo fast test gate (card ci-test-gate): after a clean merge in the
# throwaway worktree the repo's test command runs there BEFORE the result
# pushes to origin — a red suite holds the merge exactly like a conflict
# (close_out returns test_failures; kanban-dispatch requeues with
# action.last_failure carrying the failing test names). Fail-open on
# missing pytest (same convention as the merge guard); a suite timeout
# counts as a failure — the alternative is merging a tree the suite can't
# even finish on. KANBAN_TESTGATE=0 disables the gate entirely.
#
# Interpreter resolution (card dispatch-test-gate-venv — the 2026-10-13
# line-multihome incident: ada-voice's suite needs google.genai from its
# .venv, system python3 lacks it, the gate went red 42/42-green-under-
# venv and held a good merge). A command that starts with `python`/
# `python3` gets that token replaced with the resolved interpreter —
# the first candidate that can actually `import pytest`:
#
#   1. REPO_TESTS[repo]["python"] — explicit pin (escape hatch)
#   2. <tree under test>/{.venv,venv}/bin/python[3]
#   3. <canonical checkout>/{.venv,venv}/bin/python[3] — the linked
#      worktree's git-common parent; dispatch worktrees carry no .venv
#      of their own, this is where ada-voice's lives
#   4. <repos.conf path>/{.venv,venv}/bin/python[3]
#   5. "" — command keeps system python3
#
# The probe is `import pytest`, not mere existence: chaba's venv/ has
# no pytest and must NOT win over a pytest-capable system python, else
# the gate silently fail-opens there. Non-python commands (make, npm)
# are left untouched.
DEFAULT_TEST_CMD = "python3 -m pytest tests -x -q"
DEFAULT_TEST_TIMEOUT = 240
VENV_DIRS = (".venv", "venv")  # checkout venv conventions in use
REPO_TESTS = {
    "chaba": {"command": DEFAULT_TEST_CMD, "timeout": 240},
    "ada-voice": {"command": "python3 -m pytest tests -k 'not slow' -x -q",
               "timeout": 300},
    # legacy alias — same suite for cards still saying repo: ada-pi
    "ada-pi": {"command": "python3 -m pytest tests -k 'not slow' -x -q",
               "timeout": 300},
    # Unlisted repos get the default command — but only when the merged
    # tree actually carries a tests/ dir (run_test_gate skips otherwise),
    # so "others: none" holds in practice. {"command": None} opts a repo
    # out explicitly; {"python": <path>} pins the interpreter.
}

# pytest failure names: `FAILED tests/x.py::test_y - ...` (-r summary) or
# the `____ test_y ____` traceback headers a plain -x -q run prints.
_FAILED_SUMMARY_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.M)
_FAILED_HEADER_RE = re.compile(r"^_{3,}\s+(.+?)\s+_{3,}\s*$", re.M)


def test_gate_config(repo_name: str) -> dict:
    """Resolved {command, timeout, python?} for a repo's merge test gate;
    {} when the repo is opted out (command: None)."""
    ent = REPO_TESTS.get(repo_name or "")
    if ent is None:
        ent = {"command": DEFAULT_TEST_CMD,
               "timeout": DEFAULT_TEST_TIMEOUT}
    if not ent.get("command"):
        return {}
    cfg = {"command": ent["command"],
           "timeout": int(ent.get("timeout") or DEFAULT_TEST_TIMEOUT)}
    if ent.get("python"):
        cfg["python"] = ent["python"]
    return cfg


def _venv_python_candidates(wt: Path, repo_name: str):
    """Checkout venv pythons that could own the repo's test deps,
    best-first: the tree under test, the canonical checkout (a linked
    worktree's git-common parent — dispatch worktrees have no .venv of
    their own), then the repos.conf-declared path."""
    dirs: list[Path] = []
    for d in (wt, _repo_root(Path(wt)),
              (repos().get(repo_name or "") or {}).get("path")):
        if d:
            d = Path(d)
            if d not in dirs:
                dirs.append(d)
    for d in dirs:
        for vd in VENV_DIRS:
            for bn in ("python", "python3"):
                p = d / vd / "bin" / bn
                if p.is_file() and os.access(p, os.X_OK):
                    yield p


def _has_pytest(py: Path) -> bool:
    return sh([str(py), "-c", "import pytest"],
              timeout=20).returncode == 0


def gate_python(wt: Path, repo_name: str, cfg: dict) -> str:
    """Interpreter for a `python3 -m pytest` test command; "" keeps the
    system python3 already in the command. An explicit REPO_TESTS
    "python" pin wins when it exists; otherwise the first checkout venv
    whose python can import pytest."""
    pin = cfg.get("python")
    if pin:
        p = Path(pin).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    for p in _venv_python_candidates(wt, repo_name):
        if _has_pytest(p):
            return str(p)
    return ""


_PY_LEAD_RE = re.compile(r"^\s*python[\d.]*(?=\s)")  # python, python3, python3.11


def _resolve_gate_cmd(cmd: str, wt: Path, repo_name: str,
                      cfg: dict) -> tuple:
    """Swap the command's leading python token for the resolved
    interpreter. (resolved_cmd, python) — python is "" when the command
    isn't python-led or no venv qualified."""
    if not _PY_LEAD_RE.match(cmd):
        return cmd, ""
    py = gate_python(wt, repo_name, cfg)
    if not py:
        return cmd, ""
    return _PY_LEAD_RE.sub(shlex.quote(py), cmd, count=1), py


def run_test_gate(wt: Path, repo_name: str) -> dict:
    """Run the repo's fast test step inside the merged worktree.

    {ran, ok, failed?, skipped?, command?, elapsed?, error?} —
    ok=False only for red tests / suite timeout; missing pytest or a
    tree without tests/ skips fail-open (merge_guard convention)."""
    if os.environ.get("KANBAN_TESTGATE", "1") == "0":
        return {"ran": False, "ok": True, "skipped": "KANBAN_TESTGATE=0"}
    cfg = test_gate_config(repo_name)
    cmd = cfg.get("command")
    if not cmd or not wt or not Path(wt).is_dir():
        return {"ran": False, "ok": True, "skipped": "no test config"}
    if not (Path(wt) / "tests").is_dir():
        return {"ran": False, "ok": True,
                "skipped": "no tests/ dir in merged tree"}
    cmd, py = _resolve_gate_cmd(cmd, wt, repo_name, cfg)
    interp = py or ("python3" if _PY_LEAD_RE.match(cmd) else None)
    timeout = int(cfg["timeout"])
    t0 = time.time()
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=str(wt),
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ran": True, "ok": False, "command": cmd, "python": interp,
                "failed": [f"suite timeout ({timeout}s)"],
                "error": f"test gate timed out after {timeout}s"}
    out = f"{r.stdout or ''}\n{r.stderr or ''}"
    if r.returncode != 0 and re.search(
            r"No module named .?pytest|command not found", out):
        return {"ran": False, "ok": True, "command": cmd, "python": interp,
                "skipped": "pytest unavailable — fail-open"}
    if r.returncode == 5:
        return {"ran": False, "ok": True, "command": cmd, "python": interp,
                "skipped": "no tests collected"}
    if r.returncode == 0:
        return {"ran": True, "ok": True, "command": cmd, "python": interp,
                "elapsed": round(time.time() - t0, 1)}
    failed = _FAILED_SUMMARY_RE.findall(out) or _FAILED_HEADER_RE.findall(out)
    tail = [ln for ln in out.splitlines() if ln.strip()][-2:]
    return {"ran": True, "ok": False, "command": cmd, "python": interp,
            "failed": failed[:8] or tail or ["pytest exited nonzero"]}


def _gate_failfast_strip(cmd: str) -> str:
    """The gate command without -x/--exitfast so a red suite enumerates
    EVERY failure, not just the first. -rf is appended when the command
    carries no -r summary flag — without it pytest may not print the
    FAILED nodeid lines the parser reads."""
    parts = [p for p in shlex.split(cmd)
             if p not in ("-x", "--exitfirst")]
    if not any(re.fullmatch(r"-r[A-Za-z]*", p) for p in parts):
        parts.append("-rf")
    return " ".join(shlex.quote(p) for p in parts)


def _gate_failures(wt: Path, repo_name: str) -> tuple:
    """Complete failing-nodeid set under the repo's gate command
    (failfast stripped). (set, meta) — set() only when the run actually
    proved emptiness (suite green); None when it can't prove anything
    (timeout, pytest missing, infra) and the caller must keep the hold.
    """
    cfg = test_gate_config(repo_name)
    cmd = cfg.get("command")
    if not cmd:
        return None, {"skipped": "no test config"}
    if not _PY_LEAD_RE.match(cmd):
        # enumeration is pytest-shaped — a make/npm/custom gate gets no
        # baseline compare; the branch result stands
        return None, {"command": cmd, "skipped": "non-pytest gate"}
    cmd, py = _resolve_gate_cmd(cmd, wt, repo_name, cfg)
    cmd = _gate_failfast_strip(cmd)
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=str(wt),
                           capture_output=True, text=True,
                           timeout=int(cfg["timeout"]))
    except subprocess.TimeoutExpired:
        return None, {"command": cmd,
                      "error": f"enumeration timed out after "
                               f"{cfg['timeout']}s"}
    out = f"{r.stdout or ''}\n{r.stderr or ''}"
    if r.returncode != 0 and re.search(
            r"No module named .?pytest|command not found", out):
        return None, {"command": cmd, "skipped": "pytest unavailable"}
    return set(_FAILED_SUMMARY_RE.findall(out)), {
        "command": cmd, "python": py or "python3", "rc": r.returncode}


def _baseline_failures(base_wt: Path, repo_name: str,
                       nodeids: list) -> "set | None":
    """Which of the branch's failing `nodeids` also fail on the
    baseline tree — the same focused failures run against base. A
    nodeid pytest can't collect there (new test file, renamed case) is
    absent from the result and therefore counts as NEW. None = can't
    prove (timeout / pytest missing) — the hold must stand."""
    if not nodeids:
        return set()
    cfg = test_gate_config(repo_name)
    if not cfg.get("command") or \
            not _PY_LEAD_RE.match(cfg["command"]):
        return None
    _, py = _resolve_gate_cmd(cfg["command"], base_wt, repo_name, cfg)
    interp = py or "python3"
    # nodeids run ONE PER pytest call: a single missing pathspec (a
    # branch-only test file) makes pytest exit 4 and run nothing,
    # which would misclassify every pre-existing failure as new.
    failed = set()
    deadline = time.time() + int(cfg["timeout"])
    for nodeid in nodeids[:48]:      # beyond this the suite is red
        if time.time() > deadline:   # enough that no compare is safe
            return None
        cmd = " ".join([shlex.quote(interp), "-m", "pytest", "-q",
                        "-rf", "--tb=no", shlex.quote(nodeid)])
        try:
            r = subprocess.run(["bash", "-c", cmd], cwd=str(base_wt),
                               capture_output=True, text=True,
                               timeout=120)
        except subprocess.TimeoutExpired:
            return None
        out = f"{r.stdout or ''}\n{r.stderr or ''}"
        if r.returncode != 0 and re.search(
                r"No module named .?pytest|command not found", out):
            return None
        if nodeid in _FAILED_SUMMARY_RE.findall(out):
            failed.add(nodeid)
    return failed


def baseline_aware_test_gate(wt: Path, repo_name: str, base_ref: str) -> dict:
    """Do not blame a change for failures already present on base —
    and never let a pre-existing failure hide a new one.

    The -x gate reports only the FIRST failure, so a red branch run is
    re-enumerated without failfast (a new failure sorting after a
    pre-existing one would otherwise ride in unseen — the 2026-10-26
    OpenCode README-marker incident class). The same focused nodeids
    then run on a detached baseline worktree: failures identical to
    base are classified pre-existing; anything absent on base still
    holds the merge. Any comparison step that can't prove its set
    leaves the hold in place — suppression needs evidence, not doubt.
    """
    branch = run_test_gate(wt, repo_name)
    if branch.get("ok") or not branch.get("ran") or not base_ref:
        return branch
    enum, meta = _gate_failures(wt, repo_name)
    if not enum:
        return branch
    root = _repo_root(Path(wt))
    if root is None:
        return branch
    base_wt = Path(tempfile.mkdtemp(prefix="dispatch-baseline-"))
    try:
        r = sh(["git", "-C", str(root), "worktree", "add", "--detach",
                str(base_wt), base_ref], timeout=120)
        if r.returncode:
            return branch
        base_failed = _baseline_failures(base_wt, repo_name,
                                         sorted(enum))
    finally:
        sh(["git", "-C", str(root), "worktree", "remove", "--force",
            str(base_wt)], timeout=60)
        try:
            base_wt.rmdir()
        except OSError:
            pass
    if base_failed is None:
        return branch
    new = sorted(enum - base_failed)
    out = dict(branch)
    out.update(command=meta.get("command") or branch.get("command"),
               baseline_failed=sorted(enum & base_failed))
    if new:
        out["failed"] = new[:8]
        out["error"] = (f"{len(new)} new failure(s) vs base "
                        f"({len(enum & base_failed)} pre-existing)")
    else:
        out.update(ok=True,
                   skipped="pre-existing baseline test failure")
    return out


# ---------------------------------------------------------- shadow guard
#
# Pre-merge guard (card dispatch-gitignore-shadow-guard — the 2026-10-10
# .venv incident: a worktree `.venv` SYMLINK rode a merge into main while
# .gitignore only carried `.venv/`, a dir-only pattern that never matches
# a file/symlink of that name; deploy-ada.sh then replaced the production
# venv with a dangling link). Paths `head` adds vs `base` are flagged when:
#
#   (a) the entry is a symlink (mode 120000) — every added symlink gets a
#       human look; they routinely point outside the repo, or
#   (b) `git check-ignore --no-index` would ignore a DIR of the same name
#       (the matched pattern ends in `/`) while the blob itself is
#       trackable — i.e. the name is reserved for an ignored directory
#       and a checked-in file now sits where the runtime recreates it.
#
# check-ignore runs in `cwd`, the checkout whose ignore rules apply —
# the merged worktree on merge paths (the union .gitignore governs the
# result), the session worktree for pre-merge notes. Fail-open: any
# plumbing error yields [] rather than a phantom block.

def shadow_paths(repo: Path, base: str, head: str,
                 cwd: Path | None = None) -> list:
    """Annotated shadow-path list for `head`'s net additions vs `base`."""
    r = sh(["git", "-C", str(repo), "diff", "--raw", "-r",
            "--no-renames", "--diff-filter=A", "-z", base, head],
           timeout=60)
    if r.returncode != 0 or not r.stdout:
        return []
    # -z raw records: ":<srcmode> <dstmode> <sha> <sha> <status>\0<path>\0"
    fields = r.stdout.split("\0")
    entries = []  # (path, dstmode)
    i = 0
    while i + 1 < len(fields):
        meta, path = fields[i], fields[i + 1]
        i += 2
        parts = meta.lstrip(":").split()
        if len(parts) < 5:
            continue
        entries.append((path, parts[1]))
    if not entries:
        return []
    out = [f"{p} (symlink)" for p, m in entries if m == "120000"]
    # check-ignore is only needed for blobs/gitlinks — a `P/` probe on a
    # symlink is FATAL ("pathspec is beyond a symbolic link") and would
    # kill the whole --stdin batch.
    rest = [(p, m) for p, m in entries if m != "120000"]
    if not rest:
        return out
    probe = "".join(f"{p}\n{p}/\n" for p, _ in rest)
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd or repo), "check-ignore",
             "-v", "-n", "--no-index", "--stdin"],
            input=probe, capture_output=True, text=True, timeout=60)
        lines = (r.stdout or "").splitlines()
    except Exception:
        lines = []
    for idx, (path, mode) in enumerate(rest):
        fprobe = lines[2 * idx] if 2 * idx < len(lines) else "::"
        dprobe = lines[2 * idx + 1] if 2 * idx + 1 < len(lines) else "::"
        # verbose match shape: "<source>:<linenum>:<pattern>\t<path>";
        # "::\t<path>" for non-matches (-n keeps output aligned 1:1).
        pat = ""
        if not dprobe.startswith("::") and "\t" in dprobe:
            seg = dprobe.split("\t", 1)[0].split(":", 2)
            pat = seg[2] if len(seg) == 3 else ""
        if pat.endswith("/") and fprobe.startswith("::"):
            out.append(f"{path} (file shadows ignored dir "
                       f"— pattern '{pat}')")
    return out


def _merge_in(wt: Path, ref: str) -> tuple:
    """merge --no-ff ref inside wt -> (ok, unresolved_conflict_paths, err).

    Generated paths resolve --ours (default branch = served state, the
    safe-pull upstream-wins convention); dispatch-outcome*.md resolves
    --theirs (session scratch). Kanban cards never reach the conflict
    loop when the card-union merge driver is bound (incident 2026-10-23,
    card kanban-commit-reconcile-rebase-deadlocks-4d95a9): they union-
    merge inline via merge_cards, so a session's card writes and the
    live board's writes both survive. Any other conflict aborts. A merge
    that fails without conflicted paths (e.g. missing git identity)
    surfaces as err, not an empty conflict list."""
    cmd = ["git", "-C", str(wt)]
    driver = wt / "scripts/board/merge-card-yaml.py"
    if driver.exists():
        cmd += ["-c",
                f"merge.card-union.driver=python3 {driver} %O %A %B"]
    r = sh(cmd + ["merge", "--no-ff", "--no-edit", ref], timeout=90)
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


def _merge_and_gate(mwt: Path, mref: str, repo_name: str,
                    base: str) -> tuple:
    """_merge_in + shadow guard + the post-merge test gate ->
    (ok, conflicts, err, tests, shadows).

    tests is the run_test_gate() result ({} when the merge never got
    that far); shadows is the shadow_paths() flag list ([] likewise).
    ok=False means do NOT push the merged tree."""
    ok, conflicts, merr = _merge_in(mwt, mref)
    if not ok:
        return False, conflicts, merr, {}, []
    shadows = shadow_paths(mwt, base, "HEAD")
    if shadows:
        return False, [], "", {}, shadows
    tests = baseline_aware_test_gate(mwt, repo_name, base)
    if not tests.get("ok"):
        return False, [], "", tests, []
    return True, [], "", tests, []


def close_out(card: dict) -> dict:
    """Dispatch close-out merge step. Consumed by close_out_notes().

    Result keys: merged, noop (silent skip — no commits produced),
    checkpoint, pushed/push_error, gate, conflicts, shadows (pre-push
    gitignored-dir shadow guard), merged_sha,
    tests/test_failures (post-merge test gate), skipped|error, note,
    session."""
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
    # 2. push the branch always — strand-proof even if the merge bails.
    #    When the host can't push (fetch-only clone, wrong-repo deploy
    #    key — card runner-push-cred-gap) relay the head as a bundle so
    #    merge-sweep on the board host can land it anyway.
    if s.get("head"):
        pr = push_branch(wt or repo, branch)
        out["pushed"] = pr.get("pushed")
        if pr.get("error"):
            # push_error (not 'error') so the merge step's own errors
            # don't mask the branch push failure — and so the comms
            # note below actually fires
            out["push_error"] = pr["error"]
        if not out.get("pushed") and \
                os.environ.get("KANBAN_PATCH_RELAY", "1") != "0":
            out["relay"] = relay_session(card, s)
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
    # 5. merge into origin/<default> in a throwaway detached worktree,
    #    then the fast test gate runs on the merged tree before it pushes
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
        ok, conflicts, merr, tests, shadows = _merge_and_gate(
            mwt, mref, s.get("repo_name") or "", s["base_ref"])
        if tests:
            out["tests"] = tests
        if not ok:
            if shadows:
                out["shadows"] = shadows
            elif merr:
                out["error"] = f"merge: {merr}"
            elif tests and not tests.get("ok"):
                out["test_failures"] = tests.get("failed") or ["?"]
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
            ok, conflicts, merr, tests, shadows = _merge_and_gate(
                mwt, mref, s.get("repo_name") or "", s["base_ref"])
            if tests:
                out["tests"] = tests
            if not ok:
                if shadows:
                    out["shadows"] = shadows
                elif merr:
                    out["error"] = f"merge: {merr}"
                elif tests and not tests.get("ok"):
                    out["test_failures"] = tests.get("failed") or ["?"]
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
    rl = res.get("relay") or {}
    if rl.get("relayed"):
        notes.append(f"push failed → session head relayed to the board "
                     f"host as a bundle ({rl.get('file') or '?'}, "
                     f"{rl.get('bytes', '?')}B) — merge-sweep will land "
                     f"it from patch-inbox")
    elif rl.get("error"):
        notes.append(f"push failed AND patch-relay failed: "
                     f"{rl['error']} — rescue the branch by hand")
    if res.get("noop"):
        return notes  # no commits to merge — silent per spec
    gate = res.get("gate") or {}
    if not res.get("merged") and gate and not gate["ok"]:
        bad = gate.get("bad") or gate.get("errors") or ["?"]
        notes.append("auto-merge held — expected_goals not met: "
                     + "; ".join(str(b)[:80] for b in bad[:4]))
        return notes
    if res.get("shadows"):
        notes.append("merge held — gitignored-dir shadow path(s): "
                     + ", ".join(str(s) for s in res["shadows"][:8])
                     + " — untrack/rename them or add the bare ignore "
                       "name (the 2026-10-10 .venv incident class)")
        return notes
    if res.get("conflicts"):
        notes.append("auto-merge conflicts: "
                     + ", ".join(res["conflicts"][:8])
                     + " — card stays in review for manual resolution")
        return notes
    tests = res.get("tests") or {}
    if res.get("test_failures"):
        # names ride this note into action.last_failure via the caller —
        # the retry session starts knowing exactly what broke
        names = ", ".join(str(f) for f in res["test_failures"][:6])
        pre = len(tests.get("baseline_failed") or [])
        notes.append(f"test gate failed — merge held: {names}"
                     + (f" (+{pre} pre-existing baseline failure(s))"
                        if pre else ""))
        return notes
    if tests.get("skipped"):
        notes.append(f"test gate skipped: {tests['skipped']}")
    if res.get("merged"):
        if tests.get("baseline_failed"):
            notes.append("test gate: failure(s) identical to base "
                         "(pre-existing) — not blocking: "
                         + ", ".join(tests["baseline_failed"][:6]))
        elif tests.get("ran"):
            notes.append(f"test gate passed ({tests['command']}, "
                         f"{tests.get('elapsed', '?')}s)")
        notes.append(res.get("note") or "auto-merged")
    elif res.get("error") or res.get("skipped"):
        why = res.get("error") or res.get("skipped")
        notes.append(f"auto-merge not done: {why} — close will block "
                     "until merged")
    return notes


# -------------------------------------------------------- worktree GC
#
# Card dispatch-worktree-gc: dispatch worktrees and dispatch/<id>
# branches accumulate forever (the 2026-10-11 tony-dell disk pressure —
# manual sweep freed 10%). devin-dispatch-prune.sh is the weekly
# backstop; gc_worktree() is the close-path GC — once the merge step has
# PROVEN the session head is on origin/<default>, the worktree goes now
# instead of lingering a week. Guards mirror the prune script — removal
# only when ALL hold:
#
#   * worktree exists and `git status --porcelain` is empty (dirty
#     worktrees are NEVER touched — uncommitted work has no backup)
#   * no devin-task-<tid>* unit is active/activating for it
#   * HEAD is an ancestor of `merged_into` — a local rev the caller
#     already proved carries the work: close_out's pushed merge sha, or
#     a fetched origin/<base> (merge-sweep hands the runner the sha it
#     merged, via its own probe — same check, other side of the ssh)
#
# `git worktree remove` (never --force) re-refuses dirty/locked trees —
# our porcelain check is a pre-check for a readable skip reason, git is
# the second opinion. Branch delete tries -d, falls back to -D only
# after re-proving ancestry (the -d refusal case: branch pushed without
# upstream reachability — commits are already on origin, the local ref
# loses nothing; prune.sh's branch_delete uses the same escape).
# KANBAN_WTGC=0 disables both this and the merge-sweep probe call.

def gc_worktree(worktree: Path, merged_into: str, branch: str = "",
                task_id: str = "") -> dict:
    """{"removed": [str], ...} — "skipped" (nothing done, reason) or
    "error" (removal attempted, git refused), "kept_branch" when the
    worktree went but the branch delete failed."""
    out: dict = {"removed": []}
    if os.environ.get("KANBAN_WTGC", "1") == "0":
        out["skipped"] = "KANBAN_WTGC=0"
        return out
    wt = Path(worktree) if worktree else None
    if not wt or not wt.is_dir():
        out["skipped"] = "worktree gone"
        return out
    dirty = dirty_count(wt)
    if dirty is None:
        out["skipped"] = "worktree unreadable"
        return out
    if dirty:
        out["skipped"] = f"dirty — {dirty} uncommitted file(s)"
        return out
    if task_id and sh(["systemctl", "--user", "list-units",
                       f"devin-task-{task_id}*",
                       "--state=active,activating",
                       "--no-legend", "--plain"], timeout=15
                      ).stdout.strip():
        out["skipped"] = f"devin-task-{task_id}* still active"
        return out
    head = _rev_parse(wt, "HEAD")
    if not head:
        out["skipped"] = "no HEAD"
        return out
    if not merged_into or not _rev_parse(wt, merged_into):
        out["skipped"] = f"merged-ref {merged_into or '?'} not present"
        return out
    if sh(["git", "-C", str(wt), "merge-base", "--is-ancestor",
           head, merged_into]).returncode != 0:
        out["skipped"] = f"unmerged commits — HEAD not in {merged_into}"
        return out
    root = _repo_root(wt)
    if root is None:
        out["skipped"] = "no repo root"
        return out
    r = sh(["git", "-C", str(root), "worktree", "remove", str(wt)],
           timeout=60)
    if r.returncode != 0:
        out["error"] = ("worktree remove: "
                        + (r.stderr or r.stdout).strip()[:160])
        return out
    out["removed"].append(f"worktree {wt}")
    if branch:
        r = sh(["git", "-C", str(root), "branch", "-d", branch],
               timeout=30)
        if r.returncode != 0:
            # -d can refuse when the branch has no upstream and the
            # checkout's HEAD doesn't contain it — the ancestry gate
            # already proved the commits are in merged_into.
            anc = sh(["git", "-C", str(root), "merge-base",
                      "--is-ancestor", branch, merged_into])
            if anc.returncode == 0:
                r = sh(["git", "-C", str(root), "branch", "-D", branch],
                       timeout=30)
        if r.returncode == 0:
            out["removed"].append(f"branch {branch}")
        else:
            out["kept_branch"] = branch
    sh(["git", "-C", str(root), "worktree", "prune"], timeout=30)
    return out


def gc_session(res: dict) -> list:
    """Post-merge worktree GC for a close_out() result -> comms lines.

    Self-gating: runs only when the session left a worktree whose head is
    provably inside merged_into (the pushed merge sha, else the fetched
    origin/<base> — the ancestry check inside gc_worktree is the real
    gate, so an unmerged/conflicted result simply skips). One line lists
    what was removed; a kept-for-a-reason tree gets one line explaining
    (silent when the worktree was already gone)."""
    s = res.get("session") or {}
    wt = s.get("worktree")
    if not wt or not s.get("head"):
        return []
    merged_into = res.get("merged_sha") or s.get("base_ref") or ""
    try:
        r = gc_worktree(wt, merged_into, s.get("branch") or "",
                        s.get("task_id") or "")
    except Exception as e:
        return [f"worktree GC failed: {type(e).__name__}: {e}"]
    if r.get("removed"):
        kept = (f"; kept branch {r['kept_branch']}"
                if r.get("kept_branch") else "")
        return ["worktree GC: removed "
                + ", ".join(str(x) for x in r["removed"]) + kept]
    skip = str(r.get("skipped") or r.get("error") or "")
    if skip and "gone" not in skip:
        return [f"worktree kept: {skip}"]
    return []


def try_merge(card: dict) -> dict:
    """Back-compat shim — close_out() subsumes the old best-effort merge."""
    return close_out(card)
