#!/usr/bin/env python3
"""board-api — write endpoint for the kanban board page.

Binds 127.0.0.1:8787 on tony-dell; Caddy proxies /apps/board-api/* here
(prefix stripped). Each request edits the card YAML in the *served*
checkout (chaba-tony-dell — the web container bind-mounts that tree),
then re-runs render-board.py so cards.json + index.html refresh
immediately. Git persistence is handled by kanban-commit.timer.

Endpoints (after prefix strip):
  GET  /health                       -> {"ok": true}
  GET  /cards                        -> cards.json payload
  POST /action   {id, do, column?, host?}   do: queue|close|hold|retry|claim|move|finish
      close/move->done runs the merge guard (dispatch_repos.guard): a
      dispatch card whose session branch still has commits not in
      origin/<default_branch> gets a comms entry ('unmerged commits
      remain …') and stays in review instead of closing.
      finish {host, ok?, result?} is the remote-runner report path
      (runner-agent.py): only the claiming host may finish; ok:true
      moves the card to review, ok:false marks it failed in place.
  POST /respond  {id, request_id, answer, from?, reopen?}
      also pushes the answer into a running dispatch session: when the
      card's action.status=='running', a kind:"answer" line is appended
      to $DISPATCH_DIR/tasks/<task_id>/answers.jsonl on the runner host
      (ssh for remote runners) — TASK_RAILS tells sessions to poll it.
      Without request_id, answers the card-level `ask:` (structured
      responses, board-structured-responses): {id|card, option: N} picks
      ask.options[N]; {id, text|answer} is free text that resolves to the
      option it uniquely names (id, label, or label prefix — the voice
      path "yes to the disk card" lands on the Yes option). Sets
      ask.status=answered + answer + answered_at, writes the resolved
      label to comms.
  POST /comment  {id, from, text}    from: devin|ada|chaba|tony
      when the card's action.status=='running', comments from ada|tony
      are also pushed into the live session as kind:"comment" lines in
      answers.jsonl — card comms the session weighs as review input
      (Tony's notes, Ada's [opinion]-tagged takes;
      report-loop-comment-delivery). devin|chaba comments are never
      echoed back: a session must not get its own progress posts, and
      chaba system notes are noise.
  POST /request  {id, ask, request_id?, options?, suggested?, from?, to?}
      raises a requests[] entry {id, ask, status: open, at, from, to?};
      `to` defaults to tony (absent = tony). A request targeting tony
      raised by a non-tony actor queues a push notification
      (board_notify.py — HA iPhone push by default, debounced
      BOARD_NOTIFY_DEBOUNCE_S=30s so bursts arrive as one batched
      summary). request-sweep.py re-pings once after 12h unanswered.
      `suggested` must match one of options[] (string, {id,label}, or the
      'id — label' composite) — stored on the entry as a recommendation
      the UI renders ★ + 'accept suggestion'; never auto-applied.
  POST /pipeline {id, opt_in?, pipeline?, stage?, status?, detail?, from?}
      CI pipeline write path (docs/ssot/ssot.ci.yml). opt_in:true sets the
      `pipeline: ci` opt-in; pipeline:{...} merges a full status block
      (stages deep-merged); stage+status records one stage result.
  POST /card     {id?, title, column?, note?, help?, text?, from?,
                  spec?, report?, action?, queue?, brief?, priority?,
                  tags?, program?, blocked_by?, on_exists?}
      creates a card — including ARMED dispatch cards (report-session-loop
      §1a). spec is stored verbatim; when absent and report (a cms slug
      ^[a-z0-9-]{1,80}) is set, spec is composed from REPORT_SPAWN_TEMPLATE
      so every spawn caller files an identical card. action {type:
      dispatch|manual, repo?} — repo must be in the dispatch whitelist
      (dispatch_repos.repos, $DISPATCH_DIR/repos.conf); unknown action
      keys are dropped (a caller cannot pre-seed status/runner). queue:true
      sets action.status=queued in the same locked write — no create+queue
      race. priority ∈ high|medium|low; tags is a list; brief/program/
      blocked_by are pass-throughs. on_exists: 'error' (default — 400 on a
      duplicate id) or 'queue': an existing card that is already
      queued/running returns its status ('already active'), otherwise it
      is re-armed to queued + comms 're-spawned from report page' — a
      second click on a report page's spawn button is safe. Response
      carries id (+ status when the card is armed).

Writes are serialized with an flock so concurrent clicks don't race.
ALL card writes must go through this API — any direct card-YAML edit
outside it (scripts, dispatch rails, hand fixes) must hold LOCK
(/tmp/board-api.lock) first or it races the server.

Write auth (card board-api-auth): POSTs need a verified identity —
either the Tailscale-User-Login header that tailscale serve injects on
tailnet-authed requests, or a direct loopback caller (dispatch rails,
systemd units, card-pipeline — they hit 127.0.0.1:8787 with no
X-Forwarded-For). A LAN client can forge the login header, but Caddy
appends the real client IP to X-Forwarded-For at every hop, so a forged
request still carries a non-tailnet/non-loopback address in the chain
and is denied. Reads (GET /cards, /health) stay open. Caddy also denies
unauthenticated non-GETs at the edge (stacks/web/Caddyfile).
BOARD_API_ALLOWED_LOGINS (comma list) optionally restricts which
tailnet logins may write; unset = any tailnet identity.

Smoke test: python3 scripts/board/board-api.py --selftest
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from pathlib import Path
from urllib.parse import urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch_repos as dr
import board_notify as bn

REPO = Path(__file__).resolve().parent.parent.parent
CARD_DIR = REPO / "docs/ssot/kanban/cards"
RENDER = REPO / "scripts/render-board.py"
LOCK = Path("/tmp/board-api.lock")
PORT = int(os.environ.get("BOARD_API_PORT", "8787"))
ACTORS = {"devin", "ada", "chaba", "tony"}
TRANSITIONS = {"queue", "close", "hold", "retry", "claim", "move",
               "finish"}
COLUMNS = {"backlog", "doing", "review", "done"}

# /card spawn fields (report-session-loop §1a)
REPORT_SLUG_RE = r"[a-z0-9-]{1,80}"
REPORT_SPAWN_TEMPLATE = (
    "Work on the CMS report '{slug}' — \"{title}\".\n"
    "Report: ada-cms-pages/{slug}\n"
    "This card is report-linked (report: {slug}) — read the report first, "
    "keep it updated per the report rails, and post progress to this card."
)
PRIORITIES = {"high", "medium", "low"}
ACTION_TYPES = {"dispatch", "manual"}
# action keys a caller may set — status/runner/task_id are board-owned and
# silently dropped so a spawn can't fake a running card
ACTION_KEYS = ("type", "repo", "host", "labels", "button", "model")

# --- write gate (card board-api-auth) ------------------------------------
LOOPBACK_NETS = [ip_network("127.0.0.0/8"), ip_network("::1/128")]
TRUSTED_NETS = LOOPBACK_NETS + [
    ip_network("100.64.0.0/10"),       # tailnet CGNAT
    ip_network("fd7a:115c:a1e0::/48"), # tailnet ULA
]
ALLOWED_LOGINS = {x.strip() for x in
                  os.environ.get("BOARD_API_ALLOWED_LOGINS", "").split(",")
                  if x.strip()}


def _in_nets(ip_s: str, nets: list) -> bool:
    try:
        ip = ip_address(ip_s)
    except ValueError:
        return False
    return any(ip in n for n in nets)


def caller_identity(headers, peer_ip: str) -> str:
    """Verified writer identity: the tailnet login, 'local' for a direct
    loopback caller, or '' when the request may not write.

    tailscale serve injects Tailscale-User-Login on tailnet-authed
    requests; Caddy appends the real client IP to X-Forwarded-For at
    every hop, so a forged login header from LAN still leaves a LAN
    address in the chain -> denied. Local automation posts straight to
    127.0.0.1:8787 (loopback peer, no XFF) and is trusted."""
    login = (headers.get("Tailscale-User-Login") or "").strip()
    xff = [h.strip() for h in
           (headers.get("X-Forwarded-For") or "").split(",") if h.strip()]
    if login:
        if ALLOWED_LOGINS and login not in ALLOWED_LOGINS:
            return ""
        if _in_nets(peer_ip, TRUSTED_NETS) and \
                all(_in_nets(h, TRUSTED_NETS) for h in xff):
            return login
        return ""
    if not xff and _in_nets(peer_ip, LOOPBACK_NETS):
        return "local"
    return ""


def now() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


def card_path(cid: str) -> Path:
    if not cid or "/" in cid or ".." in cid:
        raise ValueError("bad card id")
    p = CARD_DIR / f"{cid}.yml"
    if not p.exists():
        raise ValueError(f"no card {cid}")
    return p


def load(p: Path) -> dict:
    return yaml.safe_load(p.read_text()) or {}


def save(p: Path, card: dict) -> None:
    p.write_text(
        yaml.safe_dump(card, allow_unicode=True, sort_keys=False, width=110)
    )


def comms_add(card: dict, frm: str, text: str) -> None:
    card.setdefault("comms", []).append(
        {"at": now(), "from": frm, "text": text[:500]}
    )


def actor(body: dict, default: str = "tony") -> str:
    frm = str(body.get("from") or default).strip()
    if frm not in ACTORS:
        raise ValueError(f"from must be one of {sorted(ACTORS)}")
    return frm


def slugify(text: str) -> str:
    """Request id from free-text ask; the hash keeps non-ascii asks and
    near-identical slugs from colliding into false duplicates."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    h = hashlib.sha1(text.encode()).hexdigest()[:6]
    return f"{slug}-{h}" if slug else f"req-{h}"


