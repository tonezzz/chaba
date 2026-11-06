#!/usr/bin/env python3
"""publication — provider-neutral DevNest publication layer
(card devnest-publication-adapter-layer / OPS-0913).

One canonical PublicationEvent fans out to pluggable sinks: WP CPTs
(nest_job / lesson / news through board-api's wp_api seam), ada-cms-pages
report dossiers, Telegram, kanban-card comms (operational audit), and a
JSONL ledger. Agents POST /publish to board-api — they never call
WordPress REST and never hold provider credentials; the door owns every
adapter. WP is provably only one adapter: any second sink (json,
telegram, a test mock) receives the byte-identical canonical event.

The legacy endpoints stay live as compatibility adapters — /job,
/lesson, /report keep their request bodies and semantics; /publish
routes the canonical event through the SAME writer functions
(do_job/do_lesson/do_report), so there is one provider implementation,
not two.

Kind semantics (the DevNest mapping):
  progress   -> nest_job live execution state + board audit.
              Heartbeat-class: rate-limited, never auto-routes to
              telegram/news — "do not publish every heartbeat".
  milestone  -> nest_job + board audit + concise telegram.
  report     -> project dossier (ada-cms-pages note) + board audit.
  lesson     -> Education — reusable knowledge. WP lesson CPT today;
              dual-write to the protected wiki Education: namespace rides
              the WikiLessonSink (board-api flag WIKI_EDUCATION_WRITE).
  news       -> member-facing milestone news (WP news CPT) + board +
              telegram. Evidence is REQUIRED; public needs verified.
  alert      -> telegram + board audit + nest_job error state.

Visibility is private-first: an event only reaches sinks whose surface
class does not exceed the event's declared visibility. private ->
internal sinks (board comms, json ledger); members -> + WP private
posts, telegram group; public -> + publish-status surfaces.

This module is pure/standalone — board-api injects the provider
functions; tests inject mocks. No imports from board-api.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from html.parser import HTMLParser
from http.cookiejar import CookieJar

KINDS = ("progress", "milestone", "report", "lesson", "news", "alert")
CONFIDENCE = ("observed", "measured", "verified")
VISIBILITY = ("private", "members", "public")
VIS_RANK = {v: i for i, v in enumerate(VISIBILITY)}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}$")

# Default fan-out per kind. Callers may override with an explicit
# `sinks` list; adapters that lack the refs they need skip gracefully.
# progress deliberately excludes telegram/news (heartbeat noise) and
# alert deliberately includes telegram (someone must see it).
DEFAULT_ROUTES = {
    "progress": ["job", "board"],
    "milestone": ["job", "board", "telegram"],
    "report": ["report", "board"],
    "lesson": ["lesson"],
    "news": ["news", "wiki", "wiki-private", "board", "telegram"],
    "alert": ["telegram", "board", "job"],
}

TITLE_MAX = 240
BODY_MAX = 20000
LIST_MAX = 20
LINK_MAX = 500


class PubError(ValueError):
    """Bad event or bad request — surfaces as a 400."""


class DeliveryError(RuntimeError):
    """Sink-side failure — retried via the outbox, not a caller error."""


class Skip(Exception):
    """Adapter declines this event (missing ref, not applicable) —
    recorded as skipped in the receipt, never retried."""


def _str_list(v, name: str) -> list:
    if v is None:
        return []
    if not isinstance(v, list):
        raise PubError(f"{name} must be a list")
    return [str(x)[:LINK_MAX] for x in v[:LIST_MAX] if str(x).strip()]


def _norm_occurred(v) -> str:
    if not v:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    s = str(v).strip()
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise PubError("occurred_at must be ISO-8601")
    return s


def default_idempotency_key(ev: dict) -> str:
    """Deterministic key for callers that don't supply one: identical
    logical events (same kind+source+title+refs+body) dedupe — a retried
    POST cannot double-publish. Callers who want always-distinct events
    pass their own event_id/idempotency_key."""
    parts = [ev["kind"], ev["source"], ev["title"], ev["body"],
             ev.get("project") or "", ev.get("job") or "",
             ev.get("card") or "", ev.get("parent") or ""]
    return "pub-" + hashlib.sha1(
        "\x1f".join(parts).encode()).hexdigest()[:24]


def validate_event(body: dict) -> dict:
    """Normalize + validate a canonical PublicationEvent. Returns a new
    dict; raises PubError on violations."""
    if not isinstance(body, dict):
        raise PubError("event must be an object")
    ev = {}
    kind = str(body.get("kind") or "").strip()
    if kind not in KINDS:
        raise PubError(f"kind must be one of {list(KINDS)}")
    ev["kind"] = kind
    title = str(body.get("title") or "").strip()
    if not title:
        raise PubError("title required")
    ev["title"] = title[:TITLE_MAX]
    body_text = str(body.get("body") or "").strip()
    if kind in ("lesson", "report", "news") and not body_text:
        raise PubError(f"body required for kind {kind}")
    ev["body"] = body_text[:BODY_MAX]
    source = str(body.get("source") or body.get("from") or "").strip()
    if not SOURCE_RE.match(source):
        raise PubError("source required (producer name, "
                       "[a-z0-9][a-z0-9._-]{0,60})")
    ev["source"] = source
    conf = str(body.get("confidence") or "observed").strip()
    if conf not in CONFIDENCE:
        raise PubError(f"confidence must be one of {list(CONFIDENCE)}")
    ev["confidence"] = conf
    vis = str(body.get("visibility") or "private").strip()
    if vis not in VISIBILITY:
        raise PubError(f"visibility must be one of {list(VISIBILITY)}")
    ev["visibility"] = vis
    ev["evidence"] = _str_list(body.get("evidence"), "evidence")
    if kind == "news" and not ev["evidence"]:
        raise PubError("news requires at least one evidence link")
    if kind == "news" and vis == "public" and conf != "verified":
        raise PubError("public news requires confidence=verified")
    ev["audience"] = _str_list(body.get("audience"), "audience")
    ev["media"] = _str_list(
        body.get("media") or body.get("artifacts"), "media")
    for ref in ("project", "job", "card"):
        v = str(body.get(ref) or "").strip()
        if v and not SLUG_RE.match(v):
            raise PubError(f"{ref} must match {SLUG_RE.pattern}")
        ev[ref] = v
    parent = str(body.get("parent") or "").strip()
    if parent and not SLUG_RE.match(parent):
        raise PubError("parent must be a slug or event ref")
    ev["parent"] = parent
    ev["occurred_at"] = _norm_occurred(body.get("occurred_at"))
    meta = body.get("meta")
    if meta is not None and not isinstance(meta, dict):
        raise PubError("meta must be an object")
    ev["meta"] = {str(k): v for k, v in (meta or {}).items()}
    ev["force"] = bool(body.get("force"))
    sinks = body.get("sinks")
    if sinks is not None:
        if not isinstance(sinks, list) or not sinks:
            raise PubError("sinks must be a non-empty list")
        ev["sinks"] = [str(s).strip() for s in sinks]
    # idempotency: explicit key wins; otherwise derive a deterministic
    # one so a client retry of the same logical event dedupes.
    key = str(body.get("idempotency_key") or "").strip()
    ev["idempotency_key"] = key or default_idempotency_key(ev)
    eid = str(body.get("event_id") or "").strip()
    ev["event_id"] = eid or "evt-" + hashlib.sha1(
        ev["idempotency_key"].encode()).hexdigest()[:16]
    return ev


def topic_key(ev: dict) -> str:
    """Noise-policy grouping — 'same topic' = same job/project/card,
    else the title hash."""
    return (ev.get("job") or ev.get("project") or ev.get("card")
            or "t:" + hashlib.sha1(ev["title"].encode()).hexdigest()[:10])


# --- html -> wikitext (education corpus) ------------------------------------

_HEADING = {"h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_LESSON_TITLE_BAD = re.compile(r"[#<>\[\]|{}_]")


class _HtmlToWikitext(HTMLParser):
    """Lesson-body HTML -> wikitext (stdlib only).

    Covers the markup lesson writers emit: headings, paragraphs, nested
    lists, links, bold/italic, code/pre, <hr>. Table-family and unknown
    tags are flattened — their text content survives."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.lists = []               # stack of '*' | '#'
        self._a = None                # (href, out_index) inside <a>
        self._skip = 0                # inside script/style
        self._pre = 0

    def _break(self, n):
        cur = "".join(self.out)
        if not cur.strip():
            self.out = []
            return
        trailing = len(cur) - len(cur.rstrip("\n"))
        if trailing < n:
            self.out.append("\n" * (n - trailing))

    def handle_starttag(self, tag, attrs):
        if self._skip:
            self._skip += tag in ("script", "style")
            return
        if tag in ("script", "style"):
            self._skip = 1
        elif tag in _HEADING or tag == "h1":
            n = _HEADING.get(tag, 2)          # h1 -> == (page title is h1)
            self._break(2)
            self.out.append("=" * n + " ")
        elif tag in ("p", "div", "section", "article"):
            self._break(2)
        elif tag == "br":
            self.out.append("\n")
        elif tag == "hr":
            self._break(2)
            self.out.append("----")
            self._break(2)
        elif tag in ("ul", "ol"):
            self.lists.append("*" if tag == "ul" else "#")
            self._break(1)
        elif tag == "li":
            self._break(1)
            self.out.append(("".join(self.lists) or "*") + " ")
        elif tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            self._a = (href, len(self.out)) if href else None
        elif tag in ("strong", "b"):
            self.out.append("'''")
        elif tag in ("em", "i"):
            self.out.append("''")
        elif tag == "code" and not self._pre:
            self.out.append("<code>")
        elif tag == "pre":
            self._pre += 1
            self.out.append("<pre>")
        elif tag == "blockquote":
            self._break(1)
            self.out.append(": ")

    def handle_endtag(self, tag):
        if self._skip:
            if tag in ("script", "style"):
                self._skip = 0
            return
        if tag in _HEADING or tag == "h1":
            n = _HEADING.get(tag, 2)
            self.out.append(" " + "=" * n)
            self._break(2)
        elif tag in ("p", "div", "section", "article"):
            self._break(2)
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self._break(1)
        elif tag == "a" and self._a is not None:
            href, mark = self._a
            self._a = None
            label = "".join(self.out[mark:]).strip()
            del self.out[mark:]
            self.out.append(f"[{href}]" if not label or label == href
                            else f"[{href} {label}]")
        elif tag in ("strong", "b"):
            self.out.append("'''")
        elif tag in ("em", "i"):
            self.out.append("''")
        elif tag == "code" and not self._pre:
            self.out.append("</code>")
        elif tag == "pre":
            self._pre = max(0, self._pre - 1)
            self.out.append("</pre>")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.out.append("\n")
        elif tag == "hr":
            self._break(2)
            self.out.append("----")
            self._break(2)

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def html_to_wikitext(markup: str) -> str:
    """Convert lesson-body HTML to wikitext for the Education: pages.
    Not a general converter — unknown tags flatten to their text."""
    p = _HtmlToWikitext()
    p.feed(markup or "")
    p.close()
    text = "".join(p.out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def lesson_wiki_title(topic: str, prefix: str = "Education:") -> str:
    """Readable Education: page title from a lesson topic — the
    lesson-<md5> slug never leaks to readers. First letter of each
    lowercase (hyphen-)word is capitalized; acronyms survive;
    MediaWiki-forbidden title chars fold to spaces."""
    t = _LESSON_TITLE_BAD.sub(" ", str(topic or ""))
    words = []
    for w in re.split(r"\s+", t):
        if not w:
            continue
        if w.islower():
            w = "-".join(seg[:1].upper() + seg[1:]
                         for seg in w.split("-"))
        words.append(w)
    return prefix + " ".join(words)


def _topic_slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(topic).lower()).strip("-")


