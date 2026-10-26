#!/usr/bin/env python3
"""Project rollups — group kanban cards into named projects.

Convention (docs/ssot/infrastructure/ssot.project-lifecycle.yml): a
project is ONE ada-cms-pages doc + the `project: <slug>` tag on every
card that belongs to it ("page slug = card tag value"). A dedicated
`project:` card field (str or list) is honored the same way — both
sources union.

Shared by render-board.py / render-board2.py (payload + HTML) and
board-api.py (GET /cards?project=… query params).
"""
import re

PROJECT_TAG_RE = re.compile(
    r"^project\s*:\s*([a-z0-9][a-z0-9._-]{0,79})\s*$", re.I)

_PRI_RANK = {"high": 0, "medium": 1, "low": 3}


def card_projects(card: dict) -> list:
    """Project slugs a card belongs to — `project:` field (str|list)
    unioned with `project:<slug>` tags (space after ':' tolerated).
    Slugs normalize to lowercase so `Project: Foo` and `project:foo`
    land in the same group."""
    out = []
    p = card.get("project")
    if isinstance(p, str):
        p = [p]
    for v in (p if isinstance(p, list) else []):
        s = str(v).strip().lower()
        if s and s not in out:
            out.append(s)
    for t in card.get("tags") or []:
        m = PROJECT_TAG_RE.match(str(t).strip())
        if m and m.group(1).lower() not in out:
            out.append(m.group(1).lower())
    return out


def _pri_rank(c: dict) -> int:
    return _PRI_RANK.get(str(c.get("priority") or "").lower(), 2)


def _open_items(c: dict) -> int:
    n = sum(1 for r in c.get("requests") or []
            if isinstance(r, dict) and r.get("status") != "answered")
    a = c.get("ask")
    if isinstance(a, dict) and a.get("question") \
            and a.get("status") != "answered":
        n += 1
    elif isinstance(a, str) and a.strip():
        n += 1
    return n


def _first_open(c: dict) -> str:
    for r in c.get("requests") or []:
        if isinstance(r, dict) and r.get("status") != "answered" \
                and r.get("ask"):
            return str(r["ask"])
    a = c.get("ask")
    if isinstance(a, dict) and a.get("status") != "answered":
        return str(a.get("question") or "")
    if isinstance(a, str):
        return a.strip()
    return ""


def _stage(members: list) -> str:
    """Column-derived project stage — the fallback when the linked CMS
    page (whose `stage:` field is the steward-owned truth) is not
    readable, e.g. the static board render. Furthest live column wins."""
    cols = {(c.get("column") or "backlog") for c in members}
    if cols == {"done"}:
        return "done"
    for col, label in (("doing", "in flight"), ("review", "in review"),
                       ("backlog", "queued"), ("lab", "lab")):
        if col in cols:
            return label
    return "queued"


def _next_action(members: list):
    """The one line a project watcher needs next: an open ask/request on
    the highest-priority live card, else running/queued work, else the
    top of the backlog. None when every card is done."""
    live = [c for c in members if (c.get("column") or "backlog") != "done"]
    if not live:
        return None
    for c in sorted(live, key=_pri_rank):
        q = _first_open(c)
        if q:
            return {"id": c.get("id"), "kind": "ask", "text": q}
    for st in ("running", "queued"):
        hit = next((c for c in live
                    if (c.get("action") or {}).get("status") == st), None)
        if hit:
            return {"id": hit.get("id"), "kind": st,
                    "text": hit.get("title") or hit.get("id")}
    doing = next((c for c in live
                  if (c.get("column") or "") == "doing"), None)
    if doing:
        return {"id": doing.get("id"), "kind": "doing",
                "text": doing.get("title") or doing.get("id")}
    top = sorted(live, key=_pri_rank)[0]
    return {"id": top.get("id"), "kind": "next",
            "text": top.get("title") or top.get("id")}


def project_rollup(cards: list) -> list:
    """Per-project rollup rows, open work first. Each row: slug, member
    count, by_column tallies, derived stage, open ask/request count, a
    next_action line, and the member card list (id/title/column)."""
    groups = {}
    for c in cards:
        for slug in card_projects(c):
            groups.setdefault(slug, []).append(c)
    out = []
    for slug, members in groups.items():
        by_column = {}
        for c in members:
            col = c.get("column") or "backlog"
            by_column[col] = by_column.get(col, 0) + 1
        out.append({
            "slug": slug,
            "n": len(members),
            "by_column": by_column,
            "stage": _stage(members),
            "stage_source": "columns",
            "open": sum(_open_items(c) for c in members),
            "updated": max(str(c.get("updated") or "") for c in members),
            "next_action": _next_action(members),
            "cards": [{
                "id": c.get("id"),
                "title": c.get("title") or c.get("id"),
                "column": c.get("column") or "backlog",
                "priority": c.get("priority"),
                "updated": c.get("updated"),
                "needs_you": _open_items(c),
            } for c in members],
        })
    out.sort(key=lambda p: (0 if p["next_action"] else 1,
                            -p["open"], p["slug"]))
    return out


def matches(card: dict, slug: str) -> bool:
    return str(slug or "").strip().lower() in card_projects(card)
