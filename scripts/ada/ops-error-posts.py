#!/usr/bin/env python3
"""ops-error-posts.py — Ada tool/stream failures -> WP ops_error posts.

One private `ops_error` CPT post per failure that deserves a truthful
explanation (card boards-error-post-type). Sources, per lane:

  journald (journalctl --user -u <unit> -o json, since-cursor in state):
    function_call result ok:False/error      -> runtime_error
      ...error text SchemaError/usage hint   -> schema_error
      ...arg/identifier rejection            -> schema_error
      ...payload stale:true                  -> stale_result
      ...degraded:true/quota/delivered:0     -> degraded_result
    provider reconnect resumed=False         -> silent_reconnect
      (one post per session per day — storms coalesce on the slug)
  MDDB ada-ha-events-<lane> kind=ops-event:
    phantom_write_claim                      -> phantom_claim
    stale_result                             -> stale_result
    (other ops types — tool_storm, actuation_cap, confirm_strip — are
     containment events already covered by the ops digest, not posted)

Dedup: deterministic slug err-<md5(lane|session|tool|occurred_at|type)>
looked up via ?slug= on the REST endpoint — re-runs are idempotent; the
local state file only bounds how far back the journal is re-read.

Review loop: comments are open on the CPT — Kaewta/Devin post the
plain-language explanation as a comment, Tony flips meta status=resolved
when the pair (raw error vs explanation) reads right.

Writes go to origin_base (boards.h3) — the public edge bot-checks bare
script UAs (CF 1010); creds from ~/.config/secrets/wp-boards.env.

Usage:
  ops-error-posts.py                      # run since-cursor -> WP
  ops-error-posts.py --dry-run            # print would-post, no writes
  ops-error-posts.py --since "2 hours ago" --session 183e9c8d7e
                                        # backfill one session (seed runs)
  ops-error-posts.py --lane kk            # one lane only
  ops-error-posts.py --journal-file F --no-mddb --dry-run   # fixture
  ops-error-posts.py --selftest           # synthetic fixture end-to-end

Env:
  WP_BOARDS_ENV      wp-boards.env path (WP_SITE_URL/WP_APP_USER/WP_APP_PASSWORD)
  MDDB_BASE_URL      mddb base (default http://100.102.134.91:11023/v1)
  OPS_ERROR_STATE    state file (default ~/.local/share/ada/ops-error-posts-state.json)
  ADA_TRANSCRIPT_DIR transcript dir for transcript_ref lookup
                     (default ~/.local/share/ada/transcripts)
"""
from __future__ import annotations

import argparse
import ast
import base64
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
ENV_PATH = os.environ.get(
    "WP_BOARDS_ENV",
    os.path.expanduser("~/.config/secrets/wp-boards.env"))
STATE_PATH = Path(os.environ.get(
    "OPS_ERROR_STATE",
    os.path.expanduser("~/.local/share/ada/ops-error-posts-state.json")))
TRANSCRIPT_DIR = os.environ.get(
    "ADA_TRANSCRIPT_DIR",
    os.path.expanduser("~/.local/share/ada/transcripts"))

# lane -> journald unit + MDDB ops-event collection (ssot.apps.ada-persona-lanes)
LANES = {
    "kk":      {"unit": "ada-kk",      "events": "ada-ha-events-kk"},
    "tony":    {"unit": "ada-ha-tony", "events": "ada-ha-events-tony"},
    "michael": {"unit": "ada-michael", "events": "ada-ha-events-michael"},
}

FIRST_RUN_S = 3600          # first run looks back 1h (no flood of history)
J_OVERLAP_S = 300           # journal refetch overlap — slug dedup absorbs it
M_OVERLAP_S = 900           # mddb indexing lag allowance
WINDOW_CAP_S = 86400        # never rescan more than 24h back
MAX_POSTS_PER_RUN = 50      # storm guard — overflow retries next run
RAW_MAX = 4000              # raw_result payload cap

# ops-event doc types that map onto the CPT's error_type enum
OPS_EVENT_MAP = {
    "phantom_write_claim": "phantom_claim",
    "stale_result": "stale_result",
    "silent_reconnect": "silent_reconnect",
}

# --- journal regexes (same shapes as scripts/ada/session-audit.py) -----------
TS = r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
RE_RECV = re.compile(
    r".*function_call received id=(?P<cid>\S+) "
    r"name=(?P<name>\w+) args=(?P<args>\{.*)$")
RE_RES = re.compile(
    r".*function_call result id=(?P<cid>\S+) "
    r"name=(?P<name>\w+) result=(?P<res>.*)$")