# --- sinks ------------------------------------------------------------------


class Sink:
    """A provider adapter. `surface` is the audience class the sink
    exposes (the eligibility gate); a sink may deliver a MORE visible
    event at a narrower surface (wp news posts members events as
    private posts) but never a less visible event at a wider one."""

    name = "sink"
    surface = "private"
    kinds = frozenset(KINDS)
    evidence_required = False

    def __init__(self, name=None, surface=None, kinds=None,
                 evidence_required=None):
        if name is not None:
            self.name = name
        if surface is not None:
            self.surface = surface
        if kinds is not None:
            self.kinds = frozenset(kinds)
        if evidence_required is not None:
            self.evidence_required = evidence_required

    def check(self, ev: dict):
        """None = deliverable; else a human reason it is skipped."""
        if ev["kind"] not in self.kinds:
            return f"kind {ev['kind']} unsupported"
        if VIS_RANK[ev["visibility"]] < VIS_RANK[self.surface]:
            return (f"visibility {ev['visibility']} below "
                    f"{self.name}'s {self.surface} surface")
        if self.evidence_required and not ev["evidence"]:
            return "sink requires evidence"
        return None

    def capabilities(self) -> dict:
        return {"surface": self.surface, "kinds": sorted(self.kinds),
                "evidence_required": self.evidence_required}

    def publish(self, ev: dict) -> dict:
        raise NotImplementedError


