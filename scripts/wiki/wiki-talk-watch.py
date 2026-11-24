#!/usr/bin/env python3
"""wiki-talk-watch — auto-reply loop for MediaWiki talk pages.

Polls Special:RecentChanges on wiki.surf-thailand.com for edits/new pages
in every talk namespace, classifies each candidate comment through the
LiteLLM gateway (JevTeam stand-in, card
wiki-talk-watch-auto-reply-to-wiki-talk-a9f107), drafts a reply via
opencode headless (LiteLLM generateContent fallback when opencode is
absent), and posts it as a new signed section through the Ada bot
credentials.

Watermark = max rcid handled, stored in
~/.local/state/wiki-talk-watch/last-rcid (timestamp mirror in
state.json). rcend=<watermark-ts> bounds the poll server-side; the
rcid > watermark filter makes reruns idempotent. Per-rcid outcomes are
recorded in state.json BEFORE the watermark advances, so a crash
mid-run resumes without double-posting and without blind retries —
failed candidates are flagged to the focus inbox instead.

Visibility guard: talk namespaces 3001/3003/3005/3007 (Infrastructure,
PrivateNews, Education, Reports talk) are Lockdown-protected 'inhouse'
surfaces — replies there may carry members-level detail. Every other
polled talk namespace is public: drafts are constrained to public-safe
content and leak-scanned (tailnet IPs, ts.net names, internal
hostnames, secret-shaped strings) before posting.

Usage:
  wiki-talk-watch.py              # one poll->reply pass
  wiki-talk-watch.py --dry-run    # print candidates, write nothing
  wiki-talk-watch.py --seed       # set watermark to newest rcid, exit
  wiki-talk-watch.py --max N      # cap candidates examined this run
  wiki-talk-watch.py --json       # machine-readable summary on stdout
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from http.cookiejar import CookieJar
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# --- config -----------------------------------------------------------------

WIKI_ENV_FILE = Path(os.environ.get(
    "WIKI_TALK_ENV",
    str(Path.home() / ".config/secrets/wiki-h3-gizmo.env")))
STATE_DIR = Path(os.environ.get(
    "WIKI_TALK_STATE",
    str(Path.home() / ".local/state/wiki-talk-watch")))
LAST_RCID = STATE_DIR / "last-rcid"
STATE_JSON = STATE_DIR / "state.json"
RUNS_DIR = STATE_DIR / "runs"

# Spec poll set: every talk namespace on the wiki (Form talk 107 excluded
# per card spec; custom 3001/3003/3005/3007 verified live 2026-11-24).
TALK_NAMESPACES = "1|3|5|7|9|11|13|15|3001|3003|3005|3007"
MEMBERS_TALK_NS = {3001, 3003, 3005, 3007}   # inhouse-locked namespaces
RCLIMIT = 50
MAX_CANDIDATES = int(os.environ.get("WIKI_TALK_MAX_CANDIDATES", "8"))
MAX_REPLIES = int(os.environ.get("WIKI_TALK_MAX_REPLIES", "5"))
COMMENT_CAP = 4000          # chars fed to the classifier
DRAFT_CAP = 8000            # chars fed to the drafter
REPLY_CAP = 6000            # chars allowed in a posted reply body
ALERT_REPEAT_H = 24.0
ALERT_MIN_INTERVAL_S = 3600  # hard floor between /inbox posts per slug

CLASSIFY_MODEL = os.environ.get(
    "WIKI_TALK_CLASSIFY_MODEL", "gemini-3.5-flash-lite")
DRAFT_OPENCODE_MODEL = os.environ.get(
    "WIKI_TALK_DRAFT_MODEL", "litellm/gemini-3.5-flash-lite")
DRAFT_LITELLM_MODEL = os.environ.get(
    "WIKI_TALK_DRAFT_LLM_MODEL", "gemini-3.5-flash-lite")
OPENCODE_TIMEOUT = int(os.environ.get("WIKI_TALK_OPENCODE_TIMEOUT", "300"))

BOARD_API = os.environ.get(
    "WIKI_TALK_BOARD_API",
    "https://idc03.taila0626a.ts.net:10000").rstrip("/")

# Own-bot + noise filters. The bot account comes from the env file
# (WIKI_USER=ada on idc03); extra users can be skipped via
# WIKI_TALK_SKIP_USERS="User One,User Two".
SKIP_USERS = {u.strip().lower() for u in os.environ.get(
    "WIKI_TALK_SKIP_USERS", "").split(",") if u.strip()}

# Public-surface leak guard — patterns that must never appear in a reply
# posted to a public talk page. Deliberately narrow: infra hostnames,
# tailnet addresses, and secret-shaped strings.
LEAK_PATTERNS = [
    re.compile(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"[a-z0-9-]+\.ts\.net\b", re.I),
    re.compile(r"\b(idc0[0-9]|tony-dell|tony-omen|tony-macbook|mn01|"
               r"michael-ha|kk-mac\w*|taila0626a)\b", re.I),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{10,}|LITELLM_KEY|WIKI_PASSWORD|"
               r"api[_-]?key|bearer\s+\S+)", re.I),
]


# --- small helpers ----------------------------------------------------------

def _load_env_file(p: Path) -> dict:
    env = {}
    try:
        for ln in p.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _secret_env_names() -> list[Path]:
    home = Path.home() / ".config/secrets"
    return [home / n for n in (
        "litellm-keys.env", "litellm-chaba.env", "mddb-gemini.env")]


def litellm_creds() -> tuple[str | None, str | None]:
    """(base_url, key) for the LiteLLM gateway — env first, then the
    chaba secret files. base_url is normalized to the bare host (the
    gemini native endpoint appends /v1beta itself)."""
    url = os.environ.get("WIKI_TALK_LITELLM_URL") \
        or os.environ.get("LITELLM_URL")
    key = os.environ.get("WIKI_TALK_LITELLM_KEY") \
        or os.environ.get("LITELLM_KEY")
    if not url or not key:
        merged = {}
        for p in _secret_env_names():
            merged.update(_load_env_file(p))
        # prefer the dedicated chaba key, then the shared gateway key
        if not key:
            for var in ("LITELLM_KEY_WIKI_TALK", "LITELLM_KEY_CHABA",
                        "LITELLM_KEY_MDDB", "LITELLM_KEY"):
                if merged.get(var):
                    key = merged[var]
                    break
        url = url or merged.get("LITELLM_URL")
    if not url:
        url = "http://100.102.134.91:4000"   # ssot.llm-gateway.yml base
    url = url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url or None, key or None


def _gemini_mod():
    """Import scripts/ada/gemini_rest.py from this checkout — the same
    gateway caller board-api's /lesson Thai translation uses."""
    spec = importlib.util.spec_from_file_location(
        "gemini_rest", REPO / "scripts/ada/gemini_rest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- wiki client ------------------------------------------------------------

def wiki_env() -> tuple[dict, str]:
    """(env, api_url) — same normalization as board-api._wiki_env."""
    env = _load_env_file(WIKI_ENV_FILE)
    host = env.get("WIKI_HOST", "").rstrip("/")
    if host.endswith("/v0"):
        host = host[:-3]
    api = (env.get("WIKI_API_URL")
           or f"{host}/api.php").rstrip("/")
    if not host or not env.get("WIKI_USER") or not env.get("WIKI_PASSWORD"):
        raise RuntimeError("wiki credentials unavailable "
                           f"({WIKI_ENV_FILE})")
    return env, api


def wiki_call(api: str, opener, params: dict, post: bool = False,
              timeout: int = 30) -> dict:
    data = urllib.parse.urlencode(params).encode() if post else None
    url = api if post else api + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": "chaba-wiki-talk-watch/0.1"})
    try:
        return json.loads(opener.open(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise RuntimeError(f"mediawiki -> {e.code}: {detail}")
    except OSError as e:
        raise RuntimeError(f"mediawiki -> {e}")


def anon_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))


def wiki_login(api: str, env: dict, opener=None):
    """Bot-password login -> (opener, csrf_token). Mirrors
    board-api._wiki_login."""
    opener = opener or anon_opener()
    login = wiki_call(api, opener,
                      {"action": "query", "meta": "tokens",
                       "type": "login", "format": "json"})
    lt = login["query"]["tokens"]["logintoken"]
    logged = wiki_call(api, opener,
                       {"action": "login", "lgname": env["WIKI_USER"],
                        "lgpassword": env["WIKI_PASSWORD"],
                        "lgtoken": lt, "format": "json"}, post=True)
    if logged.get("login", {}).get("result") != "Success":
        raise RuntimeError("mediawiki login failed")
    csrf = wiki_call(api, opener,
                     {"action": "query", "meta": "tokens",
                      "format": "json"})["query"]["tokens"]["csrftoken"]
    return opener, csrf


def recent_changes(api: str, opener, since_ts: str | None) -> list[dict]:
    """Talk-namespace recent changes newer than since_ts (rcend is the
    enumeration floor — results are newest-first, bounded by rclimit)."""
    params = {
        "action": "query", "list": "recentchanges",
        "rctype": "edit|new",
        "rcnamespace": TALK_NAMESPACES,
        "rcprop": "title|ids|timestamp|comment|user|flags",
        "rclimit": str(RCLIMIT), "format": "json",
    }
    if since_ts:
        params["rcend"] = since_ts
    res = wiki_call(api, opener, params)
    return res.get("query", {}).get("recentchanges", [])


def revision_text(api: str, opener, revid: int) -> str:
    res = wiki_call(api, opener,
                    {"action": "query", "prop": "revisions",
                     "revids": str(revid), "rvprop": "content",
                     "rvslots": "main", "format": "json"})
    for page in res.get("query", {}).get("pages", {}).values():
        for rev in page.get("revisions", []):
            return str(rev.get("slots", {})
                       .get("main", {}).get("*", "") or "")
    return ""


def added_text(api: str, opener, rc: dict) -> str:
    """The comment payload of a talk-page change.

    type=new  -> the page's whole wikitext is the first comment.
    type=edit -> diff old_revid -> revid and keep the '+' lines; that is
                 the new section/comment the editor appended.
    Falls back to the rc comment (edit summary) when the diff is empty —
    some clients put the comment text in the summary.
    """
    title, rtype = rc.get("title", ""), rc.get("type", "")
    new_id = int(rc.get("revid") or 0)
    old_id = int(rc.get("old_revid") or 0)
    if not new_id:
        return ""
    try:
        if rtype == "new" or not old_id:
            return revision_text(api, opener, new_id)
        new_wt = revision_text(api, opener, new_id)
        old_wt = revision_text(api, opener, old_id)
        if not new_wt:
            return ""
        added = []
        for line in difflib.unified_diff(
                old_wt.splitlines(), new_wt.splitlines(), lineterm=""):
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])
        return "\n".join(added).strip()
    except Exception:
        return ""


