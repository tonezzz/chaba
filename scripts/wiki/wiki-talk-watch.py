#!/usr/bin/env python3
"""wiki-talk-watch — poll MediaWiki talk namespaces, classify new comments,
and post signed Ada replies (card wiki-talk-watch-auto-reply-to-wiki-talk-a9f107,
OPS-0074; supersedes the manual procedure on OPS-0073).

Loop per tick:
  1. Poll api.php list=recentchanges over the talk namespaces
     (1,3,5,7,9,11,13,15 public + 3001/3003 private + 3005/3007 members),
     bounded by the stored watermark (max rcid; its timestamp feeds rcend).
  2. For each new rcid (ascending): skip own-bot comments (user == the
     bot account), minor/bot-flagged and system edits; extract the added
     wikitext by diffing the change's revid against old_revid.
  3. Classify v1 (JevTeam stand-in): LiteLLM gemini-3.5-flash-lite via the
     gateway -> lane=ada-code | no-response.
  4. Draft the reply (opencode headless when available, else the same
     LiteLLM gateway) and POST action=edit — appendtext inside the
     commenter's own section, falling back to section=new.
  5. Visibility guard: the reply inherits the talk page's Lockdown
     boundary; the DRAFT is additionally scanned so protected content
     never lands on a more-public talk page.

State: ~/.local/state/wiki-talk-watch/{state.json,last-rcid} — watermark,
processed rcids, per-rcid attempt counts, alert conditions. Idempotent
reruns; flock guards overlapping timer ticks.

Failures file deduped focus-inbox entries via board-api /inbox
(system-report-watchdog pattern) — no blind retries: a candidate gets
MAX_ATTEMPTS tries, then it is flagged and marked processed.

Usage:
  wiki-talk-watch.py                # one poll+reply pass
  wiki-talk-watch.py --dry-run      # poll+extract+classify, print plan,
                                    # write nothing (no state/inbox/posts)
  wiki-talk-watch.py --self-test    # offline checks of pure helpers
  wiki-talk-watch.py --drafter litellm|opencode|auto   (default auto:
                                    # opencode when the binary resolves,
                                    # else litellm)
"""
from __future__ import annotations

import argparse
import fcntl
import difflib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from http.cookiejar import CookieJar
from pathlib import Path

try:
    REPO = Path(__file__).resolve().parents[2]
except IndexError:
    REPO = Path.home() / "CascadeProjects/chaba"
if not (REPO / "scripts/ada/gemini_rest.py").is_file():
    # script copied out-of-tree (manual run, /tmp test) — fall back to the
    # job-exec checkout so the LiteLLM helper still resolves
    alt = Path(os.environ.get(
        "CHABA_REPO", str(Path.home() / "CascadeProjects/chaba")))
    if (alt / "scripts/ada/gemini_rest.py").is_file():
        REPO = alt

# --- tunables ---------------------------------------------------------------
TALK_NAMESPACES = "1|3|5|7|9|11|13|15|3001|3003|3005|3007"
RCLIMIT = 50
MAX_PAGES = 5               # pagination safety bound per tick
MAX_CANDIDATES = 50         # rcids examined per tick (oldest first)
MAX_REPLIES = int(os.environ.get("WIKI_TALK_MAX_REPLIES", "5"))
MAX_ATTEMPTS = 3
REPEAT_ALERT_H = 6.0        # systemic failure re-alert cooldown
STATE_DIR = Path(os.environ.get(
    "WIKI_TALK_STATE_DIR",
    str(Path.home() / ".local/state/wiki-talk-watch")))
STATE_FILE = STATE_DIR / "state.json"
LAST_RCID_FILE = STATE_DIR / "last-rcid"
LOCK_FILE = STATE_DIR / "lock"
BOARD_API = os.environ.get(
    "BOARD_API", "http://127.0.0.1:8787").rstrip("/")
DEFAULT_API = "https://wiki.surf-thailand.com/api.php"
LITELLM_DEFAULT_URL = "http://100.102.134.91:4000"
CLASSIFY_MODEL = os.environ.get("WIKI_TALK_CLASSIFY_MODEL",
                                "gemini-3.5-flash-lite")
DRAFT_MODEL = os.environ.get("WIKI_TALK_DRAFT_MODEL",
                             "gemini-3.5-flash-lite")

# Namespace -> visibility tier. Talk pages inherit their namespace's
# Lockdown boundary; the tier drives the draft content guard.
NS_TIER = {
    1: "public", 3: "public", 5: "public", 7: "public", 9: "public",
    11: "public", 13: "public", 15: "public",
    3005: "members", 3007: "members",          # Education/Reports talk
    3001: "private", 3003: "private",          # Infrastructure/PrivateNews talk
}
TIER_RANK = {"public": 0, "members": 1, "private": 2}