RE_SESS = re.compile(r"session=(?P<sid>[0-9a-f]{6,16})")
RE_CONFIRM = re.compile(r"NOT EXECUTED|requires confirmation", re.I)
RE_ACL = re.compile(
    r"access policy|permission-gated|not allowed|permission denied|"
    r"acl deny|outside this session|only the session owner|"
    r"secondary speaker|guest tools are only available|"
    r"blocked:[a-z_]+", re.I)
RE_USAGE = re.compile(
    r"SchemaError|"
    r"invalid (action|what|lang|op|period|kind|cmd|who|provider|photo action)\b|"
    r"unknown \w+ provider|"
    r"\bmust be one of\b|"
    r"\bis required\b|requires text\b|"
    r"no page '[^']+' in|no such page|"
    r"no card '[^']+' on the board|"
    r"no \w+ camera matched|"
    r"not a registered display", re.I)
RE_FAIL = re.compile(r"'ok':\s*False|\"ok\":\s*false")
RE_HEAD_ERR = re.compile(
    r"^result=\{[^}]{0,400}?['\"]err(or)?['\"]:\s*['\"]?[\w{]")
RE_DEGRADED = re.compile(
    r"'degraded':\s*(?!False|None|'')|quota_exhausted': True|"
    r"'delivered': 0")
RE_RECONNECT = re.compile(r"resumed=False")


def _literal(text: str):
    """Parse the python-dict-shaped payload; tolerate trailing log junk."""
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


def _clip(s: str, n: int = 240) -> str:
    s = " ".join(str(s).split())
    return s[:n] + ("…" if len(s) > n else "")


def classify_result(res_txt: str, res) -> str | None:
    """result payload -> error_type, or None for clean/correct-by-design.

    confirm-gate and acl denials are skipped — they are not errors to
    explain, they are the tool working as intended."""
    if RE_CONFIRM.search(res_txt):
        return None
    if isinstance(res, dict):
        if res.get("needs_confirm") or res.get("would_interrupt"):
            return None
        if res.get("ok") is False or res.get("error") or res.get("err"):
            err = str(res.get("error") or res.get("err") or "ok:false")
            if RE_ACL.search(err):
                return None
            if RE_USAGE.search(err) or res.get("usage"):
                return "schema_error"
            return "runtime_error"
        if res.get("stale"):
            return "stale_result"
        if res.get("degraded") or res.get("quota_exhausted") or \
                res.get("delivered") == 0:
            return "degraded_result"
        return None
    # unparsed (truncated line) — head-region markers only
    if RE_ACL.search(res_txt[:600]):
        return None
    if RE_USAGE.search(res_txt[:600]):
        return "schema_error"
    if RE_FAIL.search(res_txt) or RE_HEAD_ERR.match(res_txt):
        return "runtime_error"
    if RE_DEGRADED.search(res_txt):
        return "degraded_result"
    return None


# --- sources -----------------------------------------------------------------

def fetch_journal(unit: str, since_epoch: float) -> list[dict]:
    """[{ts_epoch, line}] newest-last for one unit, or [] on failure."""
    cmd = ["journalctl", "--user", "-u", unit, "-o", "json",
           "--since", f"@{int(since_epoch)}", "--no-pager"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=60)
    except Exception as exc:
        print(f"warn: journalctl {unit}: {exc}", file=sys.stderr)
        return []
    if r.returncode != 0:
        print(f"warn: journalctl {unit} rc={r.returncode} "
              f"{r.stderr.strip()[:120]}", file=sys.stderr)
        return []
    out = []
    for ln in r.stdout.splitlines():
        try:
            d = json.loads(ln)
            ts = int(d.get("__REALTIME_TIMESTAMP", 0)) / 1e6
        except Exception:
            continue
        msg = d.get("MESSAGE")
        if msg:
            out.append({"ts_epoch": ts, "line": msg})
    return out