def apply_merge_guard(card: dict) -> str:
    """review->done gate (card dispatch-merge-guard). Returns a block
    message when the session branch still has commits not in
    origin/<default_branch>; "" when the transition may proceed. Guard
    notes are appended to card comms either way; a guard error never
    wedges the board — it logs and allows."""
    try:
        g = dr.guard(card)
    except Exception as e:
        comms_add(card, "chaba", f"merge guard skipped (error: {e})")
        return ""
    if g["note"]:
        comms_add(card, "chaba", g["note"])
    return "" if g["allowed"] else f"blocked — {g['summary']}"


SESSIONS_DB = Path.home() / ".local/share/devin/cli/sessions.db"
DISPATCH_TASKS = Path(
    os.environ.get("DISPATCH_DIR", str(Path.home() / ".local/share/devin-dispatch"))
) / "tasks"
HOST = os.uname().nodename
# Remote hosts that may have run dispatch tasks (session db + task dir live
# on the runner). action.runner is consulted first; this list is the
# fallback for tasks launched outside kanban-dispatch (e.g. Ada over ssh).
REMOTE_DISPATCH_HOSTS = [
    h.strip() for h in
    os.environ.get("BOARD_REMOTE_DISPATCH_HOSTS", "tony-omen").split(",")
    if h.strip() and h.strip() != HOST
]

# Runs on the runner host via `ssh <host> python3 - <task_id>` — resolves
# transcript.json -> session_id, then sets sessions.hidden=1 there.
REMOTE_HIDE = """
import json, sqlite3, sys
from pathlib import Path
tid = sys.argv[1]
tj = Path.home() / ".local/share/devin-dispatch/tasks" / tid / "transcript.json"
if tj.exists():
    sid = (json.loads(tj.read_text()) or {}).get("session_id") or ""
    db = Path.home() / ".local/share/devin/cli/sessions.db"
    if sid and db.exists():
        con = sqlite3.connect(str(db), timeout=15)
        try:
            cur = con.execute("UPDATE sessions SET hidden=1 WHERE id=?", (sid,))
            con.commit()
            if cur.rowcount:
                print(f"hidden {sid[:12]}")
        finally:
            con.close()
"""


def _hide_local_session(tid: str) -> str:
    """Hide the session locally; returns the session_id on success."""
    tj = DISPATCH_TASKS / tid / "transcript.json"
    if not tj.exists() or not SESSIONS_DB.exists():
        return ""
    sid = (json.loads(tj.read_text()) or {}).get("session_id") or ""
    if not sid:
        return ""
    import sqlite3
    con = sqlite3.connect(f"file:{SESSIONS_DB}?mode=rw", uri=True,
                          timeout=15)
    try:
        cur = con.execute("UPDATE sessions SET hidden=1 WHERE id=?",
                          (sid,))
        con.commit()
        return sid if cur.rowcount else ""
    finally:
        con.close()


def _hide_remote_session(tid: str, host: str) -> str:
    """Hide the session on a remote runner host; returns sid on success."""
    r = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
         host, "python3", "-", tid],
        input=REMOTE_HIDE, capture_output=True, text=True, timeout=30)
    if r.returncode == 0 and (r.stdout or "").startswith("hidden "):
        return r.stdout.split()[-1]
    return ""


def hide_dispatch_session(card: dict) -> None:
    """On close/done: mark the dispatch task's Devin session hidden=1 in
    sessions.db so finished jobs stop cluttering the session list. The
    card's action.task_id names the task dir; transcript.json carries the
    session_id. Tries the local db first, then remote runner hosts.
    Best-effort — never blocks the close."""
    try:
        a = card.get("action") or {}
        tid = a.get("task_id") or ""
        if not tid:
            return
        sid = _hide_local_session(tid)
        if sid:
            comms_add(card, "chaba", f"session {sid}… hidden")
            return
        hosts = []
        runner = (a.get("runner") or "").strip()
        if runner and runner != HOST:
            hosts.append(runner)
        hosts += [h for h in REMOTE_DISPATCH_HOSTS if h not in hosts]
        for host in hosts:
            try:
                sid = _hide_remote_session(tid, host)
            except Exception:
                continue
            if sid:
                comms_add(card, "chaba",
                          f"session {sid}… hidden on {host}")
                return
    except Exception:
        pass


