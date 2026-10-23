#!/usr/bin/env python3
"""activity-posts.py — Ada tool executions -> WP activity posts.

Card wp-activity-cpt-timeline-links (ADA-0650): tool executions
(image render, video render, page snapshot, translate/vision) become
durable private `activity` CPT items; the lane timelines link the post
instead of re-inlining the artifact, so nothing is stored twice.

Source: journald `function_call received`/`function_call result` pairs
per lane unit (same shapes as ops-error-posts.py). This deliberately
avoids an ada-voice hook — the sweep sees every call the provider
logged, and a `received` that never got a `result` (killed/refused
mid-turn, e.g. a service restart) is posted with status=blocked after
PENDING_GRACE_S — that IS the incident evidence.

Hierarchy (KNB-0659): parent = one `activity` post per lane+session
(kind=session, slug act-s-<lane>-<sid>); children = one post per tool
call (kind=tool, parent=<session post>). The parent meta status tracks
the worst child status seen so far.

Status: ok | failed | blocked
  ok      — result logged, no error markers
  failed  — result ok:False / error payload
  blocked — received never produced a result within PENDING_GRACE_S
            (killed mid-turn, restart, provider drop)

Dedup: deterministic slug act-<md5(lane|session|call)> looked up via
?slug= — re-runs are idempotent; the local state file only bounds how
far back the journal is re-read and holds calls still pending a result.

event_id = <lane>:<session>:<call> is stored in meta so the relay can
stamp the same id into journal entries and the timeline can join on it;
today the timeline joins on artifact_url instead.

Writes go to origin_base (boards.h3) — the public edge bot-checks bare
script UAs (CF 1010); creds from ~/.config/secrets/wp-boards.env.

Usage:
  activity-posts.py                      # run since-cursor -> WP
  activity-posts.py --dry-run            # print would-post, no writes
  activity-posts.py --since "2 hours ago" --session 183e9c8d7e
  activity-posts.py --lane kk            # one lane only
  activity-posts.py --journal-file F --dry-run   # fixture
  activity-posts.py --selftest           # synthetic fixture end-to-end

Env:
  WP_BOARDS_ENV      wp-boards.env path (WP_SITE_URL/WP_APP_USER/WP_APP_PASSWORD)
  ACTIVITY_STATE     state file (default ~/.local/share/ada/activity-posts-state.json)
  ACTIVITY_TOOLS     comma-separated tool allowlist override
                     (default regex: ada_render_image|ada_render_video|
                      page_snapshot|.*translat.*|.*vision.*)
"""
from __future__ import annotations

import argparse
import ast
import base64
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

ENV_PATH = os.environ.get(
    "WP_BOARDS_ENV",
    os.path.expanduser("~/.config/secrets/wp-boards.env"))
STATE_PATH = Path(os.environ.get(
    "ACTIVITY_STATE",
    os.path.expanduser("~/.local/share/ada/activity-posts-state.json")))

# lane -> journald unit (ssot.apps.ada-persona-lanes; same map as
# ops-error-posts.py — both jobs tail the same units on idc03)
LANES = {
    "kk":      {"unit": "ada-kk"},
    "tony":    {"unit": "ada-ha-tony"},
    "michael": {"unit": "ada-michael"},
}

FIRST_RUN_S = 3600          # first run looks back 1h (no flood of history)
J_OVERLAP_S = 300           # journal refetch overlap — slug dedup absorbs it
WINDOW_CAP_S = 86400        # never rescan more than 24h back
MAX_POSTS_PER_RUN = 100     # storm guard — overflow retries next run
PENDING_GRACE_S = 900       # received w/o result >15min old -> blocked
ERR_MAX = 4000              # error payload cap

# Emitters per the answered board request: renders + translate only.
# Names are matched case-insensitively against this regex; ACTIVITY_TOOLS
# (comma list) replaces it entirely.
TOOL_RE = re.compile(
    os.environ.get("ACTIVITY_TOOLS", "").strip()
    and "^(" + "|".join(
        re.escape(t.strip())
        for t in os.environ["ACTIVITY_TOOLS"].split(",") if t.strip()) + ")$"
    or r"ada_render_image|ada_render_video|page_snapshot|.*translat.*|.*vision.*",
    re.I)