def parse_journal_events(rows: list[dict], lane: str,
                         session_filter: str = "") -> list[dict]:
    """journald rows -> ops_error events. Reconnects without an explicit
    session= attribute inherit the most recent session in that lane's
    stream (streams are single-active-session). Received/result pairs are
    joined on (session, call id) so the post carries the call's args."""
    events = []
    pending: dict[tuple[str, str], dict] = {}
    last_sid = ""
    for row in rows:
        line = row["line"]
        sm = RE_SESS.search(line)
        sid = sm.group("sid") if sm else ""
        if sid:
            last_sid = sid
        if session_filter and sid and sid != session_filter:
            continue
        m = RE_RECV.match(line)
        if m:
            pending[(sid, m.group("cid"))] = {
                "args": _literal(m.group("args")) or {}}
            continue
        m = RE_RES.match(line)
        if m:
            rec = pending.pop((sid, m.group("cid")), {})
            res_txt = "result=" + m.group("res")
            res = _literal(m.group("res"))
            etype = classify_result(res_txt, res)
            if etype:
                raw = res if isinstance(res, dict) else {"raw": _clip(res_txt, 600)}
                if "args" in rec and isinstance(raw, dict):
                    raw = {**raw, "_call_args": rec["args"]}
                events.append({
                    "lane": lane, "session_id": sid,
                    "tool": m.group("name"), "error_type": etype,
                    "occurred_at": row["ts_epoch"],
                    "raw_result": json.dumps(raw, ensure_ascii=False,
                                             default=str)[:RAW_MAX],
                    "evidence": _clip(
                        str((res or {}).get("error")
                            or (res or {}).get("err")
                            or (res or {}).get("degraded")
                            or res_txt), 240)})
            continue
        if RE_RECONNECT.search(line):
            sid = sid or last_sid
            if session_filter and sid != session_filter:
                continue
            events.append({
                "lane": lane, "session_id": sid, "tool": "stream",
                "error_type": "silent_reconnect",
                "occurred_at": row["ts_epoch"],
                "raw_result": json.dumps(
                    {"resumed": False, "line": _clip(line, 400)},
                    ensure_ascii=False),
                "evidence": _clip(line, 240)})
    return events


def fetch_ops_events(lane: str, collection: str, since_epoch: float,
                     session_filter: str = "") -> list[dict]:
    try:
        payload = json.dumps({
            "collection": collection,
            "filterMeta": {"kind": ["ops-event"]},
            "limit": 200}).encode()
        req = urllib.request.Request(
            f"{MDDB}/search", data=payload,
            headers={"content-type": "application/json"}, method="POST")
        docs = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as exc:
        print(f"warn: mddb {collection}: {exc}", file=sys.stderr)
        return []
    out = []
    for d in docs or []:
        meta = d.get("meta") or {}
        etype = OPS_EVENT_MAP.get((meta.get("type") or [""])[0])
        if not etype:
            continue
        ts = (meta.get("ts") or [""])[0]
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            epoch = dt.timestamp()
        except Exception:
            continue
        if epoch < since_epoch:
            continue
        sid = (meta.get("session_id") or meta.get("session") or [""])[0]
        if session_filter and sid != session_filter:
            continue
        head = ((d.get("contentMd") or "").splitlines() or [""])[0]
        out.append({
            "lane": lane, "session_id": sid,
            "tool": (meta.get("tool") or [""])[0],
            "error_type": etype, "occurred_at": epoch,
            "raw_result": json.dumps(
                {"type": (meta.get("type") or [""])[0], "head": head},
                ensure_ascii=False)[:RAW_MAX],
            "evidence": _clip(head, 240)})
    return out


# --- WP ---------------------------------------------------------------------

def load_wp_env(path: str) -> dict:
    env = {}
    for line in open(path):
        if "=" in line and not line.startswith("#"):
            k, v = line.rstrip("\n").split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    for k in ("WP_SITE_URL", "WP_APP_USER", "WP_APP_PASSWORD"):
        if k not in env:
            sys.exit(f"missing {k} in {path}")
    return env


class WP:
    UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

    def __init__(self, env: dict):
        self.base = env["WP_SITE_URL"].rstrip("/")
        self.h = {
            "Authorization": "Basic " + base64.b64encode(
                f"{env['WP_APP_USER']}:{env['WP_APP_PASSWORD']}"
                .encode()).decode(),
            "User-Agent": self.UA}

    def api(self, route: str, data: dict | None = None):
        url = (f"{self.base}/index.php?rest_route="
               f"{urllib.parse.quote(route, safe='/&=')}")
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(
            url, data=body, headers=self.h,
            method="POST" if data else "GET")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {"raw": str(e)}
        except Exception as e:
            return 0, {"raw": str(e)}

    def slug_lookup(self, slug: str) -> int:
        s, r = self.api(
            f"/wp/v2/ops_error&slug={slug}&status=private,archived"
            f"&per_page=1")
        if s != 200:
            # 'archived' may not be in the REST status enum on older
            # plugin versions — fall back to private-only rather than
            # treat a lookup error as "absent" (would double-post)
            s, r = self.api(
                f"/wp/v2/ops_error&slug={slug}&status=private&per_page=1")
        if s == 200 and isinstance(r, list) and r:
            return r[0]["id"]
        return 0

    def create(self, post: dict):
        return self.api("/wp/v2/ops_error", post)


# --- assembly ----------------------------------------------------------------