class FuncSink(Sink):
    """Adapter around an injected writer callable — this is how board-api
    binds do_job/do_lesson/do_report/wp_api and how tests bind mocks."""

    def __init__(self, name, send, **kw):
        super().__init__(name=name, **kw)
        self._send = send

    def publish(self, ev: dict) -> dict:
        return dict(self._send(ev) or {})


class JsonSink(Sink):
    """JSONL sink — the second-sink proof and a spool/ledger adapter.
    Every delivered event lands as one canonical JSON line."""

    def __init__(self, path, **kw):
        kw.setdefault("surface", "private")
        super().__init__(name="json", **kw)
        self.path = Path(path)

    def publish(self, ev: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"delivered_at": _now_iso(), "event": ev},
                          ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(line + "\n")
        return {"ref": f"{self.path.name}#{ev['event_id']}"}


class TelegramSink(Sink):
    """Telegram sink — concise same-topic notifications through the
    devnest-tg-relay loopback /send door (or any injected poster). The
    group is a members surface: private events never reach it."""

    def __init__(self, url="http://127.0.0.1:8919/send", poster=None,
                 **kw):
        kw.setdefault("surface", "members")
        kw.setdefault("kinds", ("milestone", "news", "alert"))
        super().__init__(name="telegram", **kw)
        self.url = url
        self._poster = poster or self._http_post

    def _http_post(self, payload: dict) -> dict:
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            return json.loads(
                urllib.request.urlopen(req, timeout=20).read())
        except urllib.error.HTTPError as e:
            raise DeliveryError(
                f"telegram relay -> {e.code}: "
                f"{e.read()[:200].decode('utf-8', 'replace')}")
        except OSError as e:
            raise DeliveryError(f"telegram relay -> {e}")

    @staticmethod
    def render(ev: dict) -> str:
        head = f"[DevNest {ev['kind']}] {ev['title']}"
        bits = [head]
        if ev["body"]:
            bits.append(ev["body"][:220])
        if ev["kind"] == "news" and ev["evidence"]:
            bits.append(str(ev["evidence"][0]))
        return "\n".join(bits)[:3800]

    def publish(self, ev: dict) -> dict:
        payload = {"text": self.render(ev)}
        thread = (ev.get("meta") or {}).get("tg_thread_id")
        if isinstance(thread, int):
            payload["message_thread_id"] = thread
        r = self._poster(payload)
        if isinstance(r, dict) and r.get("ok") is False:
            raise DeliveryError(f"telegram relay -> {r.get('error')}")
        return {"ref": f"tg:{(r or {}).get('message_thread_id', '')}"
                       if isinstance(r, dict) else "tg"}