def do_action(card: dict, verb: str, frm: str) -> str:
    a = card.setdefault("action", {})
    card.pop("awaiting_action", None)  # any deliberate action is triage
    st = a.get("status", "idle")
    if verb == "queue":
        if st in ("queued", "running"):
            return f"already {st}"
        a.setdefault("type", "dispatch")
        a["status"] = "queued"
        a.pop("runner", None)   # a re-queue after done/failed must be
        a.pop("task_id", None)  # claimable by any host, not its last one
        a.pop("verified", None)  # stale stamp must not survive a re-queue
        if card.get("column") in ("done", "review"):
            card["column"] = "backlog"
        comms_add(card, frm, "queued for processing")
        return "queued — kanban-dispatch will claim it"
    if verb == "retry":
        a["status"] = "queued"
        prev = a.pop("result", None)
        if prev:
            a["last_failure"] = str(prev)[:300]
        a.pop("runner", None)  # free for any host to re-claim
        a["attempts"] = int(a.get("attempts") or 0) + 1
        a.pop("verified", None)  # a retried card is unverified until it lands
        comms_add(card, frm, "retry requested")
        return "re-queued"
    if verb == "close":
        blocked = apply_merge_guard(card)
        if blocked:
            return blocked
        card["column"] = "done"
        a["status"] = "done"
        comms_add(card, frm, f"closed by {frm}")
        hide_dispatch_session(card)
        return "moved to done"
    if verb == "hold":
        a["status"] = "idle"
        card["column"] = "backlog"
        comms_add(card, frm, "put on hold")
        return "back to backlog"
    raise ValueError(f"unknown verb {verb}")


def do_move(card: dict, body: dict, frm: str = "tony") -> str:
    col = (body.get("column") or "").strip()
    if col not in COLUMNS:
        raise ValueError(f"column must be one of {sorted(COLUMNS)}")
    old = card.get("column", "backlog")
    if col == old:
        return f"already in {col}"
    if col == "done":
        blocked = apply_merge_guard(card)
        if blocked:
            return blocked
    card["column"] = col
    card.pop("awaiting_action", None)  # a manual move is triage too
    if col == "done":
        card.setdefault("action", {})["status"] = "done"
        card.setdefault("claim", {}).pop("session", None)
        hide_dispatch_session(card)
    comms_add(card, frm, f"moved {old} -> {col}")
    return f"moved to {col}"


def do_claim(card: dict, body: dict) -> str:
    """Atomic first-wins claim for multi-host dispatch — runs under the
    request flock so two hosts can't both grab a queued card."""
    a = card.setdefault("action", {})
    if a.get("status") != "queued":
        raise ValueError(f"not claimable (status={a.get('status', 'idle')})")
    host = (body.get("host") or "").strip()
    if not host:
        raise ValueError("claim needs host")
    pinned = a.get("host")
    if pinned and pinned != host:
        raise ValueError(f"card is pinned to {pinned}")
    a["runner"] = host
    a["status"] = "running"  # claimed = running from the board's view;
    # the runner's finish call (or a sweeper) is the only way out
    if card.get("column") == "backlog":
        card["column"] = "doing"
    card.pop("awaiting_action", None)
    comms_add(card, host, "claimed")
    return "claimed"


def do_finish(card: dict, body: dict) -> str:
    """Remote runner reports its claimed task finished — status->done and
    column->review on success, status->failed (card stays put) on failure.
    Only the claiming host may finish a card."""
    a = card.setdefault("action", {})
    host = (body.get("host") or "").strip()
    if not host:
        raise ValueError("finish needs host")
    if a.get("status") != "running":
        raise ValueError(f"not running (status={a.get('status', 'idle')})")
    if a.get("runner") and a["runner"] != host:
        raise ValueError(f"claimed by {a['runner']}")
    ok = bool(body.get("ok", True))
    a["status"] = "done" if ok else "failed"
    result = str(body.get("result") or "").strip()
    if result:
        a["result"] = result[:300]
    if "verified" in body:
        # runner close-out merge result (dispatch-auto-merge): True =
        # session branch landed in origin/<default>; False = checked and
        # NOT merged (conflicts / failed goals — stays for a human)
        a["verified"] = bool(body["verified"])
    if ok:
        card["column"] = "review"
        card.setdefault("claim", {}).pop("session", None)
    comms_add(card, host,
              f"finished ({'ok' if ok else 'failed'})"
              + (f": {result[:120]}" if result else ""))
    return "finished -> review" if ok else "marked failed"


def _opt_label(o) -> str:
    return str(o if not isinstance(o, dict)
               else (o.get("label") or o.get("id") or ""))


def _opt_value(o) -> str:
    return str(o) if not isinstance(o, dict) \
        else str(o.get("id") or o.get("label") or "")


def do_ask_respond(card: dict, body: dict, frm: str) -> str:
    """Answer the card-level `ask:` — one standing decision per card.
    {option: N} picks ask.options[N]; free text is kept verbatim unless it
    uniquely names an option (exact id/label or a unique label prefix),
    which resolves to the canonical label — that's what makes a voice
    answer like "yes" land on the 'Yes — …' option."""
    ask = card.get("ask")
    if isinstance(ask, str):
        ask = {"question": ask}
    if not isinstance(ask, dict) \
            or not str(ask.get("question") or "").strip():
        raise ValueError("no request_id and card has no ask")
    opts = ask.get("options") or []
    answer = ""
    opt = body.get("option")
    if opt is not None and str(opt).strip() != "":
        if not opts:
            raise ValueError("card ask has no options")
        try:
            idx = int(opt)
        except (TypeError, ValueError):
            raise ValueError("option must be an index")
        if not 0 <= idx < len(opts):
            raise ValueError(f"option must be 0..{len(opts) - 1}")
        answer = _opt_label(opts[idx])
    else:
        answer = str(body.get("text") or body.get("answer") or "").strip()
        if not answer:
            raise ValueError("answer required")
        low = answer.lower()
        hit = [o for o in opts
               if low in (_opt_label(o).lower(), _opt_value(o).lower())]
        if not hit:
            hit = [o for o in opts if _opt_label(o).lower().startswith(low)]
        if len(hit) == 1:
            answer = _opt_label(hit[0])
        # ambiguous or unmatched free text stands as its own answer
    if ask.get("status") == "answered" and not body.get("reopen"):
        raise ValueError("ask already answered")
    verb = "re-answered" if ask.get("status") == "answered" else "answered"
    card["ask"] = ask  # writes back the dict when ask was a bare string
    ask["status"] = "answered"
    ask["answer"] = answer[:500]
    ask["answered_at"] = now()
    body["answer"] = answer  # resolved text feeds live-session delivery
    comms_add(card, frm, f"{verb} ask: {answer[:200]}")
    # answer recorded but nothing is armed to act on it — same triage
    # nudge as the requests[] path
    a = card.get("action") or {}
    if (card.get("column") != "done"
            and a.get("status") not in ("queued", "running")):
        card["awaiting_action"] = True
        comms_add(card, "chaba",
                  "answer recorded but no active action — card needs "
                  "triage (queue it, or spec+arm an action)")
    return "answer saved"


def do_respond(card: dict, body: dict, frm: str) -> str:
    rid = str(body.get("request_id") or "").strip()
    if not rid:
        return do_ask_respond(card, body, frm)
    answer = str(body.get("answer") or body.get("text") or "").strip()
    if not answer:
        raise ValueError("answer required")
    for r in card.get("requests") or []:
        if r.get("id") == rid:
            verb = "answered"
            if r.get("status") == "answered":
                if not body.get("reopen"):
                    raise ValueError("already answered")
                verb = "re-answered"
            r["status"] = "answered"
            r["answer"] = answer[:500]
            comms_add(card, frm, f"{verb} {rid}: {answer[:200]}")
            # answer recorded but nothing is armed to act on it —
            # flag for triage so the decision doesn't sit silent
            a = card.get("action") or {}
            if (card.get("column") != "done"
                    and a.get("status") not in ("queued", "running")):
                card["awaiting_action"] = True
                comms_add(card, "chaba",
                          "answer recorded but no active action — card needs "
                          "triage (queue it, or spec+arm an action)")
            return "answer saved"
    raise ValueError(f"no request {rid}")


