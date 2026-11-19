#!/usr/bin/env python3
"""card-run — launch an opencode session primed with a card context pack.

Pipeline: fetch card -> build context pack (card-context.py) -> write
pack file -> run `opencode run` (one-shot, non-interactive) in the
target repo dir -> optionally post the outcome as a card comment.

Default is --dry-run: prints the pack path and the command it would
exec, nothing touches the card or the repo.

Usage:
  card-run.py CARD_ID [--dir REPO] [--model M] [--ssh idc03]
  card-run.py ada-card-runner --dry-run     # default
  card-run.py ada-card-runner --dir ~/CascadeProjects/chaba --comment
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import yaml as _yaml
except ImportError:  # yaml files just skip the parse gate
    _yaml = None

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from importlib import import_module  # noqa: E402

def _act(card: dict) -> dict:
    """card['action'] read accessor — schema says dict, but marker cards
    carry scalars ('spec-review'). Returns {} for non-dict WITHOUT
    writing, so read-only passes don't stamp action:{} onto cards."""
    a = card.get("action")
    return a if isinstance(a, dict) else {}

_board_cli = import_module("board-cli")
_context = import_module("card-context")

WRAP = (
    "You are processing a kanban card end-to-end. Follow the pack's "
    "gates: worktree discipline, board-api for card mutations, "
    "git-safe-push + PR for repo changes, verify before claiming done. "
    "When finished, state clearly: what changed, how it was verified, "
    "and whether the done-condition holds.\n\n"
)

# Bounded retry contract (spec piece 4; DEV-0253 'failure evidence
# rides the next attempt'): retries resume the SAME opencode session
# (--continue) so the agent sees its own work plus the eval evidence,
# never a cold restart. Cap matches the board's re-arm philosophy —
# after MAX_ATTEMPTS the card fails for a human, it never loops.
MAX_ATTEMPTS = 3
RETRY_MSG = (
    "Eval attempt {n}/{total} — the previous attempt FAILED review:\n"
    "{evidence}\n\n"
    "Fix the problem and finish the card. Same gates apply: work only "
    "in this worktree, leave changes uncommitted, verify real state "
    "before claiming done."
)


def _api(method: str, path: str, payload: dict | None, ssh: str | None,
         api: str | None) -> dict:
    if api:
        _board_cli.API = api
    return _board_cli.call(method, path, payload, ssh)


def _comment(card_id: str, text: str, ssh: str | None,
             api: str | None) -> None:
    try:
        _api("POST", "/comment",
             {"id": card_id, "from": "devin", "text": text},
             ssh, api)
    except Exception as exc:
        print(f"comment failed: {str(exc)[:200]}", file=sys.stderr)


def _action(card_id: str, do: str, ssh: str | None, api: str | None,
            column: str | None = None) -> dict:
    return _api("POST", "/action",
                {"id": card_id, "from": "devin", "do": do,
                 "column": column}, ssh, api)


def _git(wt: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(wt), *argv],
                          capture_output=True, text=True)


def _sh(argv: list[str], cwd: Path | None = None,
        timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True,
                          text=True, timeout=timeout)


def _card_blocked_reason(card: dict, host: str) -> str | None:
    if card.get("column") in ("done", "archive"):
        return f"column {card.get('column')}"
    for r in card.get("requests") or []:
        if r.get("status") not in ("answered", "closed"):
            return f"open request {r.get('id', '?')}"
    a = _act(card)
    if a.get("status") in ("claimed", "running"):
        runner = str(a.get("runner") or "")
        if runner.split(".")[0] == host:
            return None  # our own stale claim — resume
        return f"already claimed/running by {runner or '?'}"
    return None


def _finish(card_id: str, host: str, ok: bool, result: str,
            ssh: str | None, api: str | None,
            verified: bool | None = None) -> None:
    body = {"id": card_id, "from": "devin", "do": "finish",
            "host": host, "ok": ok, "result": result[:300]}
    if verified is not None:
        body["verified"] = verified
    _api("POST", "/action", body, ssh, api)