def visibility_of(ns: int) -> str:
    return "members" if int(ns) in MEMBERS_TALK_NS else "public"


# --- classify (LiteLLM stand-in for JevTeam) ---------------------------------

def classify(rc: dict, comment: str) -> dict | None:
    """One gateway call -> {"respond": bool, "lane": str, "reason": str}.
    None on any failure (caller treats as no-response + counts it)."""
    mod = _gemini_mod()
    base, key = litellm_creds()
    if not (base and key):
        return None
    ns = int(rc.get("ns") or 0)
    prompt = (
        "You are the routing classifier for a wiki talk-page auto-responder "
        "(Chaba home-infrastructure wiki). Decide whether the agent fleet "
        "should post a reply to this talk-page comment.\n\n"
        f"Page: {rc.get('title')}\n"
        f"Talk namespace: {ns} "
        f"({'members-only (inhouse)' if ns in MEMBERS_TALK_NS else 'public'})\n"
        f"Author: {rc.get('user')}\n"
        f"Edit summary: {rc.get('comment') or '(none)'}\n\n"
        "Comment text:\n" + comment[:COMMENT_CAP] + "\n\n"
        "Rules:\n"
        "- respond=true only for a genuine question, request, or comment "
        "addressed to the wiki community or the agent fleet that a reply "
        "would help.\n"
        "- respond=false for thanks/acknowledgements, spam, bot noise, "
        "content that is not a question, edits with no conversational "
        "payload, or anything already answered on the page.\n"
        "- When respond=true the only lane is \"ada-code\" (v1 single "
        "executor lane). Otherwise lane is \"no-response\".\n"
        "- Output JSON only: "
        '{"respond": true|false, "lane": "ada-code"|"no-response", '
        '"reason": "<=20 words"}')
    try:
        out = mod.generate_json(
            prompt, CLASSIFY_MODEL, key=key, base_url_override=base,
            timeout=60, max_attempts=2, label="wiki-talk-watch-classify",
            tags="service=wiki-talk-watch,job=talk-classify,route=gemini")
    except Exception:
        return None
    if not isinstance(out, dict):
        return None
    respond = bool(out.get("respond"))
    lane = str(out.get("lane") or "")
    if respond and lane != "ada-code":
        lane = "ada-code"
    if not respond:
        lane = "no-response"
    return {"respond": respond, "lane": lane,
            "reason": str(out.get("reason") or "")[:200]}


