#!/usr/bin/env python3
"""opencode_command.py — narrow publisher for allowlisted OpenCode
command files (card ada-opencode-command-publisher-20261108, ADA-1224).

One shared backend for Ada (via the ada-control MCP wrapper in ada-voice)
and Devin (via scripts/board/opencode-command.py or direct HTTP): every
op is a name-locked operation on a COMMANDS registry entry — the caller
picks a command name and an op, never a path, never a shell or git
command.

Ops (POST /opencode-command on board-api, or `--via local` on a host
with the repo checked out):

  preview   sha + byte-diff of the canonical repo file vs the deployed
            workspace file (diff capped at DIFF_MAX_LINES)
  validate  structural checks on candidate content (frontmatter,
            required markers, size, UTF-8) — the sweep native-menu
            block is a required marker so it cannot silently drop again
  publish   confirm+sha-gated write of the canonical repo file; the
            caller must pass expect_sha = sha256(content) so the bytes
            reviewed at preview are the bytes committed. board-api
            queues the file through its commit worker -> kanban-commit
            safe-pull+push (the established safe pipeline — no new git
            plumbing, no direct pushes from the request path)
  sync      confirm-gated atomic copy of the COMMITTED canonical bytes
            to the deploy host workspace (local when the host matches,
            fixed-argv ssh otherwise), sha-verified after landing
  verify    sha256 canonical vs deployed

Safety shape: allowlisted names only, fixed paths, fixed remote argv
(no caller-controlled shell), confirm+sha gates on every mutation,
compact receipts sized for agent context.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import shlex
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

DIFF_MAX_LINES = 200
SSH_TIMEOUT_S = 25
OPS = ("preview", "validate", "publish", "sync", "verify")

# Allowlist: the ONLY files this door can touch. Adding an entry is a
# code review, not a call-time parameter — that is the narrow scope Tony
# approved (request which-publisher-scope-should-i-implement-d42d5b).
COMMANDS = {
    "ada": {
        "repo_rel": "stacks/idc02/ada-code/commands/ada.md",
        "deploy_host": "idc02",
        "deploy_path":
            "/home/tony/.local/share/ada-code/workspace/"
            ".opencode/commands/ada.md",
        "max_bytes": 65536,
        "frontmatter": True,
        # The /ada sweep native-menu requirement (the fix this card
        # makes durable — it was silently lost in the ADA0186 live
        # edit 2026-11-19). Validation rejects any candidate missing
        # these markers.
        "required_markers": [
            "/ada sweep",
            "Sweep Verdicts",
            "`question` tool",
        ],
    },
}


class PublishError(RuntimeError):
    """Remote/deploy failure — maps to 502 at the board-api door."""


def _repo() -> Path:
    return Path(os.environ.get(
        "OPENCODE_COMMAND_REPO",
        str(Path(__file__).resolve().parents[2])))


def entry(name: str) -> dict:
    e = COMMANDS.get(name)
    if e is None:
        raise ValueError(
            f"unknown command name {name!r} — allowlist: "
            f"{sorted(COMMANDS)}")
    return e


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_path(name: str) -> Path:
    p = _repo() / entry(name)["repo_rel"]
    # defense in depth: the registry is fixed, but never let a future
    # entry escape the repo root
    if not p.resolve().is_relative_to(_repo().resolve()):
        raise PublishError(f"canonical path escapes repo: {p}")
    return p


def read_canonical(name: str) -> bytes | None:
    try:
        return _canonical_path(name).read_bytes()
    except OSError:
        return None


def _is_local(name: str) -> bool:
    if os.environ.get("OPENCODE_COMMAND_LOCAL") == "1":
        return True
    host = entry(name)["deploy_host"]
    if host in ("localhost", "127.0.0.1"):
        return True
    return socket.gethostname().split(".")[0] == host


def _ssh(name: str, remote_cmd: str,
         stdin: bytes | None = None) -> subprocess.CompletedProcess:
    """Fixed-argv ssh — remote_cmd is built only from allowlist paths."""
    host = entry(name)["deploy_host"]
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            host, remote_cmd]
    try:
        return subprocess.run(argv, input=stdin, capture_output=True,
                              timeout=SSH_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise PublishError(f"ssh {host}: {e}")


def read_deployed(name: str) -> bytes | None:
    e = entry(name)
    if _is_local(name):
        try:
            return Path(e["deploy_path"]).read_bytes()
        except OSError:
            return None
    r = _ssh(name, f"cat -- {shlex.quote(e['deploy_path'])}")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()
        if "No such file" in err:
            return None
        raise PublishError(f"deployed read failed: {err[:200]}")
    return r.stdout


def _write_local(path: str, content: bytes) -> None:
    dst = Path(path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=dst.name + ".new-", dir=str(dst.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, dst)
    except BaseException:
        os.unlink(tmp) if os.path.exists(tmp) else None
        raise


def write_deployed(name: str, content: bytes) -> None:
    """Atomic deploy: land beside the target then rename over it."""
    e = entry(name)
    dst = e["deploy_path"]
    if _is_local(name):
        _write_local(dst, content)
        return
    tmp = f"{dst}.new-{sha256(content)[:8]}"
    remote = (f"mkdir -p -- {shlex.quote(str(Path(dst).parent))} && "
              f"umask 022 && cat > {shlex.quote(tmp)} && "
              f"mv -f -- {shlex.quote(tmp)} {shlex.quote(dst)}")
    r = _ssh(name, remote, stdin=content)
    if r.returncode != 0:
        raise PublishError(
            f"deploy write failed: "
            f"{r.stderr.decode('utf-8', 'replace').strip()[:200]}")


def validate_content(name: str, content: bytes) -> list:
    """Structural gate — returns a list of errors ([] = valid)."""
    e = entry(name)
    errors = []
    if not content:
        return ["content is empty"]
    if len(content) > e["max_bytes"]:
        errors.append(f"content {len(content)}B > max {e['max_bytes']}B")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as ex:
        return [f"content is not UTF-8: {ex}"]
    if "\x00" in text:
        errors.append("content contains NUL")
    if e.get("frontmatter"):
        lines = text.split("\n")
        if not lines or lines[0].strip() != "---":
            errors.append("missing frontmatter opening '---'")
        else:
            close = next((i for i in range(1, min(len(lines), 20))
                          if lines[i].strip() == "---"), None)
            if close is None:
                errors.append("missing frontmatter closing '---'")
            elif "description:" not in "\n".join(lines[1:close]):
                errors.append("frontmatter lacks 'description:'")
    for m in e.get("required_markers", []):
        if m not in text:
            errors.append(f"missing required marker: {m!r}")
    return errors


def _diff(name: str, canonical: bytes | None,
          deployed: bytes | None) -> str:
    a = (canonical or b"").decode("utf-8", "replace").splitlines()
    b = (deployed or b"").decode("utf-8", "replace").splitlines()
    lines = list(difflib.unified_diff(
        b, a, fromfile=f"deployed:{entry(name)['deploy_host']}",
        tofile="canonical", lineterm=""))
    if len(lines) > DIFF_MAX_LINES:
        lines = lines[:DIFF_MAX_LINES] + [
            f"... diff truncated at {DIFF_MAX_LINES} lines"]
    return "\n".join(lines)


def _receipt(name: str, op: str) -> dict:
    return {"ok": True, "op": op, "name": name,
            "command": dict(
                repo_rel=entry(name)["repo_rel"],
                deploy_host=entry(name)["deploy_host"],
                deploy_path=entry(name)["deploy_path"])}


def handle(body: dict, commit_hook=None) -> dict:
    """Dispatch one op. commit_hook(abs_repo_path) is called after a
    publish write so board-api can queue the commit; standalone callers
    pass None and get commit='untracked'."""
    op = str(body.get("op") or "").strip()
    if op not in OPS:
        raise ValueError(f"op must be one of {list(OPS)}")
    name = str(body.get("name") or "ada").strip()
    e = entry(name)
    res = _receipt(name, op)

    if op in ("preview", "verify"):
        canonical = read_canonical(name)
        deployed = read_deployed(name)
        res.update(
            canonical_sha=sha256(canonical) if canonical else None,
            canonical_bytes=len(canonical) if canonical else 0,
            deployed_sha=sha256(deployed) if deployed else None,
            deployed_bytes=len(deployed) if deployed else 0,
            in_sync=bool(canonical) and canonical == deployed)
        if op == "preview":
            res["diff"] = _diff(name, canonical, deployed)
            res["message"] = (
                "in sync" if res["in_sync"]
                else f"canonical {'missing' if not canonical else 'differs'}"
                     f" — deployed "
                     f"{'missing' if not deployed else 'differs'}")
        else:
            res["match"] = res["in_sync"]
            res["message"] = ("deployed hash matches canonical"
                              if res["in_sync"] else "hash mismatch")
        return res

    if op == "validate":
        if "content" in body:
            content = str(body["content"]).encode("utf-8")
            src = "supplied"
        else:
            content = read_canonical(name)
            src = "canonical"
        errors = [] if content is None else validate_content(name, content)
        if content is None:
            errors = ["canonical file missing"]
        res.update(source=src, errors=errors, valid=not errors,
                   sha256=sha256(content) if content else None,
                   bytes=len(content) if content else 0,
                   message="valid" if not errors
                           else f"{len(errors)} error(s)")
        return res

    # mutations — confirm + sha gates
    if body.get("confirm") is not True:
        raise ValueError(
            f"{op} needs confirm=true — preview first, then confirm")

    if op == "publish":
        content = str(body.get("content") or "").encode("utf-8")
        expect = str(body.get("expect_sha") or "").strip()
        if not expect:
            raise ValueError(
                "publish needs expect_sha=sha256(content) — proves the "
                "previewed bytes are the bytes committed")
        if expect != sha256(content):
            raise ValueError(
                "expect_sha mismatch — the content changed since "
                "preview; re-preview and retry")
        errors = validate_content(name, content)
        if errors:
            raise ValueError("validation failed: " + "; ".join(errors))
        p = _canonical_path(name)
        prior = read_canonical(name)
        res.update(canonical_sha=sha256(content),
                   canonical_path=e["repo_rel"])
        if prior == content:
            res.update(changed=False, commit="unchanged",
                       message="canonical already matches — nothing "
                               "to commit")
            return res
        _write_local(str(p), content)
        if commit_hook is not None:
            commit_hook(p)
            commit_state = "queued"
        else:
            commit_state = "untracked"
        res.update(changed=True, commit=commit_state,
                   push="kanban-commit safe-pull+push (writer pipeline, "
                        "~15min cadence)",
                   message="canonical updated; commit " + commit_state)
        return res

    # sync
    canonical = read_canonical(name)
    if canonical is None:
        raise PublishError("canonical file missing — publish first")
    expect = str(body.get("expect_sha") or "").strip()
    if expect and expect != sha256(canonical):
        raise ValueError(
            "expect_sha mismatch — canonical changed since preview; "
            "re-preview and retry")
    deployed = read_deployed(name)
    res.update(canonical_sha=sha256(canonical))
    if deployed == canonical:
        res.update(changed=False, deployed_sha=sha256(canonical),
                   match=True,
                   message="already in sync — nothing deployed")
        return res
    write_deployed(name, canonical)
    after = read_deployed(name)
    ok = after == canonical
    res.update(changed=True, deployed_sha=sha256(after) if after else None,
               match=ok,
               message="deployed and verified"
               if ok else "deployed but hash verify FAILED")
    if not ok:
        raise PublishError(
            "sync landed but deployed hash does not match canonical")
    return res


if __name__ == "__main__":
    import json
    print(json.dumps(handle(json.loads(sys.argv[1])), indent=1))
