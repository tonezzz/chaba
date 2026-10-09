#!/usr/bin/env python3
"""session-audit.py — daily Ada voice-session quality audit (headless).

Automates the ada-transcript-audit skill (.devin/skills/ada-transcript-audit)
on a timer so session quality is watched every day, not only when Tony asks.

Window: transcripts on the Ada hosts with mtime > the last-run marker
(~/.local/share/devin/ada-audit-marker on the audit host; absent = 24h).
The marker advances after a successful run — "since last check" stays true.

Sources (all over ssh, BatchMode):
  <host>:~/.local/share/ada/transcripts/2026-*.md   per-turn User/Ada text
  <host>: journalctl --user -u ada-ha-tony          function_call pairs
  mddb ada-ha-events-tony kind=ops-event            containment events
  (post-migration the live unit is on idc03; idc01 keeps the archive —
   both are scanned and deduped by session id.)

Findings per session (skill checklist):
  fail     — tool result ok:False / 'error' / 'err' (excl. confirm+acl)
  confirm  — NOT EXECUTED/needs_confirm round trips (friction, not failure)
  acl      — access-policy denials (correct-by-design friction)
  degraded — ok:True but degraded/quota_exhausted/delivered:0
  phantom  — Ada's reply asserts a completed action but no function_call
             was received for that session inside the turn window
  repeat   — consecutive near-identical user asks (re-prompting)
  latency  — user->ada gap > LATENCY_FLAG_S
  no_result— function_call received with no result inside the window

Outputs (the card's output contract):
  1. ada-ha-scenario-reports  audit/session-<date>   kind: session-audit
  2. ada-cms-pages            ada-session-audit       cms-page-standard page
  3. focus-inbox entries for SURFACED friction (repeated/high-severity —
     single low-sev friction stays on the page; never silently dropped)
  4. recurring signatures (seen >= CARD_MIN_DAYS days, or a high-sev storm)
     -> kanban card via board-api /card, deduped by card id `audit-<sig>`
  5. labeled corpus rows appended on the Ada host to
     ~/.local/share/ada/session-audit-corpus.jsonl — the corpus dir the
     nest loop harvests, rows in bankq-router-corpus shape
     ({at, session, text, label, kind, tool, severity, evidence}).

Runs on tony-dell (ada-session-audit.timer, ~05:30 — before the 07:05
daily-brief). Self-contained install at ~/.local/share/session-audit/
via install-session-audit.sh (log-shipper pattern: a stale repo checkout
can never break the audit).

Usage:
  session-audit.py                     # full run (marker window, publish)
  session-audit.py --dry-run           # compute + print, write nothing
  session-audit.py --since "36 hours ago"   # override window start
  session-audit.py --transcripts-dir D --journal-file F   # fixture mode
  session-audit.py --transcripts-dir D --journal-file F --publish
                                       # fixture run WITH live sinks
  session-audit.py --selftest          # synthetic fixture end-to-end

Env:
  AUDIT_HOSTS          ssh hosts to scan (default "idc03,idc01")
  ADA_TRANSCRIPT_DIR   remote transcript dir (default ~/.local/share/ada/transcripts)
  AUDIT_MARKER         marker path (default ~/.local/share/devin/ada-audit-marker)
  AUDIT_STATE_DIR      history state dir (default ~/.local/share/ada-audit)
  AUDIT_CORPUS_SSH     corpus append host (default idc03; "local" = local file)
  AUDIT_CORPUS_PATH    corpus file (default ~/.local/share/ada/session-audit-corpus.jsonl)
  AUDIT_INBOX_DIR      focus-inbox dir (default served checkout on dell)
  BOARD_API            board api base (default http://127.0.0.1:8787)
  MDDB_BASE_URL        mddb base (default http://100.102.134.91:11023/v1)
  ADA_OPS_COLLECTION   ops events collection (default ada-ha-events-tony)
  AUDIT_LATENCY_S      user->ada flag threshold (default 8)
  AUDIT_SSH_TIMEOUT    per-ssh seconds (default 90)
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - dell has PyYAML
    yaml = None

HOME = Path.home()
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
OPS_COLLECTION = os.environ.get("ADA_OPS_COLLECTION", "ada-ha-events-tony")
REPORTS_COLLECTION = "ada-ha-scenario-reports"
PAGE_COLLECTION = "ada-cms-pages"
PAGE_SLUG = "ada-session-audit"
GENERATOR = "session-audit"

AUDIT_HOSTS = os.environ.get("AUDIT_HOSTS", "idc03,idc01")
TRANSCRIPT_DIR = os.environ.get(
    "ADA_TRANSCRIPT_DIR", "~/.local/share/ada/transcripts")
MARKER = Path(os.environ.get(
    "AUDIT_MARKER", str(HOME / ".local/share/devin/ada-audit-marker")))
STATE_DIR = Path(os.environ.get(
    "AUDIT_STATE_DIR", str(HOME / ".local/share/ada-audit")))
CORPUS_SSH = os.environ.get("AUDIT_CORPUS_SSH", "idc03")
CORPUS_PATH = os.environ.get(
    "AUDIT_CORPUS_PATH", "~/.local/share/ada/session-audit-corpus.jsonl")
INBOX_DIR = Path(os.environ.get(
    "AUDIT_INBOX_DIR",
    str(HOME / "CascadeProjects/chaba-tony-dell/docs/ssot/focus-inbox")))
BOARD_API = os.environ.get("BOARD_API", "http://127.0.0.1:8787").rstrip("/")

SSH_TIMEOUT = int(os.environ.get("AUDIT_SSH_TIMEOUT", "90"))
LATENCY_FLAG_S = float(os.environ.get("AUDIT_LATENCY_S", "8"))
REPEAT_RATIO = 0.78          # consecutive user asks above this = re-prompt
REPEAT_MIN_CHARS = 6         # ignore tiny turns ("yes", "ok")
SURFACE_MIN = 3              # occs in window before a low-sev sig surfaces
SURFACE_CAP = 15             # max inbox entries per run — overflow stays on
                             # the page (never swallowed) + one cap note
CARD_MIN_DAYS = 2            # distinct days seen -> kanban card
CARD_STORM_MIN = 3           # high-sev occs in one window -> card now
HISTORY_KEEP_D = 14
PAGE_HISTORY_DAYS = 7
JOURNAL_LINE_MAX = 2000      # remote-side truncate; error fields lead the dict
EVIDENCE_MAX = 240

SEVERE_OPS = {"phantom_write_claim", "confirm_strip", "tool_storm",
              "actuation_cap"}
SEV_ORDER = {"high": 3, "medium": 2, "low": 1, "info": 0}

# --- regexes ---------------------------------------------------------------
TS = r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
RE_RECV = re.compile(
    r".*" + TS + r".*function_call received id=(?P<cid>\S+) "
    r"name=(?P<name>\w+) args=(?P<args>\{.*)$")
RE_RES = re.compile(
    r".*" + TS + r".*function_call result id=(?P<cid>\S+) "
    r"name=(?P<name>\w+) result=(?P<res>.*)$")
RE_SESS = re.compile(r"session=(?P<sid>[0-9a-f]{6,16})")
RE_TURN = re.compile(
    r"^## (User|Ada)(?: \[(\d{2}):(\d{2}):(\d{2})\])?\s*$")
RE_SESSION_HDR = re.compile(r"^# Ada voice session (\S+)")
# confirm-gate markers: NOT EXECUTED / requires confirmation are error-text
# markers; needs_confirm/would_interrupt are checked as dict keys (quoted
# + colon) so the same words inside a tool's `usage` docstring don't
# misclassify a real ok:False failure as a confirm round-trip.
RE_CONFIRM = re.compile(r"NOT EXECUTED|requires confirmation", re.I)
RE_CONFIRM_KEY = re.compile(
    r"['\"](needs_confirm|would_interrupt)['\"]:\s*(True|[^\s,'\"])")
RE_ACL = re.compile(
    r"access policy|permission-gated|not allowed|permission denied|"
    r"acl deny|outside this session", re.I)
# 'error'/'err' keys are checked only in the head region right after
# result={ — nested 'error' text inside payload strings (e.g. a degraded
# web_search's fallback_error traceback) is not a tool failure.
RE_HEAD_ERR = re.compile(r"^result=\{[^}]{0,400}?['\"]err(or)?['\"]:\s*['\"]?[\w{]")
RE_FAIL = re.compile(r"'ok':\s*False|\"ok\":\s*false")
RE_DEGRADED = re.compile(
    r"'degraded':\s*(?!False|None|'')|quota_exhausted': True|"
    r"'delivered': 0")
# Ada asserting a completed action — kept deliberately narrow; the second
# half of the check (no tool call in the window) is the real guard.
RE_CLAIM = re.compile(
    r"\b(i'?ve|i have|i just)\s+(saved|set|turned|switched|added|created|"
    r"updated|deleted|sent|posted|written|booked|scheduled|restarted|"
    r"muted|lowered|raised|opened|closed|done)\b|"
    r"\b(done|all set|saved it|it's done|that'?s done)\b|"
    r"เรียบร้อย|จัดการแล้ว|ตั้งไว้แล้ว|บันทึก[^ ]*แล้ว|ให้แล้ว|"
    r"เบาลง[^ ]*แล้ว|ดังขึ้น[^ ]*แล้ว|เปิด[^ ]*แล้ว|ปิด[^ ]*แล้ว",
    re.I)


# --- shell / net helpers ----------------------------------------------------

def sh(cmd: list[str], timeout: int = SSH_TIMEOUT, stdin: str = "") -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        return r.returncode, r.stdout
    except subprocess.TimeoutExpired:
        return 124, ""


def ssh(host: str, remote: str, stdin: str = "",
        timeout: int = SSH_TIMEOUT) -> tuple[int, str]:
    return sh(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
               host, remote], timeout=timeout, stdin=stdin)


def post(url: str, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def get(url: str, timeout: int = 20):
    return json.loads(urllib.request.urlopen(url, timeout=timeout).read())


def _literal(text: str):
    """Parse the python-dict-shaped payload; tolerate trailing log junk
    and remote-side truncation (unbalanced braces -> try anyway)."""
    text = text.strip()
    depth, end = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    for cand in (text[:end] if end else text, text):
        try:
            return ast.literal_eval(cand)
        except Exception:
            continue
    return None


def _clip(s: str, n: int = EVIDENCE_MAX) -> str:
    s = " ".join(str(s).split())
    return s[:n] + ("…" if len(s) > n else "")


# --- fetching ----------------------------------------------------------------

def read_marker() -> float:
    try:
        txt = MARKER.read_text().strip()
        try:
            return float(txt)
        except ValueError:
            return datetime.fromisoformat(
                txt.replace("Z", "+00:00")).timestamp()
    except FileNotFoundError:
        return datetime.now(timezone.utc).timestamp() - 86400
    except Exception as exc:
        print(f"warn: marker unreadable ({exc}) — defaulting to 24h",
              file=sys.stderr)
        return datetime.now(timezone.utc).timestamp() - 86400


def bump_marker() -> None:
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")


def fetch_transcripts(host: str, since_epoch: float) -> dict[str, dict]:
    """session_id -> {file, host, turns:[{role, sec, text}], mtime}"""
    remote = (
        f"find {TRANSCRIPT_DIR} -name '2026-*.md' "
        f"-newermt @{int(since_epoch)} -type f 2>/dev/null | sort | "
        "while read -r f; do echo \"@@FILE@@ $f\"; cat \"$f\"; done")
    rc, out = ssh(host, remote)
    if rc != 0:
        print(f"warn: transcript fetch on {host} rc={rc}", file=sys.stderr)
        return {}
    sessions: dict[str, dict] = {}
    fname = None
    buf: list[str] = []
    files: list[tuple[str, list[str]]] = []
    for line in out.splitlines():
        if line.startswith("@@FILE@@ "):
            if fname is not None:
                files.append((fname, buf))
            fname = line[9:].strip()
            buf = []
        else:
            buf.append(line)
    if fname is not None:
        files.append((fname, buf))

    for fpath, lines in files:
        rec = parse_transcript(fpath, lines)
        if rec and rec["session"] not in sessions:
            rec["host"] = host
            sessions[rec["session"]] = rec
    return sessions


def parse_transcript(fpath: str, lines: list[str]) -> dict | None:
    name = Path(fpath).name
    date = name[:10] if re.match(r"^\d{4}-\d{2}-\d{2}-", name) else ""
    sid = name.split("-", 3)[-1].removesuffix(".md")
    turns: list[dict] = []
    cur = None
    for line in lines:
        m = RE_SESSION_HDR.match(line)
        if m:
            sid = m.group(1)
            continue
        m = RE_TURN.match(line.strip())
        if m:
            if cur:
                turns.append(cur)
            sec = (int(m.group(2)) * 3600 + int(m.group(3)) * 60
                   + int(m.group(4))) if m.group(2) else None
            cur = {"role": "user" if m.group(1) == "User" else "ada",
                   "sec": sec, "text": []}
            continue
        if cur is not None and line.strip():
            cur["text"].append(line.strip())
    if cur:
        turns.append(cur)
    for t in turns:
        t["text"] = " ".join(t["text"]).strip()
    if not turns:
        return None
    return {"session": sid, "date": date, "file": name, "turns": turns}


def fetch_journal(host: str, since_epoch: float) -> tuple[bool, list[str]]:
    remote = (
        f"journalctl --user -u ada-ha-tony --since @{int(since_epoch)} "
        "--no-pager 2>/dev/null | grep -E 'function_call (received|result)' "
        f"| cut -c1-{JOURNAL_LINE_MAX}")
    rc, out = ssh(host, remote)
    if rc != 0:
        print(f"warn: journal fetch on {host} rc={rc}", file=sys.stderr)
        return False, []
    return True, out.splitlines()


def parse_journal(lines: list[str]) -> dict[str, dict]:
    """session -> {calls:[{ts_s,sec,name,args,cls,res,latency}], orphans}"""
    # pending keyed by (session, call id) — ids like call_1 repeat per session
    pending: dict[tuple[str, str], dict] = {}
    sessions: dict[str, dict] = defaultdict(lambda: {"calls": []})
    for ln in lines:
        sm = RE_SESS.search(ln)
        sid = sm.group("sid") if sm else "?"
        m = RE_RECV.match(ln)
        if m:
            pending[(sid, m.group("cid"))] = {
                "ts": m.group("ts"), "sec": _ts_sec(m.group("ts")),
                "dsec": _dsec(m.group("ts")), "day": m.group("ts")[:10],
                "name": m.group("name"), "session": sid,
                "args": _literal(m.group("args")) or {}}
            continue
        m = RE_RES.match(ln)
        if not m:
            continue
        cid = m.group("cid")
        rec = pending.pop((sid, cid), None)
        res_txt = "result=" + m.group("res")
        res = _literal(m.group("res"))
        cls, why = classify_result(res_txt, res)
        call = {"ts": m.group("ts"), "sec": _ts_sec(m.group("ts")),
                "dsec": _dsec(m.group("ts")), "day": m.group("ts")[:10],
                "name": m.group("name"), "cls": cls, "why": why,
                "session": sid,
                "args": (rec or {}).get("args") or {},
                "recv_ts": (rec or {}).get("ts"),
                "latency_s": (round(_ts_sec(m.group("ts"))
                                    - rec["sec"], 3)
                              if rec else None)}
        sessions[sid]["calls"].append(call)
        if rec is None:
            sessions[sid].setdefault("orphan_results", 0)
            sessions[sid]["orphan_results"] += 1
    # calls that never produced a result inside the window
    for _key, rec in pending.items():
        s = sessions[rec["session"]]
        s.setdefault("no_result", [])
        s["no_result"].append({"name": rec["name"], "ts": rec["ts"],
                               "dsec": rec["dsec"], "day": rec["day"],
                               "args": rec["args"]})
    for s in sessions.values():
        s["calls"].sort(key=lambda c: c["sec"])
    return sessions


def _ts_sec(ts: str) -> float:
    """Epoch of the naive journal text timestamp — used for deltas only
    (both ends share the same basis, so tz never enters)."""
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S,%f").timestamp()
    except Exception:
        return 0.0


def _dsec(ts: str) -> float:
    """Seconds-of-day (UTC — the Ada hosts and transcripts run UTC) —
    used to place a tool call inside a transcript turn window."""
    try:
        d = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S,%f")
        return d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6
    except Exception:
        return 0.0


def classify_result(raw: str, res) -> tuple[str, str]:
    """(cls, why) — cls: ok|fail|confirm|acl|degraded. `raw` carries the
    'result=' prefix; the parsed dict is preferred (a truncated line can
    still classify via head-region regexes)."""
    if RE_CONFIRM.search(raw):
        return "confirm", "confirm-gate round trip (NOT EXECUTED)"
    if isinstance(res, dict):
        if res.get("needs_confirm") or res.get("would_interrupt"):
            return "confirm", "needs_confirm round trip"
        if res.get("ok") is False or res.get("error") or res.get("err"):
            err = str(res.get("error") or res.get("err") or "ok:false")
            if RE_ACL.search(err):
                return "acl", _clip(err, 160)
            return "fail", _clip(err, 160)
        if res.get("degraded") or res.get("quota_exhausted") or \
                res.get("delivered") == 0:
            return "degraded", _clip(str(res.get("degraded") or
                                         "delivered:0"), 160)
        return "ok", ""
    # unparsed (truncated) — head-region markers only
    if RE_CONFIRM_KEY.search(raw):
        return "confirm", "needs_confirm round trip (unparsed)"
    if RE_ACL.search(raw[:600]):
        return "acl", "access-policy denial"
    if RE_FAIL.search(raw) or RE_HEAD_ERR.match(raw):
        return "fail", "ok:false/error in result (unparsed)"
    if RE_DEGRADED.search(raw):
        return "degraded", "degraded/delivered:0 (unparsed)"
    return "ok", ""


def fetch_ops_events(since_epoch: float) -> list[dict]:
    try:
        docs = post(f"{MDDB}/search", {
            "collection": OPS_COLLECTION,
            "filterMeta": {"kind": ["ops-event"]}, "limit": 300})
    except Exception as exc:
        print(f"warn: ops events fetch failed ({exc})", file=sys.stderr)
        return []
    if not isinstance(docs, list):
        return []
    out = []
    for d in docs:
        meta = d.get("meta") or {}
        ts = (meta.get("ts") or [""])[0]
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.timestamp() < since_epoch:
                continue
        except Exception:
            pass
        out.append({"ts": ts, "type": (meta.get("type") or ["?"])[0],
                    "tool": (meta.get("tool") or [""])[0],
                    "head": (d.get("contentMd") or "").splitlines()[:1]})
    return out


# --- analysis -----------------------------------------------------------------

def analyze_session(sess: dict, calls: list[dict], no_result: list[dict],
                    journal_ok: bool = True) -> list[dict]:
    """Transcript-journal join for one session -> findings list.
    journal_ok=False means the host's journal fetch failed — claim/no-call
    cannot be proven, so phantom detection is disabled for that host."""
    sid = sess["session"]
    findings: list[dict] = []
    turns = sess["turns"]
    sdate = sess.get("date") or ""
    # tool-call positions on the transcript's day axis (UTC seconds-of-day;
    # a call logged the next UTC day maps past 86400 like the turn wrap)
    def _call_pos(c) -> float:
        d = c.get("dsec", 0.0)
        if sdate and c.get("day") and c["day"] > sdate:
            d += 86400
        return d
    call_pos = [_call_pos(c) for c in calls] + [
        _call_pos(c) for c in no_result]

    def had_call_between(lo: float, hi: float) -> bool:
        return any(lo <= s <= hi for s in call_pos)

    prev_user = None
    prev_user_txt = ""
    last_user_txt = ""   # survives ada turns — repeat-ask detection
    for i, t in enumerate(turns):
        if t["role"] == "user":
            if last_user_txt:
                a = " ".join(last_user_txt.lower().split())
                b = " ".join(t["text"].lower().split())
                if len(a) >= REPEAT_MIN_CHARS and len(b) >= REPEAT_MIN_CHARS:
                    ratio = difflib.SequenceMatcher(None, a, b).ratio()
                    if a == b or ratio >= REPEAT_RATIO:
                        findings.append({
                            "kind": "repeat", "severity": "medium",
                            "sig": "repeat:user-reask",
                            "title": "user repeated the same ask",
                            "evidence": _clip(b),
                            "detail": f"turns apart, sim={ratio:.2f}"})
            last_user_txt = t["text"]
            prev_user = t
            prev_user_txt = t["text"]
            continue
        # ada turn following a user turn
        if prev_user is None:
            continue
        if prev_user["sec"] is None or t["sec"] is None:
            prev_user = None
            prev_user_txt = ""
            continue
        gap = t["sec"] - prev_user["sec"]
        if gap < 0:
            gap += 86400   # crossed midnight
        if gap > LATENCY_FLAG_S:
            findings.append({
                "kind": "latency", "severity": "low", "sig": "latency:turn",
                "title": f"slow turn {gap:.0f}s",
                "evidence": _clip(prev_user_txt, 80),
                "detail": f"user {prev_user['sec']} -> ada {t['sec']}"})
        if journal_ok and RE_CLAIM.search(t["text"]) \
                and not had_call_between(prev_user["sec"] - 10,
                                         t["sec"] + 40):
            findings.append({
                "kind": "phantom", "severity": "medium",
                "sig": "phantom:claim-no-call",
                "title": "action claimed with no tool call in the window",
                "evidence": _clip(t["text"]),
                "detail": f"after user: {_clip(prev_user_txt, 80)}"})
        prev_user = None
        prev_user_txt = ""

    for c in calls:
        if c["cls"] == "ok":
            continue
        sev = {"fail": "high", "confirm": "info", "acl": "info",
               "degraded": "medium"}[c["cls"]]
        findings.append({
            "kind": c["cls"], "severity": sev,
            "sig": f"{c['cls']}:{c['name']}",
            "tool": c["name"],
            "title": f"{c['name']} -> {c['cls']}",
            "evidence": _clip(c["why"] or
                              json.dumps(c.get("args") or {},
                                         ensure_ascii=False)),
            "detail": c["ts"][:19]})
    for nr in no_result:
        findings.append({
            "kind": "no_result", "severity": "medium",
            "sig": f"no_result:{nr['name']}", "tool": nr["name"],
            "title": f"{nr['name']} call got no result in-window",
            "evidence": nr["ts"][:19], "detail": ""})
    return findings


# --- history / surfacing -------------------------------------------------------

def history_path() -> Path:
    return STATE_DIR / "friction-history.jsonl"


def load_history() -> list[dict]:
    try:
        return [json.loads(l) for l in
                history_path().read_text().splitlines() if l.strip()]
    except Exception:
        return []


def record_history(sig_counts: Counter, today: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = (datetime.now(timezone.utc).timestamp()
              - HISTORY_KEEP_D * 86400)
    kept = [h for h in load_history()
            if (datetime.fromisoformat(h["date"]).timestamp()
                if re.match(r"^\d{4}-\d{2}-\d{2}$", h.get("date", ""))
                else 0) > cutoff]
    kept += [{"date": today, "sig": sig, "count": n}
             for sig, n in sig_counts.items()]
    history_path().write_text(
        "".join(json.dumps(h) + "\n" for h in kept))


def days_seen(sig: str, hist: list[dict], today: str) -> int:
    return len({h["date"] for h in hist if h["sig"] == sig} | {today})


def surfacing(findings: list[dict], hist: list[dict],
              today: str) -> list[dict]:
    """One row per signature that meets the publish bar — the
    false-positive flood gate (repeated OR high-severity only)."""
    sigs: dict[str, dict] = {}
    counts = Counter(f["sig"] for f in findings)
    for f in findings:
        d = sigs.setdefault(f["sig"], dict(f))
        d["count"] = counts[f["sig"]]
        if SEV_ORDER[f["severity"]] > SEV_ORDER[d["severity"]]:
            d["severity"] = f["severity"]
    out = []
    for sig, d in sigs.items():
        if d["kind"] in ("ok",):
            continue
        sev = d["severity"]
        days = days_seen(sig, hist, today)
        surface = sev == "high" or d["count"] >= SURFACE_MIN or days >= 2
        # cards: real escalation only — high-sev storm in one window, or a
        # medium+ signature recurring across days. info/low recurrence
        # (confirm gates, slow turns) stays an inbox entry, never a card.
        card = (sev == "high" and d["count"] >= CARD_STORM_MIN) or \
               (SEV_ORDER[sev] >= 2 and days >= CARD_MIN_DAYS)
        out.append({**d, "days_seen": days,
                    "surface": surface, "card": surface and card})
    out.sort(key=lambda d: (-SEV_ORDER[d["severity"]],
                            -d["count"], d["sig"]))
    # worst-case flood guard: past the cap a signature is still on the
    # page/doc/corpus — it just doesn't get its own inbox entry this run.
    overflow = sum(1 for d in out if d["surface"]) - SURFACE_CAP
    if overflow > 0:
        for d in [d for d in out if d["surface"]][SURFACE_CAP:]:
            d["surface"] = False
            d["card"] = False
        out.append({"sig": "overflow:surface-cap", "kind": "overflow",
                    "severity": "medium", "count": overflow,
                    "days_seen": 1, "surface": True, "card": False,
                    "title": f"{overflow} more surfaced signature(s) capped",
                    "evidence": "see the ada-session-audit CMS page for the "
                                "full list — raise SURFACE_CAP if legit",
                    "tool": "", "detail": ""})
    return out


# --- sinks ---------------------------------------------------------------------

def corpus_rows(findings: list[dict], sessions: list[dict],
                day: str) -> list[dict]:
    """Labeled rows for the nest-loop corpus dir — bankq-corpus shape."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for s in sessions:
        fs = [f for f in findings if f.get("_session") == s["session"]]
        label = "clean" if not fs else (
            "fail" if any(f["kind"] == "fail" for f in fs) else "friction")
        rows.append({
            "at": now, "session": s["session"], "kind": "session_summary",
            "label": label, "turns": len(s["turns"]),
            "findings": len(fs)})
    for f in findings:
        rows.append({
            "at": now, "session": f.get("_session"), "kind": f["kind"],
            "tool": f.get("tool"), "severity": f["severity"],
            "label": f["kind"], "sig": f["sig"],
            "text": f["evidence"][:400], "title": f["title"]})
    return rows


