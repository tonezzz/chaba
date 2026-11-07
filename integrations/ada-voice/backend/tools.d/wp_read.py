"""wp_read — read-only browse of the boards WordPress site: list
posts/pages/CPT entries and fetch one entry (incl. drafts) for preview.

Member-side half of card line-wp-site-manager P2: before this tool the
lanes could only WRITE (wp_post/cpt_post) — "is it up?", "what did we
post?", "read me the draft" had no answer path. action=list returns a
compact index (id/title/status/link); action=get returns the full
title + rendered body text for Ada to read back in chat — the draft
preview, since a WP draft link only renders for logged-in wp-admin
sessions (members don't have those).

Read-only by construction: every call is a GET through
backend/wp_client (same wp-boards.env app password as wp_post — reads
see private + draft records the anonymous edge can't).

Env (wp-boards.env on the backend host):
    WP_SITE_URL     — e.g. https://boards.surf-thailand.com/wp
    WP_APP_USER     — WP username the app password belongs to
    WP_APP_PASSWORD — application password (24 chars, revocable)
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from backend import wp_client as wp

DECLARATION = {
    "name": "wp_read",
    "description": (
        "Look at the boards WordPress site — action=list posts/pages "
        "(or a CPT kind) with optional status/person/search filters, "
        "action=get one entry by id or slug and return its title + "
        "body text to read back (draft preview — members have no "
        "wp-admin login, so the text is the preview). Read-only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "list | get",
            },
            "post_type": {
                "type": "string",
                "description": "posts (default), pages, or a CPT kind "
                               "like expense/contact/reminder/asset/"
                               "place/trip/news/lesson.",
            },
            "status": {
                "type": "string",
                "description": "publish (default), draft, private, "
                               "trash, or any.",
            },
            "person": {
                "type": "string",
                "description": "Filter posts by member tag: tony, kk, "
                               "nhong (list only).",
            },
            "search": {
                "type": "string",
                "description": "WP search terms (list only).",
            },
            "id": {
                "type": "integer",
                "description": "Post/page id for action=get.",
            },
            "slug": {
                "type": "string",
                "description": "Slug for action=get when the id is not "
                               "known.",
            },
            "limit": {
                "type": "integer",
                "description": "Max list rows, 1-20 (default 10).",
            },
            "full": {
                "type": "boolean",
                "description": "action=get: return the complete body "
                               "instead of the ~1200-char preview.",
            },
        },
        "required": ["action"],
    },
}

# post_type rides the REST route — keep it to the wp/v2 collection-name
# charset so a weird arg can't escape the collection shape.
_TYPE_RE = re.compile(r"^[a-z0-9_]+$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
PREVIEW_CHARS = 1200
LIST_MAX = 20


def _text(rendered: str) -> str:
    """rendered HTML -> speakable plain text."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", rendered or "")).strip()


async def _tag_id(client: httpx.AsyncClient, env: dict[str, str],
                  slug: str) -> int | None:
    """Read-only tag lookup — wp.ensure_tag would CREATE a missing tag,
    which a read tool must not do."""
    r = await wp.api(client, env, "GET", "tags", params={"slug": slug})
    tags = r.json() if r.status_code == 200 else []
    if isinstance(tags, list) and tags:
        return tags[0].get("id")
    return None


def _row(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p.get("id"),
        "title": _text((p.get("title") or {}).get("rendered") or ""),
        "status": p.get("status"),
        "date": (p.get("date") or "")[:10],
        "modified": (p.get("modified") or "")[:10],
        "link": wp.https(p.get("link") or ""),
    }