def _deliver_to_session(card: dict, record: dict) -> str:
    """Best-effort push of one JSON line into a still-running dispatch
    session's $TASK_DIR/answers.jsonl (card board-answer-live-session +
    report-loop-comment-delivery). TASK_RAILS tells sessions to poll that
    file; this is what makes it exist — appended directly for a local
    runner, over ssh for a remote one (same pattern as
    hide_dispatch_session). `at`/`card` are stamped here; callers supply
    the rest ({from, kind, ...}). The record's kind names the line in
    comms notes ('answer delivered…', 'comment saved but…'). Never
    raises: returns a short note for comms, or "" when the card has no
    running dispatch to feed."""
    a = card.get("action") or {}
    if a.get("status") != "running":
        return ""
    kind = str(record.get("kind") or "answer")
    tid = str(a.get("task_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", tid):
        return f"{kind} saved but session delivery skipped (bad task_id)"
    line = json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                       "card": str(card.get("id") or ""), **record},
                      ensure_ascii=False) + "\n"
    runner = str(a.get("runner") or "").strip()
    if not runner or runner == HOST:
        try:
            d = DISPATCH_TASKS / tid
            if d.is_dir():
                with (d / "answers.jsonl").open("a") as f:
                    f.write(line)
                return f"{kind} delivered to running session {tid}"
            if runner:
                return (f"{kind} saved but task dir missing on runner "
                        f"({tid})")
        except OSError as e:
            return f"{kind} saved but session delivery failed: {e}"
    hosts = []
    if runner and runner != HOST:
        if re.fullmatch(r"[A-Za-z0-9_.-]+", runner):
            hosts.append(runner)
        else:
            return f"{kind} saved but bad runner name {runner!r}"
    hosts += [h for h in REMOTE_DISPATCH_HOSTS if h not in hosts]
    for host in hosts:
        try:
            # test -d, not mkdir -p: a fallback host that never ran this
            # task must not grow a phantom task dir holding only answers
            d = f"~/.local/share/devin-dispatch/tasks/{tid}"
            r = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                 host, f"test -d {d} && cat >> {d}/answers.jsonl"],
                input=line, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return (f"{kind} delivered to running session {tid} "
                        f"on {host}")
        except Exception:
            continue
    return f"{kind} saved but session delivery failed (runner unreachable)"


def deliver_answer(card: dict, frm: str, rid: str, answer: str) -> str:
    """/respond path — the answer lands in answers.jsonl as a
    kind:"answer" line, the channel the rails mark authoritative."""
    return _deliver_to_session(
        card, {"from": frm, "kind": "answer",
               "request_id": rid, "answer": answer[:500]})


# Only voices a running session should hear mid-run: Tony's notes and
# Ada's [opinion]-tagged takes. A session's own devin progress posts must
# not echo back into its input, and chaba system notes are noise.
COMMENT_DELIVER_FROM = {"ada", "tony"}


def deliver_comment(card: dict, frm: str, text: str) -> str:
    """/comment path (report-session-loop §3a): while the card's dispatch
    session runs, ada|tony comms land in answers.jsonl as kind:"comment"
    lines — review input to weigh, not answers. Other actors' comments
    are never pushed. Same never-raises contract as _deliver_to_session.
    """
    if frm not in COMMENT_DELIVER_FROM:
        return ""
    return _deliver_to_session(
        card, {"from": frm, "kind": "comment", "text": text[:500]})


def do_request(card: dict, body: dict) -> str:
    ask = str(body.get("ask") or "").strip()
    if not ask:
        raise ValueError("ask required")
    frm = actor(body)
    to = str(body.get("to") or "tony").strip()
    if to not in ACTORS:
        raise ValueError(f"to must be one of {sorted(ACTORS)}")
    rid = str(body.get("request_id") or "").strip() or slugify(ask)
    reqs = card.setdefault("requests", [])
    if any(r.get("id") == rid for r in reqs):
        raise ValueError(f"duplicate request id {rid}")
    req = {"id": rid, "ask": ask, "status": "open",
           "at": now(), "from": frm}
    if to != "tony":
        req["to"] = to  # absent = tony
    if body.get("options"):
        req["options"] = body["options"]
    sug = str(body.get("suggested") or "").strip()
    if sug:
        valid = set()
        for o in req.get("options") or []:
            if isinstance(o, str):
                valid.add(o)
            else:
                valid.update(str(o.get(k) or "") for k in ("id", "label"))
                valid.add(f"{o.get('id')} — {o.get('label', '')}")
        if not valid:
            raise ValueError("suggested requires options")
        if sug not in valid:
            raise ValueError("suggested must match one of the options")
        req["suggested"] = sug
    reqs.append(req)
    comms_add(card, frm, f"raised request {rid}: {ask[:120]}")
    return f"request {rid} raised"