def _porcelain_paths(wt: Path) -> list[str]:
    """Paths the session touched (modified + untracked), rename-aware."""
    out = _git(wt, "status", "--porcelain").stdout
    paths = []
    for line in out.splitlines():
        if not line.strip():
            continue
        p = line[3:]
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        paths.append(p)
    return paths


def _validate_changes(wt: Path, limit: int = 40) -> list[str]:
    """Repo-validate gate: syntax-check the files the session touched —
    the cheap machine-checkable gate that catches 'agent wrote a broken
    file' before the diff ever reaches a PR. py via compile() (no
    __pycache__ litter), sh via bash -n, yml/json parsed in-process."""
    errs = []
    for rel in _porcelain_paths(wt)[:limit]:
        p = wt / rel
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        try:
            if ext == ".py":
                compile(p.read_text(), rel, "exec")
            elif ext == ".sh":
                r = _sh(["bash", "-n", str(p)], cwd=wt, timeout=30)
                if r.returncode:
                    errs.append(f"{rel}: {(r.stderr or '').strip()[:160]}")
            elif ext == ".json":
                json.loads(p.read_text())
            elif ext in (".yml", ".yaml") and _yaml is not None:
                _yaml.safe_load(p.read_text())
        except Exception as exc:
            errs.append(f"{rel}: {str(exc)[:160]}")
    return errs


def _evaluate_attempt(wt: Path, slug: str,
                      verify_cmd: str | None) -> tuple:
    """Score one session attempt -> (ok, evidence, notes, verified).

    Gate order: changes present -> git-state normalize -> repo-validate
    (diff --check + syntax on touched files) -> the card's declared
    verifier. `evidence` is the retry feedback; `verified` marks a
    declared verifier that ran green (a card with no verifier can pass
    eval but is never stamped verified)."""
    notes = []
    dirty = _git(wt, "status", "--porcelain").stdout.strip()
    committed = _git(wt, "diff", "--name-only",
                     "origin/master", "HEAD").stdout.strip()
    if not dirty and not committed:
        ignored = _git(wt, "status", "--porcelain",
                       "--ignored").stdout
        hint = (" Session wrote gitignored files — the card's "
                "target path may be inside an ignored dir."
                if "\n!!" in f"\n{ignored}" else "")
        return False, f"session produced no repo changes.{hint}", \
            notes, False
    # Sessions are told not to git, but a session may still commit/push
    # on its own — normalize committed work to a diff vs origin/master
    # re-applied on the card branch (same salvage as the single-shot
    # loop had; repeated per attempt since a retry may commit again).
    if committed or _git(wt, "rev-parse", "--abbrev-ref",
                         "HEAD").stdout.strip() != f"card/{slug}":
        patch = _git(wt, "diff", "--binary", "origin/master",
                     "HEAD").stdout
        if dirty:
            _git(wt, "stash", "--include-untracked", "-q")
        r2 = _git(wt, "checkout", "-B", f"card/{slug}", "origin/master")
        if r2.returncode:
            return False, (f"normalize checkout failed: "
                           f"{r2.stderr.strip()[:200]}"), notes, False
        if dirty:
            _git(wt, "stash", "pop", "-q")  # best effort
        if patch.strip():
            pa = subprocess.run(
                ["git", "-C", str(wt), "apply", "--whitespace=nowarn"],
                input=patch, capture_output=True, text=True)
            if pa.returncode:
                return False, (f"salvage apply failed: "
                               f"{pa.stderr.strip()[:200]}"), notes, False
        if not _git(wt, "status", "--porcelain").stdout.strip():
            return False, ("session committed only duplicate-of-master "
                           "content; nothing new to land"), notes, False
    bad_ws = _git(wt, "diff", "--check").stdout.strip()
    if bad_ws:
        notes.append("diff --check warnings present")
    errs = _validate_changes(wt)
    if errs:
        return False, "repo validate failed: " + "; ".join(
            errs[:5]), notes, False
    verified = False
    if verify_cmd and not str(verify_cmd).startswith("profile:"):
        v = _sh(["bash", "-lc", str(verify_cmd)], cwd=wt, timeout=600)
        notes.append(f"verify `{verify_cmd}` rc={v.returncode}")
        if v.returncode:
            return False, (f"declared verifier failed: "
                           f"{v.stdout[-300:]}"), notes, False
        verified = True
    return True, "", notes, verified


