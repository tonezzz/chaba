"""wp_update — change an existing post or page on the boards WordPress
site: retitle, rewrite content, or move status
(draft -> publish, publish -> draft/private, ->trash).

Card line-wp-site-manager P3: LINE-driven site maintenance needs the
write side of the loop wp_post started — fix a typo, retitle, publish a
draft the member previewed via wp_read. Create stays with wp_post;
structured CPT records stay with their writers (cpt_post/place_report/
trip_calendar own their meta — a blind retitle of an expense would
desync its slug/meta contract, so post_type is limited to posts+pages).

Manifest policy=confirmed — the dispatch layer enforces
confirmed=true/confirm_token before run() is reached (audit-logged,
single-use bound tokens). The tool still double-checks nothing is
silently writable: every call is a real mutation of a public site.

Env (wp-boards.env on the backend host): same as wp_post —
    WP_SITE_URL, WP_APP_USER, WP_APP_PASSWORD
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from backend import wp_client as wp

DECLARATION = {
    "name": "wp_update",
    "description": (
        "Change an existing boards-site post or page — new title, new "
        "content, or a status move (publish/draft/private/trash — use "
        "status=publish to push a previewed draft live). Confirmed "
        "write: describe the exact change, get an explicit yes, then "
        "call with confirmed=true. Find the id with wp_read; new posts "
        "go to wp_post."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "integer",
                "description": "Post or page id (wp_read list/get).",
            },
            "post_type": {
                "type": "string",
                "description": "posts (default) or pages.",
            },
            "title": {
                "type": "string",
                "description": "Replacement title.",
            },
            "content": {
                "type": "string",
                "description": "Replacement body text — REPLACES the "
                               "whole content, it is not appended.",
            },
            "status": {
                "type": "string",
                "description": "publish | draft | private | trash. "
                               "publish makes a draft live; trash is "
                               "restorable.",
            },
            "confirmed": {
                "type": "boolean",
                "description": "Required — set true only after the "
                               "user explicitly confirmed the change.",
            },
        },
        "required": ["id"],
    },
}

_TYPE_RE = re.compile(r"^[a-z0-9_]+$")
# posts+pages only — CPT kinds carry a slug/meta contract owned by
# their writer tools (cpt_post upserts by slug; a retitle here would
# fork the record).
_EDITABLE_TYPES = {"posts", "pages"}
_STATUSES = {"publish", "draft", "private", "trash"}
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _text(rendered: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", rendered or "")).strip()


async def run(runner: Any, **args: Any) -> dict:
    pid = args.get("id")
    post_type = str(args.get("post_type") or "posts").strip().lower()
    title = str(args.get("title") or "").strip()
    content = str(args.get("content") or "")
    status = str(args.get("status") or "").strip().lower()

    if not pid:
        return {"ok": False, "error": "id required (wp_read list/get)"}
    if post_type not in _EDITABLE_TYPES:
        return {"ok": False,
                "error": "wp_update edits posts/pages only — CPT "
                         "records (expense/contact/reminder/asset/"
                         "place/trip) belong to their writer tools"}
    if not _TYPE_RE.match(post_type):
        return {"ok": False, "error": f"bad post_type {post_type!r}"}
    if status and status not in _STATUSES:
        return {"ok": False,
                "error": f"status must be one of {sorted(_STATUSES)}"}
    if not title and not content.strip() and not status:
        return {"ok": False,
                "error": "nothing to change — pass title=, content=, "
                         "and/or status="}
    env = wp.env()
    if not wp.configured(env):
        return {"ok": False,
                "error": "wp-boards.env missing WP_SITE_URL/"
                         "WP_APP_USER/WP_APP_PASSWORD on this host"}

    try:
        async with httpx.AsyncClient(timeout=30,
                                     follow_redirects=True) as client:
            # Read first — the result reports the transition
            # ("draft -> publish") and a 404 here is the honest
            # 'post does not exist' miss before any write is claimed.
            r = await wp.api(client, env, "GET",
                             f"{post_type}/{int(pid)}")
            if r.status_code == 404:
                return {"ok": False,
                        "error": f"no {post_type} entry with id {pid} "
                                 "— check wp_read list"}
            if r.status_code != 200:
                return {"ok": False,
                        "error": f"lookup failed {r.status_code}: "
                                 f"{r.text[:160]}"}
            before = r.json()
            prev_status = before.get("status")
            prev_title = _text(
                (before.get("title") or {}).get("rendered") or "")

            payload: dict[str, Any] = {}
            if title:
                payload["title"] = title
            if content.strip():
                payload["content"] = wp.paragraphs(content)
            if status:
                payload["status"] = status
            r = await wp.api(client, env, "POST",
                             f"{post_type}/{int(pid)}", json=payload)
            if r.status_code not in (200, 201):
                return {"ok": False,
                        "error": f"update failed {r.status_code}: "
                                 f"{r.text[:160]}"}
            after = r.json()
            new_status = after.get("status")
            return {
                "ok": True,
                "id": after.get("id"),
                "post_type": after.get("type") or post_type,
                "title": _text(
                    (after.get("title") or {}).get("rendered") or ""),
                "prev_title": prev_title if title else None,
                "status": new_status,
                "transition": (f"{prev_status} -> {new_status}"
                               if status and prev_status != new_status
                               else None),
                "link": wp.https(after.get("link") or ""),
                "note": ("live — the link resolves publicly"
                         if new_status == "publish" else
                         f"status is {new_status} — not publicly "
                         "visible" if new_status != "trash" else
                         "in the trash — restorable via "
                         "status=draft/publish"),
            }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