def append_corpus(rows: list[dict]) -> str:
    if not rows:
        return "0 rows"
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n"
                      for r in rows)
    if CORPUS_SSH == "local":
        try:
            p = Path(CORPUS_PATH).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(payload)
            return f"{len(rows)} rows -> {p}"
        except Exception as exc:
            return f"FAILED {exc}"
    rc, out = ssh(CORPUS_SSH, f"cat >> {CORPUS_PATH}", stdin=payload)
    if rc != 0:
        return f"FAILED rc={rc}"
    return f"{len(rows)} rows -> {CORPUS_SSH}:{CORPUS_PATH}"


def inbox_slug(sig: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sig.lower()).strip("-")[:48]


def write_inbox_entry(sig_row: dict, day: str) -> str:
    if yaml is None:
        return "skipped (no yaml)"
    slug = inbox_slug(sig_row["sig"])
    for d in (INBOX_DIR, INBOX_DIR / "processed"):
        if not d.is_dir():
            continue
        for p in d.glob("*-session-audit.yml"):
            if slug in p.name:
                return f"already filed ({p.name})"
    item = {
        "title": "Focus Inbox Item",
        "subtitle": f"Ada session audit — {sig_row['sig']}",
        "focus": {
            "label": f"ada audit: {sig_row['sig']}",
            "text": (f"Daily session audit {day}: {sig_row['title']} — "
                     f"{sig_row['count']} occurrence(s) in window, seen "
                     f"{sig_row['days_seen']} day(s). Evidence: "
                     f"{sig_row['evidence'][:300]}. Report: CMS page "
                     f"'{PAGE_SLUG}', mddb key audit/session-{day}."),
            "branch": "ada",
            "priority": {"high": "high", "medium": "medium"}.get(
                sig_row["severity"], "low"),
            "status": "draft",
            "tags": ["ada", "session-audit", sig_row["kind"]],
            "missing_info": [
                "Is this a tool bug, a schema/desc issue, or intended friction?",
            ],
        },
        "source": {"session": GENERATOR, "date": day},
    }
    fname = f"{day}-{slug}-session-audit.yml"
    if not INBOX_DIR.is_dir():
        return f"skipped (inbox dir {INBOX_DIR} absent)"
    (INBOX_DIR / fname).write_text(yaml.safe_dump(
        item, sort_keys=False, allow_unicode=True, width=120))
    return f"filed {fname}"


