#!/usr/bin/env python3
"""Executable goal checks for kanban expected_goals (docs/ssot/ssot.ci.yml).

A card declares acceptance as machine-checkable goals:

    expected_goals:
      - {id: board-live,   check: "http 200 https://…/apps/board/"}
      - {id: bundle-built, check: "file-exists dist/card.js"}
      - {id: selftest,     check: "command python3 x.py --selftest"}
      - {id: merged,       check: "git-ancestor HEAD origin/master"}
      - {id: ws-up,        check: "ws wss://…/apps/gev-live/ws"}

check grammar (anything else is prose — rejected at the plan gate;
a goal that cannot fail carries no information):

    http <code> <url>                          GET; ok iff status == <code>
    command <shell>                            ok iff exit 0
    command <shell> expect <substr>            ok iff exit 0 AND substr in output
    command <shell> expect exit [N]            ok iff exit != 0 (or == N)
    file-exists <path>                         ~ and cwd-relative paths OK
    git-ancestor <branch> <base>               git merge-base --is-ancestor
    ws <url>                                   ws:// or wss:// handshake -> 101

Shared by scripts/ci/card-pipeline.py (verify stage) and
scripts/report/report-watch.py (done-card re-probe). No network imports
beyond urllib/socket/ssl — keep it dependency-free.
"""
from __future__ import annotations

import base64
import os
import re
import socket
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

KINDS = ("http", "command", "file-exists", "git-ancestor", "ws")
CMD_TIMEOUT = 120
NET_TIMEOUT = 15

_INT_RE = re.compile(r"^\d{3}$")


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=7))).isoformat(
        timespec="seconds")


def parse_check(check: str) -> tuple:
    """Parse a check string -> (kind, *args). Raises ValueError on prose
    or malformed checks — callers surface the message as the rejection
    reason."""
    if not isinstance(check, str) or not check.strip():
        raise ValueError("empty check — expected one of: "
                         + ", ".join(KINDS))
    s = check.strip()
    kind, _, rest = s.partition(" ")
    rest = rest.strip()

    if kind == "http":
        m = re.fullmatch(r"(\d{3})\s+(\S+)", rest)
        if not m:
            raise ValueError(
                "http check needs 'http <code> <url>' e.g. "
                "'http 200 https://host/health'")
        if not m.group(2).startswith(("http://", "https://")):
            raise ValueError("http url must start http:// or https://")
        return ("http", int(m.group(1)), m.group(2))

    if kind == "command":
        if not rest:
            raise ValueError("command check needs a shell command")
        # ' expect ' splits the shell from the expectation; the LAST
        # occurrence wins so shells containing the word still parse.
        shell, sep, expect = rest.rpartition(" expect ")
        if not sep:
            return ("command", rest, None)
        shell = shell.strip()
        expect = expect.strip()
        if not shell:
            raise ValueError("command check: empty shell before 'expect'")
        if not expect:
            raise ValueError("command check: empty expect — use "
                             "'expect <substr>' or 'expect exit [N]'")
        return ("command", shell, expect)

    if kind == "file-exists":
        if not rest or " " in rest:
            raise ValueError("file-exists check needs exactly one path")
        return ("file-exists", rest)

    if kind == "git-ancestor":
        parts = rest.split()
        if len(parts) != 2:
            raise ValueError(
                "git-ancestor check needs 'git-ancestor <branch> <base>'")
        return ("git-ancestor", parts[0], parts[1])

    if kind == "ws":
        if not rest or " " in rest:
            raise ValueError("ws check needs exactly one url")
        if not rest.startswith(("ws://", "wss://")):
            raise ValueError("ws url must start ws:// or wss://")
        return ("ws", rest)

    raise ValueError(f"unknown check kind '{kind}' — expected one of: "
                     + ", ".join(KINDS))