# --- draft (opencode headless, LiteLLM fallback) -----------------------------

def _opencode_bin() -> str | None:
    """Resolve opencode — $OPENCODE_BIN, PATH, then the two known
    install locations (same contract as runner-agent.opencode_bin)."""
    cand = os.environ.get("OPENCODE_BIN")
    if cand and Path(cand).exists():
        return cand
    hit = shutil.which("opencode")
    if hit:
        return hit
    for c in (Path.home() / ".opencode/bin/opencode",
              Path.home() / ".local/bin/opencode"):
        if c.exists():
            return str(c)
    return None


def _opencode_is_v2(oc: str) -> bool:
    try:
        r = subprocess.run([oc, "--version"],
                           capture_output=True, text=True, timeout=15)
        m = re.search(r"(\d+)\.", r.stdout or "")
        return bool(m and int(m.group(1)) >= 2)
    except Exception:
        return False


def draft_prompt(rc: dict, comment: str, vis: str) -> str:
    ns = int(rc.get("ns") or 0)
    scope = (
        "This talk page is MEMBERS-ONLY (inhouse). Internal Chaba/"
        "infrastructure context is allowed in the reply; you may read "
        f"the ops repo at {REPO} for facts if needed."
        if vis == "members" else
        "This talk page is PUBLIC — visible to anonymous visitors. Do NOT "
        "include internal infrastructure details: no hostnames, IPs, "
        "tailnet names, card IDs, credentials, secrets, or "
        "PrivateNews/Infrastructure content. If the question needs "
        "internal knowledge, say it belongs in the members space. Work "
        "only from the information given; do not read local files or "
        "repos.")
    return (
        "You are Ada, the assistant behind the Chaba home-infrastructure "
        "wiki. A visitor commented on a wiki talk page. Draft a reply.\n\n"
        f"Page: {rc.get('title')} (talk namespace {ns})\n"
        f"Comment by {rc.get('user')} at {rc.get('timestamp')}:\n"
        + comment[:DRAFT_CAP] + "\n\n" + scope + "\n\n"
        "Rules:\n"
        "- Answer the comment directly; concise (<=200 words), valid "
        "wikitext.\n"
        "- Do not claim you checked systems, logs, or telemetry — you "
        "only see the comment; answer from it and the given context.\n"
        "- Match the comment's language (English or Thai).\n"
        "- Do not promise actions you cannot take.\n"
        "- Output ONLY the reply wikitext — no preamble, no signature "
        "(one is appended automatically).")