async def _list(client: httpx.AsyncClient, env: dict[str, str],
                args: dict[str, Any]) -> dict[str, Any]:
    post_type = str(args.get("post_type") or "posts").strip().lower()
    status = str(args.get("status") or "publish").strip().lower()
    search = str(args.get("search") or "").strip()
    person = str(args.get("person") or "").strip().lower()
    limit = min(int(args.get("limit") or 10), LIST_MAX)

    if not _TYPE_RE.match(post_type):
        return {"ok": False,
                "error": f"bad post_type {post_type!r} — posts, pages, "
                         "or a CPT kind (letters/digits/_)"}
    if status not in ("publish", "draft", "private", "trash",
                      "pending", "any"):
        return {"ok": False, "error": f"bad status {status!r}"}
    params: dict[str, Any] = {"per_page": limit, "status": status,
                              "_fields": "id,title,status,date,modified,link"}
    if search:
        params["search"] = search
    if person:
        if person not in wp.PEOPLE:
            return {"ok": False,
                    "error": f"person must be one of {wp.PEOPLE}"}
        if post_type != "posts":
            return {"ok": False,
                    "error": "person= filters posts by member tag — "
                             "CPT kinds attribute via saved_by meta "
                             "instead; drop person= and filter in chat"}
        tid = await _tag_id(client, env, person)
        if not tid:
            return {"ok": False,
                    "error": f"no member tag {person!r} on the site"}
        params["tags"] = tid

    r = await wp.api(client, env, "GET", post_type, params=params)
    if r.status_code != 200:
        return {"ok": False,
                "error": f"list failed {r.status_code}: {r.text[:160]}"}
    rows = r.json()
    if not isinstance(rows, list):
        return {"ok": False,
                "error": f"unexpected list shape for {post_type}"}
    return {"ok": True, "post_type": post_type, "status": status,
            "count": len(rows), "items": [_row(p) for p in rows]}


async def _get(client: httpx.AsyncClient, env: dict[str, str],
               args: dict[str, Any]) -> dict[str, Any]:
    post_type = str(args.get("post_type") or "posts").strip().lower()
    pid = args.get("id")
    slug = str(args.get("slug") or "").strip()
    full = bool(args.get("full"))

    if not _TYPE_RE.match(post_type):
        return {"ok": False,
                "error": f"bad post_type {post_type!r}"}
    if not pid and not slug:
        return {"ok": False, "error": "action=get needs id= or slug="}

    if pid:
        r = await wp.api(client, env, "GET", f"{post_type}/{int(pid)}")
    else:
        r = await wp.api(client, env, "GET", post_type,
                         params={"slug": slug, "status": "any",
                                 "per_page": 1})
    if r.status_code != 200:
        return {"ok": False,
                "error": f"get failed {r.status_code}: {r.text[:160]}"}
    data = r.json()
    if isinstance(data, list):
        if not data:
            return {"ok": False,
                    "error": f"no {post_type} entry for slug {slug!r}"}
        data = data[0]

    body = _text((data.get("content") or {}).get("rendered") or "")
    truncated = len(body) > PREVIEW_CHARS and not full
    if truncated:
        body = body[:PREVIEW_CHARS].rstrip() + " …"
    status = data.get("status")
    return {
        "ok": True,
        "id": data.get("id"),
        "post_type": data.get("type") or post_type,
        "title": _text((data.get("title") or {}).get("rendered") or ""),
        "status": status,
        "date": (data.get("date") or "")[:10],
        "modified": (data.get("modified") or "")[:10],
        "link": wp.https(data.get("link") or ""),
        "content": body,
        "truncated": truncated,
        # A draft's permalink only renders inside a wp-admin session —
        # members have no login, so 'content' above IS the preview.
        "note": (f"status is {status} — not publicly visible; read "
                 "the content back in chat as the preview, then "
                 "wp_update status=publish after the member says yes")
                if status != "publish" else None,
    }


async def run(runner: Any, **args: Any) -> dict:
    action = str(args.get("action") or "").strip().lower()
    env = wp.env()
    if not wp.configured(env):
        return {"ok": False,
                "error": "wp-boards.env missing WP_SITE_URL/"
                         "WP_APP_USER/WP_APP_PASSWORD on this host"}
    try:
        async with httpx.AsyncClient(timeout=30,
                                     follow_redirects=True) as client:
            if action == "list":
                return await _list(client, env, args)
            if action == "get":
                return await _get(client, env, args)
            return {"ok": False,
                    "error": "action must be list or get"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