# --- journal regexes (same shapes as scripts/ada/ops-error-posts.py) ----
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
RE_FAIL = re.compile(r"'ok':\s*False|\"ok\":\s*false")
RE_URL = re.compile(r"^https?://", re.I)

ARTIFACT_KEYS = ("artifact_url", "output_url", "image_url", "video_url",
                 "media_url", "url", "file_url", "download_url")
PROMPT_KEYS = ("prompt", "text", "instruction", "prompt_excerpt",
               "description", "query")


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


def _walk_strings(obj):
    """Yield every string value anywhere in a nested dict/list."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_strings(v)
    elif isinstance(obj, str):
        yield obj


def _find_artifact(res) -> str:
    """Pull the artifact URL out of a result payload — preferred keys
    first, then any URL-looking string (relay-img/uploads wins)."""
    if not isinstance(res, dict):
        return ""
    for k in ARTIFACT_KEYS:
        v = res.get(k)
        if isinstance(v, str) and RE_URL.match(v):
            return v
    urls = [s for s in _walk_strings(res) if RE_URL.match(s)]
    for u in urls:  # durable media hosts first
        if re.search(r"/(relay-img|wp-content/uploads)/", u):
            return u
    return urls[0] if urls else ""


def _find_prompt(args) -> str:
    if not isinstance(args, dict):
        return ""
    for k in PROMPT_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return _clip(v, 400)
    return ""


def _find_field(src, keys) -> str:
    if not isinstance(src, dict):
        return ""
    for k in keys:
        v = src.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def classify_status(res_txt: str, res) -> tuple[str, str]:
    """(status, error). confirm-gate and acl denials count as blocked —
    the call did not run, which is exactly the evidence the card wants."""
    err = ""
    if isinstance(res, dict):
        if res.get("needs_confirm") or res.get("would_interrupt") \
                or RE_CONFIRM.search(res_txt):
            return "blocked", _clip(
                str(res.get("error") or res.get("err") or "confirmation required"))
        if res.get("ok") is False or res.get("error") or res.get("err"):
            err = _clip(str(res.get("error") or res.get("err") or "ok:false"), 600)
            return ("blocked" if RE_ACL.search(err) else "failed"), err
        return "ok", ""
    # unparsed (truncated line)
    if RE_CONFIRM.search(res_txt):
        return "blocked", "confirmation required"
    if RE_FAIL.search(res_txt):
        head = res_txt[:600]
        return ("blocked" if RE_ACL.search(head) else "failed"), _clip(res_txt, 600)
    return "ok", ""


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


def parse_journal(rows: list[dict], lane: str, pending: dict,
                  session_filter: str = "") -> tuple[list[dict], dict]:
    """journald rows -> (resolved events, updated pending map).

    pending: {event_key: {lane,sid,cid,tool,ts,args}} — calls seen
    `received` but not yet `result`ed. Persisted in the state file so a
    restart of THIS script doesn't lose in-flight calls; a call still
    pending past PENDING_GRACE_S is emitted as status=blocked."""
    events = []
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
        if m and TOOL_RE.match(m.group("name")):
            key = f"{lane}|{sid}|{m.group('cid')}"
            pending[key] = {
                "lane": lane, "sid": sid, "cid": m.group("cid"),
                "tool": m.group("name"), "ts": row["ts_epoch"],
                "args": _literal(m.group("args")) or {}}
            continue
        m = RE_RES.match(line)
        if m:
            key = f"{lane}|{sid}|{m.group('cid')}"
            rec = pending.pop(key, None)
            if rec is None:
                continue  # not an allowlisted tool (or pre-cursor)
            res_txt = "result=" + m.group("res")
            res = _literal(m.group("res"))
            status, err = classify_status(res_txt, res)
            args = rec.get("args") or {}
            events.append({
                "lane": lane, "session_id": sid, "call_id": m.group("cid"),
                "tool": rec["tool"], "status": status,
                "occurred_at": rec["ts"],
                "ended_at": row["ts_epoch"],
                "duration_s": _find_field(res, ("duration_s", "elapsed_s",
                                              "render_s", "secs"))
                              or (f"{row['ts_epoch'] - rec['ts']:.1f}"
                                  if row["ts_epoch"] > rec["ts"] else ""),
                "model": _find_field(res, ("model", "model_file"))
                         or _find_field(args, ("model",)),
                "cost_usd": _find_field(res, ("cost_usd", "est_cost_usd",
                                            "cost")),
                "artifact_url": _find_artifact(res),
                "ref_url": _find_field(res, ("ref_url", "ref"))
                           or _find_field(args, ("ref_url", "ref")),
                "prompt_excerpt": _find_prompt(args),
                "chat_id": _find_field(args, ("chat_id", "to"))
                           or _find_field(res, ("chat_id",)),
                "error": err,
            })
    return events, pending


def flush_stale_pending(pending: dict, now: float) -> tuple[list[dict], dict]:
    """Calls still pending past PENDING_GRACE_S -> blocked events."""
    events, keep = [], {}
    for key, rec in pending.items():
        if now - rec["ts"] > PENDING_GRACE_S:
            events.append({
                "lane": rec["lane"], "session_id": rec["sid"],
                "call_id": rec["cid"], "tool": rec["tool"],
                "status": "blocked", "occurred_at": rec["ts"],
                "ended_at": "", "duration_s": "",
                "model": _find_field(rec.get("args"), ("model",)),
                "cost_usd": "", "artifact_url": "", "ref_url": "",
                "prompt_excerpt": _find_prompt(rec.get("args")),
                "chat_id": _find_field(rec.get("args"), ("chat_id", "to")),
                "error": "no result logged — call killed/refused mid-turn",
            })
        else:
            keep[key] = rec
    return events, keep


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
            f"/wp/v2/activity&slug={slug}&status=private,archived"
            f"&per_page=1")
        if s != 200:
            s, r = self.api(
                f"/wp/v2/activity&slug={slug}&status=private&per_page=1")
        if s == 200 and isinstance(r, list) and r:
            return r[0]["id"]
        return 0

    def create(self, post: dict):
        return self.api("/wp/v2/activity", post)

    def update(self, post_id: int, post: dict):
        return self.api(f"/wp/v2/activity&{post_id}", post)


# --- assembly ----------------------------------------------------------------

SESS_RANK = {"ok": 0, "blocked": 1, "failed": 2}


def event_slug(e: dict) -> str:
    key = "|".join((e["lane"], e["session_id"], e["call_id"]))
    return "act-" + hashlib.md5(key.encode()).hexdigest()[:16]


def session_slug(lane: str, sid: str) -> str:
    return f"act-s-{lane}-{sid or 'none'}"


def event_title(e: dict) -> str:
    day = datetime.fromtimestamp(
        e["occurred_at"], timezone.utc).strftime("%Y-%m-%d")
    return f"Activity — {e['tool']} {e['lane']} {day}"


def event_content(e: dict) -> str:
    ts = datetime.fromtimestamp(
        e["occurred_at"], timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        f"**{e['tool']}** on lane `{e['lane']}` at {ts} — {e['status']}",
        "",
        f"- session: `{e['session_id'] or '?'}`",
        f"- event_id: `{e['event_id']}`",
    ]
    if e.get("artifact_url"):
        lines.append(f"- artifact: {e['artifact_url']}")
    if e.get("error"):
        lines += ["", "Error:", "", "> " + e["error"].replace("\n", "\n> ")]
    return "\n".join(lines)


def ensure_session_parent(wp: WP, lane: str, sid: str,
                          dry_run: bool) -> int:
    """Upsert the kind=session parent post; returns post id (0 = none)."""
    slug = session_slug(lane, sid)
    pid = 0 if dry_run else wp.slug_lookup(slug)
    if pid:
        return pid
    body = {
        "title": f"Activity — session {sid or '?'} {lane}",
        "slug": slug, "status": "private",
        "content": (f"Tool executions for {lane} session `{sid or '?'}` "
                    "— one child per call."),
        "meta": {"kind": "session", "lane": lane, "session_id": sid,
                 "status": "ok"},
    }
    if dry_run:
        print(f"  [dry] parent {slug}")
        return 0
    s, r = wp.create(body)
    if s in (200, 201):
        return int(r.get("id") or 0)
    print(f"  FAIL parent {slug} http {s} {json.dumps(r)[:160]}",
          file=sys.stderr)
    return 0


def post_events(wp: WP, events: list[dict], dry_run: bool) -> tuple[int, int]:
    """(created, failed) — skips existing slugs; updates parent status."""
    created = failed = 0
    parents: dict[str, int] = {}
    worst: dict[str, str] = {}
    for e in events[:MAX_POSTS_PER_RUN]:
        slug = event_slug(e)
        skey = session_slug(e["lane"], e["session_id"])
        worst[skey] = max((worst.get(skey, "ok"), e["status"]),
                          key=lambda s: SESS_RANK.get(s, 0))
        if dry_run:
            print(f"  [dry] {slug} {event_title(e)} — {e['status']} "
                  f"{_clip(e.get('error') or e.get('artifact_url') or '', 80)}")
            continue
        if wp.slug_lookup(slug):
            continue
        if skey not in parents:
            parents[skey] = ensure_session_parent(
                wp, e["lane"], e["session_id"], dry_run)
        body = {
            "title": event_title(e), "slug": slug, "status": "private",
            "parent": parents.get(skey) or 0,
            "content": event_content(e),
            "meta": {
                "kind": "tool", "tool": e["tool"], "lane": e["lane"],
                "status": e["status"], "model": e.get("model", ""),
                "cost_usd": e.get("cost_usd", ""),
                "artifact_url": e.get("artifact_url", ""),
                "ref_url": e.get("ref_url", ""),
                "prompt_excerpt": e.get("prompt_excerpt", ""),
                "session_id": e["session_id"],
                "chat_id": e.get("chat_id", ""),
                "duration_s": e.get("duration_s", ""),
                "event_id": e["event_id"],
                "occurred_at": datetime.fromtimestamp(
                    e["occurred_at"], timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "error": e.get("error", ""),
            }}
        s, r = wp.create(body)
        if s in (200, 201):
            created += 1
            print(f"  posted #{r.get('id')} {event_title(e)} [{e['status']}]")
        else:
            failed += 1
            print(f"  FAIL {slug} http {s} "
                  f"{json.dumps(r)[:160]}", file=sys.stderr)
    # parent status = worst child seen (escalate only, never downgrade)
    if not dry_run:
        for skey, want in worst.items():
            pid = parents.get(skey)
            if pid and want != "ok":
                wp.update(pid, {"meta": {"status": want}})
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
2026-10-23 09:00:01,000 INFO voice.provider: session=ab12cd34ef function_call received id=call_1 name=ada_render_image args={'prompt': 'a cat on the beach', 'model': 'sdxl'}
2026-10-23 09:00:05,000 INFO voice.provider: session=ab12cd34ef function_call result id=call_1 name=ada_render_image result={'ok': True, 'url': 'https://ada.surf-thailand.com/relay-img/arch/cat.png', 'duration_s': 4.0, 'model': 'sdxl'}
2026-10-23 09:01:00,000 INFO voice.provider: session=ab12cd34ef function_call received id=call_2 name=ada_render_video args={'prompt': 'cat jumps', 'secs': 4}
2026-10-23 09:01:20,000 INFO voice.provider: session=ab12cd34ef function_call result id=call_2 name=ada_render_video result={'ok': False, 'error': 'quota_exhausted'}
2026-10-23 09:02:00,000 INFO voice.provider: session=ab12cd34ef function_call received id=call_3 name=web_search args={'query': 'ignore me'}
2026-10-23 09:02:05,000 INFO voice.provider: session=ab12cd34ef function_call result id=call_3 name=web_search result={'ok': True, 'hits': 3}
2026-10-23 09:03:00,000 INFO voice.provider: session=ab12cd34ef function_call received id=call_4 name=page_snapshot args={'url': 'https://example.com'}
"""