def validate_goals(card: dict) -> tuple[list[dict], list[str]]:
    """Normalize card.expected_goals -> (goals, errors).

    Every entry must be {id, check} with an executable check. Prose
    entries collect as errors — the plan gate rejects the card on any.
    """
    raw = card.get("expected_goals")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["expected_goals must be a list of {id, check} maps"]
    goals, errors = [], []
    for i, g in enumerate(raw):
        if not isinstance(g, dict):
            errors.append(
                f"goal[{i}]: prose entry — needs {{id, check}} with an "
                f"executable check")
            continue
        gid = str(g.get("id") or "").strip()
        check = g.get("check")
        if not gid:
            errors.append(f"goal[{i}]: missing id")
            continue
        if not isinstance(check, str) or not check.strip():
            errors.append(
                f"goal {gid}: missing check — prose goals are not "
                f"verifiable")
            continue
        try:
            parse_check(check)
        except ValueError as e:
            errors.append(f"goal {gid}: {e}")
            continue
        goals.append({"id": gid, "check": check.strip()})
    return goals, errors


# ------------------------------------------------------------------ checks


def _http(code: int, url: str) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "goal-check/1"})
    try:
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:
            got = r.status
    except urllib.error.HTTPError as e:
        got = e.code  # a reached server with the "wrong" code is still info
    except Exception as e:
        return False, f"unreachable: {e}"
    ok = got == code
    return ok, f"GET {url} -> {got} (expected {code})"