def open_cards() -> list[dict]:
    try:
        data = get(f"{BOARD_API}/cards")
        return [c for c in (data.get("cards") or [])
                if c.get("column") != "done"]
    except Exception as exc:
        print(f"warn: board cards fetch failed ({exc})", file=sys.stderr)
        return []


def file_card(sig_row: dict, day: str, cards: list[dict]) -> str:
    cid = "audit-" + inbox_slug(sig_row["sig"])
    if any(c.get("id") == cid for c in cards):
        return f"card {cid} already open"
    body = {
        "id": cid,
        "title": f"Ada session audit: {sig_row['sig']} "
                 f"({sig_row['days_seen']}d seen)",
        "column": "backlog",
        "priority": {"high": "high"}.get(sig_row["severity"], "medium"),
        "program": "chaba-ci",
        "tags": ["session-audit", "ada", sig_row["kind"]],
        "brief": (f"Recurring session-audit signature '{sig_row['sig']}': "
                  f"{sig_row['title']} — {sig_row['count']}x on {day}, "
                  f"seen on {sig_row['days_seen']} day(s)."),
        "spec": (f"Investigate Ada session-audit signature "
                 f"`{sig_row['sig']}`.\n\nLatest evidence: "
                 f"{sig_row['evidence'][:400]}\n\n"
                 f"Report: CMS page `{PAGE_SLUG}` + MDDB "
                 f"`{REPORTS_COLLECTION}` key `audit/session-{day}`.\n"
                 "Decide: tool bug / schema-description issue / "
                 "display-side / correct-by-design friction; fix or "
                 "document and close."),
        "note": ("Auto-filed by session-audit (dedup on card id "
                 f"{cid}); refiled only if the pattern persists."),
        "from": "devin",
    }
    try:
        r = post(f"{BOARD_API}/card", body)
        return f"card {cid}: {r.get('message', 'ok')}"
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode()[:160]
        except Exception:
            detail = str(exc)
        return f"card {cid} FAILED {exc.code} {detail}"
    except Exception as exc:
        return f"card {cid} FAILED {exc}"