def _ci_wait(pr_url: str, wt: Path, wait_s: int) -> str:
    """Bounded CI surface: poll the PR's statusCheckRollup until it
    resolves or wait_s expires. Returns 'pass' | 'fail: <check>' |
    'pending' | 'skipped' | 'unknown'. The PR's own checks are the gate
    — this only surfaces the verdict for the finish note (merge stays
    the downstream human/merge-sweep gate, never blocked here)."""
    if wait_s <= 0:
        return "skipped"
    deadline = time.time() + wait_s
    pending = False
    while True:
        r = _sh(["gh", "pr", "view", pr_url, "--json",
                 "statusCheckRollup"], cwd=wt, timeout=30)
        if r.returncode:
            return f"unknown ({(r.stderr or '')[:140].strip()})"
        try:
            roll = (json.loads(r.stdout or "{}")
                    .get("statusCheckRollup") or [])
        except ValueError:
            return "unknown (unparseable rollup)"
        if not roll:
            pending = True  # checks haven't reported yet
        else:
            pending = False
            for c in roll:
                st = str(c.get("status") or "").upper()
                v = str(c.get("conclusion") or c.get("state")
                        or "").upper()
                if st and st != "COMPLETED":
                    pending = True
                    continue
                if v in ("FAILURE", "CANCELLED", "TIMED_OUT", "ERROR",
                         "ACTION_REQUIRED"):
                    return ("fail: " + str(c.get("name")
                            or c.get("context") or v)[:140])
                if v not in ("SUCCESS", "NEUTRAL", "SKIPPED"):
                    pending = True
        if not pending:
            return "pass"
        if time.time() >= deadline:
            return f"pending after {wait_s}s"
        time.sleep(15)


