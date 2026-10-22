#!/usr/bin/env python3
"""wp-comment-sync.py — member comments on boards posts -> suggestion lanes.

Card wp-comment-sync-suggestion-inbox (Tony call 2026-10-14): member
comments on boards.surf-thailand.com posts are the cheap comms channel.
Every 15 min (wp-comment-sync.timer, job id wp-comment-sync in
docs/ssot/infrastructure/ssot.jobs.yml):

  1. poll  GET /wp/v2/comments?after=<cursor>  (cursor in state file)
  2. route by the commented post's REST type:
       memory-mirror -> Ada suggestion queue
                        (~/.local/share/ada/memory-pending/mp-*.yml —
                        the staged-writes lane from ada-memory-staged-writes;
                        approval applies through the guarded write path)
       asset|place|trip -> record-corrections queue
                        (~/.local/share/wp-comment-sync/record-corrections/
                        corr-<comment_id>.yml — an agent applies the
                        correction to the record, nothing is auto-applied)
       news + recognized command (pin/watch pin up the ladder; unpin
                        demotes one rung; unwatch/clear stops tracking —
                        ปักหมุด/เลิกปักหมุด/เฝ้าระวัง/เลิกติดตาม)
                        -> situation lane:
                        the comment IS the member's instruction, so the
                        digest's `situation` meta + situation-* tag are set
                        via news-situation.py's shared transition (meta only,
                        never post content) and the ack states the change —
                        never silent. When the regex table misses, a
                        chat-local classifier reads intent (free; strict
                        one-word contract, ambiguity -> none) so phrasing
                        like "keep an eye on this flood" still lands —
                        WCS_CLASSIFY=0 disables. Other news comments ->
                        digest.
       cam|bench|render_job (and anything else) -> digest only
                        (digest.jsonl + an events.md line)
  3. ack   reply in-thread via REST (wcs-ack marker so our own replies
           are never re-routed)
  4. dedup processed-ids + ack-ids sets in the state file — comment meta
           _processed skipped per card help (would need register_meta
           on the comment object)

Comments are SUGGESTIONS only — this script never writes MDDB, never
edits the target post, never applies anything. Application is always a
separate human/agent step through the queue files.

Stdlib + PyYAML only. Env:
  WP_BOARDS_ENV           default ~/.config/secrets/wp-boards.env
  WCS_STATE_DIR           default ~/.local/share/wp-comment-sync
  ADA_MEMORY_PENDING_DIR  default ~/.local/share/ada/memory-pending
  ADA_EVENTS_FILE         default ~/.local/share/ada/events.md
  WCS_CLASSIFY            0 disables the chat-local intent fallback
  WCS_CLASSIFY_MODEL      default chat-local (LiteLLM alias)
  LITELLM_URL/LITELLM_KEY else read from ~/.config/secrets/mddb-gemini.env
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import html
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ENV_PATH = os.environ.get(
    "WP_BOARDS_ENV",
    os.path.expanduser("~/.config/secrets/wp-boards.env"))
STATE_DIR = Path(os.environ.get(
    "WCS_STATE_DIR",
    os.path.expanduser("~/.local/share/wp-comment-sync")))
PENDING_DIR = Path(os.environ.get(
    "ADA_MEMORY_PENDING_DIR",
    os.path.expanduser("~/.local/share/ada/memory-pending")))
EVENTS_FILE = Path(os.environ.get(
    "ADA_EVENTS_FILE",
    os.path.expanduser("~/.local/share/ada/events.md")))
STATE = STATE_DIR / "state.json"
LOCK = STATE_DIR / ".lock"
DIGEST = STATE_DIR / "digest.jsonl"
CORR_DIR = STATE_DIR / "record-corrections"

FIRST_RUN_LOOKBACK_H = 24     # seed cursor when no state exists yet
PAGE_SIZE = 50
KEEP_IDS = 2000               # bound the processed/acks sets
EVENTS_MAX = 120              # mirror event_log.py rolling window

UA = "wp-comment-sync/1.0 (chaba; boards member-comment router)"
TAG_RE = re.compile(r"<[^>]+>")
ACK_MARK = "<!-- wcs-ack -->"

# post rest_base -> lane
LANE_ADA = "ada_suggestion"       # memory-mirror posts
LANE_RECORD = "record_correction"  # asset/place/trip posts
LANE_DIGEST = "digest"             # cam/bench/render_job + fallback
LANE_SITUATION = "situation"       # news posts + pin/unpin/watch commands
LANES = {
    "memory-mirror": LANE_ADA,
    "memory_mirror": LANE_ADA,
    "asset": LANE_RECORD,
    "place": LANE_RECORD,
    "trip": LANE_RECORD,
    "cam": LANE_DIGEST,
    "bench": LANE_DIGEST,
    "render_job": LANE_DIGEST,
    "news": LANE_SITUATION,
}

# Situation commands — checked in order (demote/clear before pin/watch so
# "เลิกปักหมุด" doesn't trip the "ปักหมุด" substring). English uses \b,
# Thai is a plain substring; must appear in the first 60 chars so narrative
# mentions ("he pinned the notice") don't fire it.
#   "unpin" demotes one rung (pinned->watching->none) — the digest was
#   usually auto-nominated for a reason; "unwatch"/"clear" stops tracking.
DEMOTE = "__demote__"
SITUATION_CMD_WINDOW = 60
SITUATION_COMMANDS = [
    ("", (r"\bunwatch\b", r"\bunfollow\b", r"\bclear\b",
          "เลิกติดตาม", "เลิกเฝ้าระวัง", "ยกเลิกการติดตาม")),
    (DEMOTE, (r"\bunpin\b", "เลิกปักหมุด", "เอาปักหมุดออก")),
    ("pinned", (r"\bpin\b", "ปักหมุด")),
    ("watching", (r"\bwatch\b", r"\bfollow\b", "เฝ้าระวัง", "ติดตาม")),
]


def parse_situation_command(text):
    """Member comment -> target state, DEMOTE, ''=clear, or None."""
    head = " ".join((text or "").lower().split())[:SITUATION_CMD_WINDOW]
    if not head:
        return None
    for state, pats in SITUATION_COMMANDS:
        for p in pats:
            if p.startswith("\\b"):
                if re.search(p, head):
                    return state
            elif p in head:
                return state
    return None


# Free-text fallback — when the regex table misses, the chat-local lane
# (qwen2.5:7b on idc02 via the LiteLLM gateway; card chat-local-free-lane)
# reads intent. Strict one-word contract: anything outside LABELS maps to
# None -> digest lane exactly as before. WCS_CLASSIFY=0 disables.
CLASSIFY_LABELS = {"pin": "pinned", "watch": "watching",
                   "unpin": DEMOTE, "unwatch": "", "none": None}
CLASSIFY_PROMPT = """A member left this comment on a news digest post. Does it
ask us to change how we TRACK this story? Reply with exactly one word:
  pin     - pin it (top-priority tracking)
  watch   - watch/follow/keep an eye on it
  unpin   - stop pinning it (one step down, keep watching)
  unwatch - stop tracking it entirely
  none    - not a tracking request (remark, question, thanks, narrative
            mention like "glad they pinned that")