class MediaWikiSink(Sink):
    """Verified-public news adapter for a MediaWiki Action API.

    Wiki writes are deliberately public-only until a real MediaWiki
    permission boundary exists. Credentials stay in the service env; callers
    provide only a canonical event and a safe ``meta.wiki_title``.
    """

    edit_label = "DevNest News"

    def __init__(self, api_url: str, username: str, password: str,
                 template: str = "แม่แบบ:NewsReport", api=None,
                 name: str = "wiki", surface: str = "public",
                 namespace_prefix: str = "News/"):
        super().__init__(name=name, surface=surface, kinds=("news",),
                         evidence_required=True)
        self.api_url = api_url.rstrip("/")
        self.username = username
        self.password = password
        self.template = template
        self.namespace_prefix = namespace_prefix
        self._jar = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar))
        self._api_override = api

    def _api(self, params: dict, post: bool = False) -> dict:
        if self._api_override is not None:
            return self._api_override(params, post)
        data = urllib.parse.urlencode(params).encode() if post else None
        url = self.api_url if post else (
            self.api_url + "?" + urllib.parse.urlencode(params))
        req = urllib.request.Request(
            url, data=data, headers={"User-Agent": "chaba-board-api/1.0"})
        try:
            return json.loads(self._opener.open(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            raise DeliveryError(f"mediawiki -> {e.code}: {detail}")
        except OSError as e:
            raise DeliveryError(f"mediawiki -> {e}")

    def _title(self, ev: dict) -> str:
        title = str((ev.get("meta") or {}).get("wiki_title") or "").strip()
        if not title:
            raise Skip("wiki sink needs meta.wiki_title")
        if (not title.startswith(self.namespace_prefix)
                or "\n" in title or "\r" in title):
            raise Skip(f"wiki title must be under {self.namespace_prefix}")
        return title

    def check(self, ev: dict):
        reason = super().check(ev)
        if reason:
            return reason
        if self.surface == "private" and ev["visibility"] != "private":
            return "private Wiki sink accepts private events only"
        if self.surface == "public" and ev["visibility"] != "public":
            return "public Wiki sink accepts public events only"
        return None

    def _wikitext(self, ev: dict) -> str:
        meta = ev.get("meta") or {}
        summary = str(meta.get("summary") or "").strip()
        if not summary:
            raise Skip("wiki sink needs meta.summary")
        if len(summary) > 80:
            raise Skip("wiki meta.summary must be <=80 characters")
        lines = [
            f"= {ev['title']} =", "",
            f"'''Quick summary:''' {summary}", "",
            f"{{{{{self.template}",
            f"|story_id={ev['event_id']}",
            f"|status={meta.get('status', 'review' if ev['visibility'] == 'private' else 'published')}",
            f"|visibility={ev['visibility']}",
            f"|confidence={ev['confidence']}",
            f"|desk={meta.get('desk', 'DevNest')}",
            f"|geo_scope={meta.get('geo_scope', '')}",
            f"|country={meta.get('country', '')}",
            f"|region={meta.get('region', '')}",
            f"|topic={meta.get('topic', '')}",
            f"|published_at={meta.get('published_at', ev['occurred_at'])}",
            f"|source_published_at={meta.get('source_published_at', '')}",
            f"|source_url={ev['evidence'][0]}",
            f"|source_name={meta.get('source_name', ev['source'])}",
            f"|parent={meta.get('parent', '')}",
            "}}", "",
            ev["body"], "", "== Evidence ==", "",
        ]
        lines.extend(f"* [{url} {url}]" for url in ev["evidence"])
        categories = [] if ev["visibility"] == "private" else [
            "News", "News/Desks/DevNest"]
        geo_scope = str(meta.get("geo_scope") or "").strip()
        if categories and geo_scope == "world":
            categories.append("News/Geography/World")
        for key in ("region", "country"):
            value = str(meta.get(key) or "").strip()
            if categories and value:
                categories.append(f"News/Geography/{value}")
        topic = str(meta.get("topic") or "").strip()
        if categories and topic:
            categories.append(f"News/Topics/{topic}")
        lines.extend([""] + [f"[[Category:{category}]]"
                             for category in dict.fromkeys(categories)])
        return "\n".join(lines)

    def publish(self, ev: dict) -> dict:
        title = self._title(ev)
        login = self._api({
            "action": "query", "meta": "tokens", "type": "login",
            "format": "json"})
        login_token = login["query"]["tokens"]["logintoken"]
        result = self._api({
            "action": "login", "lgname": self.username,
            "lgpassword": self.password, "lgtoken": login_token,
            "format": "json"}, post=True).get("login", {})
        if result.get("result") != "Success":
            raise DeliveryError("mediawiki login failed")
        csrf = self._api({
            "action": "query", "meta": "tokens", "format": "json"
        })["query"]["tokens"]["csrftoken"]
        edited = self._api({
            "action": "edit", "title": title, "text": self._wikitext(ev),
            "summary": f"{self.edit_label} {ev['event_id']}",
            "token": csrf, "format": "json"}, post=True).get("edit", {})
        if edited.get("result") not in ("Success", "Nochange"):
            raise DeliveryError("mediawiki edit failed")
        return {"ref": f"wiki:{title}",
                "pageid": edited.get("pageid"),
                "revid": edited.get("newrevid"),
                "action": edited.get("result", "").lower()}


class WikiLessonSink(MediaWikiSink):
    """Education:-namespace adapter for kind=lesson events
    (card wiki-member-knowledge-surface-migrate-wp-3a1cf2).

    surface=private because Education: is a Lockdown-protected
    staff-only namespace at cutover (Tony 2026-11-06: inhouse-after-sso);
    members/public events skip with a reason until member wiki accounts
    exist. meta.wiki_title wins; otherwise the title derives from
    meta.topic via lesson_wiki_title. meta.format='wikitext' passes the
    body through verbatim (the migrate path pre-converts); anything else
    is treated as lesson HTML and converted."""

    edit_label = "Education lesson"

    def __init__(self, api_url: str, username: str, password: str,
                 template: str = "แม่แบบ:Education", api=None,
                 name: str = "wiki-education", surface: str = "private",
                 namespace_prefix: str = "Education:"):
        super().__init__(api_url, username, password, template=template,
                         api=api, name=name, surface=surface,
                         namespace_prefix=namespace_prefix)
        self.kinds = frozenset(("lesson",))
        self.evidence_required = False

    def _title(self, ev: dict) -> str:
        meta = ev.get("meta") or {}
        title = str(meta.get("wiki_title") or "").strip() or \
            lesson_wiki_title(meta.get("topic") or ev["title"],
                              self.namespace_prefix)
        if (not title.startswith(self.namespace_prefix)
                or "\n" in title or "\r" in title):
            raise Skip(f"wiki title must be under {self.namespace_prefix}")
        return title

    def _wikitext(self, ev: dict) -> str:
        meta = ev.get("meta") or {}
        body = ev["body"]
        if str(meta.get("format") or "").strip().lower() != "wikitext":
            body = html_to_wikitext(body)
        lines = [
            f"{{{{{self.template}",
            f"|topic={meta.get('topic', ev['title'])}",
            f"|level={meta.get('level', '')}",
            f"|source={meta.get('lesson_source')
                          or meta.get('source', ev['source'])}",
            f"|learned_at={meta.get('learned_at', '')}",
            f"|next_review={meta.get('next_review', '')}",
            f"|status={meta.get('status', 'open')}",
            f"|updated={meta.get('updated', ev['occurred_at'][:10])}",
            f"|no_th={'1' if meta.get('no_th') else ''}",
            f"|event_id={ev['event_id']}",
            "}}", "",
            body, "",
        ]
        categories = ["Education"]
        level = str(meta.get("level") or "").strip()
        if level:
            categories.append(f"Education/Level/{level}")
        status = str(meta.get("status") or "").strip()
        if status:
            categories.append(f"Education/Status/{status}")
        topic = _topic_slug(str(meta.get("topic") or ""))
        if topic:
            categories.append(f"Education/Topics/{topic}")
        lines.extend(f"[[Category:{c}]]"
                     for c in dict.fromkeys(categories))
        return "\n".join(lines)


# --- noise policy -----------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _epoch(iso: str) -> float:
    try:
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


class NoisePolicy:
    """Rate/noise policy — 'do not publish every heartbeat'.

    - progress: one publish per (sink, topic) per progress_min_s.
    - alert:    identical (sink, topic, title) deduped inside alert_min_s.
    - telegram: any kind, min telegram_min_s per topic — the group is for
                concise notifications, not a stream.
    milestone/report/lesson/news are meaningful by definition and are
    never throttled (except the telegram floor above). event.force
    bypasses noise only — never visibility (a confidentiality boundary).
    """

    def __init__(self, path, progress_min_s=900, alert_min_s=60,
                 telegram_min_s=600):
        self.path = Path(path)
        self.progress_min_s = int(progress_min_s)
        self.alert_min_s = int(alert_min_s)
        self.telegram_min_s = int(telegram_min_s)

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, st: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        items = sorted(st.items(), key=lambda kv: kv[1])[-2000:]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(items)))
        tmp.replace(self.path)

    def check(self, sink_name: str, ev: dict, now: str | None = None):
        """None = allowed; else a suppression reason."""
        if ev.get("force"):
            return None
        now_e = _epoch(now or _now_iso())
        st = self._load()
        topic = topic_key(ev)

        def gap(key):
            last = st.get(key)
            return None if last is None else now_e - last

        if ev["kind"] == "progress":
            g = gap(f"p:{sink_name}:{topic}")
            if g is not None and g < self.progress_min_s:
                return (f"progress on {topic} published to {sink_name} "
                        f"{int(g)}s ago (min {self.progress_min_s}s)")
        if ev["kind"] == "alert":
            k = f"a:{sink_name}:{topic}:{ev['title'][:60]}"
            g = gap(k)
            if g is not None and g < self.alert_min_s:
                return f"identical alert published {int(g)}s ago"
        if sink_name == "telegram":
            g = gap(f"tg:{topic}")
            if g is not None and g < self.telegram_min_s:
                return (f"telegram notified {topic} {int(g)}s ago "
                        f"(min {self.telegram_min_s}s)")
        return None

    def stamp(self, sink_name: str, ev: dict,
              now: str | None = None) -> None:
        now_s = now or _now_iso()
        now_e = _epoch(now_s)
        st = self._load()
        topic = topic_key(ev)
        st[f"p:{sink_name}:{topic}"] = now_e
        if ev["kind"] == "alert":
            st[f"a:{sink_name}:{topic}:{ev['title'][:60]}"] = now_e
        if sink_name == "telegram":
            st[f"tg:{topic}"] = now_e
        self._save(st)