def report_doc_key(day: str) -> str:
    return f"audit/session-{day}"


def scenario_doc(day: str, window: str, sessions: list[dict],
                 findings: list[dict], surfaced: list[dict],
                 ops: list[dict], sinks: dict) -> tuple[str, dict]:
    counts = Counter(f["kind"] for f in findings)
    per_sig = {s["sig"]: s for s in surfaced}
    payload = {
        "date": day, "window": window,
        "sessions": [{"id": s["session"], "file": s["file"],
                      "host": s.get("host"), "turns": len(s["turns"]),
                      "findings": sum(1 for f in findings
                                      if f.get("_session") == s["session"])}
                     for s in sessions],
        "counts": dict(counts),
        "ops_events": dict(Counter(o["type"] for o in ops)),
        "surfaced": [{"sig": s["sig"], "kind": s["kind"], "count": s["count"],
                      "severity": s["severity"], "days_seen": s["days_seen"],
                      "card": s["card"]} for s in surfaced],
        "sinks": sinks,
    }
    lines = [f"# Session audit — {day}", "",
             f"window: {window} · sessions: {len(sessions)} · "
             f"findings: {len(findings)} "
             f"({', '.join(f'{k}={v}' for k, v in counts.most_common()) or 'none'})",
             ""]
    for s in sessions:
        fs = [f for f in findings if f.get("_session") == s["session"]]
        lines.append(f"## {s['session']} — {s['file']} "
                     f"({len(s['turns'])} turns, {len(fs)} findings)")
        for f in fs:
            tag = {"fail": "FAIL", "phantom": "PHANTOM", "repeat": "REPEAT",
                   "confirm": "CONFIRM", "acl": "ACL", "degraded": "DEGRADED",
                   "latency": "SLOW", "no_result": "NORESULT"}.get(
                       f["kind"], f["kind"].upper())
            lines.append(f"- {tag} {f['title']} — {f['evidence']}")
        if not fs:
            lines.append("- clean")
        lines.append("")
    if surfaced:
        lines.append("## Surfaced")
        for s in surfaced:
            if s["surface"]:
                lines.append(
                    f"- **{s['sig']}** ({s['severity']}, {s['count']}x, "
                    f"{s['days_seen']}d) — {s['title']}"
                    + (" → card" if s["card"] else " → inbox"))
        lines.append("")
    lines += ["```json", json.dumps(payload, ensure_ascii=False, indent=1),
              "```", "",
              f"*Generated by {GENERATOR} · {day}Z · sources: "
              f"transcripts+ada-ha-tony journal on {AUDIT_HOSTS}, "
              f"{OPS_COLLECTION}*"]
    meta = {"kind": ["session-audit"], "date": [day],
            "sessions": [str(len(sessions))],
            "findings": [str(len(findings))],
            "fails": [str(counts.get("fail", 0))],
            "surfaced": [str(sum(1 for s in surfaced if s["surface"]))],
            "generated_by": [GENERATOR],
            "ts": [datetime.now(timezone.utc).isoformat(timespec="seconds")]}
    return "\n".join(lines), meta