Comment: {text}"""


def _litellm_chat():
    """Sibling scripts/ada/litellm_chat.py — OpenAI-style gateway caller."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "litellm_chat.py")
    spec = importlib.util.spec_from_file_location("litellm_chat", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def classify_situation_intent(text):
    """Free-text comment -> same contract as parse_situation_command, via
    chat-local. Returns None unless the model answers a known label."""
    if os.environ.get("WCS_CLASSIFY", "1").lower() in ("0", "no", "off"):
        return None
    text = " ".join((text or "").split())[:400]
    if len(text) < 4:
        return None
    try:
        out = _litellm_chat().chat(
            CLASSIFY_PROMPT.format(text=text),
            model=os.environ.get("WCS_CLASSIFY_MODEL", "chat-local"),
            temperature=0, max_tokens=8, timeout=90,
            label="wp-comment-classify")
    except Exception as e:
        print(f"  classify failed: {e}", file=sys.stderr)
        return None
    token = (out or "").strip().lower().strip(".,!:`\"'").split()
    label = token[0] if token else ""
    return CLASSIFY_LABELS.get(label) if label in CLASSIFY_LABELS else None


def _news_situation():
    """Sibling scripts/ada/news-situation.py — shared flag transitions."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "news-situation.py")
    spec = importlib.util.spec_from_file_location("news_situation", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def apply_situation(c, post, target, dry_run, via="command"):
    """news + pin/unpin/watch command -> set the digest's situation flag.
    The ONE lane where a member comment mutates WP state (meta/tags only —
    content untouched); the in-thread ack makes it loud. `via` notes when
    chat-local intent classification (not a regex command) drove it."""
    cid = c["id"]
    who = c.get("author_name") or f"wp-user-{c.get('author')}"
    post_obj = {"id": post.get("id"), "meta": post.get("meta") or {},
                "tags": post.get("tags") or [],
                "title": {"rendered": post.get("title") or ""},
                "link": post.get("link")}
    try:
        ns = _news_situation()
        nswp = ns.WP()
        post_obj["_tag_names"] = nswp.tag_names(post_obj["tags"])
        if target == DEMOTE:
            target = ns.demote_step(ns.effective_state(post_obj))
        old, new, changed = ns.set_state(
            nswp, post_obj, target, by=f"comment:{who}",
            note=f"comment #{cid}" + (f" via {via}" if via != "command"
                                      else ""),
            dry_run=dry_run)
    except (Exception, SystemExit) as e:
        print(f"  situation FAIL comment={cid}: {e}", file=sys.stderr)
        return f"sit:error:{cid}"
    return f"sit:{cid}:{new or 'cleared'}"


def _situation_target(c):
    return parse_situation_command(comment_text(c))


def load_wp_env(path):
    env = {}
    try:
        lines = open(path).read().splitlines()
    except OSError:
        sys.exit(f"missing env file {path}")
    for line in lines:
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    for k in ("WP_SITE_URL", "WP_APP_USER", "WP_APP_PASSWORD"):
        if k not in env:
            sys.exit(f"missing {k} in {path}")
    return env


# Lazily resolved so the module stays importable (tests, offline review)
# on hosts without the secrets file — api() fails there instead of import.
ENV = None
BASE = AUTH = None


def _ensure_env():
    global ENV, BASE, AUTH
    if ENV is None:
        ENV = load_wp_env(ENV_PATH)
        BASE = ENV["WP_SITE_URL"].strip().rstrip("/")
        AUTH = "Basic " + base64.b64encode(
            f"{ENV['WP_APP_USER'].strip()}:"
            f"{ENV['WP_APP_PASSWORD'].strip()}".encode()).decode()


def api(method, route, data=None):
    """WP REST via ?rest_route= permalink workaround (line-chat-timeline.py
    pattern). `route` may contain & separators already."""
    _ensure_env()
    url = f"{BASE}/index.php?rest_route=/wp/v2/{route}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", AUTH)
    req.add_header("User-Agent", UA)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": "?"}


def api_url(method, url):
    """Follow an absolute REST href (comment._links.up) for the parent
    post — same auth, arbitrary wp/v2 route."""
    _ensure_env()
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", AUTH)
    req.add_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": "?"}


def comment_text(c):
    """Rendered HTML -> plain text for queue payloads."""
    raw = (c.get("content") or {}).get("rendered") or ""
    txt = TAG_RE.sub(" ", raw)
    return " ".join(html.unescape(txt).split())


def post_ref(c):
    """Resolve the commented post: rest_base (type) from _links.up href,
    plus title/link/meta via one GET. Tolerates missing bits."""
    up = ((c.get("_links") or {}).get("up") or [{}])[0].get("href") or ""
    m = re.search(r"/wp/v2/([A-Za-z0-9_-]+)/(\d+)", up)
    ptype = m.group(1) if m else None
    info = {"type": ptype, "id": c.get("post"), "title": None,
            "link": None, "meta": {}}
    if up:
        s, post = api_url("GET", up)
        if s == 200 and isinstance(post, dict):
            info["type"] = post.get("type") or ptype
            t = post.get("title")
            info["title"] = (t.get("rendered") if isinstance(t, dict)
                             else t) or None
            info["link"] = post.get("link")
            if isinstance(post.get("meta"), dict):
                info["meta"] = post["meta"]
            info["tags"] = post.get("tags") or []
    return info


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"cursor": None, "processed": [], "acks": []}


def save_state(st):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE)


def log_event(kind, subject, text=""):
    """events.md line — same '## <ts> — <kind>: <actor> (<subject>)'
    rolling-log format as ada-voice backend/event_log.py."""
    stamp = time.strftime("%Y-%m-%d %H:%M")
    detail = (f"{text[:180]} · {socket.gethostname()}/wp-comment-sync"
              if text else f"{socket.gethostname()}/wp-comment-sync")
    entry = f"## {stamp} — {kind}: wp-comment-sync ({subject})\n{detail}"
    try:
        old = EVENTS_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        old = ""
    entries = [e.strip() for e in re.split(r"\n(?=## )", old) if e.strip()]
    entries.append(entry)
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        EVENTS_FILE.write_text("\n\n".join(entries[-EVENTS_MAX:]) + "\n",
                               encoding="utf-8")
    except OSError:
        pass


def digest_line(rec):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(DIGEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def stage_ada_suggestion(c, post, dry_run):
    """memory-mirror comment -> Ada memory-pending staged entry.

    Reuses the mp-*.yml schema from ada-voice backend/memory_pending.py
    so `memory-pending.py list/approve/reject` + the events digest see it
    unchanged. Deterministic id (mp-wpc<comment_id>) makes re-staging
    idempotent. route=bank: if the mirror post carries bank/key meta the
    entry is approvable end-to-end; without it the entry still lists and
    a reviewer sets bank before approving. text stays the member's words
    verbatim — the sha256 pin + post-staging rescan in approve() apply.
    """
    cid = c["id"]
    entry_id = f"mp-wpc{cid}"
    text = comment_text(c)
    meta = post.get("meta") or {}
    entry = {
        "id": entry_id,
        "status": "pending",
        "route": "bank",
        "identity": c.get("author_name") or f"wp-user-{c.get('author')}",
        "bank": meta.get("bank") or meta.get("memory_bank"),
        "key": meta.get("key") or meta.get("memory_key"),
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "args": {
            "source": "wp-comment",
            "kind": "note",
            "post_id": post.get("id"),
            "post_title": post.get("title"),
            "post_link": post.get("link"),
            "comment_id": cid,
        },
        "guest": None,
        "staged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_session": f"wp-comment-{cid}",
        "instance": "wp-boards",
    }
    if not dry_run:
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PENDING_DIR / f"{entry_id}.tmp"
        tmp.write_text(yaml.safe_dump(entry, allow_unicode=True,
                                      sort_keys=False))
        tmp.replace(PENDING_DIR / f"{entry_id}.yml")
    return entry_id


def stage_record_correction(c, post, dry_run):
    """asset/place/trip comment -> record-corrections queue entry.

    An agent applies the correction to the record later — this only
    files it, idempotent per comment id."""
    cid = c["id"]
    entry = {
        "id": f"corr-{cid}",
        "status": "pending",
        "post_type": post.get("type"),
        "post_id": post.get("id"),
        "post_title": post.get("title"),
        "post_link": post.get("link"),
        "comment_id": cid,
        "author": c.get("author_name") or f"wp-user-{c.get('author')}",
        "text": comment_text(c),
        "filed_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
    }
    if not dry_run:
        CORR_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CORR_DIR / f"corr-{cid}.tmp"
        tmp.write_text(yaml.safe_dump(entry, allow_unicode=True,
                                      sort_keys=False))
        tmp.replace(CORR_DIR / f"corr-{cid}.yml")
    return entry["id"]


def route(c, post, dry_run):
    """File the comment into its lane. Returns (lane, queue_id)."""
    lane = LANES.get(post.get("type") or "", LANE_DIGEST)
    if lane == LANE_SITUATION:
        target = _situation_target(c)
        via = "command"
        if target is None:
            via = "chat-local"
            target = classify_situation_intent(comment_text(c))
        if target is None:
            lane = LANE_DIGEST       # ordinary comment on a news post
        else:
            return lane, apply_situation(c, post, target, dry_run, via=via)
    if lane == LANE_ADA:
        return lane, stage_ada_suggestion(c, post, dry_run)
    if lane == LANE_RECORD:
        return lane, stage_record_correction(c, post, dry_run)
    if not dry_run:
        digest_line({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lane": lane,
            "comment_id": c["id"],
            "post_id": post.get("id"),
            "post_type": post.get("type"),
            "post_title": post.get("title"),
            "author": c.get("author_name"),
            "text": comment_text(c)[:400],
        })
    return lane, f"digest:{c['id']}"


LANE_BLURB = {
    LANE_ADA: "Ada suggestion queue (staged — nothing applied)",
    LANE_RECORD: "record-corrections queue (an agent applies it)",
    LANE_DIGEST: "comment digest (reference only)",
    LANE_SITUATION: "situation flag (applied to this post's meta)",
}


def ack(c, lane, qid, dry_run):
    """In-thread reply ack. Marker lets re-polls skip our own replies;
    returned reply id is recorded in state.acks as well."""
    author = c.get("author_name") or "there"
    if lane == LANE_SITUATION and qid.startswith("sit:"):
        if qid.startswith("sit:error"):
            content = (f"{ACK_MARK}\nSorry {author} — the situation flag "
                       f"change failed on our side; the ops log has the "
                       f"detail. Nothing was changed.")
        else:
            state = qid.rsplit(":", 1)[-1]
            content = (f"{ACK_MARK}\nDone, {author} — situation is now "
                       f"'{state}' on this digest. It shows on the "
                       f"/wp/ situations index; reply \"unpin\" or \"unwatch\" "
                       f"to clear.")
    else:
        content = (f"{ACK_MARK}\nNoted, {author} — filed to "
                   f"{LANE_BLURB.get(lane, lane)} [{qid}]. "
                   "Member comments are suggestions; a human/agent reviews "
                   "before anything changes.")
    if dry_run:
        return None
    s, res = api("POST", "comments",
                 {"post": c.get("post"), "parent": c["id"],
                  "content": content})
    if s in (200, 201) and isinstance(res, dict):
        return res.get("id")
    print(f"  ack FAIL comment={c['id']} status={s} "
          f"{str(res)[:160]}", file=sys.stderr)
    return None


def poll(cursor):
    """Fetch comments newer than cursor, oldest first (one page is
    plenty at 15-min cadence; loop guards bursts anyway)."""
    out = []
    after = cursor
    for _ in range(8):  # hard cap 400 comments/run
        route = (f"comments&per_page={PAGE_SIZE}&orderby=date&order=asc"
                 + (f"&after={urllib.parse.quote(after)}" if after
                    else ""))
        s, res = api("GET", route)
        if s != 200 or not isinstance(res, list):
            print(f"poll FAIL status={s} {str(res)[:200]}",
                  file=sys.stderr)
            break
        if not res:
            break
        out.extend(res)
        if len(res) < PAGE_SIZE:
            break
        after = res[-1].get("date_gmt") or res[-1].get("date")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="poll + route, but write nothing and send no acks")
    ap.add_argument("--since",
                    help="cursor override: ISO date to poll after")
    args = ap.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another wp-comment-sync is running — exit")
        return 0

    st = load_state()
    processed = set(st.get("processed") or [])
    acks = set(st.get("acks") or [])
    cursor = args.since or st.get("cursor")
    if not cursor:
        cursor = (datetime.now(timezone.utc)
                  - timedelta(hours=FIRST_RUN_LOOKBACK_H)
                  ).strftime("%Y-%m-%dT%H:%M:%S")

    comments = poll(cursor)
    n_new = 0
    for c in comments:
        cid = c.get("id")
        if cid in processed or cid in acks:
            continue
        if ACK_MARK in ((c.get("content") or {}).get("rendered") or ""):
            continue
        post = post_ref(c)
        lane, qid = route(c, post, args.dry_run)
        n_new += 1
        print(f"comment {cid} post={post.get('type')}:{post.get('id')} "
              f"by={c.get('author_name')} -> {lane} [{qid}]")
        if not args.dry_run:
            log_event("wp-comment", f"{post.get('type')}:{post.get('id')}",
                      f"{c.get('author_name')} -> {lane} [{qid}]: "
                      f"{comment_text(c)[:120]}")
        # Mark processed before the ack — a failed ack must not
        # re-route the comment into a duplicate queue entry next run.
        processed.add(cid)
        ack_id = ack(c, lane, qid, args.dry_run)
        if ack_id:
            acks.add(ack_id)
        d = c.get("date_gmt") or c.get("date")
        if d and (not st.get("cursor") or d > st["cursor"]):
            st["cursor"] = d

    st["processed"] = sorted(processed)[-KEEP_IDS:]
    st["acks"] = sorted(acks)[-KEEP_IDS:]
    if not args.dry_run:
        save_state(st)
    print(f"done: {len(comments)} fetched, {n_new} routed, "
          f"cursor={st.get('cursor')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