def _command(shell: str, expect: str | None, cwd: Path) -> tuple[bool, str]:
    try:
        r = subprocess.run(["bash", "-c", shell], capture_output=True,
                           text=True, cwd=cwd, timeout=CMD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"timeout ({CMD_TIMEOUT}s): {shell[:80]}"
    except Exception as e:
        return False, f"spawn failed: {e}"
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    tail = out.splitlines()[-1][:160] if out else ""
    base = f"exit {r.returncode}" + (f" — {tail}" if tail else "")
    if expect is None:
        return r.returncode == 0, base
    if expect == "exit":
        return r.returncode != 0, f"{base} (expected nonzero exit)"
    m = re.fullmatch(r"exit\s+(-?\d+)", expect)
    if m:
        return r.returncode == int(m.group(1)), \
            f"{base} (expected exit {m.group(1)})"
    hit = expect in out
    return r.returncode == 0 and hit, \
        f"{base} (expect substr {expect[:40]!r}: {'found' if hit else 'absent'})"


def _file_exists(path: str, cwd: Path) -> tuple[bool, str]:
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = cwd / p
    return p.exists(), f"{p} {'exists' if p.exists() else 'missing'}"


def _git_ancestor(branch: str, base: str, cwd: Path) -> tuple[bool, str]:
    r = subprocess.run(["git", "merge-base", "--is-ancestor", branch, base],
                       capture_output=True, text=True, cwd=cwd, timeout=30)
    if r.returncode == 0:
        return True, f"{branch} is an ancestor of {base}"
    if r.returncode == 1:
        return False, f"{branch} is NOT an ancestor of {base}"
    return False, f"git error: {(r.stderr or '').strip()[:160]}"


def _ws(url: str) -> tuple[bool, str]:
    """Real RFC6455 handshake: ok iff the server answers 101."""
    m = re.match(r"^(wss?)://([^/:]+)(?::(\d+))?(/.*)?$", url)
    if not m:
        return False, f"bad ws url: {url}"
    secure = m.group(1) == "wss"
    host = m.group(2)
    port = int(m.group(3) or (443 if secure else 80))
    path = m.group(4) or "/"
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
           f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    try:
        sock = socket.create_connection((host, port), timeout=NET_TIMEOUT)
        if secure:
            sock = ssl.create_default_context().wrap_socket(
                sock, server_hostname=host)
        with sock:
            sock.settimeout(NET_TIMEOUT)
            sock.sendall(req.encode())
            resp = sock.recv(4096).decode(errors="replace")
    except Exception as e:
        return False, f"unreachable: {e}"
    line = resp.splitlines()[0] if resp else "no response"
    ok = " 101 " in line or line.endswith(" 101")
    return ok, f"ws handshake {url} -> {line[:120]}"


def run_goal(goal: dict, cwd: Path | str = ".") -> dict:
    """Execute one goal -> {id, ok, evidence, at}.

    ok is True/False, or None when the check itself was malformed
    (shouldn't happen for goals that passed validate_goals, but a
    hand-edited card can carry prose — the re-prober counts it failed).
    """
    cwd = Path(cwd)
    gid = str(goal.get("id") or "?")
    at = now_iso()
    try:
        spec = parse_check(str(goal.get("check") or ""))
    except ValueError as e:
        return {"id": gid, "ok": None,
                "evidence": f"unparseable check: {e}", "at": at}
    kind = spec[0]
    if kind == "http":
        ok, ev = _http(spec[1], spec[2])
    elif kind == "command":
        ok, ev = _command(spec[1], spec[2], cwd)
    elif kind == "file-exists":
        ok, ev = _file_exists(spec[1], cwd)
    elif kind == "git-ancestor":
        ok, ev = _git_ancestor(spec[1], spec[2], cwd)
    elif kind == "ws":
        ok, ev = _ws(spec[1])
    else:  # pragma: no cover - parse_check restricts kinds
        return {"id": gid, "ok": None, "evidence": f"unhandled {kind}",
                "at": at}
    return {"id": gid, "ok": ok, "evidence": ev[:300], "at": at}


def run_goals(goals: list[dict], cwd: Path | str = ".") -> list[dict]:
    return [run_goal(g, cwd) for g in goals]


def _selftest() -> None:
    ok = lambda s: parse_check(s)  # noqa: E731
    assert ok("http 200 https://x/health") == ("http", 200, "https://x/health")
    assert ok("command echo hi") == ("command", "echo hi", None)
    assert ok("command echo hi expect hi") == ("command", "echo hi", "hi")
    assert ok("command false expect exit") == ("command", "false", "exit")
    assert ok("command x expect exit 3") == ("command", "x", "exit 3")
    assert ok("command echo a expect b expect c") == \
        ("command", "echo a expect b", "c")
    assert ok("file-exists /tmp") == ("file-exists", "/tmp")
    assert ok("git-ancestor HEAD origin/master") == \
        ("git-ancestor", "HEAD", "origin/master")
    assert ok("ws wss://h/ws") == ("ws", "wss://h/ws")
    for bad in ("make it work", "http x http://h", "http 200 h",
                "command", "file-exists a b", "git-ancestor a",
                "ws http://h", "bogus x"):
        try:
            parse_check(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"prose accepted: {bad!r}")

    g, e = validate_goals({"expected_goals": [
        {"id": "a", "check": "file-exists /tmp"},
        "prose goal",
        {"id": "b"},
        {"id": "c", "check": "ship it"},
    ]})
    assert len(g) == 1 and len(e) == 3, (g, e)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "f"
        p.write_text("x")
        r = run_goal({"id": "f", "check": f"file-exists {p}"})
        assert r["ok"] is True and r["at"], r
        r = run_goal({"id": "f", "check": f"file-exists {p}.nope"})
        assert r["ok"] is False
        r = run_goal({"id": "c", "check": "command exit 0"}, cwd=td)
        assert r["ok"] is True
        r = run_goal({"id": "c", "check": "command echo abc expect abc"})
        assert r["ok"] is True, r
        r = run_goal({"id": "c", "check": "command echo abc expect zzz"})
        assert r["ok"] is False
        r = run_goal({"id": "c", "check": "command false expect exit"})
        assert r["ok"] is True, r
        r = run_goal({"id": "c", "check": "command exit 3 expect exit 3"})
        assert r["ok"] is True, r
        r = run_goal({"id": "c", "check": "command exit 3 expect exit 4"})
        assert r["ok"] is False
        r = run_goal({"id": "b", "check": "not a check"})
        assert r["ok"] is None
    print("goals selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