def prior_audit_docs(limit: int = 40) -> list[dict]:
    try:
        docs = post(f"{MDDB}/search", {
            "collection": REPORTS_COLLECTION,
            "filterMeta": {"kind": ["session-audit"]}, "limit": limit})
    except Exception:
        return []
    rows = []
    for d in docs or []:
        m = d.get("meta") or {}
        rows.append({"key": d.get("key", "?"),
                     "date": (m.get("date") or [""])[0],
                     "sessions": (m.get("sessions") or ["?"])[0],
                     "findings": (m.get("findings") or ["?"])[0],
                     "fails": (m.get("fails") or ["?"])[0],
                     "surfaced": (m.get("surfaced") or ["?"])[0]})
    return sorted(rows, key=lambda r: r["date"], reverse=True)


def render_page(day: str, sessions: list[dict], findings: list[dict],
                surfaced: list[dict], ops: list[dict],
                history: list[dict], doc_key: str) -> str:
    """cms-page-standard layout for the standing audit page."""
    counts = Counter(f["kind"] for f in findings)
    fails = counts.get("fail", 0)
    n_surf = sum(1 for s in surfaced if s["surface"])
    if not sessions:
        status = f"**Status: GREEN — no Ada sessions since the marker ({day}).**"
    elif fails or n_surf:
        status = (f"**Status: ATTENTION — {day}: {len(sessions)} session(s), "
                  f"{fails} tool failure(s), {n_surf} friction signature(s) "
                  "surfaced.**")
    else:
        status = (f"**Status: GREEN — {day}: {len(sessions)} session(s), "
                  f"{len(findings)} minor finding(s), nothing surfaced.**")
    out = ["# Ada session audit — daily transcript + tool-call check", "",
           status, "", "## Latest", ""]
    out.append(f"- **{day}** — {len(sessions)} sessions, "
               f"{len(findings)} findings "
               f"({', '.join(f'{k}={v}' for k, v in counts.most_common()) or 'clean'}), "
               f"{n_surf} surfaced, {len(ops)} ops events")
    for h in history[:4]:
        out.append(f"- **{h['date']}** — {h['sessions']} sessions, "
                   f"{h['findings']} findings, {h['fails']} fails, "
                   f"{h['surfaced']} surfaced")
    out += ["", "Sections: [Today](#today) · [Surfaced](#surfaced) · "
            "[Sessions](#sessions) · [Method](#method)", ""]
    out.append("## Today")
    out.append("")
    if findings:
        out.append("| session | kind | tool | sev | what |")
        out.append("|---|---|---|---|---|")
        for f in findings[:40]:
            out.append(f"| {f.get('_session') or '—'} | {f['kind']} | "
                       f"{f.get('tool') or '—'} | {f['severity']} | "
                       f"{_clip(f['title'] + ' — ' + f['evidence'], 110)} |")
    else:
        out.append("No findings — clean day.")
    out += ["", "## Surfaced", ""]
    surf = [s for s in surfaced if s["surface"]]
    if surf:
        out.append("| signature | sev | count | days | routed to |")
        out.append("|---|---|---|---|---|")
        for s in surf:
            out.append(f"| {s['sig']} | {s['severity']} | {s['count']} | "
                       f"{s['days_seen']} | "
                       f"{'card audit-' + inbox_slug(s['sig']) if s['card'] else 'focus-inbox'} |")
        out.append("")
        out.append("Surfacing bar: severity=high, or ≥3 occurrences in the "
                   "window, or a signature already seen on another day. "
                   "Cards file only when the pattern recurs across days or "
                   "a high-severity signature storms (≥3 in one window).")
    else:
        out.append("Nothing crossed the surfacing bar today.")
    out += ["", "## Sessions", ""]
    out.append("| session | file | host | turns | findings |")
    out.append("|---|---|---|---|---|")
    for s in sessions:
        nf = sum(1 for f in findings if f.get("_session") == s["session"])
        out.append(f"| {s['session']} | {s['file']} | {s.get('host', '?')} | "
                   f"{len(s['turns'])} | {nf} |")
    if ops:
        out += ["", "### Ops events", ""]
        for t, c in Counter(o["type"] for o in ops).most_common():
            flag = " ⚠" if t in SEVERE_OPS else ""
            out.append(f"- {t} ×{c}{flag}")
    out += ["", "## Method", "",
            "Window = transcripts (mtime > `~/.local/share/devin/"
            "ada-audit-marker`) + `journalctl ada-ha-tony` function_call "
            "pairs + `ada-ha-events-tony` ops events, hosts "
            f"`{AUDIT_HOSTS}`. Per session: failed tool results "
            "(ok:false/err), confirm-gate round trips, acl denials, "
            "degraded results, phantom action-claims (claim text with no "
            "call in the turn window), repeated asks, turns slower than "
            f"{LATENCY_FLAG_S:g}s. Structured per-day doc: "
            f"`{REPORTS_COLLECTION}/{doc_key}` (kind=session-audit). "
            "Corpus rows append to "
            f"`{CORPUS_SSH}:{CORPUS_PATH}`.", "",
            f"*Generated by {GENERATOR} · "
            f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z · sources: "
            f"transcripts+journal ({AUDIT_HOSTS}), {OPS_COLLECTION}, "
            f"{REPORTS_COLLECTION} audit/session-**"]
    return "\n".join(out)


