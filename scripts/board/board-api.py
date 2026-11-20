#!/usr/bin/env python3
"""board-api — write endpoint for the kanban board page.

Binds 127.0.0.1:8787 on tony-dell; Caddy proxies /apps/board-api/* here
(prefix stripped). Each request edits the card YAML in the *served*
checkout (chaba-tony-dell — the web container bind-mounts that tree),
then re-runs render-board.py (+ render-board2.py --if-changed) so both
views' cards.json + index.html refresh immediately. Git persistence:
every write queues its dirty repo paths for a dedicated commit worker
that runs git add+commit AFTER the request flock is released (scoped
pathspec commit — see _queue_commit/_commit_loop; BOARD_API_COMMIT=0
disables), and kanban-commit.timer sweeps anything left over + pushes.
An uncommitted card edit is autostash bait — the next pull --rebase
stashes it and a failed pop resolves generated paths to HEAD, silently
eating comms and column moves
(board-api-writes-eaten-by-autostash-pops-515009) — so commits stay
near-immediate (~0.4s debounce) while never sitting inside the flock
(board-api-commit-outside-lock: per-write commits under the one lock
that serializes all card mutations stacked into 40-118s holds and a
503 storm, 2026-11-19).

Endpoints (after prefix strip):
  GET  /health                       -> {"ok": true}
  GET  /cards                        -> cards.json payload (legacy full dump)
  GET  /cards?<query>                -> projected/filtered card read
      (AUD-1033) so callers stop paying the multi-MB full dump for one
      card or a claim poll. Envelope {ok, count, total, offset,
      truncated, cards[]}; bare /cards keeps the raw payload shape.
      filters:   id=<card-id>, column=<col>, action_status=<s>,
                 since=<updated string> (lexicographic, same format)
      projection: fields=a,b,c (top-level keys; unknown ignored),
                 compact=1 -> {id,title,column,updated,priority,ref,
                               action_status},
                 compact=2 -> {id,ref,title,column,priority,updated,
                               brief,spec,action_status} — card-detail
                               tier, no comms/action bulk
      comms:      comms_tail=<n> keeps only the last n comms entries per
                 card (0 drops comms) and stamps comms_total; combines
                 with fields/compact and also applies to /card/<id>
      pagination: limit=<n> (cap 1000), offset=<n>
  GET  /card/<id>[?fields=|compact=1|comms_tail=<n>] -> {"ok", card} | 404
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
      {request_id?} stamps the comms entry so a retry after a client
      timeout dedupes instead of double-posting; without one, the same
      (from, text) inside BOARD_API_COMMENT_DEDUP_S (default 120s) also
      dedupes — a 200 {deduped:true} is returned, no write. dedupe:false
      bypasses. Session delivery (ada|tony -> answers.jsonl) now runs
      off the request lock on a worker; its note lands in comms via a
      second write. When the card's action.status=='running', comments
      from ada|tony are also pushed into the live session as kind:"comment"
      lines in answers.jsonl — card comms the session weighs as review input
      (Tony's notes, Ada's [opinion]-tagged takes;
      report-loop-comment-delivery). devin|chaba comments are never
      echoed back: a session must not get its own progress posts, and
      chaba system notes are noise.
  POST /attach   {id, filename, payload|b64|data, from?}
      (alias /upload) — file/photo evidence on a card
      (board-attachments-photo-image-evidence). payload is base64 (a
      data: URI prefix is stripped). The file lands in the repo at
      docs/ssot/kanban/attachments/<card-id>/<sanitized-name> — the
      canonical store, committed with the card in one commit — and a
      comms entry links it ('attachment: <repo-path> — <name> (N B)').
      render-board2 mirrors the tree into apps/board2/attachments/ so
      the board UI serves thumbnails. Filenames are sanitized to
      [A-Za-z0-9._-] and must end in an ATTACH_EXTS extension (image
      types plus pdf/video/text/archive — nothing servable as an
      executable content-type). Name collisions suffix -2/-3/… unless
      the bytes are identical (idempotent re-post). Size cap
      BOARD_API_ATTACH_MAX_BYTES (default 12 MiB decoded).
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
  POST /lesson   {topic, content, level?, source?, next_review?, status?,
                  no_th?} — WP lesson CPT upsert by topic slug (re-asked
                  topics update in place); {op:"topics"} returns the
                  existing topic list for store-aware classifiers
                  topics update in place) + auto-Thai section. The remote
                  write half of the lesson-capture duty; lesson-add.py is
                  now a thin CLI client of this endpoint. Every write also
                  mirrors into the MDDB chaba-lessons collection — the
                  retrieval surface agents search to get lessons back
                  (card assessments-to-education-split-ssot-keep-113ca4);
                  {op:list|get, source:"mddb"} reads it.
  POST /job      {slug, title?, status?, comms?|note?, parent?, kind?,
                  host?, pack?, runner?, result_ref?, error?} — nest_job
                  CPT upsert by slug: queue-mgr mirrors the ada-nest Drive
                  queue -> member surface. comms appends {at,from,text} to
                  a JSON log in meta.comms; parent (post id or slug) links
                  job trees.
  POST /report   {query} | {slug, note, lang?} | {title, content_md,
                  slug?, meta?} — report-integration duty as an endpoint:
                  search ada-cms-pages for integrate candidates, append a
                  session-log line (integrate), or create a page.
  POST /inbox    {label?, text, priority?, tags?, missing_info?,
                  session?, owner?} — focus-inbox YAML entry under the
                  card flock with the same immediate-commit discipline.
  POST /publish  {canonical PublicationEvent} — provider-neutral
                  publication door (card devnest-publication-adapter-layer,
                  scripts/board/publication.py): one event fans out to
                  sink adapters — nest_job (execution state), lesson CPT
                  (Education), report dossier (ada-cms-pages), news CPT,
                  telegram, card comms (audit), json ledger. Idempotent
                  (idempotency_key), outbox-retried, noise-policed,
                  private-first visibility. {op:"sinks"} returns the
                  capability table; {op:"drain"} retries the outbox.
                  The legacy /job /lesson /report /comment endpoints
                  remain as compatibility adapters — /publish routes
                  through the SAME writer functions, so WP is only one
                  adapter and any second sink receives the same event.
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
(/tmp/board-api.lock) first or it races the server. The acquire is
bounded (BOARD_API_LOCK_WAIT_S, default 25s): a saturated lock answers
503 + retry_after BEFORE any mutation, so a client timeout can't leave
a write landing silently behind it; waits/holds past BOARD_API_LOCK_SLOW_S
(5s) log to the journal. The lock's protected checkout is declared in
/tmp/board-api.lock.repo so pulls of other checkouts don't contend.

Unified mutation door (card nest-api-unified-mutation-service): the
namespaced write endpoints beyond card files — WP lesson/nest_job CPTs,
MDDB ada-cms-pages, focus-inbox — live here too so agents never hold
WP/mddb creds (same reason Colab stays credential-free). Remote-backed
writes (/lesson, /job, /report) serialize under WP_LOCK, NOT the card
flock — a 45s WP REST call must not stall /comment.

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
import base64
import fcntl
import hashlib
import hmac
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from datetime import date, datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import card_io
import dispatch_repos as dr
import board_notify as bn
import host_status as hs
import publication as pub

REPO = Path(__file__).resolve().parent.parent.parent
CARD_DIR = REPO / "docs/ssot/kanban/cards"
# /attach store (board-attachments-photo-image-evidence): kept inside the
# repo so uploads commit + propagate exactly like card YAML; the board
# app can't see this tree directly (/srv/public is all the web container
# mounts) — render-board2 mirrors it under apps/board2/attachments/.
ATTACH_DIR = REPO / "docs/ssot/kanban/attachments"
ATTACH_MAX_BYTES = int(os.environ.get(
    "BOARD_API_ATTACH_MAX_BYTES", str(12 * 1024 * 1024)))
# extension whitelist — anything off-list could be served back from the
# board origin with an executable content-type (html/svg/js = XSS)
ATTACH_EXTS = {
    "jpg", "jpeg", "png", "gif", "webp", "avif", "bmp", "tif", "tiff",
    "heic", "heif",
    "pdf", "mp4", "m4v", "mov", "webm", "mkv",
    "txt", "log", "md", "csv", "json", "zip", "gz",
}
RENDER = REPO / "scripts/render-board.py"
RENDER2 = REPO / "scripts/render-board2.py"
LOCK = Path("/tmp/board-api.lock")
# Bounded write-lock wait (OPS-1314, 2026-11-16 incident): an unbounded
# LOCK_EX queues a writer behind git-safe-pull's whole pull phase
# (1-6min when upstream moved) — the client's 30-60s timeout dies first,
# the write then lands anyway → duplicate comms and phantom "failed"
# posts. Wait up to LOCK_WAIT_S, then answer 503 BEFORE any mutation so
# a retry can't duplicate. LOCK_SLOW_S is the journal-side measurement:
# waits/holds past it log wait= held= per request.
LOCK_WAIT_S = float(os.environ.get("BOARD_API_LOCK_WAIT_S", "25"))
LOCK_SLOW_S = float(os.environ.get("BOARD_API_LOCK_SLOW_S", "5"))
# Sentinel naming the checkout this lock protects. git-safe-pull reads
# it and skips the shared lock when pulling a DIFFERENT checkout (e.g.
# the exec tree on the board host) — that pull's autostash window is in
# its own tree and stealing the lock for minutes stalls every API write
# for zero protection (2026-11-16: repo-sync + kanban-commit pull phases
# back-to-back queued writers for minutes).
LOCK_REPO_SENTINEL = Path(str(LOCK) + ".repo")
PORT = int(os.environ.get("BOARD_API_PORT", "8787"))
ACTORS = {"devin", "ada", "chaba", "tony"}
TRANSITIONS = {"queue", "close", "hold", "retry", "claim", "move",
               "finish", "archive", "unarchive"}
# done+verified cards older than this move to cards/archive/ via
# /action do=archive (KNB-1178; SSOT column_sla.done convention).
ARCHIVE_MIN_DAYS = float(os.environ.get("BOARD_API_ARCHIVE_DAYS", "7"))
# Queue-time lane classification (OPS-0838): when a card queues with no
# lane/executor, run the fleet classifier once and persist the pin.
# kk-mac-auto-lane-classifier (2026-11-13): a bounded read-only task
# class first self-routes to executor=kk_mac_local (dr.kk_mac_route) —
# no author pin needed; strict executors stay explicit-only.
BOARD_CLASSIFY_AT_QUEUE = \
    os.environ.get("BOARD_CLASSIFY_AT_QUEUE", "1") == "1"
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
# dict-option `action:` values answer-sweep.py will execute verbatim —
# keep in sync with answer-sweep.ACTIONS (KNB-0180)
OPTION_ACTIONS = {"queue", "retry", "close", "hold", "none"}
LLM_KEY_ALIASES = {"ada", "chaba", "bench", "kk", "michael", "cline"}
# action keys a caller may set — status/runner/task_id are board-owned and
# silently dropped so a spawn can't fake a running card
ACTION_KEYS = ("type", "repo", "host", "labels", "button", "model",
               "executor", "agent_profile", "profile", "target_host",
               "artifact", "task_class", "prompt", "expect", "lane",
               "subject_host", "llm_key_alias", "lane_envelope", "nlm_notebook",
               "nlm_source_file", "nlm_source_text", "nlm_source_url")

# --- write gate (card board-api-auth) ------------------------------------
LOOPBACK_NETS = [ip_network("127.0.0.0/8"), ip_network("::1/128")]
TRUSTED_NETS = LOOPBACK_NETS + [
    ip_network("100.64.0.0/10"),       # tailnet CGNAT
    ip_network("fd7a:115c:a1e0::/48"), # tailnet ULA
]
ALLOWED_LOGINS = {x.strip() for x in
                  os.environ.get("BOARD_API_ALLOWED_LOGINS", "").split(",")
                  if x.strip()}
EDGE_KEY = os.environ.get("BOARD_API_EDGE_KEY", "")


def _in_nets(ip_s: str, nets: list) -> bool:
    try:
        ip = ip_address(ip_s)
    except ValueError:
        return False
    return any(ip in n for n in nets)


def caller_identity(headers, peer_ip: str) -> str:
    """Verified writer identity: the tailnet login, 'edge:<cf-email>' for
    the public caddy-edge, 'local' for a direct loopback caller, or ''
    when the request may not write.

    tailscale serve injects Tailscale-User-Login on tailnet-authed
    requests; Caddy appends the real client IP to X-Forwarded-For at
    every hop, so a forged login header from LAN still leaves a LAN
    address in the chain -> denied. Local automation posts straight to
    127.0.0.1:8787 (loopback peer, no XFF) and is trusted.

    Edge lane (card board-api-auth / public-vhost writes): the CF-Access-
    gated edge injects X-Board-Edge-Key on proxied requests — anything
    that reached that vhost already passed Cloudflare Access, and the
    Cf-Access-Authenticated-User-Email header gives per-user attribution.
    The key is compared constant-time and must come from the edge's env,
    never from client JS."""
    if EDGE_KEY and hmac.compare_digest(
            (headers.get("X-Board-Edge-Key") or "").encode(),
            EDGE_KEY.encode()):
        email = (headers.get("Cf-Access-Authenticated-User-Email")
                 or "").strip()
        return "edge:" + (email or "cf")
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


_ARCHIVE_INDEX = {"t": 0.0, "map": {}}
_ARCHIVE_INDEX_TTL = 60.0


def _archive_index() -> dict:
    """id/ref/stem -> path for cards/archive/*.yml, cached 60s. The
    archive only changes via /action do=archive (which commits through
    this process), so a short TTL is safe and keeps lookups O(1)."""
    now_t = time.time()
    if now_t - _ARCHIVE_INDEX["t"] < _ARCHIVE_INDEX_TTL:
        return _ARCHIVE_INDEX["map"]
    m = {}
    adir = CARD_DIR / "archive"
    if adir.is_dir():
        for cand in adir.glob("*.yml"):
            try:
                c = yaml.safe_load(cand.read_text()) or {}
            except Exception:
                continue
            for k in (c.get("id"), c.get("ref"), cand.stem):
                if k:
                    m.setdefault(str(k), cand)
    _ARCHIVE_INDEX.update(t=now_t, map=m)
    return m


def card_path(cid: str) -> Path:
    t0 = _phase_clock()
    try:
        if not cid or "/" in cid or ".." in cid:
            raise ValueError("bad card id")
        p = CARD_DIR / f"{cid}.yml"
        if not p.exists():
            # filename/id drift happens when a session renames a card's
            # id without renaming the file — fall back to an id-field
            # scan so respond/action/comment still find it. Refs
            # (ADA-0042) resolve through the same scan.
            for cand in CARD_DIR.glob("*.yml"):
                try:
                    c = yaml.safe_load(cand.read_text()) or {}
                except Exception:
                    continue
                if c.get("id") == cid or c.get("ref") == cid:
                    return cand
            # archived cards stay resolvable via the cached archive index
            # (KNB-1178) — a per-request yaml scan of cards/archive/ would
            # be too slow for the GET path
            cand = _archive_index().get(cid)
            if cand:
                return cand
            raise ValueError(f"no card {cid}")
        return p
    finally:
        _phase_add("card_path_ms", t0)


# Card refs — human handle CAT-NNNN (Tony 2026-10-11). Slug stays the
# canonical key (filename/API); ref is for voice/TG/display. Global
# sequence in CARD_DIR/.ref-seq; allocated under the write flock so
# multi-host creates can't collide. Resolved per-call, not at import —
# selftest redirects CARD_DIR and must not touch the real .ref-seq.
REF_RE = re.compile(r"^[A-Z]{3}-\d{4}$")
REF_CATS = {
    "ada": "ADA", "voice": "ADA", "chat": "ADA",
    "infra": "SYS", "host": "SYS", "hosts": "SYS", "network": "SYS",
    "tailscale": "SYS", "macbook": "SYS",
    "dispatch": "OPS", "ops": "OPS", "worktree": "OPS", "runner": "OPS",
    "fleet": "OPS", "restore": "OPS", "remote-access": "OPS",
    "kanban": "KNB", "board": "KNB", "card": "KNB", "cards": "KNB",
    "audit": "AUD", "monitoring": "AUD", "verify": "AUD",
    "ha": "HOM", "home-assistant": "HOM", "dashboard": "HOM",
    "secret": "SEC", "secrets": "SEC", "key": "SEC", "security": "SEC",
    "rotation": "SEC", "auth": "SEC",
    "mddb": "MEM", "memory": "MEM", "embedding": "MEM",
    "cast": "MED", "media": "MED", "cctv": "MED", "gev": "MED",
    "devin": "DEV", "cli": "DEV", "skill": "DEV", "tools": "DEV",
    "bench": "BEN", "benchmark": "BEN",
}
REF_DEFAULT = "OPS"
# id-slug keywords → category, for legacy cards without tags.
# First match wins — order is the priority.
REF_ID_HINTS = (
    ("audit", "AUD"), ("ada-", "ADA"), ("voice", "ADA"), ("gemini", "ADA"),
    ("memory", "MEM"), ("mddb", "MEM"), ("embed", "MEM"),
    ("secret", "SEC"), ("key", "SEC"), ("auth", "SEC"), ("secur", "SEC"),
    ("kanban", "KNB"), ("board", "KNB"), ("card", "KNB"), ("report", "KNB"),
    ("cms", "KNB"), ("ssot", "KNB"),
    ("runner", "OPS"), ("dispatch", "OPS"), ("worktree", "OPS"),
    ("host", "SYS"), ("macbook", "SYS"), ("tailnet", "SYS"),
    ("network", "SYS"), ("wifi", "SYS"), ("ssh", "SYS"),
    ("ha-", "HOM"), ("home-", "HOM"), ("dashboard", "HOM"),
    ("cam", "MED"), ("cctv", "MED"), ("cast", "MED"), ("gev", "MED"),
    ("yt-", "MED"), ("media", "MED"), ("screen", "MED"),
    ("devin", "DEV"), ("cli", "DEV"), ("skill", "DEV"),
    ("bench", "BEN"), ("cascade", "BEN"),
)


def _ref_seed() -> int:
    """Highest ref number already on the board (for first-run init)."""
    hi = 0
    for cand in CARD_DIR.glob("*.yml"):
        try:
            r = (yaml.safe_load(cand.read_text()) or {}).get("ref") or ""
        except Exception:
            continue
        m = re.match(r"^[A-Z]{3}-(\d{4})$", str(r))
        if m:
            hi = max(hi, int(m.group(1)))
    return hi


def alloc_ref(cat: str) -> str:
    """Allocate the next global ref under the caller's write flock."""
    seq = CARD_DIR / ".ref-seq"
    if seq.exists():
        n = int(seq.read_text().strip() or 0)
    else:
        n = _ref_seed()
    n += 1
    seq.write_text(f"{n}\n")
    return f"{cat}-{n:04d}"


def ref_cat(card: dict, body: dict) -> str:
    """Pick the 3-letter category: explicit cat/ref prefix > tag map > OPS."""
    explicit = str(body.get("cat") or "").strip().upper()
    if explicit in set(REF_CATS.values()):
        return explicit
    want = str(body.get("ref") or "").strip().upper()
    if REF_RE.match(want):
        return want[:3]
    for t in body.get("tags") or card.get("tags") or []:
        c = REF_CATS.get(str(t).strip().lower())
        if c:
            return c
    slug = str(card.get("id") or "").lower()
    for kw, c in REF_ID_HINTS:
        if kw in slug:
            return c
    return REF_DEFAULT


def acquire_lock(path: Path, timeout_s: float):
    """Bounded LOCK_EX acquire — fcntl.flock has no timeout, so retry
    LOCK_NB until the deadline. Returns (open file, wait_seconds) or
    None when the lock stayed contended. A None answer MUST happen
    before any mutation so the caller can 503 and a retry can't
    duplicate a write (the 2026-11-16 stall mode)."""
    lf = path.open("w")
    t0 = time.monotonic()
    while True:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lf, time.monotonic() - t0
        except BlockingIOError:
            if time.monotonic() - t0 >= timeout_s:
                lf.close()
                return None
            time.sleep(0.25)


# Lock-wait telemetry (card board-api-lock-contention): per-endpoint
# histogram of seconds spent acquiring the card flock, so a convoy
# regression is one GET /lock-stats away instead of a journal grep.
_LOCK_STAT_BUCKETS = (0.05, 0.25, 1, 2, 5, 10, 25)
_lock_stats: dict = {}
_lock_stats_mu = threading.Lock()


def _lock_stat(path: str, wait_s: float, hold_s: float = 0.0,
               timeout: bool = False) -> None:
    b = next((f"<{x:g}s" for x in _LOCK_STAT_BUCKETS if wait_s < x),
             f">={_LOCK_STAT_BUCKETS[-1]:g}s")
    hb = next((f"h<{x:g}s" for x in _LOCK_STAT_BUCKETS if hold_s < x),
              f"h>={_LOCK_STAT_BUCKETS[-1]:g}s")
    with _lock_stats_mu:
        st = _lock_stats.setdefault(
            path, {"n": 0, "timeouts": 0,
                   "wait_s_total": 0.0, "wait_s_max": 0.0,
                   "hold_s_total": 0.0, "hold_s_max": 0.0})
        st["n"] += 1
        st["wait_s_total"] = round(st["wait_s_total"] + wait_s, 3)
        st["wait_s_max"] = max(st["wait_s_max"], round(wait_s, 3))
        st["hold_s_total"] = round(st["hold_s_total"] + hold_s, 3)
        st["hold_s_max"] = max(st["hold_s_max"], round(hold_s, 3))
        st[b] = st.get(b, 0) + 1
        st[hb] = st.get(hb, 0) + 1
        if timeout:
            st["timeouts"] += 1


# In-flock phase timing (board-api-residual-lock-holds): commits moved
# post-lock in f1f0b yet holds still hit ~80s, and the slow-lock journal
# line couldn't say where the time went. While do_POST owns the card
# flock, load/save/card_path accumulate milliseconds into this
# thread-local; mutate_ms is the hold remainder (do_* helpers, delivery
# queueing, validation). Printed on the existing slow-lock line only, so
# the next investigation reads the culprit straight off the journal.
# Off-request callers (selftest, _append_comms_note, the post-write
# worker) see on=False and pay one getattr.
_phase_t = threading.local()


def _phase_clock():
    """monotonic() seed for a measured call inside the card flock —
    None when no POST request is being timed so the instrumented
    functions keep zero cost for non-request callers."""
    return time.monotonic() if getattr(_phase_t, "on", False) else None


def _phase_add(name: str, t0) -> None:
    if t0 is not None:
        setattr(_phase_t, name,
                getattr(_phase_t, name, 0.0)
                + (time.monotonic() - t0) * 1000)


def _append_comms_note(cid: str, text: str) -> None:
    """Fold a post-lock note (session delivery/hide results) into comms
    via a second locked write — the work that produced it ran off the
    request path so it never stalled writers. Never raises."""
    try:
        p = card_path(cid)
    except Exception:
        return
    got = acquire_lock(LOCK, LOCK_WAIT_S)
    if got is None:
        sys.stderr.write(
            f"board-api post-write note skipped (lock busy): {text[:80]}\n")
        return
    lf, _w = got
    try:
        card = load(p)
        comms_add(card, "chaba", text)
        card["updated"] = now()
        save(p, card)
    except Exception as e:
        sys.stderr.write(f"board-api post-write note failed: {e}\n")
    finally:
        lf.close()
    commit_async()
    render_async()


_post_write_q = queue.Queue()
_post_write_started = False


def queue_post_write(fn) -> None:
    """Serialize slow request side-effects (ssh session deliveries, db
    hides) on one daemon worker — they must not run inside the card
    flock (~15-30s per unreachable host) nor keep a handler thread busy
    after the response is already sent."""
    global _post_write_started
    if not _post_write_started:
        threading.Thread(target=_post_write_loop, daemon=True).start()
        _post_write_started = True
    _post_write_q.put(fn)


def _post_write_loop() -> None:
    while True:
        fn = _post_write_q.get()
        try:
            fn()
        except Exception as e:
            sys.stderr.write(f"board-api post-write task failed: {e}\n")


def load(p: Path) -> dict:
    t0 = _phase_clock()
    try:
        d = yaml.load(p.read_text(),
                      Loader=getattr(yaml, "CSafeLoader",
                                     yaml.SafeLoader)) or {}
        if not isinstance(d, dict):
            raise ValueError(f"card {p.name} is not a YAML mapping")
        return d
    finally:
        _phase_add("load_ms", t0)


# Set by do_POST while holding the request flock so the queued commit in
# save() gets a useful message ("board-api comment <id>"); empty outside
# requests (selftest, module importers) where it falls back to the card
# filename.
_pending_label = ""


def save(p: Path, card: dict, extra: list | None = None) -> None:
    """Serialize, verify the dump re-parses as a mapping, then land it
    atomically. A card body that can't round-trip is refused BEFORE the
    file is touched — refuse/rollback at write time, not a corrupted
    card that kills render-board for the next N hours
    (guard-card-yaml-syntax-validation-at-wri; 2026-10-11 incident:
    3 malformed cards wedged the render loop 2.5h). The write's repo
    paths are then queued for the post-lock commit worker (see
    _queue_commit) so they sit dirty for ~seconds, not for a sweep
    interval — short enough that autostash can't eat them in practice."""
    t0 = _phase_clock()
    try:
        text = yaml.safe_dump(card, allow_unicode=True, sort_keys=False,
                              width=110)
        if not isinstance(yaml.safe_load(text), dict):
            raise ValueError(
                f"refusing to write {p.name}: serialized card did not "
                "re-parse as a mapping")
        # fsync before rename — without it a delayed-allocation writeback
        # can still lose the tail under ENOSPC (2026-11-19 idc03
        # disk-full)
        card_io.atomic_write_text(p, text)
        _queue_commit(p, _pending_label or f"write {p.stem}", extra=extra)
    finally:
        _phase_add("save_ms", t0)


def _act(card: dict) -> dict:
    """card['action'] read accessor — the schema says dict, but marker
    cards carry scalars ('spec-review' on nest-mgr-v2-actuation). One bad
    row must not 500 /queue or crash render-board for the whole board
    (2026-11-17 outage)."""
    a = card.get("action")
    return a if isinstance(a, dict) else {}


def _ensure_act(card: dict) -> dict:
    """Write-path twin of _act: a scalar action is replaced with {} so
    mutation can't TypeError on the marker string."""
    a = card.get("action")
    if not isinstance(a, dict):
        card["action"] = a = {}
    return a


def _claim(card: dict) -> dict:
    """card['claim'] read accessor — same scalar-tolerance as _act."""
    c = card.get("claim")
    return c if isinstance(c, dict) else {}


def _ensure_claim(card: dict) -> dict:
    c = _claim(card)
    if c is not card.get("claim"):
        card["claim"] = c
    return c


def _reqs(card: dict) -> list:
    """card['requests'] read accessor — dict entries only; scalar/garbage
    rows are invisible instead of crashing .get() callers."""
    r = card.get("requests")
    return [x for x in r if isinstance(x, dict)] \
        if isinstance(r, list) else []


def _ensure_reqs(card: dict) -> list:
    r = card.get("requests")
    if not isinstance(r, list):
        card["requests"] = r = []
    return r


# Pending-commit coalescing (card board-api-commit-outside-lock).
# save() used to run git add+commit while holding the request flock —
# every card/comment/action write paid two subprocesses inside the one
# lock that serializes ALL card mutations, so bursts stacked into
# 40-118s holds and the 08:33-09:02 503 storm of 2026-11-19. Now the
# locked section only records repo-relative dirty paths; a dedicated
# worker commits them after the flock is released, debounced like
# render_async so a burst coalesces into the fewest commits. Durability
# is preserved: the worker defers while the card flock is held (a
# request mid-write or git-safe-pull's whole pull+autostash+pop phase),
# respects the gitdir rebase/merge-state guard, and retries every
# COMMIT_RETRY_S until the commit lands — kanban-commit.timer remains
# the sweep backstop. Done-ness is verified by the queued paths'
# porcelain state, not the commit rc (board-api-residual-lock-holds):
# a batch the sweep already committed — or that never had changes — is
# finished, not requeued. BOARD_API_COMMIT=0 restores the sweep-only
# model.
COMMIT_DEBOUNCE_S = float(
    os.environ.get("BOARD_API_COMMIT_DEBOUNCE_S", "0.4"))
COMMIT_RETRY_S = float(
    os.environ.get("BOARD_API_COMMIT_RETRY_S", "5"))
# A path that still won't commit after this many tries is dropped to the
# kanban-commit sweep — a persistently-broken path must not retry+log
# forever (the sweep sees the same dirty tree).
COMMIT_MAX_TRIES = int(os.environ.get("BOARD_API_COMMIT_MAX_TRIES", "60"))
_pending_commits: dict = {}      # rel path -> label (insertion ordered)
_commit_tries: dict = {}         # rel path -> consecutive failed drains
_commit_mu = threading.Lock()
_commit_flag = threading.Event()
_commit_active = False
_commit_worker_started = False


def _queue_commit(p: Path, label: str, extra: list | None = None) -> None:
    """Record a write's dirty repo paths for the commit worker. Called
    under the request flock where it must stay cheap — no subprocesses.
    An uncommitted card edit in the served checkout is autostash bait
    (board-api-writes-eaten-by-autostash-pops-515009), so the worker is
    nudged immediately; it lands the commit ~debounce+git seconds after
    the flock is released. Committed writes survive every pull path —
    worst case a rebase conflict goes upstream-wins with the local side
    preserved as .local-conflict-* and folded back by
    reconcile-local-conflicts.py."""
    if os.environ.get("BOARD_API_COMMIT", "1") == "0":
        return
    paths = [p] + [Path(x) for x in (extra or [])]
    seq = CARD_DIR / ".ref-seq"
    if seq.exists():
        paths.append(seq)      # ref allocation must persist with the card
    with _commit_mu:
        for q in paths:
            try:
                _pending_commits.setdefault(
                    str(q.relative_to(REPO)), label)
            except ValueError:
                continue       # selftest/tmp paths — not repo files
        pending = bool(_pending_commits)
    if pending:
        commit_async()


def commit_async() -> None:
    """Nudge the commit worker — same shape as render_async."""
    global _commit_worker_started
    with _commit_mu:
        if not _commit_worker_started:
            threading.Thread(target=_commit_loop, daemon=True).start()
            _commit_worker_started = True
    _commit_flag.set()


def _commit_loop() -> None:
    global _commit_active
    while True:
        _commit_flag.wait()
        _commit_flag.clear()
        time.sleep(COMMIT_DEBOUNCE_S)   # let a burst coalesce
        try:
            while True:
                with _commit_mu:
                    items = dict(_pending_commits)
                    _pending_commits.clear()
                    if items:
                        _commit_active = True
                if not items:
                    with _commit_mu:
                        _commit_active = False
                    break
                rels = list(items)
                label = "; ".join(dict.fromkeys(items.values()))[:110]
                if _commit_paths(rels, label):
                    with _commit_mu:
                        for r in rels:
                            _commit_tries.pop(r, None)
                    continue      # drain anything queued during the commit
                # mid-pull/mid-rebase/index-lock — requeue and retry
                # shortly; a path that keeps failing ages out to the
                # kanban-commit sweep instead of retrying forever
                with _commit_mu:
                    for r in rels:
                        _commit_tries[r] = _commit_tries.get(r, 0) + 1
                        if _commit_tries[r] <= COMMIT_MAX_TRIES:
                            _pending_commits.setdefault(r, items[r])
                        else:
                            _commit_tries.pop(r, None)
                            sys.stderr.write(
                                f"board-api commit gave up on {r} "
                                f"after {COMMIT_MAX_TRIES} tries — "
                                "sweep owns it\n")
                time.sleep(COMMIT_RETRY_S)
        except Exception as e:
            # never let the worker die — requeue anything in flight and
            # keep waiting; the sweep is the backstop meanwhile
            sys.stderr.write(f"board-api commit worker error: {e}\n")
            with _commit_mu:
                for r in (items if "items" in dir() else {}):
                    _pending_commits.setdefault(r, items[r])
                _commit_active = False


def _card_lock_held() -> bool:
    """True while a writer or git-safe-pull's pull phase holds the card
    flock. The commit worker defers rather than racing the pull's
    autostash/rebase window — but never HOLDS the flock across a commit:
    request read-modify-write must not queue behind git."""
    try:
        with LOCK.open("w") as lf:
            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True
    except OSError:
        return False


def _rels_dirty(rels: list) -> bool | None:
    """git status --porcelain scoped to the queued paths — the batch's
    truth source. False (clean) means the paths were already committed
    (this worker's previous drain, or the kanban-commit sweep raced us
    and won) or never existed: the batch is done no matter what a later
    commit rc says. None = the check itself failed — the caller can't
    prove clean, so it keeps the conservative retry."""
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain", "--"] + rels,
            capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return bool(r.stdout.strip())


def _commit_paths(rels: list, label: str) -> bool:
    """Best-effort git add+commit of coalesced repo-relative paths —
    runs on the commit worker, off the request flock. False means the
    batch STILL has dirty queued paths AND the tree can't take a commit
    right now (pull phase holds the card flock, mid-rebase/merge,
    index.lock) — the caller requeues for a retry. True covers
    'committed' AND 'nothing left to commit': done-ness is decided by
    the queued paths' porcelain state, not the commit rc, because
    `git commit -- <rels>` exits 1 whenever the queued paths are already
    clean while OTHER files are dirty — the served checkout always is —
    which used to requeue a finished batch into a 5s 'commit skipped'
    log storm until MAX_TRIES (board-api-residual-lock-holds)."""
    if not rels:
        return True
    try:
        if _card_lock_held():
            return False       # a write or a pull phase owns the checkout
        gd = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=10)
        if gd.returncode != 0:
            return True        # not a repo (selftest/tmp) — never retries
        gitdir = Path(gd.stdout.strip())
        if not gitdir.is_absolute():
            gitdir = REPO / gitdir
        if any((gitdir / m).exists() for m in
               ("rebase-merge", "rebase-apply",
                "MERGE_HEAD", "CHERRY_PICK_HEAD")):
            return False       # git is settling — retry, don't race it
        add = subprocess.run(
            ["git", "-C", str(REPO), "add", "--"] + rels,
            capture_output=True, text=True, timeout=15)
        if add.returncode != 0:
            err = (add.stderr or "").strip()
            if "did not match" not in err:
                sys.stderr.write(
                    f"board-api commit add skipped: {err[:200]}\n")
                # transient (index.lock) — done only when the queued
                # paths are provably clean; still-dirty (or an
                # inconclusive check) requeues
                return _rels_dirty(rels) is False
            # git add is all-or-nothing on pathspecs: one queued path
            # that is neither on disk nor in the index (untracked then
            # deleted before the worker ran) must not drop the whole
            # batch — stage the survivors individually.
            staged = []
            for r in rels:
                one = subprocess.run(
                    ["git", "-C", str(REPO), "add", "--", r],
                    capture_output=True, text=True, timeout=15)
                if one.returncode == 0:
                    staged.append(r)
                elif "did not match" not in (one.stderr or ""):
                    # transient (index.lock) — requeue everything so the
                    # staged paths and this one commit together, unless
                    # the sweep provably already left them clean
                    sys.stderr.write(
                        f"board-api commit add skipped {r}: "
                        f"{(one.stderr or '').strip()[:200]}\n")
                    return _rels_dirty(rels) is False
            rels = staged
            if not rels:
                return True    # nothing stageable — sweep owns leftovers
        # verify by repo state: queued paths already clean (the sweep
        # committed between our write and this drain, or they never
        # changed) means the batch is done — committing would rc=1 with
        # 'Changes not staged for commit' over unrelated dirty files and
        # the worker would retry a finished batch forever.
        if _rels_dirty(rels) is False:
            return True
        # --no-verify: save() already round-trip-validates the YAML and the
        # full SSOT/node gate is kanban-commit's job on the 15-min sweep —
        # paying it per write would blow the client timeout. Pathspec scope
        # keeps other staged/dirty work out of the commit.
        r = subprocess.run(
            ["git", "-C", str(REPO), "-c", "user.name=board-api",
             "-c", "user.email=board-api@chaba.local",
             "commit", "--no-verify", "-qm",
             f"board-api {label}"[:120], "--"] + rels,
            capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            err = ((r.stderr or "") + (r.stdout or "")).strip()
            if "nothing to commit" in err.lower():
                return True
            # the sweep can commit between our porcelain gate and this
            # commit — re-verify before calling the batch failed
            if _rels_dirty(rels) is not False:
                sys.stderr.write(
                    f"board-api commit skipped: {err[:200]}\n")
                return False   # still dirty — transient, retry
        return True
    except Exception as e:
        sys.stderr.write(f"board-api commit skipped: {e}\n")
        return False


def commit_pending_flush(timeout_s: float = 15.0) -> bool:
    """Wait until every queued commit has landed (or been confirmed
    uncommittable) — for tests and drains that need the commit observed,
    not just the write."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with _commit_mu:
            done = not _pending_commits and not _commit_active
        if done:
            return True
        time.sleep(0.05)
    return False


def comms_add(card: dict, frm: str, text: str, req: str = "") -> None:
    e = {"at": now(), "from": frm, "text": text[:500]}
    if req:
        e["req"] = req[:120]
    comms = card.get("comms")
    if not isinstance(comms, list):
        card["comms"] = comms = []
    comms.append(e)


COMMENT_DEDUP_S = int(os.environ.get("BOARD_API_COMMENT_DEDUP_S", "120"))


def dup_comment(card: dict, frm: str, text: str, req: str) -> bool:
    """True when this comment is already recorded — a client whose
    timeout died mid-write retries and, without a dedupe, lands the same
    line twice (2026-11-16 incident: curls timed out at 30-60s while the
    write completed server-side → duplicate comms). An explicit
    request_id matches the entry's `req` stamp; without one, the same
    (from, text) inside COMMENT_DEDUP_S counts as one logical comment —
    reposts past the window always write."""
    comms = card.get("comms") or []
    if req:
        return any(isinstance(e, dict) and e.get("req") == req
                   for e in comms)
    text = text[:500]
    cutoff = (datetime.now(timezone(timedelta(hours=7)))
              - timedelta(seconds=COMMENT_DEDUP_S)) \
        .strftime("%Y-%m-%d %H:%M")
    for e in comms[-25:]:
        if isinstance(e, dict) and e.get("from") == frm \
                and str(e.get("text") or "") == text \
                and str(e.get("at") or "") >= cutoff:
            return True
    return False


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
# patch-relay spool (card runner-push-cred-gap): a runner whose close-out
# push can't authenticate bundles its session head and POSTs it here;
# merge-sweep fetches the bundle like the runner's own remote.
PATCH_INBOX = DISPATCH_TASKS.parent / "patch-inbox"
RELAY_MAX_BYTES = int(os.environ.get(
    "BOARD_API_RELAY_MAX_BYTES", str(8 * 1024 * 1024)))
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
    sessions.db so finished jobs stop cluttering the session list.
    Queues the hide on the post-write worker — each remote attempt is an
    ssh round-trip that must not sit inside the request flock
    (2026-11-16: writers queued minutes). The 'hidden' comms note lands
    in a second locked write via _append_comms_note."""
    cid = str(card.get("id") or "")
    snap = {"id": cid, "action": dict(_act(card))}

    def work():
        note = _hide_dispatch_session_now(snap)
        if note:
            _append_comms_note(cid, note)

    queue_post_write(work)


def _hide_dispatch_session_now(card: dict) -> str:
    """The hide itself: local db first, then remote runner hosts (ssh,
    ~30s timeout each). Returns the comms note text, '' on nothing to
    report. Never raises."""
    try:
        a = _act(card)
        tid = a.get("task_id") or ""
        if not tid:
            return ""
        sid = _hide_local_session(tid)
        if sid:
            return f"session {sid}… hidden"
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
                return f"session {sid}… hidden on {host}"
    except Exception:
        pass
    return ""


def queue_starve_warn(card: dict) -> str:
    """queue-type-starvation-guard: no claimer serves types outside
    dispatch_repos.SERVED_TYPES (dispatch/container/script). Queueing a
    card typed manual/devin/self silently starves it (2026-10-13
    zombie-sweep: 6 cards queued for days, zero claims). Warn the queuer
    — never auto-flip the type, a manual card queued by hand may mean
    'not for dispatch'. Same for the executor contract: executor=manual
    means Tony's hands — automation never claims it."""
    a = _act(card)
    if str(a.get("status") or "") != "queued":
        return ""
    t = str(a.get("type") or "dispatch")
    if t == "dispatch":
        if str(a.get("executor") or "") == "manual":
            return ("WARNING: action.executor=manual — never claimed by "
                    "automation; this card will starve in queue")
        return ""
    if t not in dr.SERVED_TYPES:
        return (f"WARNING: action.type={t} — kanban-dispatch claims only "
                "type=dispatch; this card will starve in queue")
    return ""


def queue_unclaimable_warn(card: dict) -> str:
    """dispatch-claim-eligibility-visibility (OPS-1097): a queued card
    whose labels/pins/push no declared runner satisfies starves
    invisibly — every host skips it and nothing says why (the
    ops0790-rollout-* cards sat ~3h on labels:[exec]). Compute the
    deterministic gaps at queue time so the queuer sees them
    immediately. '' when some declared runner might serve it."""
    try:
        reasons = dr.unsatisfiable_reasons(
            card, local_host=HOST,
            push_probe=lambda repo: bool(
                dr.push_probe(repo).get("pushable")))
    except Exception:
        return ""
    if not reasons:
        return ""
    return ("WARNING: unclaimable by the declared runner fleet — "
            + "; ".join(reasons)
            + ". Fix action.labels/host pins or teach a runner the "
              "capability (RUNNER_LABELS + ssot.kanban.yml runner_fleet)")


def human_wait_reason(card: dict) -> str:
    """Why this card is human-owned rather than runner-dispatchable.

    Manual is a first-class lane/type, not a queue error: executor=manual,
    lane=manual, or type=manual all mean Tony's hands. A type outside
    dispatch_repos.SERVED_TYPES has no unattended executor at all.
    Returns '' when automation may claim the card."""
    a = _act(card)
    if str(a.get("executor") or "") == "manual":
        return ("action.executor=manual — Tony's hands, "
                "not runner-dispatchable")
    lane = str(a.get("lane") or "")
    if lane == "manual" and not a.get("lane_source"):
        return ("action.lane=manual — Tony's hands, "
                "not runner-dispatchable")
    typ = str(a.get("type") or "dispatch")
    if typ == "manual":
        return ("action.type=manual — human-owned work, "
                "not runner-dispatchable")
    if typ not in dr.SERVED_TYPES:
        return f"action.type={typ!r} has no unattended executor"
    return ""


def queue_wait_reason(card: dict) -> str:
    """Why a queued/claimed-read card is not runner-dispatchable.

    Same contract as human_wait_reason, plus classifier-stamped
    lane=manual: runners never claim lane=manual regardless of
    lane_source, so /queue and /claim must not call it dispatchable.
    Write-door queueing still uses human_wait_reason so a stamped lane
    can be re-classified instead of refused forever."""
    reason = human_wait_reason(card)
    if reason:
        return reason
    if str(_act(card).get("lane") or "") == "manual":
        return ("action.lane=manual — Tony's hands, "
                "not runner-dispatchable")
    return ""


def _wait_kind(card: dict) -> tuple[str, str]:
    """(kind, owner) for a queue_wait_reason hit — manual lanes/types are
    Tony's hands; anything else is an unserved contract for chaba to fix."""
    a = _act(card)
    if (str(a.get("executor") or "") == "manual"
            or str(a.get("type") or "") == "manual"
            or str(a.get("lane") or "") == "manual"):
        return "human", "tony"
    return "unserved", "chaba"


def _refuse_human_queue(card: dict, frm: str, verb: str,
                        reason: str = "") -> str:
    """Record a refused queue/retry on human-owned work.

    The write door never arms a manual card for dispatch: it stays out of
    action.status=queued, is flagged awaiting_action for triage, and the
    caller gets the reason. Returns '' when the card is dispatchable."""
    reason = reason or human_wait_reason(card)
    if not reason:
        return ""
    a = _ensure_act(card)
    if a.get("status") == "queued":
        a["status"] = "idle"  # legacy queued-manual cannot stay claimable
    card["awaiting_action"] = True
    comms_add(card, frm, f"{verb} skipped — {reason}")
    comms_add(card, "chaba", reason)
    return ("not re-queued" if verb == "retry" else "not queued") \
        + f" — {reason}"


def _apply_classify_at_queue(card: dict, a: dict) -> str | None:
    """Queue-time classification (OPS-0838). Sets lane and model, and
    returns an abort message if classified as manual."""
    if not BOARD_CLASSIFY_AT_QUEUE:
        return None
    # An explicit action.lane (author-set, no lane_source provenance) is
    # the routing decision and always wins. A lane the classifier itself
    # stamped (lane_source present) is re-evaluated on each queue so a
    # fixed classifier unsticks cards it misrouted — a bare-lane check
    # left kw-manual false positives stranded forever
    # (dispatch-lane-classifier-spend-false-manual, 2026-11-17).
    if a.get("type") == "dispatch" and not a.get("executor") \
            and (not a.get("lane") or a.get("lane_source")):
        # bounded read-only classes self-route to the kk_mac lane
        # (kk-mac-auto-lane-classifier) — try-first, so a miss still
        # lands on the next lane under the same claim, never starves.
        tc = dr.kk_mac_route(card)
        if tc:
            a["task_class"] = tc
            a["executor"] = "kk_mac_local"
            comms_add(card, "chaba",
                      f"auto-routed to executor=kk_mac_local "
                      f"(task_class={tc})")
            return None
        lane, source, conf = dr.classify_lane(card, with_detail=True)
        a["lane"] = lane
        a["lane_source"] = source.split(":", 1)[0]
        if lane == "manual":
            a["status"] = "idle"
            card["awaiting_action"] = True  # surfaced for triage — a
            # kw-manual hit may be a false positive worth fixing
            comms_add(card, "chaba",
                      f"classified as manual ({source} conf {conf:.2f})")
            return "classified as manual — queue skipped"
        if lane in dr.LANE_MODELS and not a.get("model"):
            a["model"] = dr.LANE_MODELS[lane]
        comms_add(card, "chaba",
                  f"classified as {lane} ({source} conf {conf:.2f})")
    return None


def do_action(card: dict, verb: str, frm: str) -> str:
    a = _ensure_act(card)
    card.pop("awaiting_action", None)  # any deliberate action is triage
    st = a.get("status", "idle")
    if verb == "queue":
        if st == "queued":
            # a legacy queued manual card is reconciled here, not left
            # looking claimable; classifier-stamped lane=manual counts
            # too (runners never claim it) but a fresh queue below can
            # still re-classify it once it is out of queued.
            refused = _refuse_human_queue(
                card, frm, verb, queue_wait_reason(card))
            if refused:
                return refused
            return "already queued"
        if st == "running":
            return "already running"
        refused = _refuse_human_queue(card, frm, verb)
        if refused:
            return refused
        a.setdefault("type", "dispatch")
        a["status"] = "queued"
        a.pop("runner", None)   # a re-queue after done/failed must be
        a.pop("task_id", None)  # claimable by any host, not its last one
        a.pop("verified", None)  # stale stamp must not survive a re-queue
        _ensure_claim(card).pop("session", None)
        msg = _apply_classify_at_queue(card, a)
        if msg:
            return msg
        # honest columns (dispatch-failed-cards-park-in-doing): queued
        # means claimable, and claimable work lives in backlog — not
        # doing/review/done
        if card.get("column") in ("done", "review", "doing"):
            card["column"] = "backlog"
        comms_add(card, frm, "queued for processing")
        warn = queue_starve_warn(card)
        uncl = queue_unclaimable_warn(card)
        if uncl:
            comms_add(card, "chaba", uncl)
            card["awaiting_action"] = True
        if warn:
            comms_add(card, "chaba", warn)
        if warn or uncl:
            return "queued — " + " ".join(
                x for x in (warn, uncl) if x)
        return "queued — kanban-dispatch will claim it"
    if verb == "retry":
        refused = _refuse_human_queue(card, frm, verb,
                                      queue_wait_reason(card))
        if refused:
            return refused
        a["status"] = "queued"
        prev = a.pop("result", None)
        if prev:
            a["last_failure"] = str(prev)[:300]
        a.pop("runner", None)  # free for any host to re-claim
        a.pop("task_id", None)
        # a human re-arm gets a fresh dispatch budget — claims count
        # attempts from here (retry is the escape from the attempt cap)
        a["attempts"] = 0
        a.pop("verified", None)  # a retried card is unverified until it lands
        _ensure_claim(card).pop("session", None)
        if card.get("column") in ("done", "review", "doing"):
            card["column"] = "backlog"
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
        reason = queue_wait_reason(card)
        if reason:
            card["awaiting_action"] = True
            comms_add(card, "chaba", reason)
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
    if col == "review":
        # every review card needs a close-out contract or the ssot-optimize
        # gate fails commits repo-wide (same rule do_finish enforces)
        card.setdefault("review_kind", "verify")
    if col == "done":
        _ensure_act(card)["status"] = "done"
        _ensure_claim(card).pop("session", None)
        hide_dispatch_session(card)
    comms_add(card, frm, f"moved {old} -> {col}")
    return f"moved to {col}"


def do_archive(card: dict, frm: str, cap: bool = False) -> str:
    """Eligibility gate for /action do=archive — the file move itself is
    done by the caller (_archive_move). Only verified done work ages out;
    unverified done cards stay on the board for human review — unless
    cap=True (board over its card cap, archive-done.py --cap): then any
    done card ages out, but never one with an unanswered request."""
    if card.get("column") != "done":
        raise ValueError("archive needs column=done")
    verified = bool((_act(card)).get("verified"))
    if not verified and not cap:
        raise ValueError("archive needs action.verified=true "
                         "(verified done work only) or cap=true")
    if cap and any(not r.get("answer") for r in (card.get("requests") or [])
                   if isinstance(r, dict)):
        raise ValueError("cap archive skips cards with unanswered requests")
    upd = str(card.get("updated") or "")
    try:
        dt = datetime.strptime(upd, "%Y-%m-%d %H:%M")
    except Exception:
        raise ValueError(f"unparseable updated: {upd!r}")
    age = (datetime.now() - dt).days
    if age < ARCHIVE_MIN_DAYS:
        raise ValueError(
            f"too fresh: updated {upd} ({age}d < {ARCHIVE_MIN_DAYS}d)")
    comms_add(card, frm, f"archived ({age}d in done, "
                         f"{'verified' if verified else 'board over card cap'})")
    return f"archived ({age}d in done)"


def _archive_move(p: Path, card: dict) -> None:
    """Persist an archived card under cards/archive/ (non-recursive glob
    keeps it off the board, in git) and commit both sides of the move."""
    adir = p.parent / "archive"
    adir.mkdir(exist_ok=True)
    dest = adir / p.name
    save(dest, card)       # queues the archive-path write for commit
    p.unlink()             # source leaves cards/*.yml -> off the board
    _queue_commit(p, "archive move")  # worker stages source deletion too
    _ARCHIVE_INDEX["t"] = 0.0  # next lookup rebuilds (new member)


def do_unarchive(card: dict, frm: str) -> str:
    """Inverse of do_archive — the caller checks the file actually lives
    under cards/archive/ before calling. Restores column=done."""
    if card.get("column") != "done":
        raise ValueError(f"unarchive expects column=done, got "
                         f"{card.get('column')}")
    comms_add(card, frm, "unarchived — back on the board")
    return "unarchived"


def _unarchive_move(p: Path, card: dict) -> None:
    """Persist an unarchived card back under cards/ and commit both
    sides of the move (inverse of _archive_move)."""
    dest = p.parent.parent / p.name  # cards/archive/x.yml -> cards/x.yml
    save(dest, card)
    p.unlink()
    _queue_commit(p, "unarchive move")
    _ARCHIVE_INDEX["t"] = 0.0  # next lookup rebuilds (member left)


def do_claim(card: dict, body: dict) -> str:
    """Atomic first-wins claim for multi-host dispatch — runs under the
    request flock so two hosts can't both grab a queued card."""
    a = _ensure_act(card)
    if a.get("status") != "queued":
        raise ValueError(f"not claimable (status={a.get('status', 'idle')})")
    human = queue_wait_reason(card)
    if human:
        raise ValueError(f"not claimable ({human})")
    host = (body.get("host") or "").strip()
    if not host:
        raise ValueError("claim needs host")
    # Attempt cap (stalled-claim lifecycle): attempts counts every claim
    # — kanban-dispatch's mark_start and this endpoint alike — so a card
    # that keeps failing can be parked instead of re-dispatched forever.
    # /action do=retry resets attempts; that is the human re-arm.
    att = int(a.get("attempts") or 0)
    max_att = dr.dispatch_attempt_cap(card)
    if att >= max_att:
        raise ValueError(
            f"attempt cap reached ({att}/{max_att}) — /action do=retry "
            "re-arms it")
    pinned = a.get("host")
    if pinned and dr.canon_host(pinned) != dr.canon_host(host):
        raise ValueError(f"card is pinned to {pinned}")
    # Claim-time JEV routing metadata is written atomically with the
    # first-wins claim, so every remote claimer preserves the lane/model.
    lane = str(body.get("lane") or "").strip()
    model = str(body.get("model") or "").strip()
    if lane:
        if lane not in {"codemod", "free_lane", "paid_frontier", "devin",
                        "manual", "nlm_batch"}:
            raise ValueError("invalid action lane")
        a["lane"] = lane
    if model:
        if not dr.MODEL_ID_RE.match(model):
            raise ValueError("invalid action model")
        a["model"] = model
    # Executor contract (opencode-explicit-executor-routing): the claim
    # may carry the resolved executor/profile/target_host so a remote
    # claimer's routing persists atomically with the claim. A declared
    # action.executor is the contract — a claim that disagrees with it
    # is refused, not silently rewritten.
    ex = str(body.get("executor") or "").strip()
    if ex:
        if ex not in dr.EXECUTORS:
            raise ValueError(
                f"invalid action executor (one of {sorted(dr.EXECUTORS)})")
        if a.get("executor") and str(a["executor"]) != ex:
            raise ValueError(
                f"card declares executor={a['executor']} — a claim "
                "can't change the contract")
        a["executor"] = ex
    tc = str(body.get("task_class") or "").strip()
    if tc:
        # the kk_mac claim-time auto-route persists its resolved class
        # atomically with the executor it just set — refuse anything
        # that doesn't pair with kk_mac_local
        if (ex or str(a.get("executor") or "")) != "kk_mac_local" \
                or tc not in dr.KK_MAC_TASK_CLASSES:
            raise ValueError(
                "claim task_class needs executor=kk_mac_local and an "
                f"admitted class {sorted(dr.KK_MAC_TASK_CLASSES)}")
        a["task_class"] = tc
    prof = str(body.get("agent_profile") or body.get("profile")
               or "").strip()
    if prof:
        if not dr.PROFILE_ID_RE.match(prof):
            raise ValueError("invalid action agent_profile")
        a["agent_profile"] = prof
    th = str(body.get("target_host") or "").strip()
    if th:
        if not dr.HOST_ID_RE.match(th):
            raise ValueError("invalid action target_host")
        a["target_host"] = th
    a["runner"] = host
    a["status"] = "running"  # claimed = running from the board's view;
    # the runner's finish call (or a sweeper) is the only way out
    a["attempts"] = int(a.get("attempts") or 0) + 1
    # claim.since is the reaper's age basis — the runner may never write
    # again, so stamp the claim time atomically with the claim itself
    _ensure_claim(card)["since"] = now()
    # honest columns: a live claim means doing from ANY non-terminal
    # column (an auto-retried card re-claimed out of review used to
    # stay in review while it ran — undercounted doing)
    if card.get("column") not in ("doing", "done"):
        card["column"] = "doing"
    card.pop("awaiting_action", None)
    comms_add(card, host, "claimed")
    return "claimed"


def do_finish(card: dict, body: dict) -> str:
    """Remote runner reports its claimed task finished — status->done and
    column->review on success; on failure the claim is dead, so the card
    leaves doing: auto-retry queued in backlog under the attempts cap,
    else parked there as failed (a manual retry re-arms it).
    Only the claiming host may finish a card."""
    a = _ensure_act(card)
    host = (body.get("host") or "").strip()
    if not host:
        raise ValueError("finish needs host")
    if a.get("status") != "running":
        raise ValueError(f"not running (status={a.get('status', 'idle')})")
    if a.get("runner") and dr.canon_host(a["runner"]) != dr.canon_host(host):
        raise ValueError(f"claimed by {a['runner']}")
    ok = bool(body.get("ok", True))
    result = str(body.get("result") or "").strip()
    if result:
        a["result"] = result[:300]
    if "verified" in body:
        # runner close-out merge result (dispatch-auto-merge): True =
        # session branch landed in origin/<default>; False = checked and
        # NOT merged (conflicts / failed goals — stays for a human)
        a["verified"] = bool(body["verified"])
    tail = f": {result[:120]}" if result else ""
    if ok:
        a["status"] = "done"
        card["column"] = "review"
        # every review card needs a close-out contract or the ssot-optimize
        # gate fails commits repo-wide (recurring kanban-commit breakage —
        # verify = the human confirms the work, the safe default)
        card.setdefault("review_kind", "verify")
        _ensure_claim(card).pop("session", None)
        comms_add(card, host, f"finished (ok){tail}")
        return "finished -> review"
    # Failure (stalled-claim lifecycle): no live runner owns this card
    # anymore — parking it in doing overstates active work forever. Same
    # requeue-or-park rule the merge/verified-gate failures use:
    # attempts < max_attempts -> queued for another claim; at cap ->
    # failed in backlog until a human retries. KANBAN_AUTORETRY=0 skips
    # the requeue half.
    a["last_failure"] = (result or "runner reported failure")[:280]
    _ensure_claim(card).pop("session", None)
    att = int(a.get("attempts") or 0)
    max_att = dr.dispatch_attempt_cap(card)
    if os.environ.get("KANBAN_AUTORETRY", "1") != "0" and att < max_att:
        a["status"] = "queued"
        a.pop("runner", None)
        a.pop("task_id", None)
        if card.get("column") != "done":
            card["column"] = "backlog"
        comms_add(card, host,
                  f"finished (failed){tail} — auto-retry queued "
                  f"(attempt {att + 1}/{max_att}) (column -> backlog)")
        return "failed — auto-retry queued"
    a["status"] = "failed"
    if card.get("column") == "doing":
        card["column"] = "backlog"
    comms_add(card, host,
              f"finished (failed){tail} — attempt cap {max_att} reached; "
              "moved doing -> backlog, a manual retry re-arms it")
    return "marked failed"


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
        # idempotent retry: the same answer again is a no-op success —
        # voice/UI double-submits and relay retries must not error
        # (KNB-0180). A different answer still requires reopen.
        if str(ask.get("answer") or "") == answer[:500]:
            return "already answered"
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
    a = _act(card)
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
        # a lone open request is unambiguous — answer it without
        # requiring the caller to know request_id. Requests written
        # directly into card YAML (agent edits, escalations) can lack
        # id/status; heal the id so the request stays referenceable.
        open_reqs = [r for r in _reqs(card)
                     if r.get("status") not in ("answered", "closed")]
        if len(open_reqs) == 1:
            r = open_reqs[0]
            if not r.get("id"):
                r["id"] = slugify(str(r.get("ask") or "request")) or "request"
            rid = r["id"]
        else:
            return do_ask_respond(card, body, frm)
    answer = str(body.get("answer") or body.get("text") or "").strip()
    if not answer and "option" in body:
        # option-index responds work against requests[] too — the voice/UI
        # path posts {option: N} for whichever ask is open; map the index to
        # the option's value (same 'id — label' composite as the ask: path).
        for r in _reqs(card):
            if r.get("id") == rid:
                opts = r.get("options") or []
                try:
                    o = opts[int(body["option"])]
                except (IndexError, TypeError, ValueError):
                    raise ValueError(f"option must be 0..{len(opts) - 1}")
                if isinstance(o, str):
                    answer = o
                else:
                    k = o.get("id") or o.get("v")
                    answer = f"{k} — {o.get('label') or o.get('d') or ''}" if k \
                        else (o.get("label") or o.get("d") or "")
                break
    if not answer:
        raise ValueError("answer required")
    # duplicate ids (legacy cycles): prefer the open entry over answered ones
    _matches = [r for r in _reqs(card) if r.get("id") == rid]
    _matches.sort(key=lambda r: r.get("status") in ("answered", "closed"))
    for r in _matches[:1]:
        if r.get("id") == rid:
            verb = "answered"
            if r.get("status") == "answered":
                if not body.get("reopen"):
                    # idempotent retry: same answer again -> no-op
                    # success; a different answer still needs reopen
                    if str(r.get("answer") or "") == answer[:500]:
                        return "already answered"
                    raise ValueError("already answered")
                verb = "re-answered"
            r["status"] = "answered"
            r["answer"] = answer[:500]
            comms_add(card, frm, f"{verb} {rid}: {answer[:200]}")
            # owned-prefix requests execute their decision in this same
            # write — an answered lab-review used to sit awaiting_action
            # until the weekly lab-review-sweep picked it up (up to 7d).
            executed_owned = False
            if rid.startswith("lab-review") and not r.get("executed"):
                if _lab_decision(card, r):
                    r["executed"] = datetime.now().date().isoformat()
                    executed_owned = True
            # answer recorded but nothing is armed to act on it —
            # flag for triage so the decision doesn't sit silent
            a = _act(card)
            if (not executed_owned
                    and card.get("column") != "done"
                    and a.get("status") not in ("queued", "running")):
                card["awaiting_action"] = True
                comms_add(card, "chaba",
                          "answer recorded but no active action — card needs "
                          "triage (queue it, or spec+arm an action)")
            return "answer saved"
    raise ValueError(f"no request {rid}")


_LAB_SWEEP_MOD = None


def _lab_decision(card: dict, req: dict) -> bool:
    """Apply an answered lab-review immediately — the same
    execute_decision() the weekly lab-review-sweep runs, imported once
    from the sibling script so both paths share the transition table
    (promote->backlog, retire->done, extend->review_by+14d). Any failure
    degrades to the old behavior: answer stays, awaiting_action flags."""
    global _LAB_SWEEP_MOD
    if _LAB_SWEEP_MOD is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lab_review_sweep",
            Path(__file__).resolve().parent / "lab-review-sweep.py")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            _LAB_SWEEP_MOD = mod
        except Exception:
            _LAB_SWEEP_MOD = False
    if not _LAB_SWEEP_MOD:
        return False
    try:
        return bool(_LAB_SWEEP_MOD.execute_decision(card, req))
    except Exception:
        return False


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
    a = _act(card)
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


def queue_delivery(card: dict, record: dict) -> None:
    """Enqueue a session delivery off the request path. _deliver_to_session
    pays ~5-15s per unreachable runner host over ssh — inside the request
    flock that stalls every other writer (2026-11-16: writes queued for
    minutes). The delivery itself is lock-free; only its result note needs
    the lock, appended by _append_comms_note in a second short write."""
    cid = str(card.get("id") or "")
    snap = {"id": cid, "action": dict(_act(card))}
    rec = dict(record)

    def work():
        note = _deliver_to_session(snap, rec)
        if note:
            _append_comms_note(cid, note)

    queue_post_write(work)


_RELAY_SHA_RE = re.compile(r"^[0-9a-f]{6,64}$")
_RELAY_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def do_patch_relay(card: dict, body: dict, frm: str) -> tuple:
    """POST /patch-relay — card runner-push-cred-gap's safety net: a
    runner whose close-out push can't authenticate exports its session
    head as a git bundle and relays it here; the file lands in
    $DISPATCH_DIR/patch-inbox/<card>-<head10>.bundle (+ .json sidecar)
    and merge-sweep fetches it like the runner's own remote. Same head
    relays to the same name → idempotent re-posts."""
    head = str(body.get("head") or "")
    branch = str(body.get("branch") or "")
    if not _RELAY_SHA_RE.match(head):
        raise ValueError("head must be a commit sha")
    if branch and (not _RELAY_REF_RE.match(branch) or ".." in branch):
        raise ValueError("bad branch")
    try:
        blob = base64.b64decode(str(body.get("bundle") or ""),
                                validate=True)
    except Exception:
        raise ValueError("bundle must be base64")
    if not blob:
        raise ValueError("bundle required")
    if len(blob) > RELAY_MAX_BYTES:
        raise ValueError(f"bundle too large ({len(blob)} > "
                         f"{RELAY_MAX_BYTES} bytes)")
    if not blob.startswith(b"# v2 git bundle\n") \
            and not blob.startswith(b"# v3 git bundle\n"):
        raise ValueError("payload is not a git bundle")
    PATCH_INBOX.mkdir(parents=True, exist_ok=True)
    name = f"{card.get('id')}-{head[:10]}.bundle"
    (PATCH_INBOX / name).write_bytes(blob)
    sidecar = {k: body.get(k) for k in
               ("repo", "branch", "base", "head", "task_id",
                "exit_code", "host") if body.get(k) is not None}
    sidecar.update(at=now(), via=frm)
    (PATCH_INBOX / (name + ".json")).write_text(
        json.dumps(sidecar, indent=1) + "\n")
    comms_add(card, "chaba",
              f"patch-relay: {branch or head[:8]} from "
              f"{body.get('host') or frm} — {len(blob)}B bundle in "
              f"patch-inbox ({name}); merge-sweep will land it")
    return f"relayed {name}", name


_ATTACH_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def do_attach(card: dict, body: dict, frm: str) -> tuple:
    """POST /attach (alias /upload) — file/photo evidence on a card
    (board-attachments-photo-image-evidence). The payload lands in the
    repo at docs/ssot/kanban/attachments/<card-id>/<file> — canonical
    store, committed with the card in one commit — and a comms entry
    carries the repo path; render-board2 mirrors the tree into the
    board app's public dir where the UI renders thumbnails.
    Returns (message, [paths to commit alongside the card])."""
    raw = str(body.get("filename") or "").strip()
    if not raw:
        raise ValueError("filename required")
    # basename kills client-supplied directories; the char whitelist
    # kills everything else (no spaces -> the comms-link regex stays
    # trivial, no traversal, URL-safe as-is)
    fn = _ATTACH_NAME_RE.sub("-", Path(raw).name).strip(".-")
    if not fn or fn.startswith("."):
        raise ValueError("bad filename")
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
    if ext not in ATTACH_EXTS:
        raise ValueError(
            f"filename must end with one of {sorted(ATTACH_EXTS)}")
    b64 = str(body.get("payload") or body.get("b64")
              or body.get("data") or "")
    if b64[:64].lower().startswith("data:") and "," in b64[:128]:
        b64 = b64.split(",", 1)[1]      # strip a data: URI prefix
    try:
        blob = base64.b64decode(b64, validate=True)
    except Exception:
        raise ValueError("payload must be base64")
    if not blob:
        raise ValueError("payload required")
    if len(blob) > ATTACH_MAX_BYTES:
        raise ValueError(f"attachment too large ({len(blob)} > "
                         f"{ATTACH_MAX_BYTES} bytes)")
    cid = _ATTACH_NAME_RE.sub("-", str(card.get("id") or "")) or "card"
    ddir = ATTACH_DIR / cid
    ddir.mkdir(parents=True, exist_ok=True)
    dest = ddir / fn
    n = 2
    while dest.exists() and dest.read_bytes() != blob:
        stem, _, e = fn.rpartition(".")
        dest = ddir / f"{stem.rstrip('-')}-{n}.{e}"
        n += 1
    dest.write_bytes(blob)
    # canonical repo-relative link (what the UI parses + what gets
    # committed) — stable even when ATTACH_DIR is redirected in tests
    rel = f"docs/ssot/kanban/attachments/{cid}/{dest.name}"
    comms_add(card, frm,
              f"attachment: {rel} — {raw[:80]} ({len(blob)} B)")
    return f"attached {dest.name} ({len(blob)} B)", [dest], rel


def do_request(card: dict, body: dict) -> str:
    ask = str(body.get("ask") or "").strip()
    if not ask:
        raise ValueError("ask required")
    frm = actor(body)
    to = str(body.get("to") or "tony").strip()
    if to not in ACTORS:
        raise ValueError(f"to must be one of {sorted(ACTORS)}")
    rid = str(body.get("request_id") or "").strip() or slugify(ask)
    reqs = _ensure_reqs(card)
    if any(r.get("id") == rid for r in _reqs(card)):
        raise ValueError(f"duplicate request id {rid}")
    req = {"id": rid, "ask": ask, "status": "open",
           "at": now(), "from": frm}
    if to != "tony":
        req["to"] = to  # absent = tony
    opts = body.get("options")
    if not opts and to == "tony":
        # never emit a buttonless tony-facing request — it renders as an
        # open ask with no way to answer (2026-10-15 complaint). A
        # generic gate is better than a dead card; emitters that know
        # the real choices should pass them explicitly.
        opts = ["proceed", "hold"]
    if opts:
        # dict options may declare the answer's consequence
        # ({id,label,action}) — answer-sweep executes it verbatim.
        # Validate the contract at the door: a bad action would
        # dead-letter the answer silently (KNB-0180).
        for o in opts:
            if isinstance(o, str):
                continue
            if not isinstance(o, dict) or not any(
                    str(o.get(k) or "").strip()
                    for k in ("id", "label", "v", "d")):
                raise ValueError(
                    "options dicts need id/label/v/d")
            act = str(o.get("action") or "").strip().lower()
            if act and act not in OPTION_ACTIONS:
                raise ValueError(
                    f"option action must be one of "
                    f"{sorted(OPTION_ACTIONS)} (got {act!r})")
        req["options"] = opts
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
        # executor contract (opencode-explicit-executor-routing) —
        # the declared executor is first-class: bad values are refused
        # here so a misspelled executor never routes silently.
        ex = str(act.get("executor") or "").strip()
        if ex and ex not in dr.EXECUTORS:
            raise ValueError(
                f"action.executor must be one of {sorted(dr.EXECUTORS)}")
        # lane is a first-class routing knob too (executor=opencode +
        # lane=free_lane -> ops-readonly via LANE_PROFILES). Whitelist it
        # or the write door silently drops the declaration — the first
        # OPS-1021 claims failed closed on exactly that (2026-10-30).
        ln = str(act.get("lane") or "").strip()
        if ln and ln not in (set(dr.LANE_MODELS) | set(dr.LANE_EXECUTORS)):
            raise ValueError(
                f"action.lane must be one of "
                f"{sorted(set(dr.LANE_MODELS) | set(dr.LANE_EXECUTORS))}")
        for pk in ("agent_profile", "profile"):
            pv = str(act.get(pk) or "").strip()
            if pv and not dr.PROFILE_ID_RE.match(pv):
                raise ValueError(
                    f"action.{pk} must be a profile id "
                    "([a-z0-9][a-z0-9-], max 61)")
        if "lane_envelope" in act and not isinstance(act["lane_envelope"], dict):
            raise ValueError("action.lane_envelope must be an object")
        key_alias = str(act.get("llm_key_alias") or "").strip().lower()
        if key_alias and key_alias not in LLM_KEY_ALIASES:
            raise ValueError(
                f"action.llm_key_alias must be one of "
                f"{sorted(LLM_KEY_ALIASES)}")
        th = str(act.get("target_host") or "").strip()
        if th and not dr.HOST_ID_RE.match(th):
            raise ValueError(
                "action.target_host must be a host id "
                "([a-z0-9][a-z0-9.-], max 63)")
        # subject_host is the diagnosis subject, NOT an execution pin —
        # remote-read profiles need it without pinning the claim
        # (OPS-1021 third defer storm: every host read target_host=con01
        # as 'run on con01' and deferred, 2026-11-02)
        sh = str(act.get("subject_host") or "").strip()
        if sh and not dr.HOST_ID_RE.match(sh):
            raise ValueError(
                "action.subject_host must be a host id "
                "([a-z0-9][a-z0-9.-], max 63)")
        ap = str(act.get("artifact") or "").strip()
        if ap and (ap.startswith("/") or ".." in ap.split("/")
                   or len(ap) > 200):
            raise ValueError(
                "action.artifact must be a safe repo-relative path")
        # kk_mac_local executor contract (kk-mac-jev-adapter-integration):
        # the bounded task class is part of the contract — a card must
        # declare one of the admitted classes; other executors need
        # an explicit typed profile envelope.
        tc = str(act.get("task_class") or "").strip()
        if tc and ex == "opencode":
            envelope = act.get("lane_envelope")
            profile = str(act.get("agent_profile") or act.get("profile") or "")
            remote_diagnosis = (
                tc == "diagnosis"
                and profile == "ops-remote-read"
                and isinstance(envelope, dict)
                and envelope.get("task_class") == tc
                and envelope.get("profile") == profile
                and envelope.get("stage") == "S3"
                and envelope.get("target_host") == "idc02"
                and th == "idc02"
                and envelope.get("unattended") is True
                and bool(sh)
                and sh != th
                and envelope.get("subject_host") == sh
                and isinstance(envelope.get("mcp_allowlist"), list)
                and "mcp_debug" in envelope["mcp_allowlist"]
            )
            if (not isinstance(envelope, dict)
                    or envelope.get("task_class") != tc
                    or (tc not in ("read_only", "report")
                        and not remote_diagnosis)):
                raise ValueError(
                    "executor=opencode requires a read_only/report task_class "
                    "matching lane_envelope or an S3 ops-remote-read "
                    "diagnosis envelope")
        elif tc and ex != "kk_mac_local":
            # A bare task_class (no executor pin) is the auto-route
            # hint (kk-mac-auto-lane-classifier): queue-time
            # classification pins executor=kk_mac_local for admitted
            # classes. A pin to another executor, or a class outside
            # the admitted set, still fails closed.
            if ex or tc not in dr.KK_MAC_TASK_CLASSES:
                raise ValueError(
                    "action.task_class is only valid with "
                    "executor=kk_mac_local or, without an executor, "
                    "an admitted class in "
                    f"{sorted(dr.KK_MAC_TASK_CLASSES)}")
        if ex == "kk_mac_local" and tc not in dr.KK_MAC_TASK_CLASSES:
            raise ValueError(
                "executor=kk_mac_local requires action.task_class in "
                f"{sorted(dr.KK_MAC_TASK_CLASSES)}")
        if ex == "kk_mac_local" and ap:
            if not any(ap.lstrip("/").startswith(r)
                       for r in dr.KK_MAC_ARTIFACT_ROOTS):
                raise ValueError(
                    "kk_mac_local artifact must live under "
                    + "/".join(r.rstrip("/") for r in
                               dr.KK_MAC_ARTIFACT_ROOTS))
        pr = str(act.get("prompt") or "")
        if len(pr) > 6000:
            raise ValueError("action.prompt exceeds the 6000-char "
                             "read-only lane limit")
        xp = act.get("expect")
        if xp is not None:
            if not isinstance(xp, dict):
                raise ValueError("action.expect must be an object")
            for k in ("required_keys", "facts"):
                v = xp.get(k)
                if v is not None and (not isinstance(v, list)
                                      or len(v) > 20
                                      or any(not isinstance(s, str)
                                             or len(s) > 200
                                             for s in v)):
                    raise ValueError(
                        f"action.expect.{k} must be a list of <=20 "
                        "short strings")
            enums = xp.get("enums")
            if enums is not None and (
                    not isinstance(enums, dict) or len(enums) > 20
                    or any(not isinstance(v, list) or len(v) > 20
                           for v in enums.values())):
                raise ValueError(
                    "action.expect.enums must be an object of small "
                    "lists")
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
        a = _ensure_act(card)
        st = a.get("status", "idle")
        queued_human = st == "queued" and bool(queue_wait_reason(card))
        if st in ("queued", "running") and not queued_human:
            return {"message": f"card {cid} already active ({st})",
                    "id": cid, "status": st}
        # A re-queue may carry a freshly approved executor envelope. Preserve
        # board-owned lifecycle fields, but update only caller-owned action
        # fields after the same validation used for new cards.
        if act is not None:
            for key in ACTION_KEYS:
                if key in act:
                    a[key] = act[key]
            if "lane" in act:
                # a caller-declared lane is explicit routing — drop the
                # classifier provenance or the next queue re-classifies
                # over it (lane_source semantics: _apply_classify_at_queue)
                a.pop("lane_source", None)
        a.setdefault("type", "dispatch")
        human = (queue_wait_reason(card) if st == "queued"
                 else human_wait_reason(card))
        if human:
            # A manual/human card is never re-armed for dispatch — keep the
            # lifecycle honest (done stays done) and flag it for triage.
            if a.get("status") not in ("done",):
                a["status"] = "idle"
            if card.get("column") != "done":
                card["awaiting_action"] = True
            comms_add(card, frm, f"re-spawn skipped — {human}")
            comms_add(card, "chaba", human)
            card["updated"] = now()
            save(p, card)
            return {"message": f"card {cid} not queued — {human}",
                    "id": cid, "status": a.get("status") or "idle"}
        a["status"] = "queued"
        a.pop("runner", None)   # same re-arm semantics as /action do=queue
        a.pop("task_id", None)
        cmsg = _apply_classify_at_queue(card, a)
        if card.get("column") in ("done", "review"):
            card["column"] = "backlog"
        comms_add(card, frm, "re-spawned from report page")
        card["updated"] = now()
        warn = queue_starve_warn(card)
        uncl = queue_unclaimable_warn(card)
        if uncl:
            comms_add(card, "chaba", uncl)
            card["awaiting_action"] = True
        if warn:
            comms_add(card, "chaba", warn)
        save(p, card)
        warn_all = " ".join(x for x in (warn, uncl) if x)
        return {"message": (f"card {cid} " + (cmsg or "re-queued")
                            + (f" ({warn_all})" if warn_all else "")),
                "id": cid, "status": a.get("status") or "queued"}

    card = {"id": cid, "title": title[:160], "column": col,
            "updated": now()}
    brief = str(body.get("brief") or "").strip()
    if brief:
        card["brief"] = brief[:600]
    if pri:
        card["priority"] = pri
    if report:
        card["report"] = report
    for key in ("program", "blocked_by", "review_kind",
                "auto_done_when"):
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
            if not dr.MODEL_ID_RE.match(model):
                raise ValueError("action.model must be a model id "
                                 "([a-zA-Z0-9._/-], max 80)")
            card["action"]["model"] = model
    dep = body.get("deploy")
    if dep is not None:
        # deploy-preflight contract (OPS-1116): the write door used to
        # drop deploy: silently — first live rehearsal hand-edited YAML.
        # Shape-validate here; deploy-preflight still owns the target
        # registry check (unknown targets stamp deploy.status=error).
        if not isinstance(dep, dict):
            raise ValueError("deploy must be an object")
        tgt = str(dep.get("target") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", tgt):
            raise ValueError(
                "deploy.target must be a registry key ([a-z0-9-], "
                "max 41)")
        card["deploy"] = {"target": tgt}
        dnote = str(dep.get("note") or "").strip()
        if dnote:
            card["deploy"]["note"] = dnote[:300]
    cmsg = None
    if body.get("queue"):
        a = _ensure_act(card)
        a.setdefault("type", "dispatch")
        human = human_wait_reason(card)
        if human:
            a["status"] = "idle"
            card["awaiting_action"] = True
            comms_add(card, "chaba", human)
            cmsg = f"not queued — {human}"
        else:
            a["status"] = "queued"
            # same queue-time classification as /action do=queue (OPS-0838 +
            # kk-mac-auto-lane-classifier) — a spawn-and-queue gets the same
            # route pins instead of silently bypassing classification
            cmsg = _apply_classify_at_queue(card, a)
    note = str(body.get("note") or "").strip()
    if note:
        card["note"] = note[:500]
    help_txt = str(body.get("help") or "").strip()
    if help_txt:
        card["help"] = help_txt[:4000]
    want_ref = str(body.get("ref") or "").strip().upper()
    card["ref"] = (want_ref if REF_RE.match(want_ref)
                   else alloc_ref(ref_cat(card, body)))
    card.setdefault("comms", []).append(  # setdefault — queue-time
        {"at": now(), "from": frm,      # classification notes land
         "text": str(body.get("text") or  # before the first comms entry
                    "card captured via board-api")[:500]})
    warn = queue_starve_warn(card)
    uncl = queue_unclaimable_warn(card)
    if uncl:
        card["comms"].append({"at": now(), "from": "chaba",
                              "text": uncl})
        card["awaiting_action"] = True
    if warn:
        card["comms"].append({"at": now(), "from": "chaba",
                              "text": warn})
    save(p, card)
    warn_all = " ".join(x for x in (warn, uncl) if x)
    msg = f"card {cid} created in {col} as {card['ref']}"
    res = {"message": msg, "id": cid, "ref": card["ref"]}
    a = _act(card)
    if a.get("status"):
        res["status"] = a["status"]
        if a["status"] == "queued":
            res["message"] = msg + " (queued)" \
                + (f" {warn_all}" if warn_all else "")
        elif cmsg:
            res["message"] = msg + f" — {cmsg}"
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


# --- unified mutation door (card nest-api-unified-mutation-service) ----
# WP-bound writes (/lesson, /job) and MDDB-bound writes (/report) run
# under WP_LOCK — remote-service calls serialize among themselves WITHOUT
# holding the card flock (a slow WP round-trip must not stall /comment).
# /inbox writes a repo file, so it stays under the card LOCK where the
# immediate-commit discipline lives.

WP_LOCK = Path(os.environ.get("BOARD_API_WP_LOCK",
                              "/tmp/board-api-wp.lock"))
WP_ENV_FILE = Path(os.environ.get(
    "BOARD_API_WP_ENV",
    str(Path.home() / ".config/secrets/wp-boards.env")))
WIKI_ENV_FILE = Path(os.environ.get(
    "BOARD_API_WIKI_ENV",
    str(Path.home() / ".config/secrets/wiki-h3-gizmo.env")))
INBOX_DIR = REPO / "docs/ssot/focus-inbox"
MDDB = os.environ.get("MDDB_BASE_URL",
                      "http://100.102.134.91:11027/v1").rstrip("/")
MDDB_PAGES = "ada-cms-pages"
# lesson corpus mirror on the content plane (card
# assessments-to-education-split-ssot-keep-113ca4): /lesson dual-writes
# here so agents can retrieve what they file via MDDB search — without
# it, Education knowledge is thin-and-invisible to every agent.
MDDB_LESSONS = os.environ.get("BOARD_API_MDDB_LESSONS",
                              "chaba-lessons")
REMOTE_WRITE_PATHS = {"/lesson", "/job", "/report", "/publish",
                      "/wiki/extension", "/wiki/news-review",
                      "/wiki/news-diagnose", "/wiki/page"}
WIKI_EXTENSION_ALLOWLIST = {
    "CategoryTree", "Mermaid", "MsUpload", "MultimediaViewer",
    "Cargo", "PageForms", "Lockdown",
}
WIKI_API_CALL = None

# --- publication layer (devnest-publication-adapter-layer) ------------------
# State lives off-repo on the service host; tests redirect via env.
PUB_STATE_DIR = Path(os.environ.get(
    "BOARD_API_PUB_STATE",
    str(Path.home() / ".local/state/board-api-publish")))
PUB_TG_URL = os.environ.get("PUB_TELEGRAM_URL",
                            "http://127.0.0.1:8919/send")
PUB_PROGRESS_MIN_S = int(os.environ.get("PUB_PROGRESS_MIN_S", "900"))
PUB_TG_MIN_S = int(os.environ.get("PUB_TG_MIN_S", "600"))
PUB_ALERT_MIN_S = int(os.environ.get("PUB_ALERT_MIN_S", "60"))

# --- runner readiness projection (runner-readiness-projection, KNB-1007) --
# Verdicts live off-repo on the service host: each runner POSTs its own
# claimability verdicts + active claims, so GET /queue reports
# runner-observed truth instead of a central simulation of host state.
READY_STATE_DIR = Path(os.environ.get(
    "BOARD_API_READY_STATE",
    str(Path.home() / ".local/state/board-api-ready")))
READY_FILE = READY_STATE_DIR / "verdicts.json"
READY_LOCK = Path(os.environ.get("BOARD_API_READY_LOCK",
                                 "/tmp/board-api-ready.lock"))
READY_STALE_S = int(os.environ.get("BOARD_API_READY_STALE_S", "900"))
READY_HOST_TTL_S = int(os.environ.get("BOARD_API_READY_HOST_TTL_S",
                                      str(7 * 86400)))


class UpstreamError(RuntimeError):
    """Remote write service (WP/MDDB) failed — surfaces as a 502 so a
    caller can tell door-unavailable from bad-request."""


def _load_env_file(p: Path) -> dict:
    env = {}
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _wiki_env() -> tuple[dict, str]:
    """Load the Wiki service credentials and normalize its API URL."""
    env = _load_env_file(WIKI_ENV_FILE)
    host = env.get("WIKI_HOST", "").rstrip("/")
    if host.endswith("/v0"):
        host = host[:-3]
    api = (env.get("WIKI_API_URL") or f"{host}/api.php").rstrip("/")
    if not host or not env.get("WIKI_USER") or not env.get("WIKI_PASSWORD"):
        raise UpstreamError("wiki credentials unavailable")
    return env, api


def _wiki_api_call(api_url: str, opener, params: dict, post: bool = False):
    """Call MediaWiki Action API; tests may replace WIKI_API_CALL."""
    if WIKI_API_CALL is not None:
        return WIKI_API_CALL(params, post)
    data = urllib.parse.urlencode(params).encode() if post else None
    url = api_url if post else api_url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": "chaba-board-api/1.0"})
    try:
        return json.loads(opener.open(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise UpstreamError(f"mediawiki -> {e.code}: {detail}")
    except OSError as e:
        raise UpstreamError(f"mediawiki -> {e}")


def _wiki_installed(api_url: str, opener) -> list[str]:
    result = _wiki_api_call(
        api_url, opener,
        {"action": "query", "meta": "siteinfo",
         "siprop": "extensions", "format": "json"})
    return sorted(x.get("name", "")
                  for x in result.get("query", {}).get("extensions", []))


def do_wiki_extension(body: dict, frm: str) -> dict:
    """List or confirm-gated install/enable/disable of approved extensions."""
    action = str(body.get("action") or "list").strip().lower()
    name = str(body.get("name") or "").strip()
    if action not in {"list", "install", "enable", "disable"}:
        raise ValueError("action must be list|install|enable|disable")
    if action != "list" and name not in WIKI_EXTENSION_ALLOWLIST:
        raise ValueError(
            f"name is not approved (choose {sorted(WIKI_EXTENSION_ALLOWLIST)})")
    env, api_url = _wiki_env()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))
    before = _wiki_installed(api_url, opener)
    if action == "list":
        return {"action": "list", "installed": before,
                "approved": sorted(WIKI_EXTENSION_ALLOWLIST),
                "message": "wiki extension list"}

    login = _wiki_api_call(
        api_url, opener,
        {"action": "query", "meta": "tokens", "type": "login",
         "format": "json"})
    login_token = login["query"]["tokens"]["logintoken"]
    logged = _wiki_api_call(
        api_url, opener,
        {"action": "login", "lgname": env["WIKI_USER"],
         "lgpassword": env["WIKI_PASSWORD"], "lgtoken": login_token,
         "format": "json"}, post=True).get("login", {})
    if logged.get("result") != "Success":
        raise UpstreamError("mediawiki login failed")
    csrf = _wiki_api_call(
        api_url, opener,
        {"action": "query", "meta": "tokens", "format": "json"}
    )["query"]["tokens"]["csrftoken"]
    result = _wiki_api_call(
        api_url, opener,
        {"action": "springboard", "sbaction": action,
         "sbtype": "extension", "sbname": name, "token": csrf,
         "format": "json"}, post=True)
    if "error" in result:
        raise UpstreamError("springboard: " +
                            str(result["error"].get("info") or
                                result["error"].get("code")))
    after = _wiki_installed(api_url, opener)
    if action == "install" and name not in after:
        raise UpstreamError(f"{name} install was not visible after request")
    return {"action": action, "name": name, "before": before,
            "after": after, "verified": name in after,
            "actor": frm,
            "message": f"wiki extension {action}: {name}"}


def do_wiki_news_review(body: dict, frm: str) -> dict:
    """Read one protected PrivateNews page for Ada's review workflow."""
    title = str(body.get("wiki_title") or "").strip()
    if (not title.startswith("PrivateNews:") or
            "\n" in title or "\r" in title):
        raise ValueError("wiki_title must be under PrivateNews:")
    env, api_url = _wiki_env()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))
    login = _wiki_api_call(
        api_url, opener,
        {"action": "query", "meta": "tokens", "type": "login",
         "format": "json"})
    login_token = login["query"]["tokens"]["logintoken"]
    logged = _wiki_api_call(
        api_url, opener,
        {"action": "login", "lgname": env["WIKI_USER"],
         "lgpassword": env["WIKI_PASSWORD"], "lgtoken": login_token,
         "format": "json"}, post=True).get("login", {})
    if logged.get("result") != "Success":
        raise UpstreamError("mediawiki login failed")
    result = _wiki_api_call(
        api_url, opener,
         {"action": "query", "titles": title, "prop": "info|revisions",
         "rvprop": "ids|timestamp|content", "rvslots": "main",
         "format": "json"})
    page = next(iter(result.get("query", {}).get("pages", {}).values()), {})
    if "missing" in page:
        raise ValueError("private News page does not exist")
    revision = (page.get("revisions") or [{}])[0]
    content = (revision.get("slots") or {}).get("main", {}).get("*", "")
    return {
        "wiki_title": title,
        "pageid": page.get("pageid"),
        "revid": revision.get("revid"),
        "timestamp": revision.get("timestamp"),
        "wikitext": str(content)[:20000],
        "actor": frm,
        "message": "private News review read",
    }


def do_wiki_news_diagnose(body: dict, frm: str) -> dict:
    """Return promotion gates without reading or mutating a public page."""
    private_title = str(body.get("private_wiki_title") or "").strip()
    public_title = str(body.get("public_wiki_title") or "").strip()
    if not private_title.startswith("PrivateNews:"):
        raise ValueError("private_wiki_title must be under PrivateNews:")
    if not public_title.startswith("News/"):
        raise ValueError("public_wiki_title must be under News/")

    review = do_wiki_news_review(
        {"wiki_title": private_title}, frm)
    checks = [{
        "id": "private_page",
        "status": "pass",
        "revid": review.get("revid"),
    }]
    expected_revid = body.get("review_revid")
    if expected_revid is not None:
        try:
            expected_revid = int(expected_revid)
        except (TypeError, ValueError):
            expected_revid = -1
        checks.append({
            "id": "review_revision",
            "status": "pass" if expected_revid == review.get("revid")
            else "blocked",
            "expected": expected_revid,
            "actual": review.get("revid"),
        })
    else:
        checks.append({
            "id": "review_revision",
            "status": "blocked",
            "reason": "review_revid is required for promotion",
        })

    env, api_url = _wiki_env()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))
    login = _wiki_api_call(
        api_url, opener,
        {"action": "query", "meta": "tokens", "type": "login",
         "format": "json"})
    login_token = login["query"]["tokens"]["logintoken"]
    logged = _wiki_api_call(
        api_url, opener,
        {"action": "login", "lgname": env["WIKI_USER"],
         "lgpassword": env["WIKI_PASSWORD"], "lgtoken": login_token,
         "format": "json"}, post=True).get("login", {})
    if logged.get("result") != "Success":
        raise UpstreamError("mediawiki login failed")
    target = _wiki_api_call(
        api_url, opener,
        {"action": "query", "titles": public_title, "prop": "info",
         "format": "json"})
    target_page = next(
        iter(target.get("query", {}).get("pages", {}).values()), {})
    checks.append({
        "id": "public_target",
        "status": "blocked" if "missing" not in target_page else "pass",
        "exists": "missing" not in target_page,
    })

    card_ref = str(body.get("card_ref") or "").strip()
    if not card_ref:
        checks.append({
            "id": "card_authorization",
            "status": "blocked",
            "reason": "promotion requires a matching board card",
        })
    else:
        try:
            card = load(card_path(card_ref))
            haystack = json.dumps(card, ensure_ascii=False)
            authorized = private_title in haystack and public_title in haystack
            checks.append({
                "id": "card_authorization",
                "status": "pass" if authorized else "blocked",
                "card_ref": card_ref,
                "reason": None if authorized else
                "card does not name both promotion pages",
            })
        except ValueError as exc:
            checks.append({
                "id": "card_authorization",
                "status": "blocked",
                "card_ref": card_ref,
                "reason": str(exc),
            })
    checks.append({
        "id": "confirmation",
        "status": "pending",
        "reason": "diagnosis never confirms or publishes",
    })
    ready = all(c["status"] == "pass" for c in checks
                if c["id"] != "confirmation")
    return {
        "operation": "promote",
        "ready": ready,
        "diagnosis_id": "diag-" + hashlib.sha1(
            f"{private_title}\0{public_title}\0{review.get('revid')}".encode()
        ).hexdigest()[:16],
        "checks": checks,
        "review": review,
        "actor": frm,
        "message": "News promotion diagnosis",
    }


def _wiki_login(api_url: str, env: dict):
    """Bot-password login -> (opener, csrf_token). The three do_wiki_*
    doors above inline this same dance; new code uses the helper."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))
    login = _wiki_api_call(
        api_url, opener,
        {"action": "query", "meta": "tokens", "type": "login",
         "format": "json"})
    login_token = login["query"]["tokens"]["logintoken"]
    logged = _wiki_api_call(
        api_url, opener,
        {"action": "login", "lgname": env["WIKI_USER"],
         "lgpassword": env["WIKI_PASSWORD"], "lgtoken": login_token,
         "format": "json"}, post=True).get("login", {})
    if logged.get("result") != "Success":
        raise UpstreamError("mediawiki login failed")
    csrf = _wiki_api_call(
        api_url, opener,
        {"action": "query", "meta": "tokens", "format": "json"}
    )["query"]["tokens"]["csrftoken"]
    return opener, csrf


def _wiki_namespaces(api_url: str, opener) -> set:
    """Registered namespace names (canonical + localized), lowercase —
    e.g. {'template', 'แม่แบบ', 'privatenews', 'education', ...}."""
    result = _wiki_api_call(
        api_url, opener,
        {"action": "query", "meta": "siteinfo", "siprop": "namespaces",
         "format": "json"})
    names = set()
    for ns in (result.get("query", {}).get("namespaces") or {}).values():
        for k in ("*", "canonical"):
            v = str(ns.get(k) or "").strip().lower()
            if v:
                names.add(v)
    return names


def _wiki_page_templates(env: dict) -> set:
    """The support templates this door may write — configured names +
    the education/report defaults. Template: is the canonical alias of
    แม่แบบ: on the Thai wiki."""
    out = set()
    for key, default in (("WIKI_EDUCATION_TEMPLATE", "แม่แบบ:Education"),
                         ("WIKI_REPORT_TEMPLATE", "แม่แบบ:Report")):
        t = str(env.get(key) or default).strip()
        if t:
            out.add(t)
            if t.startswith("แม่แบบ:"):
                out.add("Template:" + t.split(":", 1)[1])
    return out


WIKI_PAGE_PREFIXES = ("Education:", "Reports:", "Infrastructure:")
WIKI_PAGE_TITLE_MAX = 150
WIKI_PAGE_TEXT_MAX = 200000


def do_wiki_page(body: dict, frm: str) -> dict:
    """POST /wiki/page — guarded raw page write for support pages the
    kind-gated sinks can't reach: แม่แบบ:Education / แม่แบบ:Report
    templates and Education:/Reports:/Infrastructure: index/portal/host
    pages (card wiki-member-knowledge-surface-migrate-wp-3a1cf2;
    Infrastructure: admitted by wiki-page-door-infrastructure-namespace).
    The allowlist keeps this from becoming a generic write backdoor
    around the News review gate — main space, News/, PrivateNews: and
    every other namespace are refused. Prefixed writes additionally
    verify the namespace is actually registered (siteinfo) so a premature
    call can't litter main space with 'Education:Foo' pages — and
    Infrastructure: edits still have to pass the wiki-side Lockdown
    group check (inhouse/sysop), the prefix gate is not an ACL grant."""
    title = str(body.get("title") or body.get("wiki_title") or "").strip()
    text = str(body.get("wikitext") or body.get("text") or "")
    if not title or "\n" in title or "\r" in title \
            or len(title) > WIKI_PAGE_TITLE_MAX:
        raise ValueError("title required (<=150 chars, single line)")
    if not text.strip():
        raise ValueError("wikitext required")
    if len(text) > WIKI_PAGE_TEXT_MAX:
        raise ValueError(f"wikitext over {WIKI_PAGE_TEXT_MAX} chars")
    env, api_url = _wiki_env()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))
    if title not in _wiki_page_templates(env):
        prefix = next((p for p in WIKI_PAGE_PREFIXES
                       if title.startswith(p)), None)
        if prefix is None:
            raise ValueError(
                "title not allowed — must be an approved template or "
                f"under {'/'.join(WIKI_PAGE_PREFIXES)}")
        if prefix[:-1].lower() not in _wiki_namespaces(api_url, opener):
            raise ValueError(
                f"namespace {prefix[:-1]!r} is not registered on the "
                "wiki — LocalSettings step first (card comm 2026-11-06)")
    # The edit MUST go through the login opener — it carries the session
    # cookies; the anon opener above gets badtoken on a logged-in csrf.
    opener, csrf = _wiki_login(api_url, env)
    result = _wiki_api_call(
        api_url, opener,
        {"action": "edit", "title": title, "text": text,
         "summary": str(body.get("summary")
                        or f"chaba wiki support page ({frm})")[:200],
         "token": csrf, "format": "json"}, post=True)
    edited = result.get("edit", {})
    if edited.get("result") not in ("Success", "Nochange"):
        err = result.get("error") or {}
        raise UpstreamError("mediawiki edit failed: " +
                            str(err.get("info") or edited or result)[:300])
    return {"wiki_title": title, "pageid": edited.get("pageid"),
            "revid": edited.get("newrevid"),
            "action": edited.get("result", "").lower(),
            "actor": frm,
            "message": f"wiki page {edited.get('result', '?').lower()}: "
                       f"{title}"}


def wp_api(route: str, data=None, method: str | None = None):
    """WP REST call (index.php?rest_route= style — the Plesk vhost 404s
    /wp-json). Creds live in wp-boards.env on the SERVICE host only;
    callers of /lesson and /job never see them — that is the point of
    the door. Tests monkeypatch this seam."""
    try:
        env = _load_env_file(WP_ENV_FILE)
        base = env["WP_SITE_URL"].rstrip("/")
        tok = base64.b64encode(
            f'{env["WP_APP_USER"]}:{env["WP_APP_PASSWORD"]}'
            .encode()).decode()
    except (OSError, KeyError) as e:
        raise UpstreamError(f"wp creds unavailable: {e}")
    u = (f"{base}/index.php?rest_route="
         f"{urllib.parse.quote(route, safe='/&=')}")
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        u, data=body, method=method or ("POST" if data else "GET"),
        headers={"Authorization": f"Basic {tok}",
                 "Content-Type": "application/json",
                 "User-Agent": "chaba-board-api/1.0"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=45).read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise UpstreamError(f"wp {route} -> {e.code}: {detail}")
    except OSError as e:
        raise UpstreamError(f"wp {route} -> {e}")


def _mddb_post(path: str, payload: dict, timeout: int = 30):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise UpstreamError(f"mddb {path} -> {e.code}: {detail}")
    except OSError as e:
        raise UpstreamError(f"mddb {path} -> {e}")


_gemini_mod = None


def _litellm_translation_key() -> str:
    """Return the scoped virtual key for free-only lesson translation."""
    key = os.environ.get("LITELLM_KEY_MDDB")
    if key:
        return key
    sources = (
        (Path.home() / ".config/secrets/litellm-keys.env",
         "LITELLM_KEY_MDDB"),
        (Path.home() / ".config/secrets/mddb-gemini.env",
         "LITELLM_KEY"),
    )
    for path, variable in sources:
        try:
            key = _load_env_file(path).get(variable, "")
        except OSError:
            continue
        if key:
            return key
    return ""


# Translation cache (card board-api-lesson-post-flood, KNB-1076): the
# free-tier Thai call is the expensive part of every /lesson write —
# re-filed lessons with identical content re-translated every time, and
# a flooding producer burned the whole free-tier RPM budget. Content is
# deterministic input, so sha256 -> Thai is a safe memo; only non-empty
# results are cached so a transient failure can still retry.
_TH_CACHE_PATH = Path(os.environ.get(
    "BOARD_LESSON_TH_CACHE",
    str(Path.home() / ".local/state/board-api/lesson-th-cache.json")))
_TH_CACHE_MAX = 2000
_th_cache: dict | None = None
_th_cache_lock = threading.Lock()


def _th_cache_get() -> dict:
    global _th_cache
    if _th_cache is None:
        try:
            _th_cache = json.loads(_TH_CACHE_PATH.read_text() or "{}")
            if not isinstance(_th_cache, dict):
                _th_cache = {}
        except Exception:
            _th_cache = {}
    return _th_cache


def _th_cache_put(h: str, th: str) -> None:
    with _th_cache_lock:
        c = _th_cache_get()
        c[h] = th
        if len(c) > _TH_CACHE_MAX:
            for k in list(c)[:len(c) - _TH_CACHE_MAX]:
                c.pop(k, None)
        try:
            _TH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _TH_CACHE_PATH.write_text(json.dumps(c))
        except Exception:
            pass


def _gemini_thai(html_text: str) -> str:
    """Free-only LiteLLM translation; failure degrades to English-only."""
    global _gemini_mod
    if _gemini_mod is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gemini_rest", REPO / "scripts/ada/gemini_rest.py")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            _gemini_mod = mod
        except Exception:
            _gemini_mod = False
    if not _gemini_mod:
        return ""
    key = _litellm_translation_key()
    if not key:
        return ""
    h = hashlib.sha256(html_text.encode()).hexdigest()[:24]
    cached = _th_cache_get().get(h)
    if cached:
        return cached
    try:
        # Do not fall through to a paid provider when the free tier is capped.
        th = _gemini_mod.generate(
            "Translate the following HTML lesson to natural Thai. "
            "Keep HTML tags, code, URLs, and proper names verbatim. "
            "Output ONLY the translated HTML.\n\n" + html_text,
            "gemini-3.5-flash-lite-free", key=key,
            base_url_override=os.environ.get(
                "BOARD_API_LITELLM_URL", "http://100.102.134.91:4000"),
            timeout=12, max_attempts=1, label="board-api-lesson-th",
            tags="service=board-api,job=lesson-translation,route=free-only")
        th = (th or "").strip()
        if th:
            _th_cache_put(h, th)
        return th
    except Exception:
        return ""


LESSON_LEVELS = {"intro", "working", "deep"}
LESSON_SOURCES = {"chat", "voice", "link"}



def _touch_lessons(body: dict, frm: str) -> dict:
    """Bump WP modified on lessons (all, or the slugs in body['slugs'])."""
    slugs = [str(x).strip() for x in (body.get("slugs") or []) if str(x).strip()]
    now_iso = datetime.now(timezone.utc).replace(
        microsecond=0).isoformat()
    if not slugs:
        hits = wp_api("/wp/v2/lesson&status=private&per_page=100"
                      "&_fields=slug,id")
        if isinstance(hits, list):
            slugs = [h["slug"] for h in hits if h.get("slug")]
    touched, missing = 0, []
    for slug in slugs:
        hits = wp_api(f"/wp/v2/lesson&slug={slug}&status=private")
        if isinstance(hits, list) and hits:
            pid = hits[0]["id"]
            wp_api(f"/wp/v2/lesson/{pid}", {"modified": now_iso})
            touched += 1
        else:
            missing.append(slug)
    return {"message": f"touched {touched} lessons",
            "touched": touched, "missing": missing, "via": frm}


def _read_lessons(body: dict, frm: str) -> dict:
    """op=list | op=get — read side of the education door (OPS-0821).
    Agents/lessons-due get lesson content without WP creds.
    source=wiki reads the Education: namespace instead of the WP CPT
    (post-migration store; same row shape, plus wiki_title/url).
    Unset source follows the write flag: under
    WIKI_EDUCATION_WRITE=wiki the WP CPT is a frozen archive, so the
    default read must come from the store new writes land in."""
    op = body.get("op")
    source = str(body.get("source") or "").strip().lower()
    if not source:
        mode, _wenv = _lesson_write_env()
        source = "wiki" if mode == "wiki" else "wp"
    if source == "wiki":
        return _read_lessons_wiki(body, frm)
    if source == "mddb":
        return _read_lessons_mddb(body, frm)
    if source != "wp":
        raise ValueError("source must be wp, wiki, or mddb")
    if op == "list":
        hits, page = [], 1
        while page <= 5:                # hard cap 500 — same bound as
            batch = wp_api(             # do_lesson_topics; without
                "/wp/v2/lesson&status=private&per_page=100"  # paging the
                f"&page={page}&_fields=slug,title,modified,meta")  # list
            if not isinstance(batch, list) or not batch:      # silently
                break                   # truncated at 100 of 124
            hits += batch               # (found 2026-11-06)
            if len(batch) < 100:
                break
            page += 1
        out = []
        for h in hits:
            m = h.get("meta") or {}
            out.append({"slug": h.get("slug"),
                            "topic": m.get("topic", ""),
                            "level": m.get("level", ""),
                            "modified": h.get("modified"),
                            "next_review": m.get("next_review", ""),
                            "status": m.get("status", ""),
                            "no_th": bool(m.get("no_th"))})
        return {"lessons": out, "count": len(out), "via": frm,
                "source": "wp",
                "message": f"listed {len(out)} lessons"}
    slug = str(body.get("slug") or "").strip()
    if not slug:
        raise ValueError("op=get requires slug")
    hits = wp_api(f"/wp/v2/lesson&slug={slug}&status=private")
    if not (isinstance(hits, list) and hits):
        raise ValueError(f"lesson not found: {slug}")
    h = hits[0]
    return {"slug": h.get("slug"), "title": (h.get("title") or {}).get("rendered", ""),
            "content": (h.get("content") or {}).get("rendered", ""),
            "meta": h.get("meta") or {}, "modified": h.get("modified"),
            "via": frm, "source": "wp", "message": f"get {slug}"}


def _read_lessons_mddb(body: dict, frm: str) -> dict:
    """op=list | op=get with source=mddb — the chaba-lessons mirror read:
    the retrieval surface the mirror exists for (agents search MDDB
    directly too; this keeps door-shaped reads working)."""
    op = body.get("op")
    docs = _mddb_post("search", {"collection": MDDB_LESSONS,
                                 "limit": 500})
    if not isinstance(docs, list):
        docs = docs.get("result", docs.get("docs", []))
    if op == "list":
        out = []
        for d in docs:
            m = d.get("meta") or {}
            out.append({"slug": d.get("key"),
                        "topic": _meta_first(m, "topic"),
                        "wiki_title": _meta_first(m, "wiki_title"),
                        "url": _meta_first(m, "url"),
                        "level": _meta_first(m, "level"),
                        "modified": d.get("updated_at") or
                        _meta_first(m, "updated"),
                        "next_review": _meta_first(m, "next_review"),
                        "status": _meta_first(m, "status"),
                        "no_th": bool(m.get("no_th"))})
        out.sort(key=lambda r: r["slug"])
        return {"lessons": out, "count": len(out), "via": frm,
                "source": "mddb",
                "message": f"listed {len(out)} lessons"}
    slug = str(body.get("slug") or "").strip()
    if not slug:
        raise ValueError("op=get requires slug")
    for d in docs:
        if d.get("key") == slug:
            m = d.get("meta") or {}
            return {"slug": slug,
                    "title": _meta_first(m, "title"),
                    "wiki_title": _meta_first(m, "wiki_title"),
                    "url": _meta_first(m, "url"),
                    "content": d.get("contentMd") or
                    d.get("content_md", ""),
                    "meta": m,
                    "modified": d.get("updated_at") or
                    _meta_first(m, "updated"),
                    "via": frm, "source": "mddb",
                    "message": f"get {slug}"}
    raise ValueError(f"lesson not found: {slug}")


def _delete_lesson(body: dict, frm: str) -> dict:
    """op=delete — remove a lesson by slug (guarded: devin/tony only).
    KNB-0830: the door had no delete; junk probes (id 2259/2261) were
    stuck and Cloudflare blocks direct WP DELETE (403/1010) on the public
    front — the door's server-side wp_api call bypasses that edge."""
    if frm not in ("devin", "tony"):
        raise ValueError("delete requires devin/tony actor")
    slug = str(body.get("slug") or "").strip()
    if not slug:
        raise ValueError("delete requires slug")
    hits = wp_api(f"/wp/v2/lesson&slug={slug}&status=private")
    if not (isinstance(hits, list) and hits):
        raise ValueError(f"lesson not found: {slug}")
    pid = hits[0]["id"]
    # NB: '&' not '?' — wp_api puts the whole route inside rest_route=,
    # so '?' would be %-encoded into the route path -> rest_no_route.
    r = wp_api(f"/wp/v2/lesson/{pid}&force=true", method="DELETE")
    return {"message": f"deleted {slug} (post {pid})", "slug": slug,
            "post_id": pid, "mddb": _lesson_mddb_delete(slug),
            "via": frm}


def _delete_lesson_wiki(body: dict, frm: str) -> dict:
    """op=delete under WIKI_EDUCATION_WRITE=wiki — the Education: page
    IS the store, so delete targets it (the frozen WP archive is left
    alone). slug lookups walk the namespace minting the same
    lesson-<md5(topic)> slugs the read path uses; topic/wiki_title
    resolve directly."""
    if frm not in ("devin", "tony"):
        raise ValueError("delete requires devin/tony actor")
    slug = str(body.get("slug") or "").strip()
    topic = str(body.get("topic") or "").strip()
    wiki_title = str(body.get("wiki_title") or "").strip()
    if topic and not wiki_title:
        wiki_title = pub.lesson_wiki_title(topic)
    if not (slug or wiki_title):
        raise ValueError("delete requires slug, topic, or wiki_title")
    env, api_url = _wiki_env()
    opener, csrf = _wiki_login(api_url, env)
    if not wiki_title:
        for page in _wiki_ns_pages(api_url, opener, WIKI_LESSON_NS):
            row = _lesson_from_wiki_page(page)
            if row and row["slug"] == slug:
                wiki_title = page["title"]
                break
        if not wiki_title:
            raise ValueError(f"lesson not found: {slug}")
    if not slug:
        # mirror delete needs the md5 slug; fetch the page's lesson row
        page = _wiki_page(api_url, opener, wiki_title)
        row = _lesson_from_wiki_page(page or {})
        slug = (row or {}).get("slug", "")
    r = _wiki_api_call(
        api_url, opener,
        {"action": "delete", "title": wiki_title, "token": csrf,
         "format": "json"}, post=True)
    if "error" in r:
        raise UpstreamError(
            "mediawiki delete failed: " +
            str(r["error"].get("info") or r["error"])[:300])
    result = {"message": f"deleted {wiki_title}",
              "wiki_title": wiki_title, "via": frm, "store": "wiki"}
    if slug:
        result["mddb"] = _lesson_mddb_delete(slug)
    return result


# --- source=wiki lesson reads (Education: namespace) -------------------
# Card wiki-member-knowledge-surface-migrate-wp-3a1cf2: after the
# 2026-11-06 migration the Education: namespace holds the same corpus
# the WP lesson CPT does (124 pages + dual-write). op=list/get with
# source=wiki read it through the same door contract — rows mint the
# SAME lesson-<md5(topic)> slug WP would, so audit keys, op=get-by-slug
# and exceptions files stay valid across the cutover.

WIKI_LESSON_NS = "Education"
_LESSON_TEMPLATE_RE = re.compile(
    r"\{\{\s*(?:แม่แบบ|Template)\s*:\s*Education\s*(\|.*?)\}\}", re.S)
_WIKI_CATEGORY_RE = re.compile(
    r"\[\[\s*(?:Category|หมวดหมู่)\s*:[^\]]*\]\]")
_WIKI_PARAM_RE = re.compile(r"\|\s*([A-Za-z_][\w-]*)\s*=\s*([^|]*)")


def _wiki_namespace_id(api_url: str, opener, name: str):
    """Numeric ns id for a canonical/local name ('Education' -> 3004),
    or None when the namespace is not registered."""
    result = _wiki_api_call(
        api_url, opener,
        {"action": "query", "meta": "siteinfo", "siprop": "namespaces",
         "format": "json"})
    want = name.strip().lower()
    for nsid, ns in (result.get("query", {}).get("namespaces")
                     or {}).items():
        names = {str(ns.get("*") or "").strip().lower(),
                 str(ns.get("canonical") or "").strip().lower()}
        if want in names:
            try:
                return int(nsid)
            except (TypeError, ValueError):
                return int(ns.get("id"))
    return None


def _wiki_ns_pages(api_url: str, opener, ns_name: str) -> list:
    """Every page in a namespace -> [{title, wikitext, modified}]."""
    nsid = _wiki_namespace_id(api_url, opener, ns_name)
    if nsid is None:
        raise UpstreamError(
            f"wiki namespace {ns_name!r} is not registered — "
            "LocalSettings step first")
    titles, cont = [], {}
    while True:
        params = {"action": "query", "list": "allpages",
                  "apnamespace": nsid, "aplimit": "max",
                  "format": "json"}
        params.update(cont)
        r = _wiki_api_call(api_url, opener, params)
        titles += [p.get("title") for p in
                   r.get("query", {}).get("allpages", [])
                   if p.get("title")]
        if "continue" not in r:
            break
        cont = r["continue"]
    pages = []
    for i in range(0, len(titles), 50):
        r = _wiki_api_call(
            api_url, opener,
            {"action": "query", "titles": "|".join(titles[i:i + 50]),
             "prop": "revisions", "rvslots": "main",
             "rvprop": "content|timestamp", "format": "json"})
        for p in (r.get("query", {}).get("pages") or {}).values():
            rev = (p.get("revisions") or [{}])[0]
            pages.append({
                "title": p.get("title", ""),
                "wikitext": (rev.get("slots") or {})
                            .get("main", {}).get("*", ""),
                "modified": rev.get("timestamp", "")})
    return pages


def _lesson_from_wiki_page(page: dict):
    """Education: page -> lesson row, or None for non-lesson pages
    (Index/Due/series hubs carry no Education template call). Template
    params become the meta dict; body = wikitext minus the template
    call and category links (values are writer-emitted scalars — a
    value containing '|' or a nested '{{' would misparse, which the
    sink never produces)."""
    m = _LESSON_TEMPLATE_RE.search(page.get("wikitext") or "")
    if not m:
        return None
    params = {pm.group(1): pm.group(2).strip()
              for pm in _WIKI_PARAM_RE.finditer(m.group(1))}
    topic = params.get("topic") or page["title"].split(":", 1)[-1]
    meta = {k: params.get(k, "") for k in
            ("topic", "level", "source", "learned_at", "next_review",
             "status", "updated")}
    meta["topic"] = topic
    if str(params.get("no_th") or "").strip():
        meta["no_th"] = True
    body = _WIKI_CATEGORY_RE.sub(
        "", page["wikitext"][:m.start()] + page["wikitext"][m.end():]
    ).strip()
    slug = "lesson-" + hashlib.md5(
        topic.lower().encode()).hexdigest()[:12]
    return {"slug": slug, "wiki_title": page["title"], "topic": topic,
            "level": params.get("level", ""),
            "next_review": params.get("next_review", ""),
            "status": params.get("status", ""),
            "no_th": bool(meta.get("no_th")),
            "modified": page.get("modified", ""),
            "content": body, "meta": meta}


def _read_lessons_wiki(body: dict, frm: str) -> dict:
    """/lesson {op:list|get, source:"wiki"} — the Education: namespace
    as the lesson store. The namespace is Lockdown-protected, so reads
    ride the bot login (anon gets accessdenied)."""
    env, api_url = _wiki_env()
    opener, _csrf = _wiki_login(api_url, env)

    def url_of(title):
        return _wiki_page_url(env, title)

    lessons, skipped = [], 0
    for page in _wiki_ns_pages(api_url, opener, WIKI_LESSON_NS):
        row = _lesson_from_wiki_page(page)
        # status=index marks generated support pages written through
        # the sink (Education:Index, synthetic series hubs) — they
        # carry the Education template but are not lessons.
        if row is None or row["status"] == "index":
            skipped += 1
            continue
        lessons.append(row)
    if body.get("op") == "list":
        out = [{"slug": l["slug"], "wiki_title": l["wiki_title"],
                "url": url_of(l["wiki_title"]),
                "topic": l["topic"], "level": l["level"],
                "modified": l["modified"],
                "next_review": l["next_review"],
                "status": l["status"], "no_th": l["no_th"]}
               for l in lessons]
        out.sort(key=lambda r: r["slug"])
        return {"lessons": out, "count": len(out),
                "skipped_non_lesson": skipped,
                "source": "wiki", "via": frm,
                "message": f"listed {len(out)} wiki lessons"}
    wiki_title = str(body.get("wiki_title") or "").strip()
    slug = str(body.get("slug") or "").strip()
    topic = str(body.get("topic") or "").strip()
    if not (wiki_title or slug or topic):
        raise ValueError("op=get requires slug, topic, or wiki_title")
    if topic and not wiki_title:
        wiki_title = pub.lesson_wiki_title(topic)
    row = next((l for l in lessons
                if (wiki_title and l["wiki_title"] == wiki_title)
                or (slug and l["slug"] == slug)
                or (topic and l["topic"] == topic)), None)
    if row is None:
        raise ValueError(
            f"lesson not found: {wiki_title or slug or topic}")
    return {"slug": row["slug"], "wiki_title": row["wiki_title"],
            "url": url_of(row["wiki_title"]),
            "title": row["topic"], "content": row["content"],
            "meta": row["meta"], "modified": row["modified"],
            "source": "wiki", "via": frm,
            "message": f"get {row['wiki_title']}"}


def _wiki_page_url(env: dict, title: str) -> str:
    """Human URL for a wiki page. wiki.h3 has no $wgArticlePath short
    URLs — /wiki/<t> 404s live (verified 2026-11-07); the canonical form
    is /index.php?title=<t>."""
    host = env.get("WIKI_HOST", "").rstrip("/")
    if host.endswith("/v0"):
        host = host[:-3]
    return (f"{host}/index.php?title="
            f"{urllib.parse.quote(title.replace(' ', '_'))}"
            if host else "")


def _lesson_write_env() -> tuple:
    """-> (mode, env) — WIKI_EDUCATION_WRITE in the wiki env file:
    off/absent = WP only; dual = WP + Education:; wiki = wiki-primary
    (Education: is the only store; card
    wiki-education-write-cutover-make-wiki-t-7f2e7d)."""
    try:
        env = _load_env_file(WIKI_ENV_FILE)
    except OSError:
        return "off", {}
    return (str(env.get("WIKI_EDUCATION_WRITE")
                or "").strip().lower(), env)


def _wiki_lesson_sink(env: dict):
    """-> (sink, api_url); sink is None when creds are incomplete.
    Honors the same template/prefix overrides _pub_sinks uses."""
    host = env.get("WIKI_HOST", "").rstrip("/")
    if host.endswith("/v0"):
        host = host[:-3]
    api = (env.get("WIKI_API_URL") or f"{host}/api.php").rstrip("/")
    if not (host and env.get("WIKI_USER") and env.get("WIKI_PASSWORD")):
        return None, api
    return pub.WikiLessonSink(
        api, env["WIKI_USER"], env["WIKI_PASSWORD"],
        template=env.get("WIKI_EDUCATION_TEMPLATE",
                          "แม่แบบ:Education"),
        namespace_prefix=env.get("WIKI_EDUCATION_PREFIX",
                                 "Education:")), api


def _lesson_event(topic: str, level: str, source: str, content: str,
                  meta: dict) -> dict:
    """The canonical lesson event both wiki write paths share."""
    return pub.validate_event({
        "kind": "lesson", "title": topic, "body": content,
        "source": "lesson-door", "visibility": "private",
        "meta": {
            "wiki_title": pub.lesson_wiki_title(topic),
            "topic": topic, "level": level, "lesson_source": source,
            "learned_at": meta.get("learned_at", ""),
            "next_review": meta.get("next_review", ""),
            "status": meta.get("status", "open"),
            "updated": meta.get("updated", ""),
            "no_th": bool(meta.get("no_th")),
            "format": "html"}})


def lesson_mddb_doc(slug: str, topic: str, level: str, source: str,
                    body_text: str, meta: dict, wiki_title: str = "",
                    store: str = "wiki", post_id=None,
                    url: str = "") -> dict:
    """chaba-lessons add payload — the ONE doc shape both the capture-time
    dual-write and the backfill use. body_text is readable text (lesson
    HTML pre-flattened via pub.html_to_wikitext, or wiki-source wikitext
    verbatim). Meta follows the ada-cms-pages list-values contract."""
    m = {"slug": [slug], "kind": ["lesson"], "bank": ["education"],
         "title": [f"Education — {topic}"[:160]], "topic": [topic],
         "level": [level], "lesson_source": [source],
         "learned_at": [str(meta.get("learned_at", ""))],
         "next_review": [str(meta.get("next_review", ""))],
         "status": [str(meta.get("status", "open"))],
         "updated": [str(meta.get("updated", ""))],
         "store": [store], "format": ["wikitext"],
         "written_by": ["board-api /lesson"], "lang": ["en"]}
    if meta.get("no_th"):
        m["no_th"] = ["1"]
    if wiki_title:
        m["wiki_title"] = [wiki_title]
    if post_id:
        m["post_id"] = [str(post_id)]
    if url:
        m["url"] = [url]
    head = (f"# {topic}\n\n*{level} lesson · learned "
            f"{meta.get('learned_at', '')} · review "
            f"{meta.get('next_review', '')}*\n\n")
    return {"collection": MDDB_LESSONS, "key": slug, "lang": "en",
            "contentMd": head + (body_text or "").strip(), "meta": m}


def _lesson_mddb_write(slug: str, topic: str, level: str, source: str,
                       content: str, meta: dict, wiki_title: str = "",
                       post_id=None, url: str = "", store: str = "wiki"):
    """chaba-lessons mirror — every /lesson write lands here as well as
    its primary store, so agents retrieve filed lessons through MDDB
    search (card assessments-to-education-split-ssot-keep-113ca4). The
    mirror is a retrieval index, NOT the store, so a failure degrades to
    a receipt instead of a 502 (a mirror miss is visible, not fatal)."""
    try:
        doc = lesson_mddb_doc(slug, topic, level, source,
                              pub.html_to_wikitext(content), meta,
                              wiki_title=wiki_title, store=store,
                              post_id=post_id, url=url)
        _mddb_post("add", doc, timeout=30)
        return {"status": "delivered", "collection": MDDB_LESSONS,
                "key": slug}
    except Exception as e:
        return {"status": "failed", "reason": str(e)[:300]}


def _lesson_mddb_delete(slug: str):
    """Mirror-side delete for op=delete — best effort, receipt only."""
    try:
        _mddb_post("delete", {"collection": MDDB_LESSONS, "key": slug,
                              "lang": "en"}, timeout=30)
        return {"status": "deleted", "collection": MDDB_LESSONS,
                "key": slug}
    except Exception as e:
        return {"status": "failed", "reason": str(e)[:300]}


def _lesson_wiki_write(topic: str, level: str, source: str,
                       content: str, meta: dict):
    """Education: dual-write behind WIKI_EDUCATION_WRITE=dual in the wiki
    env file (card wiki-member-knowledge-surface-migrate-wp-3a1cf2).
    A wiki failure never fails the WP write: the WP lesson ledger is
    still canonical in dual mode and the miss reports on the response."""
    mode, env = _lesson_write_env()
    if mode != "dual":
        return None
    sink, _api = _wiki_lesson_sink(env)
    if sink is None:
        return {"status": "skipped", "reason": "wiki creds incomplete"}
    try:
        r = sink.publish(_lesson_event(topic, level, source,
                                       content, meta))
        return {"status": "delivered", **r}
    except Exception as e:
        return {"status": "failed", "reason": str(e)[:300]}


def _wiki_page(api_url: str, opener, title: str):
    """One page -> {title, wikitext, modified}, or None when it doesn't
    exist."""
    r = _wiki_api_call(
        api_url, opener,
        {"action": "query", "titles": title, "prop": "revisions",
         "rvslots": "main", "rvprop": "content|timestamp",
         "format": "json"})
    for p in (r.get("query", {}).get("pages") or {}).values():
        if "missing" in p:
            return None
        rev = (p.get("revisions") or [{}])[0]
        return {"title": p.get("title") or title,
                "wikitext": (rev.get("slots") or {})
                            .get("main", {}).get("*", ""),
                "modified": rev.get("timestamp", "")}
    return None


def _lesson_wiki_primary(body: dict, frm: str, slug: str, topic: str,
                         level: str, source: str, content: str,
                         meta: dict, th_ok: bool, thai_free: bool,
                         env: dict) -> dict:
    """WIKI_EDUCATION_WRITE=wiki — Education: is the ONLY store; the WP
    CPT is never touched. Same semantics as the WP path: upsert by
    wiki_title (the slug-equivalent — a re-asked topic resolves to the
    same page via lesson_wiki_title), learned_at/next_review/status
    preserved from the existing page on re-file, no_th carried when a
    Thai-free re-file meets a prior exemption, explicit next_review
    wins. There is no second store to hide a failure behind, so a wiki
    error raises (502) instead of degrading to a receipt field."""
    sink, api = _wiki_lesson_sink(env)
    if sink is None:
        raise UpstreamError(
            "WIKI_EDUCATION_WRITE=wiki but wiki credentials are "
            "incomplete — no fallback store for the lesson")
    wiki_title = pub.lesson_wiki_title(topic)
    opener, _csrf = _wiki_login(api, env)
    page = _wiki_page(api, opener, wiki_title)
    action = "created"
    if page is not None:
        action = "updated"
        old_meta = ((_lesson_from_wiki_page(page) or {}).get("meta")
                    or {})
        # preserve first-learn provenance + review state on re-file
        # (identical rule to the WP branch; explicit next_review is the
        # spaced-review advance override — KNB-0830)
        override_review = str(body.get("next_review") or "").strip()
        for k in ("learned_at", "next_review", "status"):
            if k == "next_review" and override_review:
                meta[k] = override_review
            elif old_meta.get(k):
                meta[k] = old_meta[k]
        if thai_free and old_meta.get("no_th"):
            meta["no_th"] = True
    r = sink.publish(_lesson_event(topic, level, source, content, meta))
    return {"message": f"{action} {slug} ({wiki_title})",
            "slug": slug, "wiki_title": wiki_title,
            "url": _wiki_page_url(env, wiki_title),
            "wiki": {"status": "delivered", **r},
            "mddb": _lesson_mddb_write(
                slug, topic, level, source, content, meta,
                wiki_title=wiki_title,
                url=_wiki_page_url(env, wiki_title)),
            "action": action, "th": th_ok, "store": "wiki"}


def do_lesson(body: dict, frm: str) -> dict:
    """/lesson — the remote write half of the lesson-capture duty: upsert
    the WP lesson CPT by topic slug (re-asked topics update in place, WP
    upserts by slug), append the Thai section unless no_th, and preserve
    first-learn provenance + review state on re-file. Identical semantics
    to the old lesson-add.py — which is now a thin client of this door.

    Write store follows WIKI_EDUCATION_WRITE in the wiki env file:
    off = WP only; dual = WP + Education: page (same merged meta);
    wiki = wiki-primary — the Education: page is the ONLY store, the
    WP CPT is not touched and the result carries wiki_title instead of
    post_id (rollback = flag back to dual).

    op:"touch" — bump the WP modified timestamp of every lesson (or the
    slugs given) without touching content, so admin sort-by-last-modified
    reflects re-files (Tony 2026-10-24; WP only auto-bumps modified when
    content bytes change)."""
    if body.get("op") in ("touch", "list", "get", "delete"):
        if body.get("op") == "touch":
            return _touch_lessons(body, frm)
        if body.get("op") == "delete":
            mode, _wenv = _lesson_write_env()
            if mode == "wiki":
                return _delete_lesson_wiki(body, frm)
            return _delete_lesson(body, frm)
        return _read_lessons(body, frm)
    topic = str(body.get("topic") or "").strip()
    if not topic:
        raise ValueError("topic required")
    level = str(body.get("level") or "intro").strip()
    if level not in LESSON_LEVELS:
        raise ValueError(f"level must be one of {sorted(LESSON_LEVELS)}")
    source = str(body.get("source") or "chat").strip()
    if source not in LESSON_SOURCES:
        raise ValueError(f"source must be one of {sorted(LESSON_SOURCES)}")
    content = str(body.get("content") or "").strip()
    if not content:
        raise ValueError("content required")
    slug = "lesson-" + hashlib.md5(
        topic.lower().encode()).hexdigest()[:12]
    th_ok = False
    if not body.get("no_th"):
        th = _gemini_thai(content)
        if th:
            content += "\n<hr>\n<h3>ไทย</h3>\n" + th
            th_ok = True
    today = str(date.today())
    meta = {"topic": topic[:160], "level": level, "source": source,
            "learned_at": today,
            "next_review": str(body.get("next_review") or "").strip()
            or str(date.today() + timedelta(days=7)),
            "status": str(body.get("status") or "open").strip()[:40],
            "updated": today}
    # Persist intentional no-Thai (card
    # education-maintenance-consolidated-report; the lesson-polish job's
    # documented gap): meta.no_th marks a Thai-free lesson filed on
    # purpose, so audits tell '--no-th intent' from 'missing
    # translation'. Only when the write both skips Thai AND lands
    # Thai-free — polish passes set no_th to preserve an existing Thai
    # section and must not mark the lesson exempt.
    thai_free = not re.search(r"[\u0e00-\u0e7f]", content)
    if body.get("no_th") and thai_free:
        meta["no_th"] = True
    write_mode, wenv = _lesson_write_env()
    if write_mode == "wiki":
        # cutover mode (card wiki-education-write-cutover-make-wiki-t-
        # 7f2e7d): Education: is the only store — no WP post at all.
        # Rollback = flag back to dual.
        return _lesson_wiki_primary(body, frm, slug, topic, level,
                                    source, content, meta, th_ok,
                                    thai_free, wenv)
    payload = {"title": f"Education — {topic}"[:160], "slug": slug,
               "status": "private", "content": content, "meta": meta}
    hits = wp_api(f"/wp/v2/lesson&slug={slug}&status=private")
    if isinstance(hits, list) and hits:
        pid = hits[0]["id"]
        old_meta = hits[0].get("meta", {})
        # preserve first-learn provenance + review state on re-file
        # (unless an explicit next_review override is given — advance the
        # spaced-review date after a review pass; KNB-0830)
        override_review = str(body.get("next_review") or "").strip()
        for k in ("learned_at", "next_review", "status"):
            if k == "next_review" and override_review:
                meta[k] = override_review
            elif old_meta.get(k):
                meta[k] = old_meta[k]
        # a re-file that lands Thai-free again keeps a prior exemption
        # even when this write didn't ask for no_th (e.g. a Thai
        # backfill attempt whose translation failed upstream)
        if thai_free and old_meta.get("no_th"):
            meta["no_th"] = True
        # explicit modified bump — WP only auto-updates it when content
        # bytes change; re-filed lessons with identical content kept the
        # ORIGINAL date, so admin sort-by-last-modified was useless
        # (Tony 2026-10-24).
        now_iso = datetime.now(timezone.utc).replace(
            microsecond=0).isoformat()
        payload["modified"] = now_iso
        r = wp_api(f"/wp/v2/lesson/{pid}", payload)
        action = "updated"
    else:
        r = wp_api("/wp/v2/lesson", payload)
        action = "created"
    result = {"message": f"{action} {slug} (post {r.get('id')})",
              "slug": slug, "post_id": r.get("id"), "action": action,
              "th": th_ok}
    result["mddb"] = _lesson_mddb_write(
        slug, topic, level, source, content, meta,
        wiki_title=pub.lesson_wiki_title(topic),
        post_id=r.get("id"), store="wp")
    wiki = _lesson_wiki_write(topic, level, source, content, meta)
    if wiki is not None:
        result["wiki"] = wiki
    return result


def do_lesson_topics(body: dict = None, frm: str = "?") -> dict:
    """/lesson {op:"topics"} — READ op on the write door: the lesson
    store's existing topic titles + slugs so callers (lesson-miner
    classify, bench agents) can reuse names instead of forking slugs —
    the turn-3 store-awareness fix. WP keeps the creds here; callers
    hold none. source=wiki lists the Education: namespace; unset
    follows the write flag (post-cutover the store-awareness list must
    name the topics the write will upsert into)."""
    body = body or {}
    source = str(body.get("source") or "").strip().lower()
    if not source:
        mode, _wenv = _lesson_write_env()
        source = "wiki" if mode == "wiki" else "wp"
    if source == "wiki":
        r = _read_lessons_wiki({"op": "list"}, frm)
        out = [{"topic": l["topic"], "slug": l["slug"],
                "wiki_title": l["wiki_title"]}
               for l in r.get("lessons") or []]
        return {"message": f"{len(out)} lesson topics", "topics": out,
                "source": "wiki"}
    if source != "wp":
        raise ValueError("source must be wp or wiki")
    out = []
    page = 1
    while page <= 5:                    # hard cap 500 lessons
        hits = wp_api(f"/wp/v2/lesson&status=private&per_page=100"
                      f"&page={page}&_fields=slug,title,meta")
        if not isinstance(hits, list) or not hits:
            break
        for h in hits:
            topic = ((h.get("meta") or {}).get("topic")
                     or (h.get("title") or {}).get("rendered", "")
                     .replace("Education — ", "").strip())
            out.append({"topic": topic, "slug": h.get("slug", "")})
        if len(hits) < 100:
            break
        page += 1
    return {"message": f"{len(out)} lesson topics", "topics": out,
            "source": "wp"}


JOB_STATUSES = {"queued", "claimed", "running", "done", "failed",
                "stalled", "cancelled"}
JOB_META_KEYS = ("kind", "status", "host", "pack", "runner",
                 "result_ref", "error", "updated", "event_id")
JOB_COMMS_CAP = 200
JOB_FROM_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,40}$")


def job_actor(body: dict, ident: str) -> str:
    """/job writers are daemons (queue-mgr, pack runners) — allow ACTORS
    plus host/daemon names, defaulting to the verified caller identity."""
    frm = str(body.get("from") or "").strip() or ident
    if frm in ACTORS or JOB_FROM_RE.match(frm):
        return frm
    raise ValueError("from must be an actor or a host/daemon name")


def _job_by_slug(slug: str):
    hits = wp_api(f"/wp/v2/nest_job&slug={slug}"
                  "&status=private,archived&per_page=1")
    return hits[0] if isinstance(hits, list) and hits else None


def do_job(body: dict, frm: str) -> dict:
    """/job — nest_job CPT upsert: the Drive-queue mirror write for
    queue-mgr and pack runners. One post per job slug; status/meta merge;
    `comms` (or `note`) appends {at,from,text} to a JSON log in
    meta.comms; `parent` accepts a post id or a sibling job slug for
    job trees."""
    slug = str(body.get("slug") or "").strip()
    if not re.fullmatch(r"[a-z0-9-]{1,80}", slug):
        raise ValueError("slug must match [a-z0-9-]{1,80}")
    status = str(body.get("status") or "").strip()
    if status and status not in JOB_STATUSES:
        raise ValueError(f"status must be one of {sorted(JOB_STATUSES)}")
    parent = body.get("parent")
    pid = 0
    if parent not in (None, "", 0):
        if isinstance(parent, int) or str(parent).isdigit():
            pid = int(parent)
        else:
            pslug = str(parent).strip()
            if not re.fullmatch(r"[a-z0-9-]{1,80}", pslug):
                raise ValueError("parent must be a post id or job slug")
            hit = _job_by_slug(pslug)
            if not hit:
                raise ValueError(f"no parent job {pslug}")
            pid = hit["id"]

    existing = _job_by_slug(slug)
    meta = dict(existing.get("meta") or {}) if existing else {}
    note_text = str(body.get("comms") or body.get("note") or "").strip()
    if note_text:
        try:
            log = json.loads(str(meta.get("comms") or "[]"))
            if not isinstance(log, list):
                log = []
        except Exception:
            log = []
        log.append({"at": now(), "from": frm, "text": note_text[:500]})
        meta["comms"] = json.dumps(log[-JOB_COMMS_CAP:], ensure_ascii=False)
    for k in JOB_META_KEYS:
        v = body.get(k)
        if v is not None and str(v).strip() != "":
            meta[k] = str(v)[:300]
    extra = body.get("meta")
    if isinstance(extra, dict):
        for k, v in extra.items():
            k = str(k)
            if k in JOB_META_KEYS and str(v).strip():
                meta[k] = str(v)[:300]
    meta["updated"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    title = str(body.get("title") or "").strip()
    payload = {"slug": slug, "status": "private", "meta": meta}
    if title or not existing:
        payload["title"] = title or f"nest job {slug}"
    if pid:
        payload["parent"] = pid
    if existing:
        r = wp_api(f"/wp/v2/nest_job/{existing['id']}", payload)
        action = "updated"
    else:
        r = wp_api("/wp/v2/nest_job", payload)
        action = "created"
    return {"message": f"{action} nest_job {slug} (post {r.get('id')})",
            "slug": slug, "post_id": r.get("id"), "action": action}


def _dashed_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] \
        .strip("-") or "item"


def do_inbox(body: dict, frm: str) -> dict:
    """/inbox — a focus-inbox entry as an endpoint: agents park ideas
    without a repo checkout. Same atomic write + queued commit as
    cards; runs under the card flock."""
    text = str(body.get("text") or "").strip()
    if not text:
        raise ValueError("text required")
    label = str(body.get("label") or body.get("title") or "").strip() \
        or " ".join(text.split())[:80]
    pri = str(body.get("priority") or "medium").strip()
    if pri not in PRIORITIES:
        raise ValueError(f"priority must be one of {sorted(PRIORITIES)}")
    tags = body.get("tags")
    if tags is not None and not isinstance(tags, list):
        raise ValueError("tags must be a list")
    par = body.get("safe_to_parallel")
    if isinstance(par, dict):
        safe_par = {"value": bool(par.get("value")),
                    "reason": str(par.get("reason") or "")[:200]}
    else:
        safe_par = {"value": bool(par),
                    "reason": str(body.get("parallel_reason") or "")[:200]}
    subtasks = []
    for s in (body.get("subtasks") or [])[:20]:
        if isinstance(s, dict):
            subtasks.append({"label": str(s.get("label") or "")[:200],
                             "status": str(s.get("status")
                                           or "not_started")[:20]})
        else:
            subtasks.append({"label": str(s)[:200],
                             "status": "not_started"})
    ts = datetime.now(timezone(timedelta(hours=7)))
    entry = {
        "title": label[:120],
        "subtitle": str(body.get("subtitle")
                        or "Focus inbox item")[:160],
        "icon": str(body.get("icon") or "inbox")[:40],
        "focus": {
            "label": label[:120],
            "text": text[:4000],
            "priority": pri,
            "status": "draft",
            "tags": [str(t)[:40] for t in tags or []][:20],
            "missing_info": [str(m)[:200] for m in
                             (body.get("missing_info") or [])][:10],
            "safe_to_parallel": safe_par,
            "subtasks": subtasks,
        },
        "ownership": {
            "owner": str(body.get("owner") or "tony")[:40],
            "session": "",
            "locked": False,
            "lock_reason": "",
        },
        "source": {
            "session": str(body.get("session") or "")[:80],
            "date": ts.date().isoformat(),
        },
    }
    slug = _dashed_slug(label)
    p = INBOX_DIR / f"{ts.strftime('%Y-%m-%d-%H%M%S')}-{slug}.yml"
    if p.exists():   # same-second collision — hash disambiguates
        h = hashlib.sha1(text.encode()).hexdigest()[:6]
        p = INBOX_DIR / f"{ts.strftime('%Y-%m-%d-%H%M%S')}-{slug}-{h}.yml"
    out = yaml.safe_dump(entry, allow_unicode=True, sort_keys=False,
                         width=110)
    card_io.atomic_write_text(p, out)
    _queue_commit(p, _pending_label or f"inbox {slug}")
    return {"message": f"inbox item {p.name} filed", "file": p.name}


_crn_mod = None


def _crn():
    """scripts/ada/cms-report-note.py — lazy import so /report shares the
    session-log/managed-block/writer-contract logic instead of forking it
    (same pattern as _lab_decision)."""
    global _crn_mod
    if _crn_mod is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cms_report_note", REPO / "scripts/ada/cms-report-note.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _crn_mod = mod
    return _crn_mod


def _meta_first(meta: dict, name: str) -> str:
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v) if v else ""


def report_search(query: str, limit: int = 10) -> list:
    docs = _mddb_post("search", {"collection": MDDB_PAGES,
                                 "query": query, "limit": limit})
    if not isinstance(docs, list):
        docs = docs.get("result", docs.get("docs", []))
    return [{"slug": d.get("key"),
             "title": _meta_first(d.get("meta"), "title"),
             "updated": _meta_first(d.get("meta"), "updated")}
            for d in docs[:limit]]


def report_note_append(slug: str, text: str, lang: str) -> dict:
    try:
        return _crn().note(slug, text, lang)
    except (urllib.error.URLError, OSError) as e:
        raise UpstreamError(f"report note {slug} -> {e}")
    except SystemExit as e:
        raise ValueError(str(e))


def report_create_doc(slug: str, title: str, content_md: str,
                      meta_extra: dict) -> dict:
    """Create an ada-cms-pages doc honoring the writer contract — reuses
    cms-report-note's merged_meta (empty doc = contract defaults) so the
    create branch stays format-compatible with note-appended pages."""
    now_dt = datetime.now(timezone.utc)
    meta = _crn().merged_meta({}, slug, now_dt, now_dt.date().isoformat())
    if meta_extra:
        for k, v in meta_extra.items():
            meta[str(k)] = v if isinstance(v, list) else [str(v)]
    _mddb_post("add", {"collection": MDDB_PAGES, "key": slug, "lang": "en",
                       "contentMd": content_md, "meta": meta}, timeout=60)
    try:
        from lib.cms_index import regen_reports_index
        regen_reports_index(MDDB, written_by="board-api /report")
    except Exception as e:
        sys.stderr.write(f"board-api report index regen failed: {e}\n")
    return {"slug": slug}


def _read_wp_reports(body: dict, frm: str) -> dict:
    """mode=wp-list | wp-get — read side for the member-facing WP report
    CPT (usage-ledger class), needed by the wiki Reports: migration
    (card wiki-member-knowledge-surface-migrate-wp-3a1cf2). Distinct
    store from the MDDB dossiers the other modes serve — hence the
    wp- prefix. Runners hold no WP creds; the door reads for them."""
    mode = str(body.get("mode") or "").strip()
    if mode == "wp-list":
        hits = wp_api("/wp/v2/report&status=private,publish&per_page=100"
                      "&_fields=slug,title,modified,meta,status")
        out = []
        if isinstance(hits, list):
            for h in hits:
                m = h.get("meta") or {}
                out.append({"slug": h.get("slug"),
                            "title": (h.get("title") or {})
                            .get("rendered", ""),
                            "wp_status": h.get("status"),
                            "report_type": m.get("report_type", ""),
                            "period": m.get("period", ""),
                            "source_key": m.get("source_key", ""),
                            "modified": h.get("modified")})
        return {"reports": out, "count": len(out), "via": frm,
                "message": f"listed {len(out)} WP report CPT posts"}
    slug = str(body.get("slug") or "").strip()
    if not slug:
        raise ValueError("wp-get requires slug")
    hits = wp_api(f"/wp/v2/report&slug={slug}&status=private,publish")
    if not (isinstance(hits, list) and hits):
        raise ValueError(f"report not found: {slug}")
    h = hits[0]
    return {"slug": h.get("slug"),
            "title": (h.get("title") or {}).get("rendered", ""),
            "content": (h.get("content") or {}).get("rendered", ""),
            "meta": h.get("meta") or {}, "modified": h.get("modified"),
            "wp_status": h.get("status"), "via": frm,
            "message": f"get {slug}"}


def do_report(body: dict, frm: str) -> dict:
    """/report — the report-integration duty as an endpoint. Callers
    search first (query → candidate slugs), then either note-append to an
    existing page (integrate) or create a new one (create). `mode` may be
    given explicitly; otherwise inferred from the fields present.
    mode=wp-list|wp-get reads the member-facing WP report CPT — a
    different store from the MDDB dossiers (see _read_wp_reports)."""
    mode = str(body.get("mode") or body.get("do") or "").strip()
    slug = str(body.get("slug") or "").strip()
    note_text = str(body.get("note") or "").strip()
    query = str(body.get("query") or "").strip()
    title = str(body.get("title") or "").strip()
    content_md = str(body.get("content_md") or body.get("content")
                     or "").strip()
    if mode in ("wp-list", "wp-get"):
        return _read_wp_reports(body, frm)
    if mode and mode not in ("search", "note", "create"):
        raise ValueError("mode must be search|note|create")
    if not mode:
        if slug and note_text:
            mode = "note"
        elif (slug or title) and content_md:
            mode = "create"
        elif query or title:
            mode = "search"
        else:
            raise ValueError(
                "report needs query | slug+note | title+content_md")
    if mode == "search":
        q = query or title
        if not q:
            raise ValueError("search needs query")
        cands = report_search(q)
        return {"message": f"{len(cands)} candidate page(s) for {q!r}",
                "candidates": cands}
    if mode == "note":
        if not re.fullmatch(REPORT_SLUG_RE, slug):
            raise ValueError("slug must match ^[a-z0-9-]{1,80}")
        if not note_text:
            raise ValueError("note required")
        lang = str(body.get("lang") or "en").strip()[:10]
        r = report_note_append(slug, note_text, lang)
        return {"message": f"noted {r['slug']}: {r['line']}",
                "slug": r["slug"], "updated": r.get("updated")}
    # create
    if not content_md:
        raise ValueError("content_md required")
    if slug and not re.fullmatch(REPORT_SLUG_RE, slug):
        raise ValueError("slug must match ^[a-z0-9-]{1,80}")
    if not slug:
        if not title:
            raise ValueError("create needs slug or title")
        slug = _dashed_slug(title)[:80]
    title = title or slug
    meta_extra = body.get("meta") if isinstance(body.get("meta"), dict) \
        else {}
    r = report_create_doc(slug, title, content_md[:200000], meta_extra)
    return {"message": f"created report page {r['slug']}",
            "slug": r["slug"]}


# --- /publish — provider-neutral publication door ---------------------------
# One canonical PublicationEvent fans out to sink adapters (see
# scripts/board/publication.py for schema/policy/outbox). Each adapter
# below translates the event into the SAME writer call the compat
# endpoint uses — WP (nest_job/lesson/news), mddb report dossier,
# telegram relay, card comms audit, json ledger are peer adapters.


def _pub_job_send(ev: dict, frm: str) -> dict:
    """progress|milestone|alert -> nest_job live execution state."""
    slug = ev["job"] or ev["project"] or ev["card"]
    if not slug:
        raise pub.Skip("job sink needs a job|project|card ref")
    meta = ev.get("meta") or {}
    status = str(meta.get("job_status") or
                 {"progress": "running", "milestone": "done",
                  "alert": "stalled"}.get(ev["kind"], ""))
    body = {"slug": slug, "title": ev["title"],
            "comms": ev["body"] or ev["title"],
            "kind": str(meta.get("job_kind") or ev["kind"]),
            "event_id": ev["event_id"]}
    if status:
        body["status"] = status
    if ev["evidence"]:
        body["result_ref"] = ev["evidence"][0]
    if ev["kind"] == "alert":
        body["error"] = ev["title"][:300]
    if ev["parent"]:
        body["parent"] = ev["parent"]
    for k in ("host", "pack", "runner"):
        if meta.get(k):
            body[k] = str(meta[k])
    r = do_job(body, frm)
    return {"ref": f"nest_job:{r['slug']}", "post_id": r.get("post_id"),
            "action": r["action"]}


def _pub_lesson_send(ev: dict, frm: str) -> dict:
    """lesson -> WP lesson CPT (Education — reusable knowledge)."""
    meta = ev.get("meta") or {}
    body = {"topic": str(meta.get("topic") or ev["title"]),
            "content": ev["body"] or f"<p>{ev['title']}</p>"}
    for k in ("level", "next_review", "status"):
        if meta.get(k):
            body[k] = str(meta[k])
    if meta.get("lesson_source"):
        body["source"] = str(meta["lesson_source"])
    if meta.get("no_th"):
        body["no_th"] = True
    r = do_lesson(body, frm)
    return {"ref": f"lesson:{r['slug']}", "post_id": r.get("post_id"),
            "wiki_title": r.get("wiki_title"), "action": r["action"],
            "th": r.get("th")}


def _pub_report_send(ev: dict, frm: str) -> dict:
    """report|milestone -> project dossier (ada-cms-pages note)."""
    slug = ev["project"] or str(
        (ev.get("meta") or {}).get("report_slug") or "")
    if not slug:
        raise pub.Skip("report sink needs a project ref (dossier slug)")
    line = ev["title"]
    if ev["body"]:
        line += f" — {ev['body'][:160]}"
    line += f" [{ev['event_id']}]"
    r = do_report({"slug": slug, "note": line}, frm)
    return {"ref": f"report:{r['slug']}"}


def _pub_news_send(ev: dict, frm: str) -> dict:
    """news -> WP news CPT. Evidence rides inside content (news meta
    keys aren't REST-registered); visibility maps to the post status —
    members stays the private member surface, public flips to publish
    (validation already required confidence=verified for that)."""
    slug = "pub-" + ev["event_id"][4:]
    links = "".join(f'<li><a href="{e}">{e}</a></li>'
                    for e in ev["evidence"])
    content = (
        ev["body"] + "\n<h4>Evidence</h4><ul>" + links + "</ul>"
        f"<p><small>confidence: {ev['confidence']} · "
        f"source: {ev['source']} · event: {ev['event_id']}"
        "</small></p>")
    status = "publish" if ev["visibility"] == "public" else "private"
    hits = wp_api(f"/wp/v2/news&slug={slug}&status=private,publish")
    payload = {"title": ev["title"], "slug": slug, "status": status,
               "content": content}
    if isinstance(hits, list) and hits:
        r = wp_api(f"/wp/v2/news/{hits[0]['id']}", payload)
        action = "updated"
    else:
        r = wp_api("/wp/v2/news", payload)
        action = "created"
    return {"ref": f"news:{slug}", "post_id": r.get("id"),
            "action": action, "wp_status": status}


def _pub_board_send(ev: dict, frm: str) -> dict:
    """any kind -> card comms (operational audit trail)."""
    cid = ev["card"]
    if not cid:
        raise pub.Skip("board sink needs a card ref")
    global _pending_label
    _pending_label = f"publish {ev['event_id']}"
    # lock order WP_LOCK -> LOCK; no path takes LOCK then WP_LOCK, so
    # this nested take cannot deadlock.
    got = acquire_lock(LOCK, LOCK_WAIT_S)
    if got is None:
        raise pub.DeliveryError("board write lock saturated")
    lf, _w = got
    try:
        try:
            p = card_path(cid)
        except ValueError as e:
            raise pub.Skip(str(e))
        card = load(p)
        text = f"pub {ev['kind']}: {ev['title']}"
        if ev["body"]:
            text += f" — {ev['body'][:160]}"
        text += f" [{ev['event_id']}]"
        comms_add(card, frm, text)
        card["updated"] = now()
        save(p, card)
    finally:
        lf.close()
    return {"ref": f"card:{cid}"}


def _pub_sinks(frm: str) -> dict:
    """The adapter registry — WP is only one adapter among peers; the
    'json' ledger proves a second sink receives the same event."""
    sinks = {
        "job": pub.FuncSink(
            "job", surface="members",
            kinds=("progress", "milestone", "alert"),
            send=lambda ev: _pub_job_send(ev, frm)),
        "lesson": pub.FuncSink(
            "lesson", surface="members", kinds=("lesson",),
            send=lambda ev: _pub_lesson_send(ev, frm)),
        "report": pub.FuncSink(
            "report", surface="members",
            kinds=("report", "milestone"),
            send=lambda ev: _pub_report_send(ev, frm)),
        "news": pub.FuncSink(
            "news", surface="members", kinds=("news",),
            evidence_required=True,
            send=lambda ev: _pub_news_send(ev, frm)),
        "board": pub.FuncSink(
            "board", surface="private", kinds=pub.KINDS,
            send=lambda ev: _pub_board_send(ev, frm)),
        "telegram": pub.TelegramSink(PUB_TG_URL),
        "json": pub.JsonSink(PUB_STATE_DIR / "published.jsonl"),
    }
    try:
        wiki_env = _load_env_file(WIKI_ENV_FILE)
        wiki_host = wiki_env.get("WIKI_HOST", "").rstrip("/")
        if wiki_host.endswith("/v0"):
            wiki_host = wiki_host[:-3]
        wiki_api = (wiki_env.get("WIKI_API_URL") or
                    f"{wiki_host}/api.php").rstrip("/")
        if wiki_host and wiki_env.get("WIKI_USER") and \
                wiki_env.get("WIKI_PASSWORD"):
            sinks["wiki"] = pub.MediaWikiSink(
                wiki_api, wiki_env["WIKI_USER"], wiki_env["WIKI_PASSWORD"],
                template=wiki_env.get("WIKI_NEWS_TEMPLATE",
                                       "แม่แบบ:NewsReport"))
            sinks["wiki-private"] = pub.MediaWikiSink(
                wiki_api, wiki_env["WIKI_USER"], wiki_env["WIKI_PASSWORD"],
                template=wiki_env.get("WIKI_NEWS_TEMPLATE",
                                       "แม่แบบ:NewsReport"),
                name="wiki-private", surface="private",
                namespace_prefix="PrivateNews:")
            sinks["wiki-education"] = pub.WikiLessonSink(
                wiki_api, wiki_env["WIKI_USER"], wiki_env["WIKI_PASSWORD"],
                template=wiki_env.get("WIKI_EDUCATION_TEMPLATE",
                                       "แม่แบบ:Education"),
                namespace_prefix=wiki_env.get("WIKI_EDUCATION_PREFIX",
                                              "Education:"))
            sinks["wiki-reports"] = pub.WikiReportSink(
                wiki_api, wiki_env["WIKI_USER"], wiki_env["WIKI_PASSWORD"],
                template=wiki_env.get("WIKI_REPORT_TEMPLATE",
                                       "แม่แบบ:Report"),
                namespace_prefix=wiki_env.get("WIKI_REPORT_PREFIX",
                                              "Reports:"))
    except (OSError, KeyError):
        # Optional sink: the news event still follows the configured routes
        # and the missing wiki credentials remain a service-host concern.
        pass
    return sinks


def do_publish(body: dict, frm: str) -> dict:
    """POST /publish — canonical event in, per-sink receipts out.
    {op:"sinks"} reports the capability table, {op:"drain"} retries
    the outbox on demand. A real event validates, dedupes on
    idempotency_key, routes by kind (or explicit sinks), and delivers;
    a failed sink queues to the outbox instead of failing the call."""
    box = pub.Outbox(PUB_STATE_DIR)
    noise = pub.NoisePolicy(
        PUB_STATE_DIR / "noise.json",
        progress_min_s=PUB_PROGRESS_MIN_S,
        alert_min_s=PUB_ALERT_MIN_S,
        telegram_min_s=PUB_TG_MIN_S)
    op = str(body.get("op") or "").strip()
    if op == "sinks":
        sinks = _pub_sinks(frm)
        return {"message": f"{len(sinks)} sinks registered",
                "sinks": {n: s.capabilities()
                          for n, s in sinks.items()},
                "pending": box.pending_count()}
    if op == "drain":
        res = box.drain(_pub_sinks(frm))
        return {"message": f"drained: {len(res['delivered'])} delivered, "
                           f"{res['retrying']} retrying, "
                           f"{res['dead']} dead, {res['pending']} pending",
                **res}
    sinks = _pub_sinks(frm)
    drained = box.drain(sinks)   # piggyback retry on every publish
    res = pub.publish_event(body, sinks, box, noise, frm)
    if drained["delivered"] or drained["dead"]:
        res["drained"] = drained
    return res


_render_flag = threading.Event()
_render_worker_started = False


def render_async() -> None:
    """Respond first, render after — a burst of writes coalesces into the
    fewest renders that still cover every change (KNB-0769: the sync
    render blocked every write response ~10s). The board's poll/replay
    layer already tolerates cards.json regen lag."""
    global _render_worker_started
    if not _render_worker_started:
        threading.Thread(target=_render_loop, daemon=True).start()
        _render_worker_started = True
    _render_flag.set()


def _render_loop() -> None:
    while True:
        _render_flag.wait()
        _render_flag.clear()
        try:
            render()
        except Exception as e:
            sys.stderr.write(f"board-api async render failed: {e}\n")


def render() -> None:
    # own lock, not the card lock — renders may serialize among themselves
    # without blocking card mutations
    with Path("/tmp/board-render.lock").open("w") as rl:
        fcntl.flock(rl, fcntl.LOCK_EX)
        subprocess.run(
            [sys.executable, str(RENDER)], cwd=REPO, timeout=60, check=False
        )
        # tabs view too — a /respond answered on board2 must drop off its
        # needs-tony band on the next poll, not a render-guard tick later
        subprocess.run(
            [sys.executable, str(RENDER2), "--if-changed"],
            cwd=REPO, timeout=60, check=False
        )


def _ready_load() -> dict:
    try:
        return json.loads(READY_FILE.read_text())
    except Exception:
        return {}


def _ready_save(state: dict) -> None:
    READY_STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = READY_STATE_DIR / "verdicts.json.tmp"
    tmp.write_text(json.dumps(state, ensure_ascii=False))
    tmp.replace(READY_FILE)


def do_ready(body: dict) -> str:
    """/ready — a runner's complete claimability report for this pass.

    {host, verdicts:{card_id:{ok,reason}}, active:[{id,unit,at}]} — the
    host block is replaced wholesale; a runner always reports its full
    current view, so missing verdicts mean "not queued anymore", not
    drift. Card files are never touched (off-repo state, no re-render)."""
    host = str(body.get("host") or "").strip()
    if not dr.HOST_ID_RE.match(host):
        raise ValueError("host must be a valid host id")
    verdicts_in = body.get("verdicts") or {}
    if not isinstance(verdicts_in, dict) or len(verdicts_in) > 2000:
        raise ValueError("verdicts must be an object of card -> verdict")
    now_ts = time.time()
    verdicts = {}
    for cid, v in verdicts_in.items():
        if not isinstance(cid, str) or len(cid) > 120:
            continue
        v = v or {}
        verdicts[cid] = {"ok": bool(v.get("ok")),
                         "reason": str(v.get("reason") or "")[:300],
                         "at": now_ts}
    active = []
    for a in (body.get("active") or [])[:50]:
        if isinstance(a, dict) and a.get("id"):
            active.append({"id": str(a["id"])[:120],
                           "unit": str(a.get("unit") or "")[:160],
                           "at": int(a.get("at") or now_ts)})
    state = _ready_load()
    hosts = state.setdefault("hosts", {})
    hosts[host] = {"at": now_ts, "verdicts": verdicts, "active": active}
    # prune hosts silent > READY_HOST_TTL_S so a retired fleet member
    # doesn't keep voting on claimability forever
    for h in list(hosts):
        if now_ts - ((hosts[h] or {}).get("at") or 0) > READY_HOST_TTL_S:
            del hosts[h]
    _ready_save(state)
    return f"readiness recorded for {host} ({len(verdicts)} verdicts)"


CARDS_JSON = REPO / "stacks/web/public/apps/board/cards.json"

# The read-side contract (AUD-1033, card ops-manual-command-api-mcp-
# efficiency-audit): one small filtered/projected surface so neither
# agents nor daemons pay the whole-board dump for a single fact.
# action_status is synthesized in _project from action.status — compact
# and fields= readers must be able to see queued/claimed state without
# paying for the whole action dict (OPS-1107: clients filtering client-
# side on a projection that lacked action saw "no queued cards").
COMPACT_FIELDS = ("id", "title", "column", "updated", "priority", "ref",
                  "action_status")
# compact=2 (board-api-compact-cards): the card-detail tier — brief+spec
# for summary/answer surfaces, without the comms list or the action
# dict. action_status stays synthesized (OPS-1107).
COMPACT2_FIELDS = ("id", "ref", "title", "column", "priority", "updated",
                   "brief", "spec", "action_status")
CARDS_MAX_LIMIT = 1000


_card_read_cache = {}
_card_read_lock = threading.Lock()


def load_cards() -> dict:
    """Current canonical cards with legacy rendered board metadata.
    Unreadable canonical sources fail explicitly, never as stale/empty data."""
    try:
        payload = json.loads(CARDS_JSON.read_text()) or {}
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not CARD_DIR.is_dir():
        raise OSError("canonical card directory missing")
    with _card_read_lock:
        current = {}
        cards = []
        for path in sorted(CARD_DIR.glob("*.yml")):
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_size)
            cached = _card_read_cache.get(path)
            if cached and cached[0] == signature:
                card = cached[1]
            else:
                card = load(path)
                card.setdefault("id", path.stem)
            current[path] = (signature, card)
            cards.append(card)
        _card_read_cache.clear()
        _card_read_cache.update(current)
    return dict(payload, cards=cards)


def _lane_state_dir() -> Path:
    """DevNest lane state dir — read-only mirror of
    scripts/devnest/lane_gate.state_dir()."""
    env = os.environ.get("OPENCODE_LANE_STATE")
    if env:
        return Path(env)
    base = Path(os.environ.get("XDG_STATE_HOME")
                or Path.home() / ".local" / "state")
    return base / "opencode-lane"


def _lane_metrics(card_id: str = "", job_id: str = "",
                  limit: int = 25) -> list:
    """Read-only slice of the DevNest lane ledger (metrics.jsonl,
    METRIC_FIELDS — scripts/devnest/lane_gate.py): latest rows first."""
    out = []
    f = _lane_state_dir() / "metrics.jsonl"
    if not f.is_file():
        return out
    try:
        lines = f.read_text().splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            m = json.loads(ln)
        except (ValueError, TypeError):
            continue
        if not isinstance(m, dict):
            continue
        if card_id and m.get("card") != card_id:
            continue
        if job_id and m.get("job_id") != job_id:
            continue
        out.append(m)
    out.sort(key=lambda m: (str(m.get("at") or ""),
                            str(m.get("job_id") or "")), reverse=True)
    return out[: max(1, min(limit, 100))]


def _usage_for_job(job_id: str = "") -> dict:
    """Runner taskdir usage.json (input/output/cache tokens, exit_code,
    verdict, artifact_landed — scripts/board/runner-agent.py) — read-only."""
    if not job_id:
        return {}
    try:
        u = json.loads((DISPATCH_TASKS / job_id / "usage.json").read_text())
    except (OSError, ValueError):
        return {}
    return u if isinstance(u, dict) else {}


def _envelope_for_job(job_id: str = ""):
    """Committed DevNest envelope (evals/opencode-lane/jobs/<job_id>.yaml)
    — read-only, best-effort."""
    if not job_id:
        return None
    for p in (REPO / "evals" / "opencode-lane" / "jobs" / (job_id + ".yaml"),
              REPO / "evals" / "opencode-lane" / "jobs" / (job_id + ".yml")):
        try:
            if p.is_file():
                v = yaml.safe_load(p.read_text())
                return v if isinstance(v, dict) else None
        except (OSError, ValueError):
            continue
    return None


def _lane_evidence(job_id: str = "", card_id: str = "",
                   limit: int = 25) -> list:
    """Merged evidence rows for the control pane (KNB-0229 design §4):
    per job — ledger metric + usage.json + committed envelope, newest
    first."""
    out = []
    for m in _lane_metrics(card_id=card_id, job_id=job_id, limit=limit):
        job = {k: m.get(k) for k in (
            "job_id", "card", "executor", "profile", "model", "provider",
            "stage", "task_class",
            "input_tokens", "cache_read_tokens", "cache_write_tokens",
            "output_tokens", "provider_cost_usd", "combined_cost_usd",
            "wall_s", "queue_s", "retries", "tool_denials",
            "verifier_pass", "artifact_landed", "failure_reason",
            "escalated", "at")
            if m.get(k) is not None}
        usage = _usage_for_job(str(m.get("job_id") or ""))
        if usage:
            job["usage"] = usage
        env = _envelope_for_job(str(m.get("job_id") or ""))
        if env is not None:
            job["envelope"] = env
        out.append(job)
    return out


def _q1(q: dict, name: str, default: str = "") -> str:
    v = q.get(name)
    return v[0] if v else default


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


def _field_set(q: dict) -> set:
    cv = _q1(q, "compact").strip()
    if cv and cv.lower() not in ("0", "false", "no", "off"):
        # compact=2 is the detail tier; any other enabled value is the
        # original slim tier. Before this, compact=2 fell through to a
        # full-card dump — the heaviest possible miss.
        return set(COMPACT2_FIELDS) if cv == "2" else set(COMPACT_FIELDS)
    return {f.strip() for f in _q1(q, "fields").split(",") if f.strip()}


def _comms_tail(q: dict):
    """comms_tail=<n> keeps only the last n comms entries per card;
    0 drops comms entirely. None = untouched."""
    raw = _q1(q, "comms_tail").strip()
    if not raw:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def _tail_comms(card: dict, n: int) -> dict:
    comms = card.get("comms")
    if not isinstance(comms, list):
        return card
    out = dict(card)                    # never mutate the read-side cache
    out["comms"] = comms[-n:] if n else []
    out["comms_total"] = len(comms)
    return out


def _project(card: dict, fields: set) -> dict:
    if not fields:
        return card
    out = {k: card.get(k) for k in fields if k in card}
    if "action_status" in fields:
        out["action_status"] = (_act(card)).get("status")
    return out


def card_query(cards: list, q: dict) -> dict:
    """Filtered/projected read over rendered cards (AUD-1033 contract):
    filters -> pagination -> field projection, in that order, so count/
    total describe the filtered set and truncation is honest."""
    out = list(cards)
    cid = _q1(q, "id")
    if cid:
        out = [c for c in out if c.get("id") == cid]
    col = _q1(q, "column")
    if col:
        out = [c for c in out if c.get("column") == col]
    st = _q1(q, "action_status")
    if st:
        out = [c for c in out
               if (_act(c)).get("status") == st]
    since = _q1(q, "since")
    if since:
        out = [c for c in out if str(c.get("updated") or "") >= since]
    total = len(out)
    try:
        off = max(0, int(_q1(q, "offset", "0")))
    except ValueError:
        off = 0
    try:
        lim = int(_q1(q, "limit", "0"))
    except ValueError:
        lim = 0
    lim = min(lim, CARDS_MAX_LIMIT) if lim else 0
    page = out[off: off + lim if lim else None]
    fields = _field_set(q)
    page = [_project(c, fields) for c in page]
    tail = _comms_tail(q)
    if tail is not None:
        page = [_tail_comms(c, tail) for c in page]
    return {"ok": True, "count": len(page), "total": total,
            "offset": off, "truncated": off + len(page) < total,
            "cards": page}


def queue_view() -> dict:
    """GET /queue — the ready-package projection (KNB-1007): queued cards
    in claim-drain order with per-runner verdicts and in-flight claims.
    Read-only; verdicts fresher than READY_STALE_S count as live."""
    cards = (load_cards().get("cards") or [])
    now_ts = time.time()
    hosts_in = (_ready_load().get("hosts") or {})
    hosts = {}
    for h, hb in hosts_in.items():
        age = now_ts - ((hb or {}).get("at") or 0)
        hosts[h] = {"at": (hb or {}).get("at"),
                    "age_s": int(age),
                    "stale": age > READY_STALE_S,
                    "active": (hb or {}).get("active") or []}

    def verdicts_for(cid: str) -> dict:
        return {h: v for h, hb in hosts_in.items()
                for cv in [((hb or {}).get("verdicts") or {}).get(cid)]
                if cv is not None
                for v in [cv]}

    queued_all = [c for c in cards
                  if (_act(c)).get("status") == "queued"]
    claimable_cards, waiting = [], []
    seen_wait = set()
    for c in queued_all:
        reason = queue_wait_reason(c)
        if reason:
            waiting.append((c, reason))
            seen_wait.add(c.get("id"))
        else:
            claimable_cards.append(c)
    # The write door parks human-owned work at idle/failed + awaiting_action
    # instead of queued — keep that explicit wait visible here too, or the
    # card would vanish from every queue surface.
    for c in cards:
        cid = c.get("id") or ""
        a = _act(c)
        if (cid in seen_wait or a.get("status") == "queued"
                or a.get("status") in ("running", "starting", "claimed",
                                       "done")
                or c.get("column") == "done"
                or not c.get("awaiting_action")):
            continue
        reason = queue_wait_reason(c)
        if reason:
            waiting.append((c, reason))
            seen_wait.add(cid)
    try:
        claimable_cards = dr.sort_claimable(claimable_cards)
    except Exception:
        pass  # dr unavailable -> keep board order; still truthful
    waiting.sort(key=lambda cr: str(cr[0].get("updated") or ""))

    out_q = []
    for i, c in enumerate(claimable_cards, 1):
        cid = c.get("id") or ""
        a = _act(c)
        v = verdicts_for(cid)
        fresh = {h: x for h, x in v.items()
                 if now_ts - (x.get("at") or 0) <= READY_STALE_S}
        out_q.append({
            "pos": i, "id": cid, "ref": c.get("ref") or "",
            "title": c.get("title") or "",
            "priority": c.get("priority") or "",
            "updated": c.get("updated") or "",
            "action": {k: a.get(k) for k in
                       ("repo", "type", "lane", "executor", "model",
                        "labels", "host", "target_host", "runner")
                       if a.get(k) not in (None, "", [])},
            "eligible": sorted(h for h, x in fresh.items()
                               if x.get("ok")),
            "blocked": {h: (x.get("reason") or "blocked")
                        for h, x in fresh.items() if not x.get("ok")},
            "verdicts": v,
            "unreported": sorted(
                h for h, hb in hosts.items()
                if not hb["stale"] and h not in v)})

    out_wait = []
    for c, reason in waiting:
        cid = c.get("id") or ""
        a = _act(c)
        kind, owner = _wait_kind(c)
        open_reqs = [str(r.get("id") or "?") for r in _reqs(c)
                     if r.get("status") not in ("answered", "closed")]
        if open_reqs:
            next_action = "answer open request(s): " + ", ".join(open_reqs)
        elif kind == "human":
            next_action = "human decision — not runner-dispatchable"
        else:
            next_action = ("fix action.type/executor/lane or declare a "
                           "served lane")
        out_wait.append({
            "id": cid, "ref": c.get("ref") or "",
            "title": c.get("title") or "",
            "priority": c.get("priority") or "",
            "updated": c.get("updated") or "",
            "kind": kind,
            "reason": reason,
            "owner": owner,
            "next_action": next_action,
            "action": {k: a.get(k) for k in
                       ("repo", "type", "lane", "executor", "model",
                        "labels", "host", "target_host", "runner")
                       if a.get(k) not in (None, "", [])}})

    # in-flight: card action.status plus the runner's own active report
    # (richer — unit name + start epoch) when one exists
    active_by_card = {}
    for h, hb in hosts_in.items():
        for a in (hb or {}).get("active") or []:
            if a.get("id"):
                active_by_card[a["id"]] = {"host": h, **a}
    claimed = []
    for c in cards:
        a = _act(c)
        if a.get("status") not in ("claimed", "running", "starting"):
            continue
        cid = c.get("id") or ""
        rep = active_by_card.get(cid) or {}
        claimed.append({
            "id": cid, "ref": c.get("ref") or "",
            "title": c.get("title") or "",
            "status": a.get("status"),
            "host": rep.get("host") or a.get("runner")
                    or _claim(c).get("host") or "",
            "unit": rep.get("unit") or a.get("task_id") or "",
            "at": rep.get("at") or "",
            "repo": a.get("repo") or ""})
    return {"ok": True, "at": now(), "stale_after_s": READY_STALE_S,
            "hosts": hosts, "queued": out_q, "human_waiting": out_wait,
            "counts": {"queued": len(out_q), "human_waiting": len(out_wait),
                       "claimed": len(claimed)},
            "claimed": claimed}


class H(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        # a dead/half-open client must not pin a handler thread forever —
        # threads piling up on stalled sockets was part of the 2026-11-16
        # thread-count symptom
        self.connection.settimeout(120)

    def _send(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # client timed out/disconnected after the write already
            # landed — the mutation is committed, only the reply is lost
            sys.stderr.write("board-api reply dropped: client gone\n")

    def log_message(self, fmt, *args):
        sys.stderr.write("board-api %s\n" % (fmt % args))

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path == "/health":
            return self._send(200, {"ok": True})
        if path == "/cards" or path.startswith("/card/"):
            try:
                payload = load_cards()
            except (OSError, ValueError, yaml.YAMLError):
                return self._send(503, {"error": "canonical card store unavailable"})
        if path == "/cards":
            if not payload:
                return self._send(404, {"error": "no cards.json yet"})
            q = parse_qs(url.query)
            if not q:
                return self._send(200, payload)
            return self._send(
                200, card_query(payload.get("cards") or [], q))
        if path == "/card" or path == "/card/":
            return self._send(400, {
                "error": "missing card id",
                "hint": "use /card/<id> or /cards?id=<id>"})
        if path.startswith("/card/"):
            cid = unquote(path[len("/card/"):])
            hit = next((c for c in (payload.get("cards") or [])
                        if c.get("id") == cid), None)
            if hit is None:
                # archived cards leave cards.json — resolve them via the
                # archive index so lookups keep working (KNB-1178)
                ap = _archive_index().get(cid)
                if ap is None:
                    return self._send(404, {"error": "card not found",
                                            "id": cid})
                hit = load(ap)
            q = parse_qs(url.query)
            card = _project(hit, _field_set(q))
            tail = _comms_tail(q)
            if tail is not None:
                card = _tail_comms(card, tail)
            return self._send(200, {"ok": True, "card": card})
        if path == "/jobs":
            # Read-only evidence for the control pane (KNB-0229 design §4):
            # DevNest lane metrics + runner usage.json + envelope per
            # card/job. Never a write — board-api stays the card mutation
            # door; this is the read door for execution evidence.
            q = parse_qs(url.query)
            card_id = _q1(q, "card").strip()
            job_id = _q1(q, "job_id").strip()
            if not card_id and not job_id:
                return self._send(400, {"error": "card= or job_id= required"})
            try:
                limit = int(_q1(q, "limit", "25") or 25)
            except ValueError:
                limit = 25
            return self._send(200, {
                "ok": True,
                "jobs": _lane_evidence(job_id=job_id, card_id=card_id,
                                       limit=limit)})
        if path == "/queue":
            try:
                return self._send(200, queue_view())
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/host-status":
            # Live-first host answer (card ada-status-live-state-preference,
            # OPS-1045): heartbeat/nest-mgr/runner surfaces BEFORE board
            # records; board claims carry ages; contradictions flagged.
            q = parse_qs(url.query)
            host = _q1(q, "host").strip()
            if not host:
                return self._send(400, {
                    "error": "host= required",
                    "hint": "/host-status?host=kk-mac"})
            try:
                cards = load_cards().get("cards") or hs.default_cards()
            except Exception:
                cards = hs.default_cards()
            try:
                return self._send(200, hs.host_status(host, cards=cards))
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if path == "/lock-stats":
            with _lock_stats_mu:
                snap = json.loads(json.dumps(_lock_stats))
            return self._send(200, {
                "ok": True,
                "buckets_s": list(_LOCK_STAT_BUCKETS),
                "paths": snap})
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

        # runner readiness reports (KNB-1007) — off-repo state under its
        # own flock; no card writes, no re-render, no upstream calls
        if path == "/ready":
            try:
                got = acquire_lock(READY_LOCK, 10)
                if got is None:
                    return self._send(503, {
                        "error": "ready lock busy — retry",
                        "retry_after_s": 5})
                lf, _w = got
                try:
                    msg = do_ready(body)
                finally:
                    lf.close()
                return self._send(200, {"ok": True, "message": msg,
                                        "via": ident})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})

        # remote-backed mutation endpoints (WP/MDDB) — separate flock so a
        # slow upstream call never stalls card writes; no board re-render
        # needed (cards.json untouched)
        if path in REMOTE_WRITE_PATHS:
            try:
                frm = (job_actor(body, ident)
                       if path in ("/job", "/publish", "/wiki/extension",
                                   "/wiki/news-review",
                                   "/wiki/news-diagnose", "/wiki/page")
                       else actor(body))
                got = acquire_lock(
                    WP_LOCK,
                    float(os.environ.get("BOARD_API_WP_LOCK_WAIT_S", "75")))
                if got is None:
                    return self._send(503, {
                        "error": "remote write lock busy — retry",
                        "retry_after_s": 10})
                lf, _w = got
                try:
                    if path == "/lesson":
                        res = (do_lesson_topics(body, frm)
                               if body.get("op") == "topics"
                               else do_lesson(body, frm))
                    elif path == "/job":
                        res = do_job(body, frm)
                    elif path == "/publish":
                        res = do_publish(body, frm)
                        if (res.get("receipts") or {}).get(
                                "board", {}).get("status") == "delivered":
                            render_async()   # board audit -> cards.json
                    elif path == "/wiki/extension":
                        res = do_wiki_extension(body, frm)
                    elif path == "/wiki/news-review":
                        res = do_wiki_news_review(body, frm)
                    elif path == "/wiki/news-diagnose":
                        res = do_wiki_news_diagnose(body, frm)
                    elif path == "/wiki/page":
                        res = do_wiki_page(body, frm)
                    else:
                        res = do_report(body, frm)
                finally:
                    lf.close()
                msg = res.pop("message")
                return self._send(200, {"ok": True, "message": msg,
                                        "via": ident, **res})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except UpstreamError as e:
                return self._send(502, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})

        notify_req = None
        resp_extra = {}
        global _pending_label
        t_lock = time.monotonic()
        got = acquire_lock(LOCK, LOCK_WAIT_S)
        if got is None:
            wait_t = time.monotonic() - t_lock
            _lock_stat(path, wait_t, timeout=True)
            sys.stderr.write(
                f"board-api lock wait >{LOCK_WAIT_S:.0f}s "
                f"path={path} — 503\n")
            return self._send(503, {
                "error": "board write lock saturated — retry",
                "retry_after_s": 5})
        lf, wait_s = got
        _phase_t.on = True
        _phase_t.load_ms = _phase_t.save_ms = _phase_t.card_path_ms = 0.0
        try:
            _pending_label = (
                f"{path.lstrip('/')} "
                f"{body.get('id') or body.get('card') or ''}").strip()
            try:
                if path == "/action":
                    verb = body.get("do", "queue")
                    if verb not in TRANSITIONS:
                        raise ValueError(f"do must be one of {sorted(TRANSITIONS)}")
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    if verb in ("claim", "move", "finish"):
                        if verb == "claim":
                            msg = do_claim(card, body)
                        elif verb == "move":
                            msg = do_move(card, body, actor(body))
                        else:
                            msg = do_finish(card, body)
                        card["updated"] = now()
                        save(p, card)
                    elif verb == "archive":
                        msg = do_archive(card, actor(body),
                                         cap=body.get("cap") is True)
                        card["updated"] = now()
                        _archive_move(p, card)
                    elif verb == "unarchive":
                        if p.parent != CARD_DIR / "archive":
                            raise ValueError(
                                "unarchive needs a card under cards/archive/")
                        msg = do_unarchive(card, actor(body))
                        card["updated"] = now()
                        _unarchive_move(p, card)
                    else:
                        msg = do_action(card, verb, actor(body))
                        card["updated"] = now()
                        save(p, card)
                elif path == "/respond":
                    frm = actor(body)
                    p = card_path(body.get("id") or body.get("card") or "")
                    card = load(p)
                    msg = do_respond(card, body, frm)
                    # session delivery runs off-lock (queue_delivery) —
                    # ssh round-trips must not stall other writers; its
                    # result note lands in comms via a second write
                    queue_delivery(
                        card, {"from": frm, "kind": "answer",
                               "request_id":
                                   str(body.get("request_id") or "").strip()
                                   or "ask",
                               "answer":
                                   str(body.get("answer") or "")
                                   .strip()[:500]})
                    card["updated"] = now()
                    save(p, card)
                elif path == "/comment":
                    frm = actor(body, default="")
                    text = str(body.get("text") or "").strip()
                    if not text:
                        raise ValueError("text required")
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    req = str(body.get("request_id") or "").strip()
                    if body.get("dedupe") is not False \
                            and dup_comment(card, frm, text, req):
                        msg = "comment already recorded (dedup)"
                        resp_extra = {"deduped": True}
                    else:
                        comms_add(card, frm, text, req=req)
                        # runner defer notes can raise the triage flag in the
                        # same write (fleet-unclaimable cards need a human to
                        # fix labels/pins — OPS-1097)
                        if body.get("awaiting_action"):
                            card["awaiting_action"] = True
                        msg = "comment added"
                        if frm in COMMENT_DELIVER_FROM:
                            queue_delivery(
                                card, {"from": frm, "kind": "comment",
                                       "text": text[:500]})
                        card["updated"] = now()
                        save(p, card)
                elif path == "/patch-relay":
                    frm = actor(body)
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    msg, name = do_patch_relay(card, body, frm)
                    resp_extra = {"file": name}
                    card["updated"] = now()
                    save(p, card)
                elif path in ("/attach", "/upload"):
                    frm = actor(body)
                    p = card_path(body.get("id") or body.get("card") or "")
                    card = load(p)
                    msg, files, rel = do_attach(card, body, frm)
                    resp_extra = {"file": rel}
                    card["updated"] = now()
                    save(p, card, extra=files)
                elif path == "/request":
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    msg = do_request(card, body)
                    card["updated"] = now()
                    save(p, card)
                    req = _reqs(card)[-1]
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
                elif path == "/inbox":
                    res = do_inbox(body, actor(body))
                    msg = res["message"]
                    resp_extra = {"file": res["file"]}
                else:
                    return self._send(404, {"error": "not found"})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})
        finally:
            hold_s = time.monotonic() - t_lock - wait_s
            lf.close()
            _lock_stat(path, wait_s, hold_s)
            _phase_t.on = False
            if wait_s >= LOCK_SLOW_S or hold_s >= LOCK_SLOW_S:
                load_ms = getattr(_phase_t, "load_ms", 0.0)
                save_ms = getattr(_phase_t, "save_ms", 0.0)
                cp_ms = getattr(_phase_t, "card_path_ms", 0.0)
                mutate_ms = max(
                    0.0, hold_s * 1000 - load_ms - save_ms - cp_ms)
                sys.stderr.write(
                    f"board-api lock wait={wait_s:.1f}s "
                    f"held={hold_s:.1f}s path={path} "
                    f"load_ms={load_ms:.0f} mutate_ms={mutate_ms:.0f} "
                    f"save_ms={save_ms:.0f} card_path_ms={cp_ms:.0f}\n")
        # card lock released — queue the push (debounced, best-effort) and
        # render under its own lock so neither stalls other writers
        if notify_req:
            try:
                queue_request_notify(*notify_req)
            except Exception as e:
                sys.stderr.write(f"board-api notify queue failed: {e}\n")
        self._send(200, {"ok": True, "message": msg, "via": ident,
                         **resp_extra})
        commit_async()   # flush queued write paths post-lock (worker commits)
        render_async()


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
    # idempotent retry: same answer again is a no-op success, a
    # different one still requires reopen (KNB-0180)
    n_comms = len(card["comms"])
    assert do_respond(card, {"request_id": "r1", "answer": "yes"},
                      "tony") == "already answered"
    assert len(card["comms"]) == n_comms
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
    # idempotent retry on the ask path too — same option, no error
    assert do_respond(acard, {"option": 0}, "tony") == "already answered"
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

    # off-lock delivery (OPS-1314): queue_delivery runs the ssh-capable
    # _deliver_to_session on the post-write worker — the request path
    # never holds the card flock across it
    qcard = {"id": "zz-test",
             "action": {"status": "running", "task_id": sess.name,
                        "runner": HOST}}
    n = n_lines()
    queue_delivery(qcard, {"from": "tony", "kind": "comment",
                           "text": "async note"})
    for _ in range(50):
        if n_lines() > n:
            break
        time.sleep(0.1)
    assert n_lines() == n + 1, "queued delivery never landed"
    rec = json.loads((sess / "answers.jsonl").read_text().splitlines()[-1])
    assert rec["kind"] == "comment" and rec["text"] == "async note"
    # hide path never raises and does not block the caller
    hide_dispatch_session({"id": "zz-test",
                           "action": {"status": "done", "task_id": ""}})

    # /comment dedupe (OPS-1314): a request_id stamps the entry and
    # dedupes forever; same (from, text) inside COMMENT_DEDUP_S dedupes;
    # past the window or a different text writes
    c0 = {"comms": []}
    comms_add(c0, "tony", "x", req="r9")
    assert c0["comms"][0]["req"] == "r9"
    comms_add(c0, "tony", "y")
    assert "req" not in c0["comms"][1]
    assert dup_comment({"comms": c0["comms"]}, "tony", "x", "r9") is True
    assert dup_comment({"comms": c0["comms"]}, "tony", "x", "r8") is False
    dcard = {"comms": [{"at": now(), "from": "devin", "text": "hi"}]}
    assert dup_comment(dcard, "devin", "hi", "") is True
    assert dup_comment(dcard, "ada", "hi", "") is False
    assert dup_comment(dcard, "devin", "other", "") is False
    old = (datetime.now(timezone(timedelta(hours=7)))
           - timedelta(seconds=COMMENT_DEDUP_S + 300)) \
        .strftime("%Y-%m-%d %H:%M")
    assert dup_comment(
        {"comms": [{"at": old, "from": "devin", "text": "hi"}]},
        "devin", "hi", "") is False

    # /cards read projection (board-api-compact-cards): fields=,
    # compact tiers, comms_tail — and none of it may mutate the card
    # dicts the read cache hands out
    big = {"id": "c1", "ref": "KNB-1", "title": "t", "column": "doing",
           "priority": "high", "updated": "2026-01-01", "brief": "b",
           "spec": "s", "note": "n",
           "action": {"status": "queued", "task_id": "x"},
           "comms": [{"at": f"2026-01-0{i}", "from": "devin",
                      "text": f"m{i}"} for i in range(1, 6)]}
    res = card_query([big], parse_qs("fields=id,title"))
    assert res["cards"] == [{"id": "c1", "title": "t"}]
    res = card_query([big], parse_qs("compact=1"))
    assert res["cards"][0]["action_status"] == "queued"
    assert "comms" not in res["cards"][0] and "spec" not in res["cards"][0]
    res = card_query([big], parse_qs("compact=2"))
    c2 = res["cards"][0]
    assert c2["brief"] == "b" and c2["spec"] == "s"
    assert c2["action_status"] == "queued"
    assert "comms" not in c2 and "action" not in c2
    res = card_query([big], parse_qs("comms_tail=2"))
    ct = res["cards"][0]
    assert [m["text"] for m in ct["comms"]] == ["m4", "m5"]
    assert ct["comms_total"] == 5 and ct["spec"] == "s"
    res = card_query([big], parse_qs("comms_tail=0"))
    assert res["cards"][0]["comms"] == [] \
        and res["cards"][0]["comms_total"] == 5
    res = card_query([big], parse_qs("fields=id,comms&comms_tail=1"))
    fc = res["cards"][0]
    assert [m["text"] for m in fc["comms"]] == ["m5"] \
        and "spec" not in fc
    # the source card is untouched — the read cache serves it again
    assert len(big["comms"]) == 5 and "comms_total" not in big
    # garbage comms_tail is ignored, never a 500
    res = card_query([big], parse_qs("comms_tail=abc"))
    assert len(res["cards"][0]["comms"]) == 5
    # compact=0 disables -> fields path (empty -> full card)
    res = card_query([big], parse_qs("compact=0"))
    assert "comms" in res["cards"][0] and "action" in res["cards"][0]
    # unknown compact values map to tier 1, never the silent full dump
    res = card_query([big], parse_qs("compact=9"))
    assert "comms" not in res["cards"][0] \
        and res["cards"][0]["action_status"] == "queued"

    # bounded acquire — a held flock yields None after the deadline,
    # never a silent queue (the pre-fix stall mode)
    lpath = tmp / "t.lock"
    held_fd = lpath.open("w")
    fcntl.flock(held_fd, fcntl.LOCK_EX)
    t0 = time.monotonic()
    assert acquire_lock(lpath, 0.5) is None
    assert 0.4 <= time.monotonic() - t0 < 5
    fcntl.flock(held_fd, fcntl.LOCK_UN)
    got = acquire_lock(lpath, 1)
    assert got is not None
    got[0].close()
    held_fd.close()

    # /patch-relay (runner-push-cred-gap): a runner that can't push
    # relays its session head as a git bundle into PATCH_INBOX; the
    # sidecar carries the fetch+verify metadata merge-sweep needs
    globals()["PATCH_INBOX"] = tmp / "patch-inbox"
    rcard = {"id": "relay-card", "comms": []}
    good = base64.b64encode(b"# v2 git bundle\nfake").decode()
    rejects(lambda: do_patch_relay(rcard, {"head": "xyz"}, "devin"),
            "head must be a commit sha")
    rejects(lambda: do_patch_relay(rcard, {"head": "ab" * 20}, "devin"),
            "bundle required")
    rejects(lambda: do_patch_relay(
        rcard, {"head": "ab" * 20, "bundle": "!!!"}, "devin"),
        "bundle must be base64")
    rejects(lambda: do_patch_relay(
        rcard, {"head": "ab" * 20,
                "bundle": base64.b64encode(b"junk").decode()}, "devin"),
        "not a git bundle")
    rejects(lambda: do_patch_relay(
        rcard, {"head": "ab" * 20, "branch": "bad..ref",
                "bundle": good}, "devin"), "bad branch")
    msg, name = do_patch_relay(
        rcard, {"head": "ab" * 20, "branch": "dispatch/t-1",
                "bundle": good, "host": "no-push-runner"}, "devin")
    assert name == "relay-card-" + "ab" * 5 + ".bundle"
    assert (tmp / "patch-inbox" / name).read_bytes() == \
        b"# v2 git bundle\nfake"
    meta = json.loads(
        (tmp / "patch-inbox" / (name + ".json")).read_text())
    assert meta["head"] == "ab" * 20 and meta["host"] == "no-push-runner"
    assert meta["branch"] == "dispatch/t-1"
    assert any("patch-relay" in m["text"] for m in rcard["comms"])

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
    # (tony-targeted asks auto-fill [proceed, hold], so exercise the
    # optionless path on an ada-targeted request)
    rejects(lambda: do_request(card, {"ask": "q", "to": "ada",
                                      "suggested": "y"}),
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
    # dict-option action contract (KNB-0180): valid actions pass,
    # unknown actions and label-less dicts are refused at the door
    do_request(card, {"ask": "act?",
                      "options": [{"id": "go", "label": "Go",
                                   "action": "queue"},
                                  {"id": "later", "label": "Later",
                                   "action": "hold"}]})
    assert card["requests"][-1]["options"][0]["action"] == "queue"
    rejects(lambda: do_request(card, {"ask": "bad act",
                                      "options": [{"id": "x",
                                                   "label": "X",
                                                   "action": "explode"}]}),
            "option action must be one of")
    rejects(lambda: do_request(card, {"ask": "bad opt",
                                      "options": [{"action": "hold"}]}),
            "options dicts need id/label/v/d")
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
    # spoofed status dropped + queued; the queue-time classifier may add
    # lane/executor/task_class pins on top (OPS-0838)
    assert {k: c3["action"][k] for k in ("type", "repo", "status")} \
        == {"type": "dispatch", "repo": "chaba", "status": "queued"}
    # manual type accepted; queue:true with no action arms a dispatch card
    do_create({"title": "t", "id": "spawn-man",
               "action": {"type": "manual"}}, "devin")
    assert mkfile("spawn-man")["action"] == {"type": "manual"}
    do_create({"title": "t", "id": "spawn-4", "queue": True}, "devin")
    assert {k: mkfile("spawn-4")["action"][k]
            for k in ("type", "status")} \
        == {"type": "dispatch", "status": "queued"}
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

    # save()/load() round-trip guard — a card body whose dump doesn't
    # re-parse as a mapping is refused before the file is touched
    # (guard-card-yaml-syntax-validation-at-wri)
    gdir = tmp / "guard-cards"
    gdir.mkdir()
    gp = gdir / "g1.yml"
    good = {"id": "g1", "title": "t", "column": "backlog",
            "comms": [{"at": "x", "from": "devin", "text": "hi"}]}
    save(gp, good)
    assert load(gp) == good
    assert not (gdir / "g1.yml.tmp").exists()  # tmp renamed, not left
    rejects(lambda: save(gp, "not a mapping"), "did not re-parse")
    rejects(lambda: save(gp, ["a", "b"]), "did not re-parse")
    assert load(gp) == good            # refuse never clobbered the file
    gp.write_text("- a\n- b\n")        # syntactically valid, wrong shape
    rejects(lambda: load(gp), "not a YAML mapping")

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
    # public-edge lane: valid edge key verifies with cf-email attribution,
    # wrong/missing key falls through to the normal gates and denies
    ek = os.environ.get("BOARD_API_EDGE_KEY")
    if ek:
        edge = {"X-Board-Edge-Key": ek,
                "Cf-Access-Authenticated-User-Email": "t@e.com",
                "X-Forwarded-For": "203.0.113.5"}
        assert caller_identity(edge, "10.0.0.9") == "edge:t@e.com"
        edge2 = {"X-Board-Edge-Key": "wrong",
                 "X-Forwarded-For": "203.0.113.5"}
        assert caller_identity(edge2, "10.0.0.9") == ""

    # deferred commit (board-api-writes-eaten-by-autostash-pops-515009 +
    # board-api-commit-outside-lock): a save() in a real repo queues its
    # paths and the commit worker lands them in HEAD within ~debounce
    # seconds — no dirty card file sits long enough for autostash to
    # eat; BOARD_API_COMMIT=0 falls back to the dirty-until-sweep model;
    # paths outside REPO are ignored; a mid-rebase tree defers the
    # commit and the retry loop lands it once git settles.
    real_repo, real_cards = REPO, CARD_DIR
    real_lock = LOCK
    real_deb, real_retry = COMMIT_DEBOUNCE_S, COMMIT_RETRY_S
    grepo = tmp / "grepo"
    gcards = grepo / "docs/ssot/kanban/cards"
    gcards.mkdir(parents=True)
    subprocess.run(["git", "-C", str(grepo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(grepo), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "init"], check=True)
    globals()["REPO"] = grepo
    globals()["CARD_DIR"] = gcards
    globals()["LOCK"] = tmp / "board-api.lock"   # probe off the real flock
    globals()["COMMIT_DEBOUNCE_S"] = 0.05
    globals()["COMMIT_RETRY_S"] = 0.2
    g1 = {"id": "gc1", "title": "t", "column": "backlog"}
    save(gcards / "gc1.yml", g1)
    assert commit_pending_flush(10)
    log = subprocess.run(["git", "-C", str(grepo), "log", "--format=%s",
                          "-1"], capture_output=True, text=True).stdout
    assert "write gc1" in log and log.startswith("board-api"), log
    assert subprocess.run(["git", "-C", str(grepo), "status",
                           "--porcelain"], capture_output=True,
                          text=True).stdout.strip() == ""
    # burst coalescing: three writes land in ONE commit
    for i in (2, 3, 4):
        save(gcards / f"gc{i}.yml", {"id": f"gc{i}", "title": "t"})
    assert commit_pending_flush(10)
    log2 = subprocess.run(
        ["git", "-C", str(grepo), "log", "--format=%s", "-2"],
        capture_output=True, text=True).stdout
    assert "board-api write gc" in log2.splitlines()[0], log2
    assert subprocess.run(["git", "-C", str(grepo), "status",
                           "--porcelain"], capture_output=True,
                          text=True).stdout.strip() == ""
    # disabled -> file stays dirty for the sweep
    os.environ["BOARD_API_COMMIT"] = "0"
    g1["note"] = "later"
    save(gcards / "gc1.yml", g1)
    dirty = subprocess.run(["git", "-C", str(grepo), "status",
                            "--porcelain"], capture_output=True,
                           text=True).stdout
    assert "gc1.yml" in dirty
    del os.environ["BOARD_API_COMMIT"]
    # mid-rebase tree -> commit deferred (pending, write dirty) then the
    # retry loop lands it once the rebase state clears
    (grepo / ".git" / "rebase-merge").mkdir()
    g1["note"] = "during rebase"
    save(gcards / "gc1.yml", g1)
    assert not commit_pending_flush(2)     # stays queued while rebasing
    assert "gc1.yml" in subprocess.run(
        ["git", "-C", str(grepo), "status", "--porcelain"],
        capture_output=True, text=True).stdout
    (grepo / ".git" / "rebase-merge").rmdir()
    assert commit_pending_flush(10)        # retry lands it
    assert subprocess.run(["git", "-C", str(grepo), "status",
                           "--porcelain"], capture_output=True,
                          text=True).stdout.strip() == ""
    # sweep race (board-api-residual-lock-holds): queued paths committed
    # by an external commit while the card flock is held must end the
    # batch — `git commit -- <rels>` on clean paths rc=1s over OTHER
    # dirty files, which used to requeue into a 'commit skipped' storm.
    (grepo / "unrelated.txt").write_text("dirty")   # other dirt stays
    lf2 = acquire_lock(LOCK, 5)[0]     # held flock -> worker defers
    g1["note"] = "swept"
    save(gcards / "gc1.yml", g1)
    time.sleep(0.15)                   # let a drain cycle hit the defer
    subprocess.run(
        ["git", "-C", str(grepo), "add", "--",
         "docs/ssot/kanban/cards/gc1.yml"], check=True)
    subprocess.run(["git", "-C", str(grepo), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm",
                    "sweep"], check=True)
    lf2.close()                        # flock released -> drain runs
    assert commit_pending_flush(10)
    head = subprocess.run(["git", "-C", str(grepo), "log",
                           "--format=%s", "-1"], capture_output=True,
                          text=True).stdout.strip()
    assert head == "sweep", head       # worker did not commit over it
    assert "unrelated.txt" in subprocess.run(
        ["git", "-C", str(grepo), "status", "--porcelain"],
        capture_output=True, text=True).stdout
    (grepo / "unrelated.txt").unlink()
    # outside-REPO paths are filtered, never raise
    save(tmp / "outside.yml", {"id": "o", "title": "t"})
    globals()["REPO"] = real_repo
    globals()["CARD_DIR"] = real_cards
    globals()["LOCK"] = real_lock
    globals()["COMMIT_DEBOUNCE_S"] = real_deb
    globals()["COMMIT_RETRY_S"] = real_retry

    # ---- unified mutation door (nest-api-unified-mutation-service) ----
    class FakeWP:
        """Records POSTs, returns `existing` for slug GETs."""
        def __init__(self, existing=None):
            self.existing = existing or []
            self.posts = []

        def __call__(self, route, data=None):
            if data is None:
                return self.existing
            self.posts.append((route, data))
            return {"id": 42}

    real_wp, real_th = wp_api, _gemini_thai
    real_mddb, real_crn = _mddb_post, _crn
    try:
        # /lesson — validation
        rejects(lambda: do_lesson({}, "devin"), "topic required")
        rejects(lambda: do_lesson({"topic": "t"}, "devin"),
                "content required")
        rejects(lambda: do_lesson({"topic": "t", "content": "x",
                                   "level": "phd"}, "devin"),
                "level must be one of")
        rejects(lambda: do_lesson({"topic": "t", "content": "x",
                                   "source": "smoke"}, "devin"),
                "source must be one of")
        # create: Thai section appended, contract meta stamped
        wp = FakeWP()
        globals()["wp_api"] = wp
        globals()["_gemini_thai"] = lambda h: "<p>แปล</p>"
        res = do_lesson({"topic": "Object Storage",
                         "content": "<p>hi</p>", "level": "intro",
                         "source": "chat"}, "devin")
        assert res["action"] == "created" and res["post_id"] == 42
        assert res["th"] is True
        route, payload = wp.posts[-1]
        assert route == "/wp/v2/lesson"
        assert payload["slug"].startswith("lesson-")
        assert "ไทย" in payload["content"]
        assert payload["meta"]["topic"] == "Object Storage"
        assert payload["meta"]["next_review"]
        # re-file: update path, first-learn provenance preserved, no_th honored
        wp2 = FakeWP([{"id": 42, "meta": {"learned_at": "2026-01-01",
                                          "next_review": "2026-01-08",
                                          "status": "learned"}}])
        globals()["wp_api"] = wp2
        res = do_lesson({"topic": "Object Storage",
                         "content": "<p>v2</p>", "no_th": True}, "devin")
        assert res["action"] == "updated" and res["th"] is False
        route, payload = wp2.posts[-1]
        assert route == "/wp/v2/lesson/42"
        assert payload["meta"]["learned_at"] == "2026-01-01"
        assert payload["meta"]["next_review"] == "2026-01-08"
        assert payload["meta"]["status"] == "learned"
        assert "ไทย" not in payload["content"]
        # Thai-free --no-th write records the exemption (meta.no_th)
        assert payload["meta"]["no_th"] is True
        # re-file carrying Thai clears the exemption marker
        wp2b = FakeWP([{"id": 42, "meta": {"no_th": True}}])
        globals()["wp_api"] = wp2b
        globals()["_gemini_thai"] = lambda h: "<p>แปล</p>"
        do_lesson({"topic": "Object Storage", "content": "<p>v3</p>"},
                  "devin")
        _, payload = wp2b.posts[-1]
        assert "ไทย" in payload["content"]
        assert "no_th" not in payload["meta"]
        # re-file landing Thai-free keeps a prior exemption even when
        # this write didn't ask for no_th (translation failed upstream)
        wp2c = FakeWP([{"id": 42, "meta": {"no_th": True}}])
        globals()["wp_api"] = wp2c
        globals()["_gemini_thai"] = lambda h: ""
        do_lesson({"topic": "Object Storage", "content": "<p>v4</p>"},
                  "devin")
        _, payload = wp2c.posts[-1]
        assert "ไทย" not in payload["content"]
        assert payload["meta"]["no_th"] is True

        # /job — validation + create/update + comms log + parent
        assert job_actor({}, "local") == "local"
        assert job_actor({"from": "queue-mgr"}, "local") == "queue-mgr"
        rejects(lambda: job_actor({"from": "Bad Name!"}, "x"),
                "from must be")
        rejects(lambda: do_job({}, "queue-mgr"), "slug must match")
        rejects(lambda: do_job({"slug": "Bad_Slug"}, "queue-mgr"),
                "slug must match")
        rejects(lambda: do_job({"slug": "s", "status": "weird"},
                               "queue-mgr"), "status must be one of")
        wp3 = FakeWP()
        globals()["wp_api"] = wp3
        rejects(lambda: do_job({"slug": "s", "parent": "nope"},
                               "queue-mgr"), "no parent job")
        res = do_job({"slug": "thonburian-bench", "status": "done",
                      "comms": "finished in 98s", "pack": "thonburian-bench",
                      "kind": "pack"}, "queue-mgr")
        assert res["action"] == "created"
        route, payload = wp3.posts[-1]
        assert route == "/wp/v2/nest_job"
        assert payload["slug"] == "thonburian-bench"
        assert payload["status"] == "private"
        assert payload["meta"]["status"] == "done"
        assert payload["meta"]["pack"] == "thonburian-bench"
        log = json.loads(payload["meta"]["comms"])
        assert log[0]["from"] == "queue-mgr" and "98s" in log[0]["text"]
        assert payload["meta"]["updated"]
        # update: comms append keeps prior entries, status flips
        wp3.existing = [{"id": 7, "meta": {
            "comms": '[{"at":"x","from":"a","text":"first"}]'}}]
        res = do_job({"slug": "thonburian-bench", "status": "failed",
                      "note": "retry blew up"}, "queue-mgr")
        assert res["action"] == "updated"
        route, payload = wp3.posts[-1]
        assert route == "/wp/v2/nest_job/7"
        log = json.loads(payload["meta"]["comms"])
        assert len(log) == 2 and log[0]["text"] == "first"
        assert "retry blew up" in log[1]["text"]
        # bad comms json on the post heals instead of dying
        wp3.existing = [{"id": 7, "meta": {"comms": "not json"}}]
        res = do_job({"slug": "thonburian-bench", "note": "recovered"},
                     "queue-mgr")
        log = json.loads(wp3.posts[-1][1]["meta"]["comms"])
        assert len(log) == 1 and "recovered" in log[0]["text"]
        # parent as numeric id passes straight through
        wp3.existing = [{"id": 7, "meta": {}}]
        do_job({"slug": "child", "parent": 7, "status": "queued"},
               "queue-mgr")
        assert wp3.posts[-1][1]["parent"] == 7

        # /inbox — focus-inbox file write
        idir = tmp / "focus-inbox"
        idir.mkdir()
        globals()["INBOX_DIR"] = idir
        res = do_inbox({"text": "Try the new sweep cadence",
                        "label": "Sweep cadence", "tags": ["ops"],
                        "priority": "high"}, "ada")
        fp = idir / res["file"]
        assert fp.exists() and res["file"].endswith("-sweep-cadence.yml")
        doc = yaml.safe_load(fp.read_text())
        assert doc["focus"]["label"] == "Sweep cadence"
        assert doc["focus"]["priority"] == "high"
        assert doc["focus"]["status"] == "draft"
        assert doc["focus"]["tags"] == ["ops"]
        assert doc["source"]["date"]
        rejects(lambda: do_inbox({"text": "x", "priority": "urgent"}, "ada"),
                "priority must be")
        rejects(lambda: do_inbox({}, "ada"), "text required")

        # /report — mode inference, validation, search/note/create
        globals()["_mddb_post"] = lambda p, payload, timeout=30: [
            {"key": "dev-kanban",
             "meta": {"title": ["Dev kanban"], "updated": "u"}}]
        res = do_report({"query": "kanban"}, "devin")
        assert res["candidates"][0]["slug"] == "dev-kanban"
        assert res["candidates"][0]["title"] == "Dev kanban"
        rejects(lambda: do_report({"slug": "Bad!", "note": "x"}, "devin"),
                "slug must match")
        rejects(lambda: do_report({}, "devin"), "report needs")
        rejects(lambda: do_report({"mode": "bogus"}, "devin"),
                "mode must be")

        class FakeCRN:
            @staticmethod
            def note(slug, text, lang):
                return {"slug": slug, "line": f"* t — {text}",
                        "updated": "u"}

            @staticmethod
            def merged_meta(doc, slug, now, today):
                return {"bank": ["cms"], "subject": [slug]}

        globals()["_crn"] = lambda: FakeCRN
        res = do_report({"slug": "dev-kanban", "note": "progress"},
                        "devin")
        assert "noted dev-kanban" in res["message"]
        adds = []
        globals()["_mddb_post"] = (
            lambda p, payload, timeout=30: adds.append((p, payload)) or {})
        res = do_report({"title": "New Report", "content_md": "# hi"},
                        "devin")
        assert res["slug"] == "new-report"
        assert adds[0][0] == "add" and adds[0][1]["key"] == "new-report"
        assert adds[0][1]["meta"]["subject"] == ["new-report"]

        # /publish — provider-neutral door (devnest-publication-adapter-layer)
        pstate = tmp / "pub-state"
        globals()["PUB_STATE_DIR"] = pstate
        real_tg_url = PUB_TG_URL
        # closed port -> telegram deliveries deterministically queue
        globals()["PUB_TG_URL"] = "http://127.0.0.1:1/send"
        # validation — bad kind, news needs evidence, public needs verified
        rejects(lambda: do_publish({"kind": "heartbeat", "title": "t",
                                    "source": "devin"}, "devin"),
                "kind must be one of")
        rejects(lambda: do_publish({"kind": "news", "title": "t",
                                    "body": "b", "source": "devin"},
                                   "devin"), "news requires")
        rejects(lambda: do_publish(
            {"kind": "news", "title": "t", "body": "b", "source": "devin",
             "evidence": ["http://x"], "visibility": "public",
             "confidence": "observed"}, "devin"),
            "public news requires")
        # capability report — the registry is visible to callers
        res = do_publish({"op": "sinks"}, "devin")
        assert "job" in res["sinks"] and "json" in res["sinks"]
        assert res["sinks"]["telegram"]["surface"] == "members"
        # progress event to members -> job (WP) + json both receive the
        # SAME canonical event — WP is only one adapter
        wp4 = FakeWP()
        globals()["wp_api"] = wp4
        res = do_publish(
            {"kind": "progress", "title": "Pack thonburian-bench 50%",
             "job": "thonburian-bench", "source": "queue-mgr",
             "visibility": "members", "confidence": "measured",
             "sinks": ["job", "json"]}, "queue-mgr")
        assert res["receipts"]["job"]["status"] == "delivered"
        assert res["receipts"]["json"]["status"] == "delivered"
        route, payload = wp4.posts[-1]
        assert route == "/wp/v2/nest_job"
        assert payload["slug"] == "thonburian-bench"
        assert payload["meta"]["status"] == "running"
        assert payload["meta"]["event_id"] == res["event_id"]
        jlines = (pstate / "published.jsonl").read_text().splitlines()
        jev = json.loads(jlines[-1])["event"]
        assert jev["event_id"] == res["event_id"]
        assert jev["kind"] == "progress" and jev["job"] == "thonburian-bench"
        # retry of the same logical event dedupes — no second WP post
        res2 = do_publish(
            {"kind": "progress", "title": "Pack thonburian-bench 50%",
             "job": "thonburian-bench", "source": "queue-mgr",
             "visibility": "members", "confidence": "measured",
             "sinks": ["job", "json"]}, "queue-mgr")
        assert res2["deduped"] is True
        assert res2["idempotency_key"] == res["idempotency_key"]
        assert len([p for p in wp4.posts if p[0] == "/wp/v2/nest_job"]) == 1
        # private visibility gates members surfaces — job skipped,
        # json (private surface) still delivers
        res3 = do_publish(
            {"kind": "progress", "title": "private note", "job": "j1",
             "source": "devin", "sinks": ["job", "json"]}, "devin")
        assert res3["receipts"]["job"]["status"] == "skipped"
        assert "visibility" in res3["receipts"]["job"]["reason"]
        assert res3["receipts"]["json"]["status"] == "delivered"
        # unknown sink is a 400, not a silent drop
        rejects(lambda: do_publish(
            {"kind": "alert", "title": "t", "source": "devin",
             "sinks": ["carrier-pigeon"]}, "devin"), "unknown sink")
        # outbox: a sink that throws queues for retry, drain delivers
        res4 = do_publish(
            {"kind": "milestone", "title": "m1", "job": "j1",
             "source": "devin", "visibility": "members",
             "sinks": ["telegram"]}, "devin")
        assert res4["receipts"]["telegram"]["status"] == "queued"
        assert (pstate / "outbox.jsonl").exists()
        res5 = do_publish({"op": "drain"}, "devin")
        assert res5["pending"] == 1     # not yet due (30s base delay)
    finally:
        globals()["wp_api"] = real_wp
        globals()["_gemini_thai"] = real_th
        globals()["_mddb_post"] = real_mddb
        globals()["_crn"] = real_crn
        globals()["PUB_TG_URL"] = real_tg_url
        globals()["PUB_STATE_DIR"] = Path(os.environ.get(
            "BOARD_API_PUB_STATE",
            str(Path.home() / ".local/state/board-api-publish")))
        globals()["INBOX_DIR"] = REPO / "docs/ssot/focus-inbox"

    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    # Declare which checkout /tmp/board-api.lock protects — git-safe-pull
    # on a different checkout reads this and skips the shared lock rather
    # than stalling every write across its whole pull phase.
    try:
        LOCK_REPO_SENTINEL.write_text(str(REPO.resolve()) + "\n")
    except OSError:
        pass
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