def _parse_opencode_text(stdout: str) -> str:
    """Last part.type==text payload from `opencode run --format json`."""
    text = ""
    for line in (stdout or "").splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        part = ev.get("part") or {}
        if part.get("type") == "text" and part.get("text"):
            text = part["text"]
    return text.strip()


def draft_via_opencode(prompt: str, run_dir: Path) -> str | None:
    oc = _opencode_bin()
    if not oc:
        return None
    run_dir.mkdir(parents=True, exist_ok=True)
    pack = run_dir / "prompt.md"
    pack.write_text(prompt)
    cmd = [oc, "run", "--format", "json", "--archived",
           "--model", DRAFT_OPENCODE_MODEL,
           "--title", "wiki talk reply",
           "-f", str(pack),
           "Draft the wiki talk-page reply described in the attached "
           "prompt file."]
    if _opencode_is_v2(oc):
        cmd.insert(2, "--standalone")
    env = dict(os.environ)
    if DRAFT_OPENCODE_MODEL.startswith("litellm/") and not env.get("LITELLM_KEY"):
        for p in _secret_env_names():
            k = _load_env_file(p).get("LITELLM_KEY")
            if k:
                env["LITELLM_KEY"] = k
                break
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=OPENCODE_TIMEOUT, env=env,
                           cwd=str(run_dir))
    except Exception:
        return None
    (run_dir / "events.jsonl").write_text(r.stdout or "")
    (run_dir / "stderr.log").write_text(r.stderr or "")
    (run_dir / "run.log").write_text(
        f"cmd: {' '.join(cmd)}\nrc: {r.returncode}\n")
    if r.returncode != 0:
        return None
    text = _parse_opencode_text(r.stdout or "")
    # strip markdown fences / code wrappers the model may add
    text = re.sub(r"^```(?:wikitext|wiki|text)?\s*|\s*```$", "",
                  text.strip())
    return text.strip() or None