def publish_page(md: str, day: str, sessions: list[dict],
                 findings: list[dict], surfaced: list[dict]) -> str:
    h = hashlib.sha256(md.encode()).hexdigest()[:16]
    try:
        old = post(f"{MDDB}/get", {"collection": PAGE_COLLECTION,
                                   "key": PAGE_SLUG, "lang": "en"})
    except Exception:
        old = {}
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in ((old or {}).get("meta") or {}).items()}
    if meta.get("pub_hash") == [h]:
        return "unchanged"
    n_surf = sum(1 for s in surfaced if s["surface"])
    fails = sum(1 for f in findings if f["kind"] == "fail")
    meta.update({
        "kind": ["page"], "attribute": ["page"], "bank": ["cms"],
        "slug": [PAGE_SLUG], "subject": [PAGE_SLUG],
        "title": ["Ada session audit — daily transcript + tool-call check"],
        "format": ["markdown"], "lang": ["en"], "domain": ["ada"],
        "scope": ["tony"], "status": ["active"], "source": ["audit"],
        "generated_by": [GENERATOR], "written_by": [GENERATOR],
        "sources": [f"{REPORTS_COLLECTION}:audit/session-*",
                    f"{OPS_COLLECTION}:ops-event",
                    f"journal:ada-ha-tony@{AUDIT_HOSTS}"],
        "fresh_for": ["26h"], "freshness_slo": ["26h"],
        "updated": [datetime.now(timezone.utc).isoformat(
            timespec="seconds")],
        "last_verified": [day], "pub_hash": [h],
        "summary": [f"{day}: {len(sessions)} sessions, "
                    f"{len(findings)} findings, {fails} fails, "
                    f"{n_surf} surfaced — daily ada session-quality audit"],
    })
    meta.setdefault("valid_from", [day])
    for k in ("superseded_by", "superseded_at", "archived_at"):
        meta.pop(k, None)
    post(f"{MDDB}/add", {"collection": PAGE_COLLECTION, "key": PAGE_SLUG,
                         "lang": "en", "contentMd": md, "meta": meta})
    return "written"