# Draft-content markers. private-tier markers are inhouse-only detail;
# members-tier markers are member-knowledge-surface names. A draft for a
# talk page may not contain markers above its own tier.
PRIVATE_MARKERS = re.compile(
    r"PrivateNews:|Infrastructure:|\b(idc0[0-9]|tony-dell|tony-omen|"
    r"tony-macbook|mn01|mn-home|michael-ha|con01)\b|"
    r"[\w.-]+\.ts\.net|\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+",
    re.IGNORECASE)
MEMBERS_MARKERS = re.compile(r"\b(Education|Reports)\s*:", re.IGNORECASE)

SIGNATURE = "— Ada ({lane}) ~~~~~"


class WikiError(RuntimeError):
    pass


# --- env / config -----------------------------------------------------------

def load_env_file(path: Path) -> dict:
    env = {}
    try:
        for ln in path.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _first_env(names, files=()):
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    for path, var in files:
        v = load_env_file(path).get(var)
        if v:
            return v
    return ""


def wiki_api_url() -> str:
    url = os.environ.get("WIKI_API_URL") or os.environ.get("WIKI_TALK_API")
    if url:
        return url.rstrip("/")
    host = _first_env(["WIKI_HOST"], [(Path.home() /
                    ".config/secrets/wiki-h3-gizmo.env", "WIKI_HOST")])
    if host:
        host = host.rstrip("/")
        if host.endswith("/v0"):
            host = host[:-3]
        if host.endswith("/api.php"):
            return host
        return f"{host}/api.php"
    return DEFAULT_API


def litellm_config() -> tuple[str, str]:
    """(base_url, key) — same gateway pattern as board-api /lesson
    translation: LITELLM_URL + a scoped LITELLM_KEY_* virtual key."""
    key_files = [
        (Path.home() / ".config/secrets/litellm-keys.env",
         ("LITELLM_KEY_WIKI_TALK", "LITELLM_KEY_CHABA",
          "LITELLM_KEY_MDDB", "LITELLM_KEY_ADA")),
        (Path.home() / ".config/secrets/litellm-chaba.env",
         ("LITELLM_KEY",)),
    ]
    url = os.environ.get("LITELLM_URL") or os.environ.get(
        "BOARD_API_LITELLM_URL") or ""
    key = ""
    if not url or not key:
        merged = {}
        for path, _ in key_files:
            merged.update(load_env_file(path))
    if not url:
        url = merged.get("LITELLM_URL", "") or LITELLM_DEFAULT_URL
    url = url.rstrip("/")
    # gemini_rest.endpoint() appends /v1beta itself — env files carry the
    # OpenAI-style base (.../v1), which would double-nest the path
    if url.endswith("/v1"):
        url = url[:-3]
    for n in ("LITELLM_KEY_WIKI_TALK", "LITELLM_KEY_CHABA",
              "LITELLM_KEY_MDDB", "LITELLM_KEY_ADA", "LITELLM_KEY"):
        key = os.environ.get(n) or merged.get(n, "")
        if key:
            break
    return url.rstrip("/"), key


# --- wiki api ---------------------------------------------------------------