def do_create(body: dict, frm: str) -> dict:
    """Create a new card — the capture end of the request lifecycle
    (card request-lifecycle) and, with the spawn fields, the card half of
    the report→session loop (report-session-loop §1a). Voice/Ada and
    local automation can drop a bare ask onto the board without a repo
    checkout. Fails closed on a duplicate id unless on_exists:'queue',
    which re-arms the existing card — a second click on a report page's
    spawn button re-queues instead of duplicating."""
    title = str(body.get("title") or "").strip()
    if not title:
        raise ValueError("title required")
    cid = str(body.get("id") or "").strip() or slugify(title)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", cid):
        raise ValueError("id must match [a-z0-9-] (got " + cid + ")")
    col = str(body.get("column") or "backlog").strip()
    if col not in COLUMNS:
        raise ValueError(f"column must be one of {sorted(COLUMNS)}")
    report = str(body.get("report") or "").strip()
    if report and not re.fullmatch(REPORT_SLUG_RE, report):
        raise ValueError("report must match ^[a-z0-9-]{1,80}")
    act = body.get("action")
    if act is not None:
        if not isinstance(act, dict):
            raise ValueError("action must be an object")
        if str(act.get("type") or "") not in ACTION_TYPES:
            raise ValueError(
                f"action.type must be one of {sorted(ACTION_TYPES)}")
        repo = str(act.get("repo") or "").strip()
        if repo and repo not in dr.repos():
            raise ValueError(
                f"action.repo {repo!r} is not in the dispatch whitelist")
    on_exists = str(body.get("on_exists") or "error").strip()
    if on_exists not in ("error", "queue"):
        raise ValueError("on_exists must be error|queue")
    pri = str(body.get("priority") or "").strip()
    if pri and pri not in PRIORITIES:
        raise ValueError(f"priority must be one of {sorted(PRIORITIES)}")
    tags = body.get("tags")
    if tags is not None and not isinstance(tags, list):
        raise ValueError("tags must be a list")

    p = CARD_DIR / f"{cid}.yml"
    if p.exists():
        if on_exists == "error":
            raise ValueError(f"card {cid} already exists")
        card = load(p)
        a = card.setdefault("action", {})
        st = a.get("status", "idle")
        if st in ("queued", "running"):
            return {"message": f"card {cid} already active ({st})",
                    "id": cid, "status": st}
        a.setdefault("type", "dispatch")
        a["status"] = "queued"
        a.pop("runner", None)   # same re-arm semantics as /action do=queue
        a.pop("task_id", None)
        if card.get("column") in ("done", "review"):
            card["column"] = "backlog"
        comms_add(card, frm, "re-spawned from report page")
        card["updated"] = now()
        save(p, card)
        return {"message": f"card {cid} re-queued",
                "id": cid, "status": "queued"}

    card = {"id": cid, "title": title[:160], "column": col,
            "updated": now()}
    brief = str(body.get("brief") or "").strip()
    if brief:
        card["brief"] = brief[:600]
    if pri:
        card["priority"] = pri
    if report:
        card["report"] = report
    for key in ("program", "blocked_by"):
        v = str(body.get(key) or "").strip()
        if v:
            card[key] = v[:120]
    if tags:
        card["tags"] = [str(t)[:40] for t in tags][:20]
    spec = str(body.get("spec") or "").strip()
    if not spec and report:
        spec = REPORT_SPAWN_TEMPLATE.format(slug=report, title=title)
    if spec:
        card["spec"] = spec[:12000]
    if act is not None:
        card["action"] = {k: act[k] for k in ACTION_KEYS if k in act}
        card["action"]["type"] = str(card["action"]["type"])
        if "repo" in card["action"]:
            card["action"]["repo"] = repo
        if "labels" in card["action"]:
            labels = card["action"]["labels"]
            if not isinstance(labels, list):
                raise ValueError("action.labels must be a list")
            card["action"]["labels"] = [str(x)[:40] for x in labels][:10]
        if "model" in card["action"]:
            model = str(card["action"]["model"]).strip()
            if not re.fullmatch(r"[a-zA-Z0-9._-]{1,40}", model):
                raise ValueError("action.model must be a model id "
                                 "([a-zA-Z0-9._-], max 40)")
            card["action"]["model"] = model
    if body.get("queue"):
        a = card.setdefault("action", {})
        a.setdefault("type", "dispatch")
        a["status"] = "queued"
    note = str(body.get("note") or "").strip()
    if note:
        card["note"] = note[:500]
    help_txt = str(body.get("help") or "").strip()
    if help_txt:
        card["help"] = help_txt[:4000]
    card["comms"] = [{"at": now(), "from": frm,
                      "text": str(body.get("text") or
                                   "card captured via board-api")[:500]}]
    save(p, card)
    msg = f"card {cid} created in {col}"
    res = {"message": msg, "id": cid}
    a = card.get("action") or {}
    if a.get("status"):
        res["status"] = a["status"]
        if a["status"] == "queued":
            res["message"] = msg + " (queued)"
    return res


# --- request push notifications (card kanban-push-notify) ---------------
# New requests fire a push after a short debounce so a burst of /request
# POSTs arrives as ONE batched summary, not a ping storm. Pending items
# are in-process only — a restart loses at most the pending pings, and
# request-sweep.py re-pings unanswered requests after 12h anyway.
NOTIFY_DEBOUNCE_S = float(os.environ.get("BOARD_NOTIFY_DEBOUNCE_S", "30"))
_notify_pending: list = []
_notify_timer: threading.Timer | None = None
_notify_lock = threading.Lock()


def request_needs_notify(req: dict) -> bool:
    """Push only requests that target tony and weren't raised by him —
    anything else (to:ada, self-notes) stays quiet."""
    return req.get("to", "tony") == "tony" and req.get("from") != "tony"


def _req_line(cid: str, req: dict) -> str:
    opts = ""
    if req.get("options"):
        labels = [str(o) if not isinstance(o, dict)
                  else str(o.get("label") or o.get("id"))
                  for o in req["options"]]
        opts = f"  [{' / '.join(labels[:4])}]"
    return f"• {cid}: {str(req.get('ask'))[:80]}{opts}"


def _flush_request_notify() -> None:
    global _notify_timer
    with _notify_lock:
        items, _notify_pending[:] = _notify_pending[:], []
        _notify_timer = None
    if not items:
        return
    if len(items) == 1:
        cid, req = items[0]
        bn.send("Board request — needs Tony",
                f"{cid}: {str(req.get('ask'))[:180]}")
    else:
        body = "\n".join(_req_line(c, r) for c, r in items[:10])
        if len(items) > 10:
            body += f"\n… +{len(items) - 10} more"
        bn.send(f"Board: {len(items)} new requests", body)


def queue_request_notify(cid: str, req: dict) -> None:
    global _notify_timer
    with _notify_lock:
        _notify_pending.append((cid, req))
        if _notify_timer is None:
            _notify_timer = threading.Timer(
                NOTIFY_DEBOUNCE_S, _flush_request_notify)
            _notify_timer.daemon = True
            _notify_timer.start()


PIPELINE_STAGES = {"plan", "structure", "develop", "audit", "benchmark",
                   "verify"}
PIPELINE_STATUSES = {"pass", "fail", "skip", "delegated", "blocked",
                     "running"}


def do_pipeline(card: dict, body: dict, frm: str) -> str:
    """CI pipeline write path — see docs/ssot/ssot.ci.yml.

    Accepts either a full status block ({pipeline: {...}} — stages are
    deep-merged so partial updates don't clobber earlier stages) or a
    single stage result ({stage, status, detail?}). opt_in:true writes
    the `pipeline: ci` shorthand; opt_in:false removes the block."""
    if "opt_in" in body:
        if body["opt_in"]:
            if not isinstance(card.get("pipeline"), dict):
                card["pipeline"] = "ci"
            else:
                card["pipeline"]["opt_in"] = "ci"
        else:
            card.pop("pipeline", None)
            comms_add(card, frm, "pipeline opt-in removed")
            return "pipeline opt-in removed"

    pipe = body.get("pipeline")
    if isinstance(pipe, dict):
        cur = card.get("pipeline")
        if not isinstance(cur, dict):
            cur = {"opt_in": "ci", "stages": {}}
        merged = dict(cur)
        stages = dict(merged.get("stages") or {})
        for name, res in (pipe.get("stages") or {}).items():
            if name not in PIPELINE_STAGES:
                raise ValueError(f"stage must be one of {sorted(PIPELINE_STAGES)}")
            stages[name] = res
        merged["stages"] = stages
        for k, v in pipe.items():
            if k != "stages":
                merged[k] = v
        merged["opt_in"] = "ci"
        card["pipeline"] = merged
    elif body.get("stage"):
        stage = body["stage"]
        if stage not in PIPELINE_STAGES:
            raise ValueError(f"stage must be one of {sorted(PIPELINE_STAGES)}")
        status = body.get("status")
        if status not in PIPELINE_STATUSES:
            raise ValueError(f"status must be one of {sorted(PIPELINE_STATUSES)}")
        cur = card.get("pipeline")
        if not isinstance(cur, dict):
            cur = {"opt_in": "ci", "stages": {}}
        cur.setdefault("stages", {})[stage] = {
            "status": status, "at": now(),
            "detail": str(body.get("detail") or "")[:300]}
        card["pipeline"] = cur
    elif "opt_in" not in body:
        raise ValueError("pipeline, stage, or opt_in required")

    stages = (card.get("pipeline") or {}).get("stages") \
        if isinstance(card.get("pipeline"), dict) else None
    summary = " ".join(f"{n}={s.get('status')}" for n, s in
                       (stages or {}).items()) or "opt-in"
    comms_add(card, frm, f"pipeline updated: {summary}"[:500])
    return "pipeline updated"