# --- outbox -----------------------------------------------------------------


class Outbox:
    """Durable delivery state in one directory:

      delivered.json  idempotency_key -> {at, frm, event_id, receipts}
      events.jsonl    append-only ledger of every accepted event +
                      its receipts (the audit-of-record)
      outbox.jsonl    sink deliveries pending retry
      dead.jsonl      deliveries that exhausted retries
    """

    DELIVERED_CAP = 5000
    MAX_ATTEMPTS = 5
    BASE_DELAY_S = 30
    MAX_DELAY_S = 1800

    def __init__(self, state_dir):
        self.dir = Path(state_dir)
        self.delivered_file = self.dir / "delivered.json"
        self.events_file = self.dir / "events.jsonl"
        self.outbox_file = self.dir / "outbox.jsonl"
        self.dead_file = self.dir / "dead.jsonl"

    def _read_delivered(self) -> dict:
        try:
            d = json.loads(self.delivered_file.read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def delivered(self, key: str):
        return self._read_delivered().get(key)

    def _append(self, path: Path, rec: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def note(self, ev: dict, frm: str, receipts: dict,
             now: str | None = None) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        d = self._read_delivered()
        rec = d.get(ev["idempotency_key"]) or {
            "event_id": ev["event_id"], "frm": frm,
            "at": now or _now_iso(), "receipts": {}}
        rec["receipts"].update(receipts)
        rec["at"] = now or rec["at"]
        d[ev["idempotency_key"]] = rec
        items = sorted(d.items(),
                       key=lambda kv: kv[1].get("at") or "")[
                -self.DELIVERED_CAP:]
        tmp = self.delivered_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(items), ensure_ascii=False))
        tmp.replace(self.delivered_file)
        self._append(self.events_file,
                     {"at": rec["at"], "frm": frm, "event": ev,
                      "receipts": receipts})

    def enqueue(self, ev: dict, sink: str, error: str,
                now: str | None = None) -> None:
        self._append(self.outbox_file, {
            "key": ev["idempotency_key"], "event_id": ev["event_id"],
            "event": ev, "sink": sink, "attempts": 0,
            "next_at": _epoch(now or _now_iso()) + self.BASE_DELAY_S,
            "last_error": str(error)[:400],
            "enqueued_at": now or _now_iso()})

    def _pending(self) -> list:
        try:
            return [json.loads(ln) for ln in
                    self.outbox_file.read_text().splitlines()
                    if ln.strip()]
        except OSError:
            return []

    def _write_pending(self, entries: list) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.outbox_file.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n"
                               for e in entries))
        tmp.replace(self.outbox_file)

    def drain(self, sinks: dict, now: str | None = None,
              frm: str = "outbox-drain") -> dict:
        """Retry due deliveries; backoff 30s*2^n capped 30m, dead-letter
        after MAX_ATTEMPTS. Returns a small summary — called piggyback
        on every /publish and by a timer later."""
        now_e = _epoch(now or _now_iso())
        keep, res = [], {"delivered": [], "retrying": 0, "dead": 0}
        for e in self._pending():
            if e.get("next_at", 0) > now_e:
                keep.append(e)
                continue
            sink = sinks.get(e.get("sink") or "")
            ev = e.get("event") or {}
            try:
                if sink is None:
                    raise Skip(f"unknown sink {e.get('sink')}")
                if not isinstance(ev, dict) or "kind" not in ev:
                    raise Skip("malformed outbox event")
                r = sink.publish(ev)
            except Skip as ex:          # will never succeed — dead-letter
                e["last_error"] = str(ex)
                self._append(self.dead_file, e)
                res["dead"] += 1
                continue
            except Exception as ex:
                e["attempts"] = int(e.get("attempts") or 0) + 1
                e["last_error"] = str(ex)[:400]
                if e["attempts"] >= self.MAX_ATTEMPTS:
                    self._append(self.dead_file, e)
                    res["dead"] += 1
                    continue
                e["next_at"] = now_e + min(
                    self.BASE_DELAY_S * (2 ** e["attempts"]),
                    self.MAX_DELAY_S)
                keep.append(e)
                res["retrying"] += 1
                continue
            rec = {"status": "delivered", "via": "outbox",
                   **dict(r or {})}
            self.note(ev, frm, {e["sink"]: rec})
            res["delivered"].append(
                {"key": e["key"], "sink": e["sink"]})
        self._write_pending(keep)
        res["pending"] = len(keep)
        return res

    def pending_count(self) -> int:
        return len(self._pending())