# --- main ---------------------------------------------------------------------

def write_selftest_fixture(root: Path) -> tuple[Path, Path]:
    tdir = root / "transcripts"
    tdir.mkdir(parents=True)
    day = "2026-10-09"
    (tdir / f"{day}-feedface01.md").write_text(
        f"""<!-- ref: transcript:{day}-feedface01 -->
# Ada voice session feedface01

## User [05:10:00]
Can you cast the front camera to screen 1?

## Ada [05:10:04]
Done, the front camera is on screen 1 now.

## User [05:10:20]
Cast the front camera to screen 1

## Ada [05:10:26]
I've put the front camera on screen 1.

## User [05:11:00]
Publish a CMS page about the garden plan.

## Ada [05:11:35]
All set — published the garden plan page.

## User [05:20:00]
Turn on the hallway light.

## Ada [05:20:05]
Done, the hallway light is on.
""", encoding="utf-8")
    j = root / "journal.txt"
    j.write_text(
        """Oct 09 05:10:02 idc03 uvicorn[1]: 2026-10-09 05:10:02,000 INFO voice.provider: session=feedface01 function_call received id=call_1 name=cast_to_screen args={'action': 'play', 'screen': 1}
Oct 09 05:10:03 idc03 uvicorn[1]: 2026-10-09 05:10:03,000 INFO voice.provider: session=feedface01 function_call result id=call_1 name=cast_to_screen result={'ok': False, 'error': 'screen 1 is not a registered display', 'screens': []}
Oct 09 05:10:21 idc03 uvicorn[1]: 2026-10-09 05:10:21,000 INFO voice.provider: session=feedface01 function_call received id=call_2 name=cast_to_screen args={'action': 'play', 'screen': 1}
Oct 09 05:10:22 idc03 uvicorn[1]: 2026-10-09 05:10:22,000 INFO voice.provider: session=feedface01 function_call result id=call_2 name=cast_to_screen result={'ok': False, 'error': 'screen 1 is not a registered display', 'screens': []}
Oct 09 05:10:24 idc03 uvicorn[1]: 2026-10-09 05:10:24,000 INFO voice.provider: session=feedface01 function_call received id=call_3 name=cast_to_screen args={'action': 'play', 'screen': 1, 'confirmed': True}
Oct 09 05:10:25 idc03 uvicorn[1]: 2026-10-09 05:10:25,000 INFO voice.provider: session=feedface01 function_call result id=call_3 name=cast_to_screen result={'ok': False, 'error': 'screen 1 is not a registered display', 'screens': []}
Oct 09 05:11:02 idc03 uvicorn[1]: 2026-10-09 05:11:02,000 INFO voice.provider: session=feedface01 function_call received id=call_4 name=cms_publish_page args={'slug': 'garden-plan'}
Oct 09 05:11:03 idc03 uvicorn[1]: 2026-10-09 05:11:03,000 INFO voice.provider: session=feedface01 function_call result id=call_4 name=cms_publish_page result={'error': 'cms_publish_page failed: NOT EXECUTED — the action did not happen: cms_publish_page requires confirmation'}
Oct 09 05:11:05 idc03 uvicorn[1]: 2026-10-09 05:11:05,000 INFO voice.provider: session=feedface01 function_call received id=call_5 name=web_search args={'query': 'x'}
""", encoding="utf-8")
    return tdir, j


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="",
                    help="override window start (journalctl -since or epoch)")
    ap.add_argument("--marker", default=os.environ.get(
        "AUDIT_MARKER", str(HOME / ".local/share/devin/ada-audit-marker")))
    ap.add_argument("--hosts", default=AUDIT_HOSTS)
    ap.add_argument("--transcripts-dir", default="",
                    help="fixture mode: local transcript dir (no ssh)")
    ap.add_argument("--journal-file", action="append", default=[],
                    help="fixture mode: local journal export (repeatable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + print; no writes, no marker bump")
    ap.add_argument("--no-publish", action="store_true",
                    help="skip mddb/cms/corpus/board writes (inbox+cards too)")
    ap.add_argument("--publish", action="store_true",
                    help="fixture mode: opt in to live mddb/cms/board "
                         "writes (off by default so fixtures never pollute)")
    ap.add_argument("--json", action="store_true",
                    help="dump the findings JSON to stdout")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--day", default="",
                    help="doc/date key override (default today UTC)")
    args = ap.parse_args()

    global MARKER
    MARKER = Path(args.marker).expanduser()

    if args.selftest:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tdir, jf = write_selftest_fixture(Path(td))
            sessions = {}
            for p in sorted(tdir.glob("*.md")):
                rec = parse_transcript(
                    str(p), p.read_text(encoding="utf-8").splitlines())
                if rec:
                    rec["host"] = "fixture"
                    sessions[rec["session"]] = rec
            jsess = parse_journal(
                jf.read_text(encoding="utf-8").splitlines())
            findings = []
            for s in sessions.values():
                j = jsess.get(s["session"], {})
                for f in analyze_session(s, j.get("calls", []),
                                         j.get("no_result", [])):
                    f["_session"] = s["session"]
                    findings.append(f)
            kinds = Counter(f["kind"] for f in findings)
            day = "2026-10-09"
            expect = {"fail": 3, "confirm": 1, "repeat": 1,
                      "latency": 1, "phantom": 1, "no_result": 1}
            bad = {k: (kinds.get(k, 0), v) for k, v in expect.items()
                   if kinds.get(k, 0) != v}
            surfaced = surfacing(findings, [], day)
            md, meta = scenario_doc(
                day, "selftest", list(sessions.values()), findings,
                surfaced, [], {"selftest": "1"})
            page = render_page(day, list(sessions.values()), findings,
                               surfaced, [], [], report_doc_key(day))
            rows = corpus_rows(findings, list(sessions.values()), day)
            ok = (not bad and "audit/session-2026-10-09" ==
                  report_doc_key(day) and "## Today" in page
                  and meta.get("kind") == ["session-audit"]
                  and len(rows) == len(findings) + len(sessions))
            print(json.dumps({"kinds": dict(kinds), "mismatch": bad,
                              "surfaced": [s["sig"] for s in surfaced
                                           if s["surface"]],
                              "rows": len(rows)}, indent=1))
            print("selftest:", "PASS" if ok else "FAIL")
            return 0 if ok else 1

    return _run(args)