def render() -> None:
    # own lock, not the card lock — renders may serialize among themselves
    # without blocking card mutations
    with Path("/tmp/board-render.lock").open("w") as rl:
        fcntl.flock(rl, fcntl.LOCK_EX)
        subprocess.run(
            [sys.executable, str(RENDER)], cwd=REPO, timeout=60, check=False
        )


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("board-api %s\n" % (fmt % args))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {"ok": True})
        if path == "/cards":
            j = REPO / "stacks/web/public/apps/board/cards.json"
            if j.exists():
                return self._send(200, json.loads(j.read_text()))
            return self._send(404, {"error": "no cards.json yet"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", 0)) or b"0") or b"{}")
        except Exception:
            return self._send(400, {"error": "bad json"})

        ident = caller_identity(self.headers, self.client_address[0])
        if not ident:
            return self._send(403, {
                "error": "writes need a tailnet identity "
                         "(Tailscale-User-Login) or a local caller"})
        sys.stderr.write(
            "board-api write %s id=%s via=%s\n"
            % (path, body.get("id") or body.get("card"), ident))

        notify_req = None
        resp_extra = {}
        with LOCK.open("w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                if path == "/action":
                    verb = body.get("do", "queue")
                    if verb not in TRANSITIONS:
                        raise ValueError(f"do must be one of {sorted(TRANSITIONS)}")
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    if verb == "claim":
                        msg = do_claim(card, body)
                    elif verb == "move":
                        msg = do_move(card, body, actor(body))
                    elif verb == "finish":
                        msg = do_finish(card, body)
                    else:
                        msg = do_action(card, verb, actor(body))
                    card["updated"] = now()
                    save(p, card)
                elif path == "/respond":
                    frm = actor(body)
                    p = card_path(body.get("id") or body.get("card") or "")
                    card = load(p)
                    msg = do_respond(card, body, frm)
                    note = deliver_answer(
                        card, frm,
                        str(body.get("request_id") or "").strip() or "ask",
                        str(body.get("answer") or "").strip())
                    if note:
                        comms_add(card, "chaba", note)
                        msg += f" — {note}"
                    card["updated"] = now()
                    save(p, card)
                elif path == "/comment":
                    frm = actor(body, default="")
                    text = str(body.get("text") or "").strip()
                    if not text:
                        raise ValueError("text required")
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    comms_add(card, frm, text)
                    msg = "comment added"
                    note = deliver_comment(card, frm, text)
                    if note:
                        comms_add(card, "chaba", note)
                        msg += f" — {note}"
                    card["updated"] = now()
                    save(p, card)
                elif path == "/request":
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    msg = do_request(card, body)
                    card["updated"] = now()
                    save(p, card)
                    req = card["requests"][-1]
                    if request_needs_notify(req):
                        notify_req = (card.get("id") or body.get("id"), req)
                        msg += " — notify queued"
                elif path == "/card":
                    frm = actor(body)
                    res = do_create(body, frm)
                    msg = res["message"]
                    resp_extra = {k: v for k, v in res.items()
                                  if k != "message"}
                elif path == "/pipeline":
                    frm = actor(body)
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    msg = do_pipeline(card, body, frm)
                    card["updated"] = now()
                    save(p, card)
                else:
                    return self._send(404, {"error": "not found"})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        # card lock released — queue the push (debounced, best-effort) and
        # render under its own lock so neither stalls other writers
        if notify_req:
            try:
                queue_request_notify(*notify_req)
            except Exception as e:
                sys.stderr.write(f"board-api notify queue failed: {e}\n")
        render()
        self._send(200, {"ok": True, "message": msg, "via": ident,
                         **resp_extra})


def _selftest() -> None:
    """Pure-function smoke test — no HTTP, no card files.
    Run: python3 scripts/board/board-api.py --selftest"""
    def rejects(fn, frag):
        try:
            fn()
        except ValueError as e:
            assert frag in str(e), f"expected {frag!r} in {e!r}"
            return
        raise AssertionError(f"expected ValueError {frag!r}")

    card = {"requests": [{"id": "r1", "ask": "pick one", "status": "open"}]}
    rejects(lambda: do_respond(card, {"request_id": "r1", "answer": " "}, "tony"),
            "answer required")
    rejects(lambda: do_respond(card, {"request_id": "nope", "answer": "x"}, "tony"),
            "no request")
    do_respond(card, {"request_id": "r1", "answer": "yes"}, "ada")
    assert card["requests"][0]["status"] == "answered"
    assert any(m["from"] == "ada" and "answered r1" in m["text"]
               for m in card["comms"])
    assert card.get("awaiting_action") is True  # no armed action -> nudge
    rejects(lambda: do_respond(card, {"request_id": "r1", "answer": "b"}, "tony"),
            "already answered")
    do_respond(card, {"request_id": "r1", "answer": "b", "reopen": True}, "tony")
    assert card["requests"][0]["answer"] == "b"
    assert any("re-answered r1" in m["text"] for m in card["comms"])

    # card-level ask — structured responses (board-structured-responses):
    # /respond with no request_id answers ask.options[N] or free text
    acard = {"id": "c-ask", "column": "backlog",
             "ask": {"question": "ship it?",
                     "options": ["Yes — go", {"id": "n", "label": "No — hold"}]}}
    rejects(lambda: do_respond(acard, {}, "tony"), "answer required")
    rejects(lambda: do_respond(acard, {"option": "x"}, "tony"),
            "option must be an index")
    rejects(lambda: do_respond(acard, {"option": 5}, "tony"),
            "option must be 0..1")
    do_respond(acard, {"option": 0}, "tony")
    assert acard["ask"]["status"] == "answered"
    assert acard["ask"]["answer"] == "Yes — go"
    assert acard["ask"]["answered_at"]
    assert any(m["from"] == "tony" and "answered ask: Yes — go" in m["text"]
               for m in acard["comms"])
    assert acard.get("awaiting_action") is True  # same triage nudge
    rejects(lambda: do_respond(acard, {"option": 1}, "tony"),
            "ask already answered")
    do_respond(acard, {"option": 1, "reopen": True}, "tony")
    assert acard["ask"]["answer"] == "No — hold"
    assert any("re-answered ask" in m["text"] for m in acard["comms"])

    # free text resolves a unique option — voice path "yes to the disk card"
    bcard = {"ask": {"question": "q",
                     "options": ["Yes — full B+C", "No — keep warm-standby"]}}
    do_respond(bcard, {"text": "yes"}, "tony")
    assert bcard["ask"]["answer"] == "Yes — full B+C"
    ccard = {"ask": {"question": "q",
                     "options": [{"id": "a", "label": "A"},
                                 {"id": "b", "label": "B"}]}}
    do_respond(ccard, {"text": "b"}, "tony")
    assert ccard["ask"]["answer"] == "B"
    # unmatched / ambiguous free text stands verbatim
    dcard = {"ask": {"question": "q", "options": ["red", "green"]}}
    do_respond(dcard, {"text": "blue"}, "tony")
    assert dcard["ask"]["answer"] == "blue"
    fcard = {"ask": {"question": "q", "options": ["yes a", "yes b"]}}
    do_respond(fcard, {"text": "yes"}, "tony")
    assert fcard["ask"]["answer"] == "yes"
    # no ask + no request_id -> clear error, not a silent miss
    rejects(lambda: do_respond({}, {"answer": "x"}, "tony"),
            "no request_id and card has no ask")
    # bare-string ask normalizes to a dict on first answer
    ecard = {"ask": "keep going?"}
    do_respond(ecard, {"text": "y"}, "tony")
    assert ecard["ask"]["status"] == "answered"
    # option answer resolves into body['answer'] for session delivery
    gcard = {"ask": {"question": "q", "options": ["go"]}}
    gbody = {"option": 0}
    do_respond(gcard, gbody, "tony")
    assert gbody["answer"] == "go"

    # _deliver_to_session — /respond on a running card lands in the
    # session's task dir as answers.jsonl (board-answer-live-session);
    # /comment from ada|tony lands as kind:"comment" lines
    # (report-loop-comment-delivery)
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    globals()["DISPATCH_TASKS"] = tmp / "tasks"
    sess = tmp / "tasks" / "20990101-000000-test_sess"
    sess.mkdir(parents=True)
    assert deliver_answer({"action": {"status": "queued"}},
                          "tony", "r1", "x") == ""        # not running
    run = {"id": "zz-test", "action": {"status": "running",
                      "task_id": sess.name, "runner": HOST}}
    note = deliver_answer(run, "tony", "r1", "go left")
    assert "delivered" in note, note
    lines = (sess / "answers.jsonl").read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["request_id"] == "r1" and rec["answer"] == "go left"
    assert rec["from"] == "tony" and rec["at"] and rec["card"] == "zz-test"
    assert rec["kind"] == "answer"
    note = deliver_answer(run, "tony", "r1", "again")     # appends
    assert len((sess / "answers.jsonl").read_text().splitlines()) == 2
    # bad ids / missing dirs degrade to a note, never raise
    assert "skipped" in deliver_answer(
        {"action": {"status": "running", "task_id": "../x"}},
        "tony", "r", "a")
    note = deliver_answer({"action": {"status": "running",
                                      "task_id": "20990101-nope",
                                      "runner": HOST}}, "tony", "r", "a")
    assert "task dir missing" in note, note
    assert "bad runner" in deliver_answer(
        {"action": {"status": "running", "task_id": "t",
                    "runner": "-oProxyCommand=evil"}},
        "tony", "r", "a")

    # kind:"comment" — tony/ada comments reach the live session as review
    # input; devin/chaba comments never echo back; a non-running card
    # delivers nothing
    def n_lines():
        return len((sess / "answers.jsonl").read_text().splitlines())

    note = deliver_comment(run, "tony", "looks right so far")
    assert "delivered" in note, note
    rec = json.loads((sess / "answers.jsonl").read_text().splitlines()[-1])
    assert rec["kind"] == "comment" and rec["from"] == "tony"
    assert rec["text"] == "looks right so far" and "request_id" not in rec
    assert rec["at"] and rec["card"] == "zz-test"
    note = deliver_comment(run, "ada", "[opinion] ship it")
    assert "delivered" in note, note
    rec = json.loads((sess / "answers.jsonl").read_text().splitlines()[-1])
    assert rec["kind"] == "comment" and rec["from"] == "ada"
    n = n_lines()
    assert deliver_comment(run, "devin", "progress post") == ""
    assert deliver_comment(run, "chaba", "system note") == ""
    assert n_lines() == n
    assert deliver_comment({"action": {"status": "done"}},
                           "tony", "late note") == ""

    rejects(lambda: do_request(card, {"ask": "  "}), "ask required")
    rejects(lambda: do_request(card, {"ask": "q", "from": "nobody"}),
            "from must be one of")
    do_request(card, {"ask": "ship it?", "request_id": "rq2",
                      "options": ["y", "n"], "from": "ada"})
    req = card["requests"][-1]
    assert req["id"] == "rq2" and req["ask"] == "ship it?"
    assert req["status"] == "open" and req["options"] == ["y", "n"]
    assert req["at"] and req["from"] == "ada" and "to" not in req
    assert request_needs_notify(req)          # agent -> tony: push
    assert card["comms"][-1]["from"] == "ada"
    assert "raised request rq2" in card["comms"][-1]["text"]
    rejects(lambda: do_request(card, {"ask": "again", "request_id": "rq2"}),
            "duplicate request id")
    # suggested — recommendation validated against options, never applied
    rejects(lambda: do_request(card, {"ask": "q", "suggested": "y"}),
            "suggested requires options")
    rejects(lambda: do_request(card, {"ask": "q", "options": ["y", "n"],
                                      "suggested": "maybe"}),
            "suggested must match one of the options")
    do_request(card, {"ask": "ship it now?", "options": ["y", "n"],
                      "suggested": "y"})
    rs = card["requests"][-1]
    assert rs["suggested"] == "y" and rs["status"] == "open"
    # dict options: suggested may be the id, the label, or 'id — label'
    for sug in ("a", "A", "a — A"):
        do_request(card, {"ask": f"pick {sug}",
                          "options": [{"id": "a", "label": "A"}],
                          "suggested": sug})
        assert card["requests"][-1]["suggested"] == sug
    rejects(lambda: do_request(card, {"ask": "pick b",
                                      "options": [{"id": "a", "label": "A"}],
                                      "suggested": "b"}),
            "suggested must match one of the options")
    rejects(lambda: do_request(card, {"ask": "q", "to": "nobody"}),
            "to must be one of")
    do_request(card, {"ask": "auto id please"})
    assert card["requests"][-1]["id"].startswith("auto-id-please-")
    do_request(card, {"ask": "ตอบหน่อย"})  # non-ascii ask still gets an id
    assert card["requests"][-1]["id"].startswith("req-")
    # notify gate: tony-raised and non-tony-targeted requests stay quiet
    do_request(card, {"ask": "note to self", "from": "tony"})
    assert not request_needs_notify(card["requests"][-1])
    do_request(card, {"ask": "ada check this", "from": "devin", "to": "ada"})
    r2 = card["requests"][-1]
    assert r2["to"] == "ada" and not request_needs_notify(r2)
    # batched summary format
    assert "•" in _req_line("c1", {"ask": "q" * 100,
                                   "options": [{"id": "a", "label": "A"}]})
    assert "[A]" in _req_line("c1", {"ask": "x",
                                     "options": [{"id": "a", "label": "A"}]})

    # /pipeline
    card = {}
    rejects(lambda: do_pipeline(card, {}, "devin"),
            "pipeline, stage, or opt_in required")
    do_pipeline(card, {"opt_in": True}, "devin")
    assert card["pipeline"] == "ci"
    rejects(lambda: do_pipeline(card, {"stage": "bogus", "status": "pass"},
                                "devin"), "stage must be one of")
    rejects(lambda: do_pipeline(card, {"stage": "plan", "status": "meh"},
                                "devin"), "status must be one of")
    do_pipeline(card, {"stage": "plan", "status": "pass",
                       "detail": "spec ok"}, "devin")
    assert isinstance(card["pipeline"], dict)
    assert card["pipeline"]["stages"]["plan"]["status"] == "pass"
    # full block merge — earlier stages preserved
    do_pipeline(card, {"pipeline": {"stages": {
        "audit": {"status": "pass", "at": "t", "detail": "2 checks"}},
        "benchmark": {"metric": "m", "before": "2"}}}, "devin")
    assert card["pipeline"]["stages"]["plan"]["status"] == "pass"
    assert card["pipeline"]["stages"]["audit"]["status"] == "pass"
    assert card["pipeline"]["benchmark"]["before"] == "2"
    do_pipeline(card, {"opt_in": False}, "devin")
    assert "pipeline" not in card

    # /card spawn fields + on_exists (report-session-loop §1a). CARD_DIR
    # is redirected to a temp dir — do_create writes real card files.
    cdir = tmp / "cards"
    cdir.mkdir()
    globals()["CARD_DIR"] = cdir

    def mkfile(cid):
        return load(cdir / f"{cid}.yml")

    rejects(lambda: do_create({"title": "t", "report": "Bad_Slug"}, "devin"),
            "report must match")
    rejects(lambda: do_create({"title": "t", "report": "x" * 81}, "devin"),
            "report must match")
    res = do_create({"title": "Dev kanban health", "id": "spawn-1",
                     "report": "dev-kanban"}, "devin")
    assert res["id"] == "spawn-1"
    c1 = mkfile("spawn-1")
    assert c1["report"] == "dev-kanban"
    assert "ada-cms-pages/dev-kanban" in c1["spec"]
    assert "report-linked (report: dev-kanban)" in c1["spec"]
    assert '"Dev kanban health"' in c1["spec"]
    # explicit spec wins over the template
    do_create({"title": "t", "id": "spawn-2", "report": "dev-kanban",
               "spec": "custom spec"}, "devin")
    assert mkfile("spawn-2")["spec"] == "custom spec"
    # action validation
    rejects(lambda: do_create({"title": "t", "id": "s3",
                               "action": {"type": "bogus"}}, "devin"),
            "action.type must be one of")
    rejects(lambda: do_create({"title": "t", "id": "s3",
                               "action": {"type": "dispatch",
                                          "repo": "no-such-repo-zz"}},
                              "devin"),
            "not in the dispatch whitelist")
    rejects(lambda: do_create({"title": "t", "id": "s3",
                               "action": "dispatch"}, "devin"),
            "action must be an object")
    res = do_create({"title": "t", "id": "spawn-3",
                     "action": {"type": "dispatch", "repo": "chaba",
                                "status": "running"},  # spoof dropped
                     "queue": True}, "devin")
    assert res["status"] == "queued" and "(queued)" in res["message"]
    c3 = mkfile("spawn-3")
    assert c3["action"] == {"type": "dispatch", "repo": "chaba",
                            "status": "queued"}
    # manual type accepted; queue:true with no action arms a dispatch card
    do_create({"title": "t", "id": "spawn-man",
               "action": {"type": "manual"}}, "devin")
    assert mkfile("spawn-man")["action"] == {"type": "manual"}
    do_create({"title": "t", "id": "spawn-4", "queue": True}, "devin")
    assert mkfile("spawn-4")["action"] == {"type": "dispatch",
                                           "status": "queued"}
    # pass-through fields
    rejects(lambda: do_create({"title": "t", "id": "s5",
                               "priority": "urgent"}, "devin"),
            "priority must be one of")
    rejects(lambda: do_create({"title": "t", "id": "s5",
                               "tags": "kanban"}, "devin"),
            "tags must be a list")
    do_create({"title": "t", "id": "spawn-5", "brief": "short brief",
               "priority": "high", "tags": ["report-session-loop", "x"],
               "program": "ada-tools", "blocked_by": "other-card"}, "devin")
    c5 = mkfile("spawn-5")
    assert c5["brief"] == "short brief" and c5["priority"] == "high"
    assert c5["tags"] == ["report-session-loop", "x"]
    assert c5["program"] == "ada-tools" and c5["blocked_by"] == "other-card"
    # on_exists — default error path unchanged
    rejects(lambda: do_create({"title": "t", "id": "spawn-5"}, "devin"),
            "already exists")
    rejects(lambda: do_create({"title": "t", "id": "spawn-5",
                               "on_exists": "merge"}, "devin"),
            "on_exists must be")
    # on_exists=queue on an already-queued card reports status, unchanged
    res = do_create({"title": "t", "id": "spawn-4",
                     "on_exists": "queue"}, "devin")
    assert res["status"] == "queued" and "already active" in res["message"]
    c4 = mkfile("spawn-4")
    assert not any("re-spawned" in m["text"] for m in c4["comms"])
    # finished card re-arms: queued, column reset, runner/task_id cleared
    c4["action"].update(status="done", runner="mn01", task_id="z" * 10)
    c4["column"] = "done"
    save(cdir / "spawn-4.yml", c4)
    res = do_create({"title": "t", "id": "spawn-4",
                     "on_exists": "queue"}, "devin")
    assert res["status"] == "queued" and "re-queued" in res["message"]
    c4 = mkfile("spawn-4")
    assert c4["action"]["status"] == "queued"
    assert "runner" not in c4["action"] and "task_id" not in c4["action"]
    assert c4["column"] == "backlog"
    assert any("re-spawned from report page" in m["text"]
               for m in c4["comms"])
    globals()["CARD_DIR"] = REPO / "docs/ssot/kanban/cards"

    # write gate (card board-api-auth) — caller_identity is pure: fake
    # headers dict + peer ip stand in for a request
    def hdrs(**kw):
        return kw
    # direct loopback caller (scripts/units): no XFF -> trusted local
    assert caller_identity(hdrs(), "127.0.0.1") == "local"
    assert caller_identity(hdrs(), "::1") == "local"
    # tailnet-authed via serve -> Caddy chain (ts ip, loopback hops)
    ts = {"Tailscale-User-Login": "tonezzzz@github",
          "X-Forwarded-For": "100.99.1.2, 127.0.0.1, 127.0.0.1"}
    assert caller_identity(ts, "127.0.0.1") == "tonezzzz@github"
    # tailnet IPv6 ULA hop is trusted too
    ts6 = {"Tailscale-User-Login": "tonezzzz@github",
           "X-Forwarded-For": "fd7a:115c:a1e0::1, 127.0.0.1"}
    assert caller_identity(ts6, "127.0.0.1") == "tonezzzz@github"
    # anonymous proxied request (XFF present, no login) -> deny
    assert caller_identity(hdrs(**{"X-Forwarded-For": "192.168.2.50"}),
                           "127.0.0.1") == ""
    # forged login from LAN: LAN IP stays in the chain -> deny
    forged = {"Tailscale-User-Login": "tonezzzz@github",
              "X-Forwarded-For": "192.168.2.50, 127.0.0.1"}
    assert caller_identity(forged, "127.0.0.1") == ""
    # forged login with spoofed all-trusted XFF still leaves the LAN
    # client IP between the forged entries and the appended hop
    forged2 = {"Tailscale-User-Login": "tonezzzz@github",
               "X-Forwarded-For": "100.99.1.2, 192.168.2.50, 127.0.0.1"}
    assert caller_identity(forged2, "127.0.0.1") == ""
    # garbage XFF entry can't parse -> deny
    bad = {"Tailscale-User-Login": "x@y",
           "X-Forwarded-For": "not-an-ip"}
    assert caller_identity(bad, "127.0.0.1") == ""
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