def draft_via_litellm(prompt: str) -> str | None:
    mod = _gemini_mod()
    base, key = litellm_creds()
    if not (base and key):
        return None
    try:
        return mod.generate(
            prompt, DRAFT_LITELLM_MODEL, key=key,
            base_url_override=base, timeout=90, max_attempts=2,
            label="wiki-talk-watch-draft",
            tags="service=wiki-talk-watch,job=talk-draft,route=gemini")
    except Exception:
        return None


def draft_reply(rc: dict, comment: str, vis: str,
                run_dir: Path) -> tuple[str | None, str]:
    """-> (body, drafter). opencode first; LiteLLM gateway fallback."""
    prompt = draft_prompt(rc, comment, vis)
    body = draft_via_opencode(prompt, run_dir)
    if body:
        return body, "opencode"
    body = draft_via_litellm(prompt)
    if body:
        return body, "litellm"
    return None, "none"


# --- post --------------------------------------------------------------------

def post_reply(api: str, opener, csrf: str, title: str, body: str,
               lane: str) -> dict:
    text = body.strip()[:REPLY_CAP]
    wikitext = f"{text}\n\n— Ada ({lane}) ~~~~~"
    res = wiki_call(api, opener,
                    {"action": "edit", "title": title,
                     "section": "new", "sectiontitle": "Ada reply",
                     "appendtext": wikitext,
                     "summary": f"wiki-talk-watch reply ({lane})",
                     "token": csrf, "format": "json"}, post=True)
    edited = res.get("edit", {})
    if edited.get("result") not in ("Success", "Nochange"):
        err = res.get("error") or edited or res
        raise RuntimeError(
            "mediawiki edit failed: " + str(err)[:300])
    return {"revid": edited.get("newrevid"),
            "result": edited.get("result", "").lower()}