def _run(args) -> int:
    day = args.day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fixture = bool(args.transcripts_dir)
    global INBOX_DIR
    if fixture and "AUDIT_INBOX_DIR" not in os.environ:
        # fixture runs default to a sibling out-dir — never the real inbox
        INBOX_DIR = Path(args.transcripts_dir) / "inbox-out"
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
    if fixture:
        since_epoch = 0.0          # fixtures bypass the marker window
    elif args.since:
        since_epoch = _parse_since(args.since)
    else:
        since_epoch = read_marker()   # marker absent -> last 24h
    sessions: dict[str, dict] = {}
    jlines: list[str] = []
    journal_ok: dict[str, bool] = {}
    if fixture:
        for p in sorted(Path(args.transcripts_dir).glob("*.md")):
            rec = parse_transcript(
                str(p), p.read_text(encoding="utf-8").splitlines())
            if rec:
                rec["host"] = "fixture"
                sessions[rec["session"]] = rec
        for jf in args.journal_file:
            jlines += Path(jf).read_text(
                encoding="utf-8", errors="replace").splitlines()
    else:
        for host in [h.strip() for h in args.hosts.split(",") if h.strip()]:
            for sid, rec in fetch_transcripts(host, since_epoch).items():
                sessions.setdefault(sid, rec)
            ok, lines = fetch_journal(host, since_epoch)
            journal_ok[host] = ok
            jlines += lines
    jsess = parse_journal(jlines)
    ops = [] if fixture else fetch_ops_events(since_epoch)

    sess_list = sorted(sessions.values(), key=lambda s: s["file"])
    findings: list[dict] = []
    for s in sess_list:
        j = jsess.get(s["session"], {"calls": [], "no_result": []})
        for f in analyze_session(s, j.get("calls", []),
                                 j.get("no_result", []),
                                 journal_ok.get(s.get("host"), True)):
            f["_session"] = s["session"]
            findings.append(f)
    # journal-side findings for sessions with no transcript in-window
    known = set(sessions)
    for sid, j in sorted(jsess.items()):
        if sid in known or sid == "?":
            continue
        for c in j["calls"]:
            if c["cls"] in ("fail", "degraded"):
                findings.append({
                    "kind": c["cls"], "severity":
                        "high" if c["cls"] == "fail" else "medium",
                    "sig": f"{c['cls']}:{c['name']}", "tool": c["name"],
                    "title": f"{c['name']} -> {c['cls']} "
                             "(no transcript in window)",
                    "evidence": _clip(c["why"]),
                    "detail": c["ts"][:19], "_session": sid})

    for o in ops:
        if o["type"] in SEVERE_OPS:
            findings.append({
                "kind": "ops", "severity": "high", "tool": o["tool"],
                "sig": f"ops:{o['type']}",
                "title": f"ops event {o['type']}",
                "evidence": _clip(o["head"][0] if o["head"] else ""),
                "detail": o["ts"][:19], "_session": ""})

    hist = load_history()
    sig_counts = Counter(f["sig"] for f in findings)
    surfaced = surfacing(findings, hist, day)
    n_surf = sum(1 for s in surfaced if s["surface"])
    print(f"[audit] window since {datetime.fromtimestamp(since_epoch, timezone.utc):%Y-%m-%d %H:%M}Z — "
          f"{len(sess_list)} sessions, {len(findings)} findings, "
          f"{n_surf} surfaced")

    sinks: dict[str, str] = {}
    if args.dry_run:
        for s in surfaced:
            if s["surface"]:
                print(f"  surface {s['sig']} sev={s['severity']} "
                      f"n={s['count']} days={s['days_seen']} "
                      f"card={s['card']}")
        if args.json:
            print(json.dumps({"sessions": len(sess_list),
                              "findings": findings,
                              "surfaced": surfaced}, ensure_ascii=False,
                             indent=1))
        return 0

    # ---- sinks, in order; marker only bumps if all non-fatal steps ran ----
    # fixture mode never touches live mddb/board/remote-corpus unless
    # --publish is passed; corpus may still append when CORPUS_SSH=local.
    publish_live = not args.no_publish and (not fixture or args.publish)
    corpus = corpus_rows(findings, sess_list, day)
    if args.no_publish:
        sinks["corpus"] = "skipped (--no-publish)"
    elif CORPUS_SSH == "local" or publish_live:
        sinks["corpus"] = append_corpus(corpus)
    else:
        sinks["corpus"] = "skipped (fixture — pass --publish to force)"
    print(f"[corpus] {sinks['corpus']}")

    md, meta = scenario_doc(
        day, f">{datetime.fromtimestamp(since_epoch, timezone.utc):%Y-%m-%d %H:%M}Z",
        sess_list, findings, surfaced, ops, sinks)
    if not publish_live:
        sinks["mddb_doc"] = ("skipped (--no-publish)" if args.no_publish
                             else "skipped (fixture — pass --publish)")
        sinks["cms_page"] = sinks["mddb_doc"]
    else:
        try:
            post(f"{MDDB}/add", {"collection": REPORTS_COLLECTION,
                                 "key": report_doc_key(day), "lang": "en",
                                 "contentMd": md, "meta": meta})
            sinks["mddb_doc"] = report_doc_key(day)
        except Exception as exc:
            sinks["mddb_doc"] = f"FAILED {exc}"
        hist_rows = prior_audit_docs()
        page_md = render_page(day, sess_list, findings, surfaced, ops,
                              hist_rows, report_doc_key(day))
        try:
            sinks["cms_page"] = publish_page(
                page_md, day, sess_list, findings, surfaced)
            try:
                repo = Path(__file__).resolve().parents[2]
                sys.path.insert(0, str(repo / "scripts" / "lib"))
                import cms_index
                cms_index.regen_reports_index(MDDB, written_by=GENERATOR)
            except Exception as exc:
                print(f"warn: reports-index regen: {exc}", file=sys.stderr)
        except Exception as exc:
            sinks["cms_page"] = f"FAILED {exc}"
    print(f"[mddb] {sinks.get('mddb_doc')} / [cms] {sinks.get('cms_page')}")

    if not args.no_publish:
        for s in surfaced:
            if not s["surface"]:
                continue
            sinks[f"inbox:{s['sig']}"] = write_inbox_entry(s, day)
            print(f"[inbox] {s['sig']}: {sinks[f'inbox:{s['sig']}']}")
        if publish_live:
            open_now = open_cards()
            for s in surfaced:
                if s["surface"] and s["card"]:
                    sinks[f"card:{s['sig']}"] = file_card(s, day, open_now)
                    print(f"[card] {s['sig']}: {sinks[f'card:{s['sig']}']}")

    record_history(sig_counts, day)
    fatal = any(str(v).startswith("FAILED") for v in sinks.values())
    if fatal:
        print("warn: a sink failed — marker NOT bumped; next run retries "
              "the same window (dedup keeps it quiet)", file=sys.stderr)
        return 1
    bump_marker()
    print(f"[marker] -> {MARKER}")
    return 0


def _parse_since(s: str) -> float:
    s = s.strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    m = re.match(r"^(\d+)\s*(hour|day|minute)s?\s*ago$", s)
    if m:
        mult = {"minute": 60, "hour": 3600, "day": 86400}[m.group(2)]
        return datetime.now(timezone.utc).timestamp() - int(m.group(1)) * mult
    raise SystemExit(f"cannot parse --since {s!r} (ISO or 'N hours ago')")


if __name__ == "__main__":
    sys.exit(main())
