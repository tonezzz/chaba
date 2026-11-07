#!/usr/bin/env python3
"""Read-only OpenCode session audit — parity with the Ada transcript
audit and the Devin session audit (card opencode-session-audit-parity).

Reads the OpenCode session store at
``~/.local/share/opencode/opencode.db`` with SQLite ``mode=ro`` — the
audit never opens the DB writable, never deletes sessions, never
changes models. It walks EVERY session newer than the audit marker
(``~/.local/share/devin/opencode-audit-marker``, override with
``--marker`` / ``$OPENCODE_AUDIT_MARKER``), not just the newest, and
per session reports:

    prompts/task turns · agent/model/provider · tool calls ·
    denied/error calls · write/delete/commit/push attempts (incl.
    mutations smuggled through ``bash``/``python -c`` that tool-name
    accounting misses) · artifact paths and durable-landing verdicts ·
    claims without evidence · input/output/reasoning/cache tokens ·
    wall/step latency · retries · mixed-focus/context contamination ·
    safety flags.

Session claims are cross-checked against the filesystem, git
(``git ls-files`` on surviving worktrees), the committed lane
evidence (``evals/opencode-lane/runs/*/run.json`` +
``events.jsonl`` sessionIDs), the promotion reviews
(``evals/opencode-lane/reports/*promotion-review.json``), and the
shadow benchmark (``evals/shadow/reports/*shadow-benchmark.json``).
Final prose is never trusted alone.

Output: ``evals/opencode-lane/reports/<date>-session-audit.{json,md}``
(override with ``--out``/``--report-prefix``). The marker moves only
after both report files are written. ``--file-cards`` files one
kanban card per durable-artifact miss or safety issue via board-api
(idempotent ids ``audit-oc-<kind>-<suffix>``; duplicates are skipped).

Usage:
    python3 scripts/devnest/opencode_session_audit.py              # since marker
    python3 scripts/devnest/opencode_session_audit.py --all        # full store
    python3 scripts/devnest/opencode_session_audit.py --since 2026-10-27
    python3 scripts/devnest/opencode_session_audit.py --session ses_x ...
    python3 scripts/devnest/opencode_session_audit.py --file-cards
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LANE = REPO / "evals" / "opencode-lane"
RUNS = LANE / "runs"
LANE_REPORTS = LANE / "reports"
SHADOW_REPORTS = REPO / "evals" / "shadow" / "reports"
CARDS_DIR = REPO / "docs" / "ssot" / "kanban" / "cards"

DEFAULT_DB = Path.home() / ".local/share/opencode/opencode.db"
DEFAULT_MARKER = Path.home() / ".local/share/devin/opencode-audit-marker"
DEFAULT_BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000")

DENY_SIGNATURE = "prevents you from using this"

# Profiles whose declared scope is read-only; any mutation there is a
# safety flag, and an unattended run with no lane evidence is ungated.
READONLY_AGENTS = {
    "ops-readonly", "ssot-research", "storage-dryrun", "ops-remote-read",
    "mddb-sequence",
}
# Profiles allowed bounded artifact writes — writes are expected, but
# deletes/commits/pushes/protected-root writes still flag.
BOUNDED_WRITE_AGENTS = {"artifact-write"}
INTERACTIVE_AGENTS = {"build", "plan", "general"}

EPHEMERAL_ROOTS = ("/tmp/", "/var/tmp/", "/dev/shm/", "/run/user/")
PROTECTED_ROOTS = (
    "~/.config/secrets", "~/.ssh", "~/.gnupg", "~/.aws",
)

WRITE_TOOLS = {"write", "edit", "apply", "patch", "multiedit"}

# bash-command mutation classification. Order matters: first match wins.
BASH_MUTATIONS = [
    ("push", re.compile(r"\bgit\s+push\b")),
    ("commit", re.compile(
        r"\bgit\s+(commit|merge|rebase|cherry-pick|revert|tag|am)\b")),
    ("stage", re.compile(r"\bgit\s+(add|rm|mv)\b")),
    ("branch", re.compile(
        r"\bgit\s+(checkout|switch)\b[^\n|;&]*\s-?[bB]\b|\bgit\s+worktree\s+(add|remove)\b")),
    ("delete", re.compile(
        r"\brm\b|\brmdir\b|\bunlink\b|\bfind\b[^\n|;&]*-delete\b"
        r"|\bgit\s+clean\b[^\n|;&]*-[^\s]*f")),
    ("service", re.compile(
        r"\bsystemctl\s+(?!--version)(?:--user\s+)?(start|stop|restart|reload"
        r"|enable|disable|mask|unmask)\b|\bkill(?:all)?\s+-?\d")),
    ("net_write", re.compile(
        r"\bcurl\b[^\n|;&]*(-X\s*(POST|PUT|DELETE|PATCH)|--data|-d\s|-F\s)"
        r"|\bwget\b[^\n|;&]*--post")),
    ("pkg", re.compile(
        r"\b(pip3?|npm|pnpm|yarn|apt(-get)?|brew|cargo|uv)\s+(install|add"
        r"|remove|uninstall|upgrade)\b")),
    ("write", re.compile(
        r"(?<![\d&<>|=+-])>>?(?![\d=&|])|\btee\b|\bsed\b[^\n|;&]*\s-i\b"
        r"|\b(mv|cp|mkdir|touch|ln|chmod|chown|truncate|dd)\b")),
]
PY_SMUGGLED_WRITE = re.compile(
    r"open\s*\([^)]*['\"][wa]x?\+?['\"]|\.write_(text|bytes)\s*\("
    r"|os\.(remove|unlink|rename|makedirs)|shutil\.(rmtree|move|copy)")
PY_NET_WRITE = re.compile(
    r"requests\.(post|put|delete|patch)|urllib\.request\.|urlopen|"
    r"http\.client|socket\.send")

CARD_ID_RE = re.compile(r"kanban card '([a-z0-9][a-z0-9-]{2,80})'")
GENERIC_CARD_RE = re.compile(
    r"\b([a-z][a-z0-9]*-(?:[a-z0-9]+-){2,}[a-z0-9]+)\b")
WORKTREE_RE = re.compile(r"(/[\w.\-/]*dispatch-wt-[\w.\-]+)")
STAGE_LABEL_RE = re.compile(r"\b[sS]([0-5])(?=[-_]|\b)")
PATH_RE = re.compile(r"(/?[\w.\-]+/[\w.\-/]+[\w.\-])")

CLAIM_WRITE = re.compile(
    r"\b(?:wrote|written|saved|created|generated|report (?:is )?at"
    r"|artifact (?:at|landed(?: at)?)|output (?:to|at))\b", re.I)
CLAIM_CARD = re.compile(
    r"\bfiled (?:a |the )?(?:kanban )?card ['\"]?([\w-]+)", re.I)
CLAIM_GIT = re.compile(r"\b(committed|pushed|merged)\b", re.I)
CLAIM_NEG = re.compile(
    r"(?:not|no|nothing|never|without|didn'?t|did not|nor|false|0)"
    r"\W{0,20}$", re.I)
# sentence-scoped negation: "Nothing committed, pushed, or merged" —
# the negation governs every verb until an override word (but/so/
# later...) or 80 chars.
CLAIM_NEG_SENT = re.compile(
    r"\b(?:nothing|no|not|never|without|didn'?t|did not|nor|false)\b"
    r"(?:(?!\b(?:but|however|so|then|later|instead|still)\b).){0,80}$",
    re.I | re.S)
# "the YAML is committed", "files are merged", "will be pushed" —
# passive/modal constructions describe the system, not a claim the
# session performed the action.
CLAIM_PASSIVE = re.compile(
    r"(?:is|are|be|been|being|gets?|getting|will|would|should|must|can"
    r"|may|shall)\s+(?:\w+\s+){0,2}$", re.I)


_TRACKED_CACHE = {}


def _repo_tracked_basename(base: str) -> bool:
    """True if any git-tracked file in this checkout ends with the
    basename — message-mode artifacts land via the runner, not a
    session write call."""
    # generic basenames (report.md, out.json) resolve against
    # everything — only descriptive artifact names count as evidence
    if not base or "/" in base or len(base) < 20:
        return False
    if base in _TRACKED_CACHE:
        return _TRACKED_CACHE[base]
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", f"*{base}"],
            capture_output=True, text=True, timeout=15)
        hit = bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        hit = False
    _TRACKED_CACHE[base] = hit
    return hit


def _claim_real(blob: str, start: int, end: int = None) -> bool:
    """False for JSON keys ("committed": false), negations, and
    passive/modal prose."""
    if end is None:
        end = start
    # sentence scope: "Nothing committed, pushed, or merged" negates
    # every verb in the list, not just the first
    sent_start = max(blob.rfind(". ", 0, start),
                     blob.rfind("\n", 0, start),
                     blob.rfind(";", 0, start),
                     start - 90)
    ctx = blob[max(0, sent_start):start]
    tail = blob[max(0, start - 60):start]
    if (CLAIM_NEG_SENT.search(ctx) or CLAIM_NEG.search(tail)
            or CLAIM_PASSIVE.search(tail)):
        return False
    if tail.rstrip().rstrip("\\").rstrip().endswith('"') and \
            blob[end:].lstrip().lstrip("\\").startswith('"'):
        return False
    return True
CLAIM_PATH = re.compile(
    r"\b(?:wrote|written|saved|created|generated)\b[^\n]{0,80}?"
    r"([\w.\-]+(?:/[\w.\-]+)+)")

SLOW_STEP_S = 60.0
SLOW_TOOL_S = 30.0
TOKEN_MISMATCH_PCT = 0.05

CARDABLE_KINDS = {
    "artifact_not_durable", "denied_tool", "mutating_command",
    "protected_root_write", "ungated_profile_run", "sequence_anomaly",
    "claims_without_evidence", "unsafe_classification",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ms_to_iso(ms) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def iso_to_ms(s: str) -> int:
    s = s.strip()
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.fromisoformat(s + "T00:00:00+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def jloads(text, default=None):
    try:
        return json.loads(text) if text else (default if default is not None else {})
    except (ValueError, TypeError):
        return default if default is not None else {}


# ---------------------------------------------------------------- DB


def open_db(path: Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    return db


def list_sessions(db: sqlite3.Connection, since_ms: int,
                  ids: list) -> list:
    q = ("select id, title, directory, agent, model, permission, "
         "tokens_input, tokens_output, tokens_reasoning, "
         "tokens_cache_read, tokens_cache_write, cost, "
         "summary_additions, summary_deletions, summary_files, "
         "time_created, time_updated, parent_id, version "
         "from session")
    args = []
    conds = []
    if ids:
        conds.append("id in (%s)" % ",".join("?" * len(ids)))
        args.extend(ids)
    elif since_ms:
        conds.append("time_updated > ?")
        args.append(since_ms)
    if conds:
        q += " where " + " and ".join(conds)
    q += " order by time_created"
    return [dict(r) for r in db.execute(q, args)]


def session_messages(db, sid) -> list:
    return [dict(r) for r in db.execute(
        "select id, time_created, data from message "
        "where session_id=? order by time_created", (sid,))]


def session_parts(db, sid) -> list:
    return [dict(r) for r in db.execute(
        "select id, message_id, time_created, data from part "
        "where session_id=? order by time_created", (sid,))]


# ------------------------------------------------------------ analysis


def classify_bash(cmd: str) -> list:
    """Return mutation classes for a shell command string."""
    hits = []
    for kind, rx in BASH_MUTATIONS:
        if rx.search(cmd):
            hits.append(kind)
    if "python" in cmd or "urllib" in cmd:
        if PY_SMUGGLED_WRITE.search(cmd):
            hits.append("write")
        if PY_NET_WRITE.search(cmd):
            hits.append("net_write")
    return sorted(set(hits))


def bash_targets(cmd: str) -> list:
    out = []
    for m in re.finditer(r">>?\s*(/[\w.\-/]+|~[\w.\-/]*)", cmd):
        out.append(m.group(1))
    for m in re.finditer(
            r"\b(?:tee|mv|cp|mkdir|touch|ln|chmod|chown|rm)\s+"
            r"(?:-[\w]+\s+)*(/[\w.\-/]+|~[\w.\-/]*)", cmd):
        out.append(m.group(1))
    return out


def norm_input(tool: str, inp: dict) -> str:
    keep = {k: inp.get(k) for k in
            ("command", "filePath", "path", "pattern", "host",
             "url", "tool") if k in inp}
    return tool + ":" + json.dumps(keep, sort_keys=True)[:300]


def is_durable_path(path: str) -> tuple:
    """(verdict, detail) for a written/claimed artifact path."""
    p = os.path.expanduser(path)
    if any(p.startswith(r) for r in EPHEMERAL_ROOTS):
        return "ephemeral", "under ephemeral root"
    for pr in PROTECTED_ROOTS:
        if p.startswith(os.path.expanduser(pr)):
            return "protected", "under protected root " + pr
    if not os.path.exists(p):
        # dispatch worktrees are deleted after merge — a tracked
        # basename in the served repo means the artifact landed
        if _repo_tracked_basename(os.path.basename(p)):
            return "landed", "worktree gone but tracked in repo"
        return "missing", "not on disk, not tracked in repo"
    try:
        top = subprocess.run(
            ["git", "-C", os.path.dirname(p), "rev-parse",
             "--show-toplevel"],
            capture_output=True, text=True, timeout=10)
        if top.returncode == 0:
            tracked = subprocess.run(
                ["git", "-C", top.stdout.strip(), "ls-files",
                 "--error-unmatch", "--", p],
                capture_output=True, text=True, timeout=10)
            if tracked.returncode == 0:
                return "committed", "exists + git-tracked"
            return "exists_uncommitted", "exists, not git-tracked"
    except (OSError, subprocess.SubprocessError):
        pass
    return "exists", "exists outside git"


def stage_label(sess: dict, prompt_text: str) -> str:
    for src in (sess.get("directory") or "", sess.get("title") or ""):
        m = STAGE_LABEL_RE.search(src)
        if m:
            return "S" + m.group(1)
    head = prompt_text[:400]
    m = re.search(r"\bstage[=:\s]+([sS][0-5])\b", head)
    if m:
        return m.group(1).upper()
    return ""


def audit_session(db, sess: dict, promote_at: dict) -> dict:
    sid = sess["id"]
    msgs = session_messages(db, sid)
    parts = session_parts(db, sid)

    rec = {
        "session_id": sid,
        "title": sess.get("title") or "",
        "directory": sess.get("directory") or "",
        "agent": sess.get("agent") or "",
        "model": "", "provider": "",
        "created": ms_to_iso(sess.get("time_created")),
        "updated": ms_to_iso(sess.get("time_updated")),
        "wall_s": round(((sess.get("time_updated") or 0)
                         - (sess.get("time_created") or 0)) / 1000, 1),
        "parent_id": sess.get("parent_id") or "",
        "prompts": [], "prompt_count": 0,
        "messages": {"user": 0, "assistant": 0},
        "steps": 0,
        "tools": {"total": 0, "by_tool": {}, "denied": 0, "errors": 0,
                  "running_stuck": 0, "invalid": 0,
                  "denied_calls": [], "error_calls": []},
        "mutations": {"writes": [], "deletes": [], "commits": [],
                      "pushes": [], "stages": [], "services": [],
                      "net_writes": [], "pkg": [], "branches": [],
                      "count": 0},
        "artifacts": [],
        "claims_without_evidence": [],
        "tokens": {"input": 0, "output": 0, "reasoning": 0,
                   "cache_read": 0, "cache_write": 0, "cost_usd": 0.0,
                   "session_columns": {
                       "input": sess.get("tokens_input") or 0,
                       "output": sess.get("tokens_output") or 0,
                       "reasoning": sess.get("tokens_reasoning") or 0,
                       "cache_read": sess.get("tokens_cache_read") or 0,
                       "cache_write": sess.get("tokens_cache_write") or 0},
                   "mismatch": False},
        "latency": {"wall_s": 0.0, "step_s_max": 0.0, "step_s_mean": 0.0,
                    "tool_s_max": 0.0, "slow_steps": [], "slow_tools": [],
                    "first_response_s": None},
        "retries": {"count": 0, "pairs": []},
        "contamination": {"card_ids": [], "worktree_roots": [],
                          "outside_root_reads": 0, "flagged": False},
        "stage_label": "",
        "safety_flags": [],
        "findings": [],
        "text_tail": "",
    }

    prompts = []
    models, providers = set(), set()
    step_times = {}
    step_lat = []
    tool_lat = []
    call_seq = []          # (ts, key, status, tool, summary)
    write_paths = []       # (path, via, status)
    last_user_ts = None
    first_resp = None
    final_texts = []
    session_root = (sess.get("directory") or "").rstrip("/")

    for m in msgs:
        d = jloads(m["data"])
        role = d.get("role", "")
        rec["messages"][role] = rec["messages"].get(role, 0) + 1
        if d.get("modelID"):
            models.add(d["modelID"])
        if d.get("providerID"):
            providers.add(d["providerID"])
        if isinstance(d.get("model"), dict):
            if d["model"].get("modelID"):
                models.add(d["model"]["modelID"])
            if d["model"].get("providerID"):
                providers.add(d["model"]["providerID"])
        tok = d.get("tokens") or {}
        cache = tok.get("cache") or {}
        rec["tokens"]["input"] += tok.get("input") or 0
        rec["tokens"]["output"] += tok.get("output") or 0
        rec["tokens"]["reasoning"] += tok.get("reasoning") or 0
        rec["tokens"]["cache_read"] += cache.get("read") or 0
        rec["tokens"]["cache_write"] += cache.get("write") or 0
        t = d.get("time") or {}
        if t.get("created") and t.get("completed"):
            step_lat.append((t["completed"] - t["created"]) / 1000)
        if role == "user":
            last_user_ts = m["time_created"]
        elif role == "assistant" and last_user_ts and first_resp is None:
            first_resp = (t.get("created") or m["time_created"]
                          ) - last_user_ts

    for p in parts:
        d = jloads(p["data"])
        ptype = d.get("type")
        if ptype == "step-start":
            step_times[p["id"]] = p["time_created"]
            rec["steps"] += 1
        elif ptype == "step-finish":
            tok = d.get("tokens") or {}
            cache = tok.get("cache") or {}
        elif ptype == "text":
            txt = d.get("text") or ""
            mid = p.get("message_id", "")
            mrole = next((jloads(m["data"]).get("role") for m in msgs
                          if m["id"] == mid), "")
            if mrole == "user":
                prompts.append(txt)
            else:
                final_texts.append(txt)
        elif ptype == "patch":
            for f in d.get("files") or []:
                write_paths.append((f, "patch", "completed"))
        elif ptype == "tool":
            tool = d.get("tool", "?")
            st = d.get("state") or {}
            status = st.get("status", "?")
            inp = st.get("input") or {}
            rec["tools"]["total"] += 1
            rec["tools"]["by_tool"][tool] = (
                rec["tools"]["by_tool"].get(tool, 0) + 1)
            tt = st.get("time") or {}
            if tt.get("start") and tt.get("end"):
                tool_lat.append(
                    (tool, (tt["end"] - tt["start"]) / 1000))
            summary = json.dumps(inp, sort_keys=True)[:200]
            if status == "error":
                err = st.get("error") or ""
                if DENY_SIGNATURE in err:
                    rec["tools"]["denied"] += 1
                    rec["tools"]["denied_calls"].append(
                        {"tool": tool, "input": summary,
                         "error": err[:200]})
                else:
                    rec["tools"]["errors"] += 1
                    rec["tools"]["error_calls"].append(
                        {"tool": tool, "input": summary,
                         "error": err[:200]})
            elif status == "running":
                rec["tools"]["running_stuck"] += 1
            if tool == "invalid":
                rec["tools"]["invalid"] += 1
            call_seq.append((p["time_created"],
                             norm_input(tool, inp), status, tool,
                             summary))

            # mutation accounting — direct write tools
            if tool in WRITE_TOOLS and status == "completed":
                tgt = inp.get("filePath") or inp.get("path") or ""
                if tgt:
                    write_paths.append((tgt, tool, status))
                    rec["mutations"]["writes"].append(
                        {"tool": tool, "path": tgt})
            elif tool == "write" or tool == "edit":
                tgt = inp.get("filePath") or inp.get("path") or ""
                if tgt and status != "completed":
                    rec["mutations"]["writes"].append(
                        {"tool": tool, "path": tgt,
                         "status": status})

            # mutation accounting — smuggled through bash
            if tool == "bash":
                cmd = inp.get("command") or ""
                for kind in classify_bash(cmd):
                    key = {"push": "pushes", "commit": "commits",
                           "delete": "deletes", "stage": "stages",
                           "service": "services", "net_write":
                           "net_writes", "pkg": "pkg",
                           "branch": "branches"}.get(kind, "writes")
                    rec["mutations"][key].append(
                        {"tool": "bash", "command": cmd[:200],
                         "status": status})
                    if kind == "write":
                        for tgt in bash_targets(cmd):
                            write_paths.append((tgt, "bash", status))

    rec["prompts"] = [p[:300] for p in prompts]
    rec["prompt_count"] = len(prompts)
    rec["model"] = "/".join(sorted(models)) if models else (
        jloads(sess.get("model")).get("id", "")
        if isinstance(sess.get("model"), str) else "")
    if isinstance(sess.get("model"), str) and sess.get("model"):
        md = jloads(sess["model"])
        if not models and md.get("id"):
            rec["model"] = md["id"]
        if md.get("providerID"):
            providers.add(md["providerID"])
    rec["provider"] = "/".join(sorted(providers))
    rec["latency"]["wall_s"] = rec["wall_s"]
    if step_lat:
        rec["latency"]["step_s_max"] = round(max(step_lat), 1)
        rec["latency"]["step_s_mean"] = round(
            sum(step_lat) / len(step_lat), 1)
        rec["latency"]["slow_steps"] = [
            round(s, 1) for s in step_lat if s > SLOW_STEP_S]
    if tool_lat:
        rec["latency"]["tool_s_max"] = round(
            max(t for _, t in tool_lat), 1)
        rec["latency"]["slow_tools"] = [
            {"tool": t, "s": round(v, 1)}
            for t, v in tool_lat if v > SLOW_TOOL_S]
    if first_resp is not None:
        rec["latency"]["first_response_s"] = round(first_resp / 1000, 1)

    # retries: same tool+input re-issued after a non-completed call
    seen_fail = {}
    for ts, key, status, tool, summary in call_seq:
        if status == "completed" and key in seen_fail:
            rec["retries"]["count"] += 1
            rec["retries"]["pairs"].append(
                {"tool": tool, "input": summary})
            seen_fail.pop(key)
        elif status in ("error",):
            seen_fail.setdefault(key, ts)
        elif status == "running":
            pass

    # token reconciliation: message sums vs session columns
    sc = rec["tokens"]["session_columns"]
    for k in ("input", "output", "cache_read", "cache_write"):
        if sc[k] and abs(rec["tokens"][k] - sc[k]) > sc[k] * (
                TOKEN_MISMATCH_PCT):
            rec["tokens"]["mismatch"] = True

    # artifact durability
    seen_paths = set()
    for path, via, status in write_paths:
        ap = os.path.expanduser(path)
        if ap in seen_paths:
            continue
        seen_paths.add(ap)
        verdict, detail = is_durable_path(ap)
        rec["artifacts"].append({"path": ap, "via": via,
                                 "status": status, "verdict": verdict,
                                 "detail": detail})

    # claims without evidence — final assistant text vs tool record
    final_blob = "\n".join(final_texts[-4:])
    rec["text_tail"] = final_blob[-1200:]
    for m in CLAIM_CARD.finditer(final_blob):
        cid = m.group(1)
        if not (CARDS_DIR / f"{cid}.yml").exists():
            rec["claims_without_evidence"].append(
                {"claim": f"filed card {cid}", "evidence":
                 "no card file in docs/ssot/kanban/cards"})
    for m in CLAIM_GIT.finditer(final_blob):
        if not _claim_real(final_blob, m.start(), m.end()):
            continue
        git_done = any(c[3] == "bash" and re.search(
            r"\bgit\s+(commit|push|merge)\b", c[4])
            and c[2] == "completed" for c in call_seq)
        if not git_done:
            rec["claims_without_evidence"].append(
                {"claim": "committed/pushed/merged",
                 "evidence": "no completed git mutation call"})
        break
    for m in CLAIM_PATH.finditer(final_blob):
        p = m.group(1).rstrip(".,)'\"] ")
        if not _claim_real(final_blob, m.start(), m.end()):
            continue
        cands = [os.path.expanduser(p)]
        if not p.startswith("/") and session_root:
            cands.insert(0, os.path.join(session_root, p))
        wrote = any(a["path"] in cands for a in rec["artifacts"])
        landed = wrote or any(os.path.exists(c) for c in cands)
        if not landed:
            # last resort: message-mode artifacts are written by the
            # runner — check the repo index for the basename
            landed = bool(_repo_tracked_basename(
                os.path.basename(p)))
        if not landed:
            rec["claims_without_evidence"].append(
                {"claim": f"wrote {p}",
                 "evidence": "no write call and file absent"})

    # contamination — multiple cards / worktree roots in one session
    cards = set(CARD_ID_RE.findall("\n".join(prompts)))
    blob = "\n".join(prompts + final_texts[-2:])
    cards |= {c for c in GENERIC_CARD_RE.findall(blob)
              if (CARDS_DIR / f"{c}.yml").exists()}
    roots = set()
    all_inputs = "\n".join(c[4] for c in call_seq)
    for w in WORKTREE_RE.findall(all_inputs + "\n" + sess.get(
            "directory") or ""):
        w = w.rstrip("/")
        m = re.match(r"(/[\w.\-/]*dispatch-wt-[\w\-]+?)(?:/|$)", w)
        if m:
            roots.add(m.group(1))
    if session_root and "dispatch-wt" in session_root:
        roots.add(session_root)
    outside = 0
    if session_root:
        for ts, key, status, tool, summary in call_seq:
            try:
                inp = json.loads(summary) if summary else {}
            except ValueError:
                inp = {}
            for k in ("path", "filePath"):
                v = inp.get(k) or ""
                if v.startswith("/") and not v.startswith(
                        session_root) and not any(
                        v.startswith(r) for r in EPHEMERAL_ROOTS):
                    outside += 1
    own_card = ""
    mdir = re.match(r".*dispatch-wt-(.+?)-\d{9,}$", session_root or "")
    if mdir:
        own_card = mdir.group(1)
    foreign = cards - {own_card} if own_card else cards
    rec["contamination"] = {
        "card_ids": sorted(cards), "own_card": own_card,
        "foreign_cards": sorted(foreign),
        "worktree_roots": sorted(roots),
        "outside_root_reads": outside,
        "flagged": len(roots) > 1 or len(foreign) > 1}

    # stage label + sequence anomaly
    rec["stage_label"] = stage_label(sess, "\n".join(prompts))
    if rec["stage_label"]:
        p_at = promote_at.get(rec["stage_label"])
        if p_at and sess.get("time_created") and \
                ms_to_iso(sess["time_created"]) < p_at:
            rec["safety_flags"].append(
                f"sequence_anomaly: labeled {rec['stage_label']} but "
                f"predates promotion at {p_at}")
            rec["findings"].append({
                "kind": "sequence_anomaly", "severity": "high",
                "summary": f"session labeled {rec['stage_label']} ran "
                           f"before the {rec['stage_label']} promotion "
                           f"decision ({p_at})"})

    # safety flags
    ro = rec["agent"] in READONLY_AGENTS
    bw = rec["agent"] in BOUNDED_WRITE_AGENTS
    if rec["tools"]["denied"]:
        rec["safety_flags"].append(
            f"{rec['tools']['denied']} denied tool call(s)")
        sev = "high" if rec["tools"]["denied"] >= 20 else "medium"
        rec["findings"].append({
            "kind": "denied_tool", "severity": sev,
            "summary": f"{rec['tools']['denied']} denied call(s): "
                       + "; ".join(c["tool"] for c in
                                   rec["tools"]["denied_calls"][:4])})
    mut = rec["mutations"]
    # for bounded-write profiles, writes are the job — only the
    # irreversible/out-of-scope classes flag
    mut_kinds = [k for k in ("deletes", "commits", "pushes", "services",
                           "net_writes", "pkg", "stages", "branches")
                 if mut[k]]
    write_flag = bool(mut["writes"]) and not bw
    if write_flag or mut_kinds:
        kinds = (["writes"] if write_flag else []) + mut_kinds
        if ro or (bw and mut_kinds):
            rec["safety_flags"].append(
                "mutation outside profile scope: " + ",".join(kinds))
        rec["findings"].append({
            "kind": "mutating_command",
            "severity": "high" if (ro or (bw and mut_kinds)) else "info",
            "summary": "mutations: " + ",".join(kinds)})
    for a in rec["artifacts"]:
        if a["verdict"] == "protected":
            rec["safety_flags"].append(
                "protected-root write: " + a["path"])
            rec["findings"].append({
                "kind": "protected_root_write", "severity": "high",
                "summary": "write under protected root: " + a["path"]})
        elif a["verdict"] in ("ephemeral", "missing"):
            rec["findings"].append({
                "kind": "artifact_not_durable",
                "severity": "medium" if a["verdict"] == "missing"
                else "info",
                "verdict": a["verdict"],
                "summary": f"{a['verdict']}: {a['path']} "
                           f"(via {a['via']})"})
    if rec["claims_without_evidence"]:
        rec["findings"].append({
            "kind": "claims_without_evidence", "severity": "medium",
            "summary": f"{len(rec['claims_without_evidence'])} "
                       "unverified claim(s): " + "; ".join(
                           c["claim"] for c in
                           rec["claims_without_evidence"][:3])})
    if rec["tokens"]["mismatch"]:
        rec["safety_flags"].append("token accounting mismatch "
                                   "(message sums vs session columns)")
    if rec["tools"]["running_stuck"]:
        rec["safety_flags"].append(
            f"{rec['tools']['running_stuck']} tool call(s) stuck "
            "'running'")
    if rec["contamination"]["flagged"]:
        rec["safety_flags"].append(
            "mixed-focus: "
            + ",".join(rec["contamination"]["card_ids"] or
                       rec["contamination"]["worktree_roots"]))
    mut["count"] = sum(len(mut[k]) for k in mut if k != "count")
    return rec


# ----------------------------------------------------------- reconcile


def load_promotion_map(reports_dir: Path) -> dict:
    """stage -> earliest ISO time a review promoted TO that stage."""
    out = {}
    if not reports_dir.is_dir():
        return out
    for f in sorted(reports_dir.glob("*promotion-review.json")):
        d = jloads(f.read_text())
        tgt = d.get("promote_to")
        at = d.get("at")
        if d.get("decision") == "promote" and tgt and at:
            if tgt not in out or at < out[tgt]:
                out[tgt] = at
    return out


LANE_STATE_DEFAULT = Path(
    os.environ.get("OPENCODE_LANE_STATE")
    or (Path(os.environ.get("XDG_STATE_HOME",
                           Path.home() / ".local/state"))
        / "opencode-lane"))

DISPATCH_RAILS_RE = re.compile(
    r"Rails: you are processing kanban card|dispatch-wt-")
JOB_EPOCH_RE = re.compile(r"-(\d{9,})$")


def load_ledger_epochs(state_dir: Path) -> set:
    """Epochs embedded in metrics.jsonl job_ids — ledger-recorded
    runs (runner-agent records dispatch-rails jobs there too)."""
    out = set()
    f = state_dir / "metrics.jsonl"
    if not f.exists():
        return out
    try:
        for line in f.read_text().splitlines():
            jid = (jloads(line).get("job_id") or "")
            m = JOB_EPOCH_RE.search(jid)
            if m:
                out.add(m.group(1))
    except OSError:
        pass
    return out


def reconcile_lane_runs(db, runs_dir: Path, sessions_by_id: dict,
                        state_dir: Path = LANE_STATE_DEFAULT) -> dict:
    """Join committed lane run evidence + ledger to DB sessions and
    classify governance: lane_gated | ledger_recorded |
    dispatch_rails | interactive | ungated."""
    res = {"runs": [], "ungated_profile_sessions": [],
           "evidence_missing_sessions": [],
           "governance": {"lane_gated": 0, "ledger_recorded": 0,
                          "dispatch_rails": 0, "interactive": 0,
                          "ungated": 0, "other": 0}}
    evidence_sids = set()
    if runs_dir.is_dir():
        for rd in sorted(runs_dir.iterdir()):
            run_json = rd / "run.json"
            ev = rd / "events.jsonl"
            sid = ""
            if ev.exists():
                for line in ev.read_text().splitlines():
                    d = jloads(line)
                    sid = d.get("sessionID") or (
                        (d.get("part") or {}).get("sessionID") or "")
                    if sid:
                        break
            entry = {"run": rd.name, "session_id": sid}
            if run_json.exists():
                rj = jloads(run_json.read_text())
                entry.update({
                    "job": rj.get("job"), "profile": rj.get("profile"),
                    "verdict": rj.get("verdict"),
                    "artifact_landed": rj.get("artifact_landed"),
                    "denials": len(rj.get("denials") or []),
                    "mutating": len(rj.get("mutating") or []),
                    "metric": rj.get("metric") or {}})
            res["runs"].append(entry)
            if sid:
                evidence_sids.add(sid)
            else:
                res["evidence_missing_sessions"].append(rd.name)
    # cross-check run.json metric vs session DB accounting
    for entry in res["runs"]:
        sid = entry["session_id"]
        rec = sessions_by_id.get(sid)
        if not rec:
            continue
        entry["session_found"] = True
        rec["lane_run"] = {k: entry.get(k) for k in
                           ("run", "job", "verdict", "artifact_landed")}
        mt = entry.get("metric") or {}
        inp = mt.get("input_tokens")
        if inp and rec["tokens"]["session_columns"]["input"]:
            delta = abs(inp - rec["tokens"]["session_columns"][
                "input"]) / max(inp, 1)
            entry["input_token_delta"] = round(delta, 3)
            if delta > 0.10:
                rec["safety_flags"].append(
                    f"ledger metric mismatch: run.json input_tokens "
                    f"{inp} vs session "
                    f"{rec['tokens']['session_columns']['input']}")
                rec["findings"].append({
                    "kind": "metric_mismatch", "severity": "medium",
                    "summary": f"run {entry['run']} ledger "
                               f"input_tokens {inp} vs session DB "
                               f"{rec['tokens']['session_columns']['input']}"})
    ledger_epochs = load_ledger_epochs(state_dir)
    gov = res["governance"]
    for sid, rec in sessions_by_id.items():
        agent = rec["agent"]
        d = rec["directory"]
        m = JOB_EPOCH_RE.search(d or "")
        dir_epoch = m.group(1) if m else ""
        rails = ("dispatch-wt-" in d
                 or any(DISPATCH_RAILS_RE.search(p)
                        for p in rec["prompts"]))
        if sid in evidence_sids:
            g = "lane_gated"
        elif dir_epoch and dir_epoch in ledger_epochs:
            g = "ledger_recorded"
        elif rails:
            g = "dispatch_rails"
        elif agent in INTERACTIVE_AGENTS or not agent:
            g = "interactive"
        elif agent in READONLY_AGENTS or agent in BOUNDED_WRITE_AGENTS:
            g = "ungated"
        else:
            g = "other"
        gov[g] = gov.get(g, 0) + 1
        rec["governance"] = g
        if g == "ungated":
            res["ungated_profile_sessions"].append({
                "session_id": sid, "agent": agent,
                "title": rec["title"], "created": rec["created"],
                "directory": d})
            rec["safety_flags"].append(
                "ungated_profile_run: profile "
                f"{agent} ran outside lane gate, dispatch rails, "
                "and ledger")
            rec["findings"].append({
                "kind": "ungated_profile_run", "severity": "high",
                "summary": f"profile {agent} session has no lane "
                           "runs evidence, no ledger record, and no "
                           "dispatch-rails prompt"})
    return res


def reconcile_shadow(shadow_dir: Path, reports_dir: Path) -> dict:
    """Shadow benchmark opencode-arm verdicts vs lane ledger
    aggregate in the promotion reviews."""
    res = {"benchmarks": [], "reviews": [], "discrepancies": []}
    bench_runs = []
    for f in sorted(shadow_dir.glob("*shadow-benchmark.json")):
        d = jloads(f.read_text())
        oc = {r["fixture"]: r for r in d.get("runs", [])
              if r.get("arm") == "opencode"}
        passed = sum(1 for r in oc.values()
                     if r.get("verdict") == "pass")
        entry = {"file": f.name, "at": d.get("at"),
                 "host": d.get("host"), "total": len(oc),
                 "opencode_pass": passed,
                 "per_fixture": {k: v.get("verdict")
                                 for k, v in oc.items()}}
        res["benchmarks"].append(entry)
        bench_runs.append(entry)
    for f in sorted(reports_dir.glob("*promotion-review.json")):
        d = jloads(f.read_text())
        agg = d.get("aggregate") or {}
        res["reviews"].append({
            "file": f.name, "at": d.get("at"), "stage": d.get("stage"),
            "decision": d.get("decision"),
            "jobs": agg.get("jobs"), "verified": agg.get("verified"),
            "rate": agg.get("verified_success_rate")})
        # a promote decision's verified count vs benchmark pass count
        if d.get("decision") == "promote" and bench_runs:
            b = bench_runs[-1]
            if agg.get("verified") != b["opencode_pass"]:
                res["discrepancies"].append({
                    "kind": "ledger_vs_benchmark",
                    "review": f.name,
                    "ledger_verified": agg.get("verified"),
                    "benchmark_pass": b["opencode_pass"],
                    "verdict": "independent executions of the same "
                               "fixtures — flash-lite is "
                               "non-deterministic, so per-run verdict "
                               "divergence is expected; not a ledger "
                               "error unless the SAME session ids "
                               "disagree"})
    return res


# -------------------------------------------------------------- report


def summarize(sessions: list) -> dict:
    return {
        "sessions": len(sessions),
        "messages": sum(sum(s["messages"].values()) for s in sessions),
        "prompts": sum(s["prompt_count"] for s in sessions),
        "tool_calls": sum(s["tools"]["total"] for s in sessions),
        "denied": sum(s["tools"]["denied"] for s in sessions),
        "tool_errors": sum(s["tools"]["errors"] for s in sessions),
        "mutating_calls": sum(s["mutations"]["count"] for s in sessions),
        "artifacts": sum(len(s["artifacts"]) for s in sessions),
        "artifacts_not_durable": sum(
            1 for s in sessions for a in s["artifacts"]
            if a["verdict"] in ("ephemeral", "missing")),
        "claims_without_evidence": sum(
            len(s["claims_without_evidence"]) for s in sessions),
        "tokens": {k: sum(s["tokens"][k] for s in sessions)
                   for k in ("input", "output", "reasoning",
                             "cache_read", "cache_write")},
        "retries": sum(s["retries"]["count"] for s in sessions),
        "flagged_sessions": sum(
            1 for s in sessions if s["safety_flags"]),
        "findings": sum(len(s["findings"]) for s in sessions),
    }


def render_md(report: dict) -> str:
    s = report["summary"]
    L = ["# OpenCode session audit — " + report["generated"][:10], ""]
    L.append(f"window: **{report['window']}** · host store: "
             f"`{report['db']}` (mode=ro) · sessions audited: "
             f"**{s['sessions']}** · messages: {s['messages']}")
    L.append("")
    L.append(f"- prompts: {s['prompts']} · tool calls: "
             f"{s['tool_calls']} · denied: **{s['denied']}** · "
             f"errors: {s['tool_errors']} · retries: {s['retries']}")
    L.append(f"- mutations: **{s['mutating_calls']}** · artifacts: "
             f"{s['artifacts']} ({s['artifacts_not_durable']} not "
             f"durable) · claims w/o evidence: "
             f"{s['claims_without_evidence']}")
    t = s["tokens"]
    L.append(f"- tokens: in {t['input']:,} / out {t['output']:,} / "
             f"reason {t['reasoning']:,} / cache-r {t['cache_read']:,} "
             f"/ cache-w {t['cache_write']:,}")
    L.append(f"- flagged sessions: **{s['flagged_sessions']}** · "
             f"findings: **{s['findings']}**")
    L.append("")
    for sess in report["sessions"]:
        L.append(f"## {sess['session_id']} — {sess['title'][:70]}")
        L.append(f"{sess['created']} → {sess['updated']} "
                 f"({sess['wall_s']}s) · agent `{sess['agent'] or '-'}`"
                 f" · {sess['model'] or '-'} @ {sess['provider'] or '-'}"
                 f" · dir `{sess['directory']}`")
        tl = sess["tools"]
        L.append(f"- prompts {sess['prompt_count']} · tools "
                 f"{tl['total']} {tl['by_tool']} · denied "
                 f"**{tl['denied']}** errors {tl['errors']} · retries "
                 f"{sess['retries']['count']}")
        tk = sess["tokens"]
        L.append(f"- tokens in {tk['input']:,} out {tk['output']:,} "
                 f"cache-r {tk['cache_read']:,} cache-w "
                 f"{tk['cache_write']:,}"
                 + (" · **MISMATCH vs session columns**"
                    if tk["mismatch"] else ""))
        lt = sess["latency"]
        L.append(f"- wall {lt['wall_s']}s · step max/mean "
                 f"{lt['step_s_max']}/{lt['step_s_mean']}s · tool max "
                 f"{lt['tool_s_max']}s"
                 + (f" · slow steps {lt['slow_steps']}"
                    if lt["slow_steps"] else ""))
        if sess.get("lane_run"):
            lr = sess["lane_run"]
            L.append(f"- lane run `{lr.get('run')}` → verdict "
                     f"**{lr.get('verdict')}** artifact_landed="
                     f"{lr.get('artifact_landed')}")
        if sess.get("governance"):
            L.append(f"- governance: {sess['governance']}")
        if sess["mutations"]["count"]:
            L.append(f"- **mutations {sess['mutations']['count']}**: "
                     + ", ".join(k for k in
                                 ("writes", "deletes", "commits",
                                  "pushes", "stages", "branches",
                                  "services", "net_writes", "pkg")
                                 if sess["mutations"][k]))
        for a in sess["artifacts"]:
            mark = (" **NOT DURABLE**" if a["verdict"] in
                    ("ephemeral", "missing", "protected") else
                    " (uncommitted)" if a["verdict"] ==
                    "exists_uncommitted" else "")
            L.append(f"- artifact `{a['path']}` via {a['via']} → "
                     f"{a['verdict']}{mark}")
        for c in sess["claims_without_evidence"]:
            L.append(f"- CLAIM-NO-EVIDENCE: {c['claim']} — "
                     f"{c['evidence']}")
        for fl in sess["safety_flags"]:
            L.append(f"- SAFETY: {fl}")
        for f in sess["findings"]:
            L.append(f"- finding[{f['kind']}] {f['summary']}")
        L.append("")
    r = report["reconcile"]
    L.append("## Reconcile")
    L.append("")
    L.append(f"- lane runs with committed evidence: "
             f"{len(r['lane']['runs'])} · ungated profile sessions: "
             f"**{len(r['lane']['ungated_profile_sessions'])}**")
    g = r["lane"].get("governance", {})
    if g:
        L.append("- governance: " + " · ".join(
            f"{k} {v}" for k, v in sorted(g.items())))
    for u in r["lane"]["ungated_profile_sessions"][:15]:
        L.append(f"  - UNGATED {u['session_id']} "
                 f"({u['agent']}) {u['created']} {u['title'][:60]}")
    for b in r["shadow"]["benchmarks"]:
        L.append(f"- benchmark {b['file']}: opencode "
                 f"{b['opencode_pass']}/{b['total']} pass "
                 f"{b['per_fixture']}")
    for rv in r["shadow"]["reviews"]:
        L.append(f"- review {rv['file']}: {rv['stage']} → "
                 f"{rv['decision']} (jobs {rv['jobs']}, verified "
                 f"{rv['verified']})")
    for d in r["shadow"]["discrepancies"]:
        L.append(f"- DISCREPANCY {d['kind']}: ledger "
                 f"{d['ledger_verified']} vs benchmark "
                 f"{d['benchmark_pass']} — {d['verdict']}")
    L.append("")
    L.append("marker: " + report.get("marker_note", ""))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- cards


def card_id_for(kind: str, session_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", kind.lower()).strip("-")
    suffix = re.sub(r"[^a-z0-9]+", "", session_id.lower())[-8:]
    return f"audit-oc-{slug}-{suffix}"[:80]


def file_cards(report: dict, board_api: str, dry: bool) -> list:
    filed = []
    seen_cards = set()
    for sess in report["sessions"]:
        for f in sess["findings"]:
            if f["kind"] not in CARDABLE_KINDS:
                continue
            if f["severity"] == "info":
                continue
            # enforced denials are the gate working (friction, not a
            # bug) — only storms are cardable
            if f["kind"] == "denied_tool" and f["severity"] != "high":
                continue
            if f["kind"] == "mutating_command" and \
                    f["severity"] != "high":
                continue
            # /tmp canaries are intentionally ephemeral — only
            # genuinely lost durable-path artifacts card
            if f["kind"] == "artifact_not_durable" and \
                    f.get("verdict") != "missing":
                continue
            cid = card_id_for(f["kind"], sess["session_id"])
            if cid in seen_cards:
                continue
            seen_cards.add(cid)
            payload = {
                "id": cid, "from": "devin",
                "title": f"[audit] {f['kind']} in opencode session "
                         f"{sess['session_id'][-12:]}",
                "column": "backlog", "priority": "medium",
                "tags": ["opencode", "audit", f["kind"]],
                "program": "ai-workforce",
                "note": f["summary"],
                "spec": (f"Auto-filed by opencode_session_audit.py "
                         f"{report['generated']}. Session "
                         f"{sess['session_id']} "
                         f"({sess['title'][:80]}). Evidence: "
                         f"{f['summary']}"),
                "on_exists": "error",
            }
            entry = {"card": cid, "kind": f["kind"],
                     "session": sess["session_id"], "status": ""}
            if dry:
                entry["status"] = "dry-run"
                filed.append(entry)
                continue
            try:
                req = urllib.request.Request(
                    board_api.rstrip("/") + "/card",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    jloads(r.read().decode())
                entry["status"] = "filed"
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode()[:200]
                except Exception:
                    pass
                if e.code in (400, 409) and (
                        "exist" in body or "duplicate" in body):
                    entry["status"] = "already-filed"
                else:
                    entry["status"] = f"http-{e.code}:{body[:80]}"
            except Exception as e:  # noqa: BLE001 — audit must not die
                entry["status"] = f"failed:{e}"
            filed.append(entry)
    return filed


# ----------------------------------------------------------------- main


def resolve_marker(path: Path) -> tuple:
    """(since_ms, note). Absent marker -> last 24h, like ada audit."""
    try:
        raw = path.read_text().strip()
        if raw:
            return iso_to_ms(raw), f"marker {raw}"
    except OSError:
        pass
    fallback = datetime.now(timezone.utc) - timedelta(hours=24)
    return int(fallback.timestamp() * 1000), \
        "no marker — default 24h window"


def write_marker(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(now_iso() + "\n")


def run_audit(args) -> dict:
    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"error: no opencode db at {db_path}", file=sys.stderr)
        sys.exit(2)
    db = open_db(db_path)
    if args.session:
        since_ms, note = 0, "explicit --session list"
    elif args.all:
        since_ms, note = 0, "--all (full store)"
    elif args.since:
        since_ms, note = iso_to_ms(args.since), f"--since {args.since}"
    else:
        since_ms, note = resolve_marker(Path(args.marker).expanduser())
    sessions = list_sessions(db, since_ms, args.session or [])

    promote_at = load_promotion_map(
        Path(args.reports_dir).expanduser())
    audited = [audit_session(db, s, promote_at) for s in sessions]
    by_id = {s["session_id"]: s for s in audited}
    lane = reconcile_lane_runs(
        db, Path(args.runs_dir).expanduser(), by_id,
        Path(args.lane_state).expanduser())
    shadow = reconcile_shadow(
        Path(args.shadow_dir).expanduser(),
        Path(args.reports_dir).expanduser())

    report = {
        "generated": now_iso(),
        "db": str(db_path),
        "window": note,
        "sessions": audited,
        "summary": summarize(audited),
        "reconcile": {"lane": lane, "shadow": shadow},
        "cards": [],
        "marker_note": note,
    }
    return report


def write_reports(report: dict, out_dir: Path, prefix: str) -> tuple:
    out_dir.mkdir(parents=True, exist_ok=True)
    jpath = out_dir / f"{prefix}.json"
    mpath = out_dir / f"{prefix}.md"
    jpath.write_text(json.dumps(report, indent=1, default=str) + "\n")
    mpath.write_text(render_md(report))
    return jpath, mpath


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--marker", default=os.environ.get(
        "OPENCODE_AUDIT_MARKER", str(DEFAULT_MARKER)))
    ap.add_argument("--since", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--session", action="append", default=[])
    ap.add_argument("--out", default=str(LANE_REPORTS))
    ap.add_argument("--runs-dir", default=str(RUNS))
    ap.add_argument("--reports-dir", default=str(LANE_REPORTS))
    ap.add_argument("--shadow-dir", default=str(SHADOW_REPORTS))
    ap.add_argument("--lane-state", default=str(LANE_STATE_DEFAULT))
    ap.add_argument("--report-prefix", default="")
    ap.add_argument("--file-cards", action="store_true")
    ap.add_argument("--cards-dry-run", action="store_true")
    ap.add_argument("--board-api", default=DEFAULT_BOARD_API)
    ap.add_argument("--no-marker-update", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    report = run_audit(args)

    if args.file_cards or args.cards_dry_run:
        report["cards"] = file_cards(
            report, args.board_api, dry=args.cards_dry_run)

    prefix = args.report_prefix or (
        report["generated"][:10] + "-session-audit")
    try:
        jpath, mpath = write_reports(
            report, Path(args.out).expanduser(), prefix)
    except OSError as e:
        print(f"error: report write failed: {e}", file=sys.stderr)
        sys.exit(1)

    marker_msg = "marker not updated"
    if (not args.no_marker_update and not args.session
            and not args.since):
        try:
            write_marker(Path(args.marker).expanduser())
            marker_msg = f"marker updated {args.marker}"
        except OSError as e:
            marker_msg = f"marker update FAILED: {e}"
    report["marker_note"] = marker_msg
    # re-write md so it carries the final marker line
    Path(mpath).write_text(render_md(report))
    jpath_obj = Path(jpath)
    jpath_obj.write_text(
        json.dumps(report, indent=1, default=str) + "\n")

    if not args.quiet:
        s = report["summary"]
        print(f"audited {s['sessions']} sessions · findings "
              f"{s['findings']} · flagged {s['flagged_sessions']} · "
              f"denied {s['denied']} · not-durable "
              f"{s['artifacts_not_durable']}")
        print(f"report: {mpath}")
        print(marker_msg)
        if report["cards"]:
            for c in report["cards"]:
                print(f"card {c['status']}: {c['card']}")


if __name__ == "__main__":
    main()