# --- orchestration ----------------------------------------------------------


def route_event(ev: dict, sinks: dict) -> list:
    explicit = ev.get("sinks")
    if explicit:
        return list(dict.fromkeys(explicit))
    return [s for s in DEFAULT_ROUTES.get(ev["kind"], []) if s in sinks]


def publish_event(body: dict, sinks: dict, outbox: Outbox,
                  noise: NoisePolicy | None = None, frm: str = "?",
                  now: str | None = None) -> dict:
    """Validate -> dedupe -> route -> deliver with per-sink receipts.

    Never raises for delivery failures: a sink that throws lands in the
    outbox and its receipt says `queued`. Validation problems raise
    PubError (400); the caller sees deduped receipts unchanged on a
    retried key."""
    ev = validate_event(body)
    if ev.get("sinks"):           # checked before dedupe: a retried key
        unknown = [s for s in ev["sinks"] if s not in sinks]
        if unknown:               # with a bad sink list is still a 400
            raise PubError(
                f"unknown sink(s): {', '.join(unknown)} "
                f"(have {sorted(sinks)})")
    prior = outbox.delivered(ev["idempotency_key"])
    if prior:
        return {"event_id": prior.get("event_id") or ev["event_id"],
                "idempotency_key": ev["idempotency_key"],
                "deduped": True,
                "receipts": prior.get("receipts") or {},
                "message": f"deduped {prior.get('event_id') or ev['event_id']}"}
    receipts = {}
    for name in route_event(ev, sinks):
        sink = sinks[name]
        reason = sink.check(ev)
        if reason:
            receipts[name] = {"status": "skipped", "reason": reason}
            continue
        if noise is not None:
            reason = noise.check(name, ev, now=now)
            if reason:
                receipts[name] = {"status": "suppressed",
                                  "reason": reason}
                continue
        try:
            r = sink.publish(ev)
            receipts[name] = {"status": "delivered", **dict(r or {})}
            if noise is not None:
                noise.stamp(name, ev, now=now)
        except Skip as e:
            receipts[name] = {"status": "skipped", "reason": str(e)}
        except Exception as e:
            outbox.enqueue(ev, name, str(e), now=now)
            receipts[name] = {"status": "queued",
                              "reason": str(e)[:300]}
    outbox.note(ev, frm, receipts, now=now)
    parts = " ".join(f"{n}={r['status']}" for n, r in receipts.items())
    return {"event_id": ev["event_id"],
            "idempotency_key": ev["idempotency_key"],
            "deduped": False, "receipts": receipts,
            "message": f"published {ev['event_id']}: {parts or 'no sinks'}"}