def leak_hits(text: str) -> list[str]:
    return [p.pattern for p in LEAK_PATTERNS if p.search(text or "")]


# --- state + alerts -----------------------------------------------------------

def load_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def save_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    tmp.replace(p)


def load_state() -> dict:
    st = load_json(STATE_JSON, {})
    st.setdefault("done", {})
    st.setdefault("alerts", {})
    st.setdefault("stats", {})
    return st


def save_state(st: dict) -> None:
    # bound the done/alerts maps — this is a long-lived timer state file
    for key, cap in (("done", 1000), ("alerts", 200)):
        m = st.get(key) or {}
        if len(m) > cap:
            for k in sorted(m, key=lambda k: str(m[k]))[:len(m) - cap]:
                m.pop(k, None)
    save_json(STATE_JSON, st)


def read_watermark() -> tuple[int, str | None]:
    """(rcid, iso-timestamp). rcid from last-rcid per spec; the ts mirror
    lives in state.json so rcend can bound the server-side scan."""
    rcid = 0
    try:
        rcid = int(LAST_RCID.read_text().strip())
    except Exception:
        pass
    ts = (load_json(STATE_JSON, {}).get("watermark") or {}).get("ts")
    return rcid, ts


def write_watermark(rcid: int, ts: str | None) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RCID.write_text(str(rcid) + "\n")
    st = load_state()
    st["watermark"] = {"rcid": rcid, "ts": ts,
                       "at": datetime.now(timezone.utc).isoformat()}
    save_state(st)


def mark_done(st: dict, rcid: int, result: str) -> None:
    st["done"][str(rcid)] = {"result": result,
                            "at": datetime.now(timezone.utc)
                            .isoformat(timespec="seconds")}
    save_state(st)


def file_alert(st: dict, slug: str, text: str,
               priority: str = "medium") -> bool:
    """Deduped board-api /inbox flag — one open alert per slug per
    ALERT_REPEAT_H, hard floor ALERT_MIN_INTERVAL_S."""
    alerts = st.setdefault("alerts", {})
    now = datetime.now(timezone.utc)
    last = alerts.get(slug)
    if last:
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
            if age < ALERT_MIN_INTERVAL_S:
                return False
            if age < ALERT_REPEAT_H * 3600:
                return False
        except Exception:
            pass
    body = {"text": text[:4000],
            "label": f"wiki-talk-watch: {slug}",
            "priority": priority,
            "tags": ["wiki", "talk-watch", slug.split("-")[-1]],
            "owner": "tony"}
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/inbox", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            if 200 <= r.status < 300:
                alerts[slug] = now.isoformat()
                save_state(st)
                return True
    except Exception as e:
        print(f"alert post failed ({slug}): {e}", file=sys.stderr)
    return False


# --- main ---------------------------------------------------------------------

def collect_candidates(rcs: list[dict], watermark: int,
                       bot_user: str) -> list[dict]:
    out = []
    for rc in rcs:
        try:
            rcid = int(rc.get("rcid") or 0)
        except (TypeError, ValueError):
            continue
        if rcid <= watermark:
            continue
        user = str(rc.get("user") or "")
        if user.lower() in SKIP_USERS or user.lower() == bot_user:
            continue
        flags = str(rc.get("flags") or "")
        if "minor" in flags:
            continue
        out.append(rc)
    out.sort(key=lambda r: int(r.get("rcid") or 0))
    return out