def lifecycle(args) -> int:
    """queue -> claim(host) -> worktree -> run -> verify -> PR -> finish.

    Follows the dispatch contract in board-api: claim is first-wins on a
    queued card, finish(ok) moves the card to review. Merge/deploy stay
    human-gated; on failure finish(ok:false) marks the card failed with
    the stage it stopped at.
    """
    repo = Path(args.repo).resolve()
    ssh = args.ssh or None
    host = socket.gethostname().split(".")[0] or "card-run"
    card = _context.fetch_card(args.id, ssh, args.api)
    card_id = card.get("id") or args.id
    ref = card.get("ref") or card_id
    slug = re.sub(r"[^a-z0-9]+", "-", str(ref).lower()).strip("-")

    blocked = _card_blocked_reason(card, host)
    if blocked:
        print(json.dumps({"ok": False, "stage": "gate",
                          "error": f"card not actionable: {blocked}"}))
        return 2

    stage = "claim"
    try:
        a = _act(card)
        ours = a.get("status") == "running" and \
            str(a.get("runner") or "").split(".")[0] == host
        if not ours:
            if a.get("status") != "queued":
                _action(card_id, "queue", ssh, args.api)
            _api("POST", "/action",
                 {"id": card_id, "from": "devin", "do": "claim",
                  "host": host}, ssh, args.api)

        stage = "worktree"
        wt = Path.home() / "CascadeProjects" / f"card-wt-{slug}"
        branch = f"card/{slug}"
        _sh(["git", "-C", str(repo), "fetch", "origin", "--quiet"])
        if wt.is_dir() and not _git(wt, "rev-parse",
                                    "--git-dir").returncode:
            # reuse a worktree from an earlier attempt — reset to
            # fresh master; a prior run's leftovers are disposable
            r = _git(wt, "checkout", "-B", branch, "origin/master")
            _git(wt, "reset", "--hard", "origin/master")
            _git(wt, "clean", "-fdxq")  # -x: ignored leftovers from a
            # previous run must not leak into the retry's view
        else:
            if wt.exists():
                _sh(["git", "-C", str(repo), "worktree", "remove",
                     "--force", str(wt)])
            r = _sh(["git", "-C", str(repo), "worktree", "add",
                     str(wt), "-B", branch, "origin/master"])
        if r.returncode:
            raise RuntimeError(
                f"worktree setup: {r.stderr.strip()[:300]}")
        _sh([str(repo / "scripts/install-hooks.sh"),
             "--role", "branch", str(wt)])

        stage = "pack"
        pack = WRAP + _context.build(
            card, wt, max_files=8, head=40,
            gates=[
                f"Work ONLY inside this directory: {wt} — it is the "
                "card's worktree. Do not cd into or modify any other "
                "checkout (other CascadeProjects dirs are other work).",
                "Leave changes UNCOMMITTED — the runner owns all git "
                "ops: no branch/checkout/commit/push/PR.",
                "Do NOT post card comments or move the card — the "
                "runner reports everything.",
                "Verify real state before asserting done "
                "(file contents, command output — not memory).",
                "No secrets in output; never print token/password "
                "values.",
            ])
        pack_path = Path(tempfile.gettempdir()) / f"card-run-{args.id}.md"
        pack_path.write_text(pack)

        stage = "run"
        verify_cmd = (_act(card)).get("verify") \
            or (_act(card)).get("verifier")
        attempts = min(max(int(args.attempts or 1), 1), MAX_ATTEMPTS)
        ok_eval, evidence, notes, verified = False, "", [], False
        for attempt in range(1, attempts + 1):
            if attempt == 1:
                cmd = ["opencode", "run", "--archived",
                       "--title", f"card {ref}"]
                msg = ("Process this kanban card per the attached "
                       "context pack.")
            else:
                # --continue resumes the same session in this worktree:
                # the agent keeps its own work and gets the eval
                # evidence back — not a cold restart on a clean slate.
                cmd = ["opencode", "run", "--archived", "--continue"]
                msg = RETRY_MSG.format(n=attempt, total=attempts,
                                       evidence=evidence[:800])
            if args.model:
                cmd += ["-m", args.model]
            if attempt == 1:
                cmd += ["-f", str(pack_path)]
            cmd += [msg]
            r = _sh(cmd, cwd=wt, timeout=1800)
            tail = ((r.stdout or "") + (r.stderr or ""))[-1500:]
            stage = "eval"
            ok_eval, evidence, notes, verified = _evaluate_attempt(
                wt, slug, verify_cmd)
            notes.append(f"attempt {attempt}/{attempts}: "
                         f"{'ok' if ok_eval else evidence[:140]}")
            if ok_eval:
                break
        if not ok_eval:
            _finish(card_id, host, False,
                    f"{attempts} attempt(s) failed eval — last: "
                    f"{evidence[:200]} tail: {tail[-150:]}",
                    ssh, args.api)
            print(json.dumps({"ok": False, "stage": "eval",
                              "attempts": attempts,
                              "error": evidence[:300]}))
            return 3

        stage = "commit"
        _git(wt, "add", "-A")
        _git(wt, "reset", "-q", "--", "docs/ssot/kanban/cards/")
        staged = _git(wt, "diff", "--cached", "--name-only").stdout.strip()
        if not staged:
            _finish(card_id, host, False,
                    "session only touched card files; nothing committable",
                    ssh, args.api)
            print(json.dumps({"ok": False, "stage": "commit",
                              "error": "nothing committable"}))
            return 3
        title = str(card.get("title") or ref)[:70]
        r = _git(wt, "commit", "-m",
                 f"card {ref}: {title}\n\n"
                 f"Automated card-run session. Card: {card_id}.",
                 "-m", "Generated with Devin\n\n"
                 "Co-Authored-By: Devin "
                 "<158243242+devin-ai-integration[bot]@users.noreply.github.com>")
        if r.returncode:
            raise RuntimeError(f"commit: {r.stderr.strip()[:300]}")

        stage = "push"
        r = _sh([str(wt / "scripts/git-safe-push.sh"), str(wt)],
                cwd=wt, timeout=300)
        if r.returncode:
            raise RuntimeError(f"push: {r.stderr.strip()[-300:]}")

        stage = "pr"
        r = _sh(["gh", "pr", "create",
                 "--head", branch,
                 "--title", f"card {ref}: {title}",
                 "--body", f"## Summary\nAutomated card-run session for "
                 f"{ref} ({card_id}).\n\n#### Test plan\n- [ ] human "
                 f"review of diff\n- [ ] CI\n\nGenerated with Devin"],
                cwd=wt, timeout=60)
        if r.returncode:
            q = _sh(["gh", "pr", "list", "--head", f"card/{slug}",
                     "--json", "url", "--jq", ".[0].url"],
                    cwd=wt, timeout=30)
            pr_url = q.stdout.strip()
            if not pr_url:
                raise RuntimeError(
                    f"pr create: {r.stderr.strip()[:300]}")
        else:
            pr_url = r.stdout.strip()

        stage = "ci"
        ci = _ci_wait(pr_url, wt, args.ci_wait)

        stage = "card"
        files = _git(wt, "diff", "--name-only",
                     "origin/master...HEAD").stdout.strip()
        _comment(
            card_id,
            f"lifecycle: PR {pr_url}\n"
            f"files: {files[:600]}\n"
            f"eval: {'; '.join(notes) or 'no declared verifier'}\n"
            f"ci: {ci}\n"
            f"session tail: {tail[-300:]}",
            ssh, args.api)
        _finish(card_id, host, True, f"PR {pr_url} (ci {ci})",
                ssh, args.api, verified=verified)
        print(json.dumps({"ok": True, "pr": pr_url, "worktree": str(wt),
                          "files": files.splitlines()}))
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        err = f"lifecycle stopped at {stage}: {str(exc)[:400]}"
        print(json.dumps({"ok": False, "stage": stage, "error": err}))
        _comment(card_id, err, ssh, args.api)
        if stage != "claim":
            try:
                _finish(card_id, host, False, err, ssh, args.api)
            except Exception:
                pass
        return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--dir", default=".",
                    help="working dir for the opencode session")
    ap.add_argument("--ssh", default="idc03")
    ap.add_argument("--api", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--comment", action="store_true",
                    help="post the run outcome as a card comment")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--execute", action="store_true",
                    help="actually run opencode (disables dry-run)")
    ap.add_argument("--lifecycle", action="store_true",
                    help="full loop: claim -> worktree -> run -> verify "
                         "-> commit/PR -> card to review")
    ap.add_argument("--attempts", type=int, default=2,
                    help="session attempts for --lifecycle (1..%d, "
                         "default 2); retries resume the opencode "
                         "session with the eval evidence" % MAX_ATTEMPTS)
    ap.add_argument("--ci-wait", type=int, default=120,
                    help="seconds to poll the PR's CI rollup after "
                         "creation (0 = report-only, default 120)")
    ap.add_argument("--repo", default=os.path.expanduser(
        "~/CascadeProjects/chaba"),
        help="checkout to create the card worktree from (--lifecycle)")
    args = ap.parse_args()

    if args.lifecycle:
        return lifecycle(args)

    card = _context.fetch_card(args.id, args.ssh or None, args.api)
    pack = WRAP + _context.build(
        card, Path(args.dir).resolve(), max_files=8, head=40)

    pack_path = Path(tempfile.gettempdir()) / f"card-run-{args.id}.md"
    pack_path.write_text(pack)

    cmd = ["opencode", "run", "--archived",
           "--title", f"card {args.id}"]
    if args.model:
        cmd += ["-m", args.model]
    cmd += ["-f", str(pack_path),
            "Process this kanban card per the attached context pack."]

    if args.dry_run and not args.execute:
        print(f"pack: {pack_path} ({len(pack)} bytes)")
        print(f"cwd:  {Path(args.dir).resolve()}")
        print(f"cmd:  {' '.join(cmd)}")
        return 0

    r = subprocess.run(cmd, cwd=args.dir, capture_output=True,
                       text=True, timeout=1800)
    tail = (r.stdout or "")[-2000:]
    rc = r.returncode
    print(tail)
    if args.comment:
        body = (f"card-run opencode session (rc={rc}) on {args.dir}: "
                f"{tail[-400:]}")
        try:
            _board_cli.call(
                "POST", "/comment",
                {"id": args.id, "from": "devin", "text": body},
                args.ssh or None)
        except Exception as exc:
            print(json.dumps({"comment_error": str(exc)[:200]}))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