def api_call(opener, api: str, params: dict, post: bool = False) -> dict:
    params = dict(params, format="json", formatversion="2")
    data = urllib.parse.urlencode(params).encode() if post else None
    url = api if post else api + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": "chaba-wiki-talk-watch/1.0"})
    try:
        return json.loads(opener.open(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise WikiError(f"mediawiki -> {e.code}: {detail}")
    except (OSError, ValueError) as e:
        raise WikiError(f"mediawiki -> {e}")


def wiki_login(opener, api: str, env: dict) -> bool:
    user = env.get("WIKI_USER") or ""
    password = env.get("WIKI_PASSWORD") or ""
    if not user or not password:
        return False
    try:
        tok = api_call(opener, api,
                       {"action": "query", "meta": "tokens",
                        "type": "login"})
        login_token = tok["query"]["tokens"]["logintoken"]
        res = api_call(opener, api,
                       {"action": "login", "lgname": user,
                        "lgpassword": password, "lgtoken": login_token},
                       post=True).get("login", {})
        return res.get("result") == "Success"
    except (WikiError, KeyError, TypeError):
        return False


def csrf_token(opener, api: str) -> str:
    tok = api_call(opener, api,
                   {"action": "query", "meta": "tokens"})
    return tok["query"]["tokens"]["csrftoken"]


def fetch_recentchanges(opener, api: str, rcend: str | None) -> list[dict]:
    """All talk-ns changes newer than the watermark, oldest first.

    rcend bounds the OLDEST side (changes newer than it); rcstart bounds
    the NEWEST side and pages backward. Client-side rcid filter is the
    authority — timestamps have 1s resolution.
    """
    out: list[dict] = []
    seen: set[int] = set()
    rcstart = None
    for _ in range(MAX_PAGES):
        params = {
            "action": "query", "list": "recentchanges",
            "rctype": "edit|new",
            "rcnamespace": TALK_NAMESPACES,
            "rcprop": "title|ids|timestamp|comment|user|flags",
            "rclimit": str(RCLIMIT),
        }
        if rcend:
            params["rcend"] = rcend
        if rcstart:
            params["rcstart"] = rcstart
        res = api_call(opener, api, params)
        page = (res.get("query") or {}).get("recentchanges") or []
        if not page:
            break
        for c in page:
            rcid = int(c.get("rcid") or 0)
            if rcid and rcid not in seen:
                seen.add(rcid)
                out.append(c)
        if len(page) < RCLIMIT:
            break
        oldest = min(c.get("timestamp", "") for c in page)
        if rcstart and oldest >= rcstart:
            break  # no progress — same-second tie flood guard
        rcstart = oldest
    out.sort(key=lambda c: int(c.get("rcid") or 0))
    return out


def _slot_text(rev: dict) -> str:
    """Main-slot wikitext — formatversion=2 emits "content", v1 "*"."""
    slot = (rev.get("slots") or {}).get("main") or {}
    return str(slot.get("*") or slot.get("content") or "")


def fetch_revision_texts(opener, api: str, revids: list[int]) -> dict[int, str]:
    """revid -> main-slot wikitext, batched."""
    texts: dict[int, str] = {}
    uniq = sorted({r for r in revids if r})
    for i in range(0, len(uniq), 40):
        chunk = uniq[i:i + 40]
        res = api_call(opener, api,
                       {"action": "query", "prop": "revisions",
                        "revids": "|".join(str(r) for r in chunk),
                        "rvprop": "ids|content", "rvslots": "main"})
        for rev in res.get("query", {}).get("pages", []) or []:
            for r in rev.get("revisions") or []:
                if "revid" not in r:
                    continue
                texts[int(r["revid"])] = _slot_text(r)
    return texts


def extract_added_text(old: str, new: str) -> str:
    """Wikitext lines present in `new` but not `old` — the comment body
    for a talk-page edit. Empty when the change added nothing."""
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(), lineterm="", n=0)
    added = [ln[1:] for ln in diff
             if ln.startswith("+") and not ln.startswith("+++")]
    return "\n".join(added).strip()


_HEADING = re.compile(r"^(={2,6})[ \t]*(.*?)[ \t]*\1[ \t]*$", re.M)


def parse_sections(wikitext: str) -> list[dict]:
    """MediaWiki section map: section 0 = lead (before first heading);
    each subsequent heading is the next sequential section number."""
    sections = [{"index": 0, "title": "", "start": 0}]
    lines = wikitext.splitlines()
    pos = 0
    for m in _HEADING.finditer(wikitext):
        line_no = wikitext.count("\n", 0, m.start())
        title = m.group(2).strip()
        sections.append({"index": len(sections), "title": title,
                         "start": line_no})
    for i, s in enumerate(sections):
        end = sections[i + 1]["start"] if i + 1 < len(sections) \
            else len(lines)
        s["end"] = end
    return sections


def locate_section(wikitext: str, needle: str) -> int | None:
    """Section index containing `needle` — matches on the first
    meaningful (non-heading) line of the added comment text."""
    needle_line = None
    for ln in needle.splitlines():
        t = ln.strip().strip("=").strip()
        if len(t) >= 8:
            needle_line = t
            break
    if needle_line is None:
        return None
    key = needle_line[:60]
    line_no = None
    for i, ln in enumerate(wikitext.splitlines()):
        if key in ln:
            line_no = i
            break
    if line_no is None:
        return None
    for s in parse_sections(wikitext):
        if s["start"] <= line_no < s["end"]:
            return s["index"]
    return None


def build_reply_text(draft: str, lane: str) -> str:
    """Sanitize the drafted reply: strip headings (a heading inside an
    appendtext would fork the section numbering), collapse excess blank
    lines, append the Ada signature."""
    lines = []
    for ln in draft.strip().splitlines():
        if re.match(r"^={2,6}\s", ln):
            continue
        lines.append(ln.rstrip())
    body = "\n".join(lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return f"\n\n{body}\n\n{SIGNATURE.format(lane=lane)}"


def guard_violations(tier: str, text: str, password: str = "") -> list[str]:
    """Draft may not carry markers above the talk page's tier."""
    hits = []
    if TIER_RANK[tier] < TIER_RANK["private"] and PRIVATE_MARKERS.search(text):
        hits.append("private-tier markers (inhouse hosts / protected ns)")
    if TIER_RANK[tier] < TIER_RANK["members"] and MEMBERS_MARKERS.search(text):
        hits.append("members-tier markers (Education:/Reports:)")
    if password and password in text:
        hits.append("contains the bot password")
    return hits


# --- classify / draft -------------------------------------------------------

_gemini_mod = None


def gemini_module():
    global _gemini_mod
    if _gemini_mod is None:
        spec = importlib.util.spec_from_file_location(
            "gemini_rest", REPO / "scripts/ada/gemini_rest.py")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            _gemini_mod = mod
        except Exception:
            _gemini_mod = False
    return _gemini_mod or None


def llm_generate(prompt: str, model: str, json_mode: bool,
                 timeout: int = 45) -> str | None:
    mod = gemini_module()
    if not mod:
        return None
    base, key = litellm_config()
    if not key:
        return None
    tags = ("service=wiki-talk-watch,job=wiki-talk-watch,"
            "route=ada-code")
    if json_mode:
        out = mod.generate_json(
            prompt, model, key=key, base_url_override=base,
            timeout=timeout, max_attempts=1, label="wiki-talk-watch",
            tags=tags)
        return json.dumps(out) if out is not None else None
    return mod.generate(
        prompt, model, key=key, base_url_override=base,
        timeout=timeout, max_attempts=1, label="wiki-talk-watch",
        tags=tags)


def classify_comment(title: str, tier: str, comment: str) -> dict:
    """v1 JevTeam stand-in -> {'lane': 'ada-code'|'no-response', ...}."""
    prompt = (
        "You are the router for a wiki talk-page assistant. Decide whether "
        "the comment below deserves a reply from the Ada code lane.\n\n"
        f"Talk page: {title}\nVisibility tier of the talk page: {tier}\n"
        f"Comment:\n{comment[:2500]}\n\n"
        "Reply with JSON only: {\"lane\": \"ada-code\" | \"no-response\", "
        "\"reason\": \"<short>\"}. Choose ada-code when the comment asks a "
        "question, requests help, gives feedback, or needs an answer the "
        "agent fleet can provide (repo, design, how-to, Education content). "
        "Choose no-response for pure chatter, thanks, emoji, content-free "
        "remarks, requests clearly needing a human decision only, or "
        "anything unsafe to answer automatically.")
    raw = llm_generate(prompt, CLASSIFY_MODEL, json_mode=True, timeout=40)
    if not raw:
        return {"lane": "error", "reason": "litellm call failed"}
    try:
        data = json.loads(raw)
        lane = str(data.get("lane") or "").strip()
        if lane not in ("ada-code", "no-response"):
            lane = "no-response"
        return {"lane": lane,
                "reason": str(data.get("reason") or "")[:200]}
    except (ValueError, AttributeError):
        return {"lane": "error", "reason": "unparseable classify output"}


def draft_reply(title: str, tier: str, comment: str,
                drafter: str) -> str | None:
    tier_rule = {
        "public": ("This reply is PUBLIC — anyone on the internet can read "
                   "it. Never include private or internal details: no "
                   "infrastructure hostnames, no PrivateNews/Infrastructure/"
                   "Education/Reports content, no credentials."),
        "members": ("This reply is visible to wiki members only. You may "
                    "reference member-level knowledge, but never "
                    "PrivateNews/Infrastructure/inhouse operational "
                    "detail."),
        "private": ("This reply is on a restricted inhouse talk page; "
                    "normal internal context is acceptable."),
    }[tier]
    prompt = (
        "You are Ada, the household's wiki assistant, replying to a comment "
        "on a talk page. Write a concise, helpful reply. Match the "
        "comment's language (the household is bilingual English/Thai — "
        "reply in Thai if the comment is Thai, else English).\n\n"
        f"Talk page: {title}\n{tier_rule}\n"
        f"Comment being replied to:\n{comment[:2500]}\n\n"
        "Output ONLY the reply text — no subject line, no signature "
        "(one is appended automatically), no markdown headers.")
    if drafter == "opencode":
        return draft_via_opencode(prompt)
    return llm_generate(prompt, DRAFT_MODEL, json_mode=False, timeout=60)


def _opencode_bin() -> str:
    env = os.environ.get("OPENCODE_BIN") or ""
    if env and Path(env).is_file():
        return env
    for p in os.environ.get("PATH", "").split(":"):
        c = Path(p) / "opencode"
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    for c in (Path.home() / ".opencode/bin/opencode",
              Path.home() / ".local/bin/opencode"):
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return ""


def _opencode_needs_standalone(oc_bin: str) -> bool:
    """v2 `run` attaches to a shared `opencode serve` which keeps its own
    env — the card's LITELLM_KEY never reaches the provider. v2 needs
    --standalone; v1.x rejects the flag (runner-agent convention)."""
    try:
        r = subprocess.run([oc_bin, "--version"], capture_output=True,
                           text=True, timeout=15)
        m = re.search(r"(\d+)\.", r.stdout or "")
        return bool(m and int(m.group(1)) >= 2)
    except Exception:
        return False


def draft_via_opencode(prompt: str) -> str | None:
    """card-run.py --execute invocation pattern: `opencode run --archived`
    with the prompt as a file, one-shot, bounded timeout."""
    oc = _opencode_bin()
    if not oc:
        return None
    with tempfile.TemporaryDirectory(prefix="wiki-talk-watch-") as td:
        pf = Path(td) / "prompt.md"
        pf.write_text(prompt)
        cmd = [oc, "run", "--archived",
               "--title", "wiki-talk-watch",
               "-f", str(pf),
               "Draft the wiki talk-page reply described in the "
               "attached prompt. Output ONLY the reply text."]
        if _opencode_needs_standalone(oc):
            cmd.insert(2, "--standalone")
        model = os.environ.get("WIKI_TALK_OPENCODE_MODEL")
        if model:
            cmd[2:2] = ["-m", model]
        try:
            r = subprocess.run(cmd, cwd=td, capture_output=True,
                               text=True, timeout=300)
        except (subprocess.TimeoutExpired, OSError):
            return None
        out = (r.stdout or "").strip()
        if r.returncode or not out:
            return None
        return out


# --- state / inbox ----------------------------------------------------------

def load_state() -> dict:
    try:
        st = json.loads(STATE_FILE.read_text())
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE_FILE)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hours_since(iso: str) -> float:
    try:
        return (datetime.now(timezone.utc)
                - datetime.fromisoformat(iso)).total_seconds() / 3600
    except Exception:
        return 1e9


def file_inbox_flag(slug: str, label: str, text: str,
                    tags: list[str], systemic: bool = False,
                    dry_run: bool = False) -> bool:
    """Dedupe-by-slug focus-inbox flag via board-api /inbox. Per-rcid
    slugs fire once ever; systemic slugs re-fire after REPEAT_ALERT_H."""
    st = load_state()
    cond = st.setdefault("conditions", {})
    key = f"alert-{slug}"
    if key in cond:
        if not systemic or _hours_since(cond[key]) < REPEAT_ALERT_H:
            return False
    if dry_run:
        print(f"  [dry-run] would file inbox flag: {label}")
        return True
    body = {"text": text, "label": label, "priority": "medium",
            "tags": ["wiki", "wiki-talk-watch"] + tags, "owner": "tony"}
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/inbox", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            ok = 200 <= r.status < 300
    except Exception as e:
        print(f"inbox flag failed ({slug}): {e}", file=sys.stderr)
        return False
    if ok:
        cond[key] = _iso_now()
        save_state(st)
    return ok


# --- reply posting ----------------------------------------------------------

def post_reply(opener, api: str, title: str, section: int | None,
               orig_section_title: str, reply_body: str,
               lane: str, token: str) -> int | None:
    """Append the reply inside the commenter's section (section=<n> +
    appendtext); fall back to a new section when the section can't be
    resolved. Returns the new revid or None."""
    summary = f"wiki-talk-watch: Ada reply ({lane})"
    if section is not None:
        params = {"action": "edit", "title": title, "section": str(section),
                  "appendtext": reply_body, "summary": summary,
                  "notminor": "1", "bot": "1", "token": token}
    else:
        st = re.sub(r"[=\[\]{}|#<>]", "", orig_section_title).strip()[:80]
        params = {"action": "edit", "title": title, "section": "new",
                  "sectiontitle": f"Re: {st}" if st else "Ada reply",
                  "text": reply_body.lstrip("\n"), "summary": summary,
                  "notminor": "1", "bot": "1", "token": token}
    res = api_call(opener, api, params, post=True)
    if "error" in res:
        # bot flag needs the bot user right — retry once without it
        if params.pop("bot", None):
            res = api_call(opener, api, params, post=True)
    edit = res.get("edit") or {}
    if edit.get("result") == "Success":
        return int(edit.get("newrevid") or 0) or None
    info = "; ".join(str(e.get("info")) for e in
                     res.get("error", {}).get("messages", [])) or \
        str(res.get("error"))[:200]
    raise WikiError(f"edit failed on {title}: {info}")


# --- main loop --------------------------------------------------------------

def candidate_comment(opener, api: str, rc: dict,
                      texts: dict[int, str],
                      page_cache: dict[str, str]) -> tuple[str, str]:
    """(added_wikitext, current_page_wikitext) for one recentchange."""
    new_text = texts.get(int(rc.get("revid") or 0), "")
    old_text = texts.get(int(rc.get("old_revid") or 0), "") \
        if rc.get("old_revid") else ""
    added = extract_added_text(old_text, new_text)
    page_text = ""
    if added:
        title = rc["title"]
        if title not in page_cache:
            try:
                res = api_call(opener, api,
                               {"action": "query", "prop": "revisions",
                                "titles": title, "rvprop": "content",
                                "rvslots": "main", "rvlimit": "1"})
                pages = res.get("query", {}).get("pages") or []
                revs = (pages[0].get("revisions") or []) \
                    if pages else []
                page_cache[title] = _slot_text(revs[0]) if revs else ""
            except WikiError:
                page_cache[title] = ""
        page_text = page_cache[title]
    return added, page_text


def run(dry_run: bool, drafter: str, max_replies: int,
        process_all: bool = False) -> int:
    env = dict(os.environ)
    # env vars win; the secrets file fills gaps (job unit also carries it
    # as EnvironmentFile — self-load keeps manual runs working too)
    wenv = load_env_file(
        Path(os.environ.get(
            "WIKI_TALK_ENV_FILE",
            str(Path.home() / ".config/secrets/wiki-h3-gizmo.env"))))
    for k, v in wenv.items():
        env.setdefault(k, v)
        os.environ.setdefault(k, v)   # helpers read os.environ directly

    api = wiki_api_url()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))
    if wiki_login(opener, api, env):
        print(f"wiki login ok as {env.get('WIKI_USER')}")
        authed = True
    else:
        print("wiki login unavailable — anon read; protected-ns "
              "candidates will be skipped", file=sys.stderr)
        authed = False

    st = load_state()
    watermark = int(st.get("watermark_rcid") or 0)
    processed = set(st.get("processed_rcids") or [])
    attempts = dict(st.get("attempts") or {})

    rcend = None
    if watermark:
        wts = st.get("watermark_ts")
        if wts:
            try:
                t = datetime.fromisoformat(wts.replace("Z", "+00:00"))
                rcend = (t - timedelta(seconds=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                rcend = None

    changes = fetch_recentchanges(opener, api, rcend)
    initialized = bool(st.get("initialized"))

    if not initialized and changes and not process_all:
        # first-ever run: baseline the watermark at the newest rcid —
        # never auto-reply to history
        top = max(int(c.get("rcid") or 0) for c in changes)
        if dry_run:
            print(f"[dry-run] uninitialized — would baseline watermark "
                  f"at rcid {top} ({len(changes)} changes seen)")
            return 0
        st["initialized"] = True
        st["watermark_rcid"] = top
        st["watermark_ts"] = next(
            (c.get("timestamp") for c in changes
             if int(c.get("rcid") or 0) == top), None)
        st["processed_rcids"] = []
        st["last_run"] = _iso_now()
        save_state(st)
        LAST_RCID_FILE.write_text(str(top))
        print(f"wiki-talk-watch: baseline watermark rcid {top}")
        return 0

    if process_all:
        fresh = sorted(changes, key=lambda c: int(c.get("rcid") or 0))
    else:
        fresh = [c for c in changes
                 if int(c.get("rcid") or 0) > watermark
                 and int(c.get("rcid") or 0) not in processed
                 ][:MAX_CANDIDATES]
    if not fresh:
        if not dry_run:
            st["last_run"] = _iso_now()
            st["stats"] = {"seen": len(changes), "fresh": 0}
            save_state(st)
        print(f"wiki-talk-watch: {len(changes)} changes seen, "
              f"{len(fresh)} new (watermark rcid {watermark})")
        return 0

    # batch-fetch revision contents for the diff
    revids = []
    for c in fresh:
        revids += [int(c.get("revid") or 0), int(c.get("old_revid") or 0)]
    texts = fetch_revision_texts(opener, api, revids)
    page_cache: dict[str, str] = {}

    token = ""
    if authed:
        try:
            token = csrf_token(opener, api)
        except WikiError as e:
            print(f"csrf token failed: {e}", file=sys.stderr)

    replies = 0
    new_watermark = watermark
    acted = []
    for rc in fresh:
        rcid = int(rc.get("rcid") or 0)
        ns = int(rc.get("ns") or 0)
        title = str(rc.get("title") or "")
        user = str(rc.get("user") or "")
        # formatversion=2 carries minor/bot as booleans; v1 a flags string
        minor = bool(rc.get("minor")) or "minor" in str(rc.get("flags") or "")
        botflag = bool(rc.get("bot")) or "bot" in str(rc.get("flags") or "")
        tier = NS_TIER.get(ns, "public")

        def mark_done():
            nonlocal new_watermark
            processed.add(rcid)
            attempts.pop(str(rcid), None)
            if rcid > new_watermark:
                new_watermark = rcid

        def mark_fail(why: str):
            n = int(attempts.get(str(rcid), 0)) + 1
            attempts[str(rcid)] = n
            if n >= MAX_ATTEMPTS:
                file_inbox_flag(
                    f"wiki-talk-watch-fail-{rcid}",
                    f"Wiki talk-watch: reply failed x{n} on {title}",
                    f"wiki-talk-watch could not handle rcid {rcid} "
                    f"({title}) after {n} attempts.\n\nLast error: {why}\n\n"
                    "The candidate is marked processed — inspect the talk "
                    "page and the watcher journal, then re-arm by clearing "
                    "state.json attempts if a retry is wanted.",
                    ["failure", f"rcid-{rcid}"], dry_run=dry_run)
                mark_done()
            else:
                print(f"  rcid {rcid}: attempt {n}/{MAX_ATTEMPTS} failed "
                      f"({why[:120]}) — will retry next tick")
            return

        # --- cheap skips -------------------------------------------------
        bot_user = (env.get("WIKI_USER") or "").strip()
        if user and (user == bot_user or user.lower() == "ada"):
            if dry_run:
                print(f"  [dry-run] rcid {rcid} {title} skip: own-bot "
                      f"(user={user})")
            mark_done()
            continue
        if minor or botflag:
            if dry_run:
                print(f"  [dry-run] rcid {rcid} {title} skip: "
                      f"minor={minor} bot={botflag}")
            mark_done()
            continue
        if not authed and tier != "public":
            if dry_run:
                print(f"  [dry-run] rcid {rcid} {title} skip: protected "
                      f"ns {ns} unreadable anon")
            mark_done()   # can't read protected talk content anon
            continue
        try:
            added, page_text = candidate_comment(
                opener, api, rc, texts, page_cache)
        except WikiError as e:
            mark_fail(f"content fetch: {e}")
            break      # API trouble — stop the pass, retry next tick
        if not added or len(added.strip()) < 3:
            if dry_run:
                print(f"  [dry-run] rcid {rcid} {title} skip: empty diff")
            mark_done()
            continue

        # --- classify ----------------------------------------------------
        verdict = classify_comment(title, tier, added)
        lane = verdict.get("lane")
        if lane == "error":
            mark_fail(f"classify: {verdict.get('reason')}")
            break
        if lane != "ada-code":
            if dry_run:
                print(f"  [dry-run] rcid {rcid} {title} user={user} "
                      f"tier={tier} -> lane={lane} "
                      f"({verdict.get('reason', '')})")
            mark_done()
            continue

        # --- draft + guard ----------------------------------------------
        drafter_eff = drafter
        if drafter_eff == "auto":
            drafter_eff = "opencode" if _opencode_bin() else "litellm"
        draft_err = ""
        try:
            draft = draft_reply(title, tier, added, drafter_eff)
        except Exception as e:
            draft = None
            draft_err = str(e)[:200]
        if not draft:
            mark_fail(f"draft ({drafter_eff}): "
                      f"{draft_err or 'empty'}")
            break
        body = build_reply_text(draft, "ada-code")
        violations = guard_violations(tier, body,
                                      env.get("WIKI_PASSWORD") or "")
        if violations:
            file_inbox_flag(
                f"wiki-talk-watch-guard-{rcid}",
                f"Wiki talk-watch: guard blocked reply on {title}",
                f"rcid {rcid} on {title} (tier={tier}) classified "
                f"ada-code but the drafted reply tripped the visibility "
                f"guard: {'; '.join(violations)}.\n\nDraft:\n{body[:1500]}",
                ["guard", f"rcid-{rcid}"], dry_run=dry_run)
            mark_done()
            continue

        # --- locate section + post ---------------------------------------
        section = None
        orig_title = ""
        if page_text:
            section = locate_section(page_text, added)
            secs = parse_sections(page_text)
            if section is not None and section < len(secs):
                orig_title = secs[section]["title"]
        if dry_run:
            print(f"  [dry-run] rcid {rcid} {title} user={user} "
                  f"tier={tier} -> lane=ada-code drafter={drafter_eff} "
                  f"section={section} guard=ok")
            print(f"    draft preview: {body[:300].strip()}")
            mark_done()
            continue
        if not authed or not token:
            mark_fail("no auth/token for posting")
            break
        if replies >= max_replies:
            print(f"  reply cap {max_replies} reached — remaining "
                  "candidates wait for next tick")
            break
        try:
            revid = post_reply(opener, api, title, section, orig_title,
                               body, "ada-code", token)
        except WikiError as e:
            mark_fail(f"post: {e}")
            break
        replies += 1
        acted.append({"rcid": rcid, "title": title, "revid": revid,
                      "section": section})
        mark_done()
        print(f"  replied rcid {rcid} {title} -> revid {revid} "
              f"(section {section})")
        time.sleep(2)   # politeness between edits

    if not dry_run:
        # watermark = highest rcid fully handled; processed set is the
        # durable dedupe so a lost watermark can't re-reply
        st["watermark_rcid"] = new_watermark
        if new_watermark:
            wts = next((c.get("timestamp") for c in reversed(changes)
                        if int(c.get("rcid") or 0) == new_watermark), None)
            if wts:
                st["watermark_ts"] = wts
        proc = sorted(processed)[-500:]
        st["processed_rcids"] = proc
        st["attempts"] = {k: v for k, v in attempts.items()
                          if int(k) not in processed}
        st["last_run"] = _iso_now()
        st["stats"] = {"seen": len(changes), "fresh": len(fresh),
                       "replies": replies, "acted": acted[:10]}
        save_state(st)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_RCID_FILE.write_text(str(new_watermark))
    print(f"wiki-talk-watch: {len(fresh)} new, {replies} replies "
          f"(watermark rcid {new_watermark})")
    return 0


def self_test() -> int:
    fails = []

    def check(name, cond):
        print(("PASS" if cond else "FAIL"), name)
        if not cond:
            fails.append(name)

    wikitext = (
        "Some lead text.\n\n"
        "== First section ==\ncomment one body\n\n"
        "== Second section ==\ncomment two body\n")
    secs = parse_sections(wikitext)
    check("parse_sections count", len(secs) == 3)
    check("lead is section 0", secs[0]["index"] == 0)
    check("locate first", locate_section(wikitext, "comment one body") == 1)
    check("locate second", locate_section(wikitext, "comment two body") == 2)
    check("locate lead", locate_section(wikitext, "Some lead text") == 0)

    old = "== A ==\nold comment\n"
    new = "== A ==\nold comment\n\n== New question ==\n\nhow do I X?\n\n— Tony ~~~~~\n"
    added = extract_added_text(old, new)
    check("extract added non-empty", "how do I X?" in added)
    check("extract skips unchanged context", "old comment" not in added)
    check("extract deletion-only empty",
          extract_added_text(new, old) == "")

    body = build_reply_text("Hello there.\n\n== fake heading ==\nworld",
                            "ada-code")
    check("signature appended", body.rstrip().endswith("— Ada (ada-code) ~~~~~"))
    check("headings stripped", "== fake heading ==" not in body)

    check("guard public blocks infra",
          guard_violations("public", "try idc03 or PrivateNews:Foo") != [])
    check("guard public blocks edu",
          guard_violations("public", "see Education:Index") != [])
    check("guard members allows edu",
          guard_violations("members", "see Education:Index") == [])
    check("guard members blocks infra",
          guard_violations("members", "check Infrastructure:Hosts") != [])
    check("guard private allows all",
          guard_violations("private", "Infrastructure:Hosts + Education:X") == [])
    check("guard clean text",
          guard_violations("public", "sure — here's how") == [])
    check("guard password",
          guard_violations("public", "pw", password="hunter2") == [])
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="poll+classify+plan only; write nothing")
    ap.add_argument("--self-test", action="store_true",
                    help="offline helper checks, no network")
    ap.add_argument("--drafter", choices=["auto", "litellm", "opencode"],
                    default="auto")
    ap.add_argument("--max-replies", type=int, default=MAX_REPLIES)
    ap.add_argument("--process-all", action="store_true",
                    help="dry-run only: classify every fetched change "
                         "(ignores watermark/processed) — verification")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.process_all and not args.dry_run:
        print("--process-all is dry-run only — refusing", file=sys.stderr)
        return 2
    if args.dry_run:
        # read-only pass: no state dir, no lock file, no writes at all
        return run(args.dry_run, args.drafter, args.max_replies,
                   process_all=args.process_all)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another wiki-talk-watch is running — exiting")
            return 0
        return run(args.dry_run, args.drafter, args.max_replies,
                   process_all=args.process_all)


if __name__ == "__main__":
    raise SystemExit(main())