def run(dry_run: bool, max_candidates: int, seed: bool,
        as_json: bool) -> int:
    env, api = wiki_env()
    # WIKI_TALK_SELF_USER overrides the own-bot filter — set to "" to
    # process the bot's own comments (sandbox testing).
    bot_user = (os.environ["WIKI_TALK_SELF_USER"].lower()
                if "WIKI_TALK_SELF_USER" in os.environ
                else str(env.get("WIKI_USER") or "").lower())
    opener = anon_opener()
    # log in once — protected talk namespaces need the session for
    # revision content and for posting; polling itself is anon-safe.
    try:
        opener, csrf = wiki_login(api, env, opener)
    except Exception as e:
        if not dry_run:
            st = load_state()
            file_alert(st, "login-error",
                       f"wiki bot login failed: {e}", "high")
        print(f"login failed: {e}", file=sys.stderr)
        return 2

    watermark, watermark_ts = read_watermark()
    rcs = recent_changes(api, opener, watermark_ts)
    max_rcid = max((int(r.get("rcid") or 0) for r in rcs), default=0)

    if seed:
        if max_rcid:
            # find the ts belonging to the newest rcid for the rcend bound
            ts = next((r.get("timestamp") for r in rcs
                       if int(r.get("rcid") or 0) == max_rcid), None)
            write_watermark(max_rcid, ts)
        print(f"seeded watermark={max_rcid}")
        return 0

    if not LAST_RCID.exists() and not dry_run and max_rcid:
        # first live run: seed to newest and process nothing — replying
        # to the entire historical backlog would be noise. Existence of
        # the file (not watermark>0) is the seeded check: a wiki with
        # zero changes still counts as seeded.
        ts = next((r.get("timestamp") for r in rcs
                   if int(r.get("rcid") or 0) == max_rcid), None)
        write_watermark(max_rcid, ts)
        print(f"first run — seeded watermark={max_rcid}, "
              "no backlog processed")
        return 0

    candidates = collect_candidates(rcs, watermark, bot_user)
    if len(candidates) > max_candidates:
        candidates = candidates[:max_candidates]

    st = load_state()
    results = []
    examined = replies = 0
    new_watermark, new_watermark_ts = watermark, watermark_ts

    for rc in candidates:
        rcid = int(rc.get("rcid") or 0)
        if str(rcid) in st["done"]:
            new_watermark = max(new_watermark, rcid)
            continue
        examined += 1
        ns = int(rc.get("ns") or 0)
        vis = visibility_of(ns)
        comment = added_text(api, opener, rc)
        if not comment.strip():
            comment = str(rc.get("comment") or "")
        rec = {"rcid": rcid, "ns": ns, "title": rc.get("title"),
               "user": rc.get("user"), "type": rc.get("type"),
               "visibility": vis,
               "comment": comment[:300]}

        if dry_run:
            rec["action"] = "would-classify"
            results.append(rec)
            print(f"[dry] rcid={rcid} ns={ns} {vis} "
                  f"{rc.get('title')} by {rc.get('user')}: "
                  f"{comment[:120]!r}")
            new_watermark = max(new_watermark, rcid)
            new_watermark_ts = rc.get("timestamp") or new_watermark_ts
            continue

        verdict = classify(rc, comment)
        if verdict is None:
            st["stats"]["classify_errors"] = \
                st["stats"].get("classify_errors", 0) + 1
            # systemic classify failure — flag once, keep watermark so
            # the candidate is retried next tick (no blind same-run retry)
            file_alert(st, "classify-error",
                       "LiteLLM classify call failing for wiki talk "
                       "comments — check gateway/key", "high")
            results.append({**rec, "action": "classify-error"})
            break          # don't burn the run on a dead gateway
        rec["classify"] = verdict
        if not verdict["respond"] or verdict["lane"] != "ada-code":
            mark_done(st, rcid, f"skip:{verdict['lane']}")
            rec["action"] = f"skip:{verdict['lane']}"
            results.append(rec)
            new_watermark = max(new_watermark, rcid)
            new_watermark_ts = rc.get("timestamp") or new_watermark_ts
            continue
        if replies >= MAX_REPLIES:
            rec["action"] = "deferred"
            results.append(rec)
            break          # leave rcid > watermark for next tick

        run_dir = RUNS_DIR / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-rc{rcid}"
        body, drafter = draft_reply(rc, comment, vis, run_dir)
        if not body:
            mark_done(st, rcid, "draft-failed")
            file_alert(st, f"draft-failed-{slugify(rc.get('title') or '')}",
                       f"wiki-talk-watch could not draft a reply for "
                       f"{rc.get('title')} (rcid {rcid}) — opencode and "
                       "LiteLLM both failed; see "
                       f"{run_dir} / journal", "medium")
            rec["action"] = "draft-failed"
            results.append(rec)
            new_watermark = max(new_watermark, rcid)
            new_watermark_ts = rc.get("timestamp") or new_watermark_ts
            continue

        if vis == "public":
            hits = leak_hits(body)
            if hits:
                mark_done(st, rcid, "guard-blocked")
                file_alert(st, f"leak-guard-{slugify(rc.get('title') or '')}",
                           f"wiki-talk-watch BLOCKED a public-ns reply "
                           f"on {rc.get('title')} (rcid {rcid}) — draft "
                           f"tripped leak patterns {hits}. Draft kept "
                           f"at {run_dir}; review before reposting.",
                           "high")
                rec["action"] = "guard-blocked"
                results.append(rec)
                new_watermark = max(new_watermark, rcid)
                new_watermark_ts = rc.get("timestamp") or new_watermark_ts
                continue

        try:
            posted = post_reply(api, opener, csrf,
                                str(rc.get("title") or ""), body,
                                verdict["lane"])
            mark_done(st, rcid,
                      f"replied:{drafter}:rev{posted.get('revid')}")
            replies += 1
            rec["action"] = f"replied:{drafter}"
            rec["revid"] = posted.get("revid")
            print(f"replied {rc.get('title')} rcid={rcid} "
                  f"via {drafter} rev={posted.get('revid')}")
        except Exception as e:
            mark_done(st, rcid, "post-failed")
            file_alert(st, f"post-error-{slugify(rc.get('title') or '')}",
                       f"wiki-talk-watch failed to post reply on "
                       f"{rc.get('title')} (rcid {rcid}, ns {ns}): {e}. "
                       "No automatic retry — check bot rights on this "
                       "namespace.", "high")
            rec["action"] = f"post-failed:{str(e)[:120]}"
            print(f"post failed {rc.get('title')}: {e}", file=sys.stderr)
        results.append(rec)
        new_watermark = max(new_watermark, rcid)
        new_watermark_ts = rc.get("timestamp") or new_watermark_ts

    if not dry_run and new_watermark != watermark:
        write_watermark(new_watermark, new_watermark_ts)

    summary = {"watermark": new_watermark, "candidates": len(candidates),
               "examined": examined, "replies": replies,
               "results": results}
    if as_json:
        print(json.dumps(summary, indent=1, ensure_ascii=False))
    else:
        for r in results:
            print(f"rcid={r['rcid']} {r.get('action','?')} "
                  f"{r.get('title')} ({r.get('user')})")
        print(f"done: watermark={new_watermark} examined={examined} "
              f"replies={replies}")
    return 0


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "page"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print candidates, write nothing")
    ap.add_argument("--seed", action="store_true",
                    help="set watermark to newest rcid and exit")
    ap.add_argument("--max", type=int, default=MAX_CANDIDATES,
                    dest="max_candidates")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        return run(args.dry_run, args.max_candidates, args.seed,
                   args.json)
    except Exception as e:
        print(f"wiki-talk-watch failed: {e}", file=sys.stderr)
        if not args.dry_run:
            try:
                st = load_state()
                file_alert(st, "run-error",
                           f"wiki-talk-watch run crashed: {e}", "high")
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