def selftest() -> int:
    now = datetime.now(timezone.utc).timestamp()
    rows = []
    for i, ln in enumerate(SELFTEST_JOURNAL.splitlines()):
        # replay fixture lines as "recent" (call_4 stays pending -> blocked
        # only after grace; here we force it stale by backdating)
        rows.append({"ts_epoch": now - 1000 + i, "line": ln})
    pending = {}
    events, pending = parse_journal(rows, "tony", pending)
    assert len(events) == 2, f"want 2 resolved, got {len(events)}"
    ok, fail = events
    assert ok["status"] == "ok" and ok["artifact_url"].endswith("cat.png"), ok
    assert ok["tool"] == "ada_render_image" and ok["duration_s"] == "4.0", ok
    assert fail["status"] == "failed" and "quota" in fail["error"], fail
    assert "tony|ab12cd34ef|call_3" not in pending  # web_search not allowlisted
    assert "tony|ab12cd34ef|call_4" in pending      # snapshot pending
    # backdate the pending call past the grace window -> blocked event
    pending["tony|ab12cd34ef|call_4"]["ts"] = now - PENDING_GRACE_S - 1
    stale, pending = flush_stale_pending(pending, now)
    assert len(stale) == 1 and stale[0]["status"] == "blocked", stale
    assert not pending
    e = ok
    e["event_id"] = f"{e['lane']}:{e['session_id']}:{e['call_id']}"
    print("selftest ok:", event_slug(e), "|", event_title(e))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since", default="")
    ap.add_argument("--session", default="")
    ap.add_argument("--lane", default="")
    ap.add_argument("--journal-file", default="",
                    help="read journal lines from a file instead of journalctl")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    now = datetime.now(timezone.utc).timestamp()
    st = load_state()
    pending = st.get("pending", {})

    if a.since:
        since = parse_since(a.since)
    else:
        since = float(st.get("since") or (now - FIRST_RUN_S)) - J_OVERLAP_S
    since = max(since, now - WINDOW_CAP_S)

    wp = None
    if not a.dry_run:
        wp = WP(load_wp_env(ENV_PATH))

    total_created = total_failed = 0
    all_events = []
    lanes = LANES if not a.journal_file else {
        (a.lane or "tony"): LANES.get(a.lane or "tony", {})}
    for lane, cfg in lanes.items():
        if a.lane and lane != a.lane:
            continue
        if a.journal_file:
            rows = [{"ts_epoch": now, "line": ln}
                    for ln in open(a.journal_file).read().splitlines() if ln]
        else:
            rows = fetch_journal(cfg["unit"], since)
        if not rows:
            continue
        ev, pending = parse_journal(rows, lane, pending, a.session)
        all_events.extend(ev)

    stale, pending = flush_stale_pending(pending, now)
    all_events.extend(stale)
    all_events.sort(key=lambda e: e["occurred_at"])
    for e in all_events:
        e["event_id"] = f"{e['lane']}:{e['session_id']}:{e['call_id']}"

    if all_events:
        c, f = post_events(wp, all_events, a.dry_run)
        total_created += c
        total_failed += f
    print(f"activity-posts: scanned since {int(since)}, "
          f"events={len(all_events)} posted={total_created} "
          f"failed={total_failed} pending={len(pending)}")

    if not a.dry_run:
        save_state({"since": now, "pending": pending})
    return 1 if total_failed else 0


if __name__ == "__main__":
    sys.exit(main())