def event_slug(e: dict) -> str:
    if e["error_type"] == "silent_reconnect":
        # one post per session per day — a reconnect storm is one incident
        day = datetime.fromtimestamp(
            e["occurred_at"], timezone.utc).strftime("%Y-%m-%d")
        key = f"{e['lane']}|{e['session_id']}|{day}|{e['error_type']}"
    else:
        key = "|".join(str(e[k]) for k in
                       ("lane", "session_id", "tool",
                        "occurred_at", "error_type"))
    return "err-" + hashlib.md5(key.encode()).hexdigest()[:16]


def event_title(e: dict) -> str:
    day = datetime.fromtimestamp(
        e["occurred_at"], timezone.utc).strftime("%Y-%m-%d")
    tool = e["tool"] or "stream"
    return f"Err — {e['lane']} {tool} {day}"


def event_content(e: dict) -> str:
    ts = datetime.fromtimestamp(
        e["occurred_at"], timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        f"**{e['error_type']}** on lane `{e['lane']}` at {ts}",
        "",
        f"- session: `{e['session_id'] or '?'}`",
        f"- tool: `{e['tool'] or '—'}`",
        f"- transcript: `{e['transcript_ref'] or '—'}`",
        "",
        "Evidence:",
        "",
        "> " + (e["evidence"] or "(none)").replace("\n", "\n> "),
        "",
        "_Review loop: explain what happened plainly in the comments, "
        "then set meta status=resolved._",
    ]
    return "\n".join(lines)


def transcript_ref(session_id: str) -> str:
    if not session_id:
        return ""
    hits = glob.glob(os.path.join(TRANSCRIPT_DIR, f"*-{session_id}.md"))
    return os.path.basename(hits[0]) if hits else ""


def post_events(wp: WP, events: list[dict], dry_run: bool) -> tuple[int, int]:
    """(created, failed) — skips existing slugs."""
    created = failed = 0
    for e in events[:MAX_POSTS_PER_RUN]:
        slug = event_slug(e)
        e["transcript_ref"] = transcript_ref(e["session_id"])
        if dry_run:
            print(f"  [dry] {slug} {event_title(e)} — {e['error_type']} "
                  f"{e['evidence'][:80]}")
            continue
        if wp.slug_lookup(slug):
            continue
        body = {
            "title": event_title(e), "slug": slug, "status": "private",
            "comment_status": "open",   # the review thread IS the loop
            "content": event_content(e),
            "meta": {
                "lane": e["lane"], "session_id": e["session_id"],
                "tool": e["tool"], "error_type": e["error_type"],
                "raw_result": e["raw_result"],
                "transcript_ref": e["transcript_ref"],
                "occurred_at": datetime.fromtimestamp(
                    e["occurred_at"], timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": "open",
            }}
        s, r = wp.create(body)
        if s in (200, 201):
            created += 1
            print(f"  posted #{r.get('id')} {event_title(e)}")
        else:
            failed += 1
            print(f"  FAIL {slug} http {s} "
                  f"{json.dumps(r)[:160]}", file=sys.stderr)
    skipped = len(events) - min(len(events), MAX_POSTS_PER_RUN)
    if skipped:
        print(f"warn: {skipped} event(s) over MAX_POSTS_PER_RUN — "
              f"carried to next run", file=sys.stderr)
    return created, failed


def parse_since(s: str) -> float:
    s = s.strip()
    try:
        return datetime.fromisoformat(
            s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    m = re.match(r"^(\d+)\s*(hour|day|minute)s?\s*ago$", s)
    if m:
        mult = {"minute": 60, "hour": 3600, "day": 86400}[m.group(2)]
        return datetime.now(timezone.utc).timestamp() - int(m.group(1)) * mult
    raise SystemExit(f"cannot parse --since {s!r} (ISO or 'N hours ago')")


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, indent=1))


SELFTEST_JOURNAL = """\
2026-10-13 16:17:41,000 INFO voice.provider: session=183e9c8d7e function_call received id=call_1 name=web_search args={}
2026-10-13 16:17:41,500 INFO voice.provider: session=183e9c8d7e function_call result id=call_1 name=web_search result={'ok': False, 'error': "SchemaError: missing required 'query'", 'usage': 'web_search(query: str)'}
2026-10-13 16:18:41,000 INFO voice.provider: session=183e9c8d7e function_call received id=call_2 name=ada_enroll_speaker args={'person': 'person.tony', 'who': 'speaker'}
2026-10-13 16:18:41,500 INFO voice.provider: session=183e9c8d7e function_call result id=call_2 name=ada_enroll_speaker result={'ok': False, 'error': "SchemaError: missing required 'name', unknown arg 'person'", 'usage': 'ada_enroll_speaker(name: str)'}
2026-10-13 16:19:23,000 INFO voice.provider: session=183e9c8d7e provider reconnected (resumed=False) — context wiped
2026-10-13 16:20:01,000 INFO voice.provider: session=183e9c8d7e function_call result id=call_3 name=ada_memory_search result={'ok': True, 'degraded': True, 'fallback': 'lexical'}
2026-10-13 16:21:00,000 INFO voice.provider: session=183e9c8d7e function_call result id=call_4 name=home_call result={'error': 'NOT EXECUTED — requires confirmation'}
"""


