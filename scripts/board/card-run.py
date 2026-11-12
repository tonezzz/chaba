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
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from importlib import import_module  # noqa: E402

_board_cli = import_module("board-cli")
_context = import_module("card-context")

WRAP = (
    "You are processing a kanban card end-to-end. Follow the pack's "
    "gates: worktree discipline, board-api for card mutations, "
    "git-safe-push + PR for repo changes, verify before claiming done. "
    "When finished, state clearly: what changed, how it was verified, "
    "and whether the done-condition holds.\n\n"
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
    a = card.get("action") or {}
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
        a = card.get("action") or {}
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
        cmd = ["opencode", "run", "--archived", "--title", f"card {ref}"]
        if args.model:
            cmd += ["-m", args.model]
        cmd += ["-f", str(pack_path),
                "Process this kanban card per the attached context pack."]
        r = _sh(cmd, cwd=wt, timeout=1800)
        tail = ((r.stdout or "") + (r.stderr or ""))[-1500:]

        stage = "changes"
        # Sessions are told not to git, but a compliant-with-the-old-
        # contract session may still commit/push on its own. Normalize:
        # committed work becomes a diff vs origin/master (a session
        # branch polluted with unrelated history still reduces to just
        # its content delta), re-applied onto a clean card branch.
        dirty = _git(wt, "status", "--porcelain").stdout.strip()
        committed = _git(wt, "diff", "--name-only", "origin/master",
                         "HEAD").stdout.strip()
        if not dirty and not committed:
            ignored = _git(wt, "status", "--porcelain",
                           "--ignored").stdout
            hint = (" Session wrote gitignored files — the card's "
                    "target path may be inside an ignored dir."
                    if "\n!!" in f"\n{ignored}" else "")
            _finish(card_id, host, False,
                    f"session rc={r.returncode}, no repo changes.{hint} "
                    f"tail: {tail[-200:]}", ssh, args.api)
            print(json.dumps({"ok": False, "stage": "changes",
                              "error": "session produced no changes"}))
            return 3
        if committed or _git(wt, "rev-parse", "--abbrev-ref",
                             "HEAD").stdout.strip() != f"card/{slug}":
            patch = _git(wt, "diff", "--binary", "origin/master",
                         "HEAD").stdout
            if dirty:
                _git(wt, "stash", "--include-untracked", "-q")
            r2 = _git(wt, "checkout", "-B", f"card/{slug}",
                      "origin/master")
            if r2.returncode:
                raise RuntimeError(
                    f"normalize checkout: {r2.stderr.strip()[:200]}")
            if dirty:
                _git(wt, "stash", "pop", "-q")  # best effort
            if patch.strip():
                pa = subprocess.run(
                    ["git", "-C", str(wt), "apply", "--whitespace=nowarn"],
                    input=patch, capture_output=True, text=True)
                if pa.returncode:
                    raise RuntimeError(
                        f"salvage apply: {pa.stderr.strip()[:200]}")
            dirty = _git(wt, "status", "--porcelain").stdout.strip()
            if not dirty:
                _finish(card_id, host, False,
                        "session committed only duplicate-of-master "
                        "content; nothing new to land",
                        ssh, args.api)
                print(json.dumps({"ok": False, "stage": "changes",
                                  "error": "nothing new to land"}))
                return 3

        stage = "verify"
        notes = []
        verified = False
        bad_ws = _git(wt, "diff", "--check").stdout.strip()
        if bad_ws:
            notes.append("diff --check warnings present")
        verify_cmd = (card.get("action") or {}).get("verify") \
            or (card.get("action") or {}).get("verifier")
        if verify_cmd and not str(verify_cmd).startswith("profile:"):
            v = _sh(["bash", "-lc", str(verify_cmd)], cwd=wt, timeout=600)
            notes.append(f"verify `{verify_cmd}` rc={v.returncode}")
            if v.returncode:
                raise RuntimeError(
                    f"declared verifier failed: {v.stdout[-300:]}")
            verified = True

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

        stage = "card"
        files = _git(wt, "diff", "--name-only",
                     "origin/master...HEAD").stdout.strip()
        _comment(
            card_id,
            f"lifecycle: PR {pr_url}\n"
            f"files: {files[:600]}\n"
            f"verify: {'; '.join(notes) or 'no declared verifier'}\n"
            f"session tail: {tail[-300:]}",
            ssh, args.api)
        _finish(card_id, host, True, f"PR {pr_url}", ssh, args.api,
                verified=verified)
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