def run_selftest() -> int:
    rows = [{"ts_epoch": datetime.strptime(
        l[:23], "%Y-%m-%d %H:%M:%S,%f").replace(
            tzinfo=timezone.utc).timestamp(), "line": l}
        for l in SELFTEST_JOURNAL.splitlines()]
    events = parse_journal_events(rows, "kk")
    kinds = [e["error_type"] for e in events]
    got = {"schema_error": kinds.count("schema_error"),
           "silent_reconnect": kinds.count("silent_reconnect"),
           "degraded_result": kinds.count("degraded_result")}
    ok = got == {"schema_error": 2, "silent_reconnect": 1,
                 "degraded_result": 1}
    print(json.dumps({"events": len(events), "counts": got,
                      "tools": [e["tool"] for e in events],
                      "slugs": [event_slug(e) for e in events]},
                     indent=1))
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since", default="",
                    help="window start (ISO, epoch, or 'N hours ago')")
    ap.add_argument("--session", default="",
                    help="only post events for this session id (backfill)")
    ap.add_argument("--lane", default="",
                    help="comma list — default all lanes")
    ap.add_argument("--journal-file", default="",
                    help="fixture: read journal lines from a file instead "
                         "of journalctl (first --lane's unit)")
    ap.add_argument("--no-mddb", action="store_true",
                    help="skip the ada-ha-events-* ops-event source")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return run_selftest()

    now = datetime.now(timezone.utc).timestamp()
    state = load_state()
    explicit = bool(args.since)
    if explicit:
        since = parse_since(args.since)
    else:
        since = min(now - FIRST_RUN_S,
                    float(state.get("journal_since", now - FIRST_RUN_S)))
        # never rescan more than WINDOW_CAP_S back
        since = max(since, now - WINDOW_CAP_S)

    lanes = [l for l in LANES
             if not args.lane or l in args.lane.split(",")]
    events: list[dict] = []

    if args.journal_file:
        rows = [{"ts_epoch": datetime.strptime(
            l[:23], "%Y-%m-%d %H:%M:%S,%f").replace(
                tzinfo=timezone.utc).timestamp()
            if re.match(r"^\d{4}-\d{2}-\d{2} ", l) else now, "line": l}
            for l in Path(args.journal_file).read_text(
                encoding="utf-8", errors="replace").splitlines()]
        events += parse_journal_events(rows, lanes[0] if lanes else "?",
                                       args.session)
    else:
        for lane in lanes:
            rows = fetch_journal(
                LANES[lane]["unit"], since - J_OVERLAP_S)
            events += parse_journal_events(rows, lane, args.session)

    if not args.no_mddb:
        mddb_since = (since if explicit else
                      float(state.get("mddb_since", since))) - M_OVERLAP_S
        for lane in lanes:
            events += fetch_ops_events(
                lane, LANES[lane]["events"], mddb_since, args.session)

    events.sort(key=lambda e: e["occurred_at"])
    print(f"[ops-error] {len(events)} event(s) since "
          f"{datetime.fromtimestamp(since, timezone.utc):%Y-%m-%d %H:%MZ}"
          + (f" session={args.session}" if args.session else ""))

    if args.dry_run:
        post_events(None, events, dry_run=True)  # type: ignore[arg-type]
        return 0

    wp = WP(load_wp_env(ENV_PATH))
    created, failed = post_events(wp, events, dry_run=False)
    print(f"[ops-error] posted={created} failed={failed} "
          f"(of {len(events)} events)")

    if failed == 0:
        # filtered runs (--session/--lane/--journal-file) are backfills —
        # the scan wasn't exhaustive, so they must not advance the cursor
        if not args.session and not args.lane and not args.journal_file:
            state["journal_since"] = now
            if not args.no_mddb:
                state["mddb_since"] = now
            save_state(state)
        else:
            print("[ops-error] filtered run — cursor unchanged")
    else:
        print("warn: post failures — cursor NOT advanced; next run "
              "rescans (slug dedup keeps it idempotent)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
