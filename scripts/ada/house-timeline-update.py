#!/usr/bin/env python3
"""house-timeline-update.py — household device events -> CMS `house-timeline`.

Family per docs/kb/cms-page-standard.md §4 (mirrors timer-timeline):

  house-timeline              rollup — one row per device + merged recent feed
  house-timeline-<entity>     leaf   — event log per device (>=LEAF_MIN events)
  house-timeline-qc           leaf   — coverage/parse/self-checks

Source: ada-ha-events-<instance> collections on the mddb primary (:11023 —
memory plane; reads only). Pages publish to ada-cms-pages on mddb-cms
(:11027). The rollup also adopts any external leaf carrying
meta.parent=house-timeline, so other generators can join the family.

Runs on tony-dell (house-timeline.timer). Stdlib only.

Usage:
  house-timeline-update.py            # collect + publish
  house-timeline-update.py --dry-run  # render, write nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
MDDB_CMS = os.environ.get(
    "MDDB_CMS_URL", "http://100.102.134.91:11027/v1").rstrip("/")
EVENTS_COLLECTION = "ada-ha-events-tony"
COLLECTION = "ada-cms-pages"
PAGE = "house-timeline"
GENERATOR = "house-timeline-update.py"
VERSION = "1.0.0 2026-10-13"
ICT = dt.timezone(dt.timedelta(hours=7))

WINDOW_H = 72          # event window rendered
MAX_SCAN = 400         # events docs scanned (sorted newest-first)
LEAF_MIN = 3           # events in window to earn a leaf page
MAX_LEAVES = 25        # leaf cap by activity
PARENT_FEED_N = 25     # merged-feed rows on the rollup
LEAF_ROWS = 60         # rows per leaf page

EV_LINE = re.compile(
    r"^-\s+(\S+)\s+[—-]\s+(.+?)\s+\(`([^`]+)`\):\s+(.+)$")
EV_LINE_BARE = re.compile(r"^-\s+(\S+)\s+[—-]\s+(.+)$")


def _post(base: str, path: str, payload: dict, timeout: float = 60):
    req = urllib.request.Request(
        f"{base}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def search_all(base, collection, limit=500):
    docs, offset = [], 0
    while True:
        page = _post(base, "search",
                     {"collection": collection, "query": "",
                      "limit": limit, "offset": offset})
        if isinstance(page, dict):
            page = page.get("documents") or page.get("docs") or []
        docs += page
        if len(page) < limit:
            return docs
        offset += limit


# ---------- collect ----------

def collect_events(now):
    """Newest-first scan of ada-ha-events-*; -> (events, stats).

    event = {ts: datetime(utc), name, entity, change}
    """
    stats = {"docs_scanned": 0, "lines": 0, "parsed": 0,
             "bare": 0, "failed": 0, "out_of_window": 0}
    cutoff = now - dt.timedelta(hours=WINDOW_H)
    docs = search_all(MDDB, EVENTS_COLLECTION)
    docs.sort(key=lambda d: (d.get("meta") or {}).get("period_start", [""])[0],
              reverse=True)
    events = []
    for d in docs[:MAX_SCAN]:
        meta = d.get("meta") or {}
        pend = (meta.get("period_end") or [""])[0]
        stats["docs_scanned"] += 1
        for ln in (d.get("contentMd") or "").splitlines():
            ln = ln.strip()
            if not ln.startswith("- "):
                continue
            stats["lines"] += 1
            m = EV_LINE.match(ln)
            if m:
                ts_s, name, entity, change = m.groups()
                stats["parsed"] += 1
            else:
                m2 = EV_LINE_BARE.match(ln)
                if not m2:
                    stats["failed"] += 1
                    continue
                ts_s, name = m2.groups()
                entity, change = "", name
                stats["bare"] += 1
            try:
                ts = dt.datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
            except ValueError:
                stats["failed"] += 1
                continue
            if ts < cutoff:
                stats["out_of_window"] += 1
                continue
            events.append({"ts": ts, "name": name.strip(),
                           "entity": entity.strip(),
                           "change": change.strip()})
        if pend and pend < cutoff.isoformat():
            break  # docs are newest-first; everything else is older
    events.sort(key=lambda e: e["ts"], reverse=True)
    return events, stats


def device_of(ev):
    return ev["entity"] or ev["name"]


def leaf_key(entity):
    slug = re.sub(r"[^a-z0-9]+", "-",
                  entity.split(".", 1)[-1].lower()).strip("-") or "misc"
    return f"{PAGE}-{slug}"


# ---------- render ----------

def _fmt(ts):
    return ts.astimezone(ICT).strftime("%m-%d %H:%M")


def render_leaf(key, entity, name, evs, now):
    L = [f"# {name or entity} — activity {WINDOW_H}h to "
         f"{now.astimezone(ICT):%m-%d %H:%M} ICT\n",
         f"_{len(evs)} event(s) from ada-ha-events · "
         f"parent: [house-timeline](#/{PAGE})_\n",
         "| when | change |", "|---|---|"]
    for e in evs[:LEAF_ROWS]:
        L.append(f"| {_fmt(e['ts'])} | {e['change']} |")
    if len(evs) > LEAF_ROWS:
        L.append(f"\n_…{len(evs) - LEAF_ROWS} older events in window._")
    return "\n".join(L)


def render_rollup(by_device, external, now):
    L = [f"# House timeline — {now.astimezone(ICT):%Y-%m-%d %H:%M} ICT\n",
         f"Every household device with activity in the last {WINDOW_H}h, "
         "rolled up from its leaf page. Open a leaf for the full log.\n"]
    L += ["\n## Devices\n",
          "| device | events | last activity | leaf |",
          "|---|---|---|---|"]
    for entity, evs in sorted(by_device.items(),
                              key=lambda kv: -len(kv[1])):
        name = evs[0]["name"] or entity
        key = leaf_key(entity)
        has_leaf = len(evs) >= LEAF_MIN
        link = (f"[{key}](#/{key})" if has_leaf else "—")
        L.append(f"| {name} (`{entity}`) | {len(evs)} | "
                 f"{_fmt(evs[0]['ts'])} | {link} |")
    for d in external:
        m = d.get("meta") or {}
        title = (m.get("title") or [d["key"]])[0]
        upd = (m.get("updated") or ["-"])[0][:16]
        L.append(f"| {title} | — | {upd} | "
                 f"[{d['key']}](#/{d['key']}) |")
    all_evs = [e for evs in by_device.values() for e in evs]
    all_evs.sort(key=lambda e: e["ts"], reverse=True)
    L += [f"\n## Across the house — last {PARENT_FEED_N}\n",
          "| when | device | change |", "|---|---|---|"]
    for e in all_evs[:PARENT_FEED_N]:
        L.append(f"| {_fmt(e['ts'])} | {e['name'] or e['entity']} | "
                 f"{e['change']} |")
    L.append(f"\n---\n_generated by {GENERATOR} {VERSION} · source: "
             f"{EVENTS_COLLECTION} (mddb primary) · window {WINDOW_H}h_")
    return "\n".join(L)


def render_qc(stats, by_device, external, n_leaves, now):
    L = [f"# house-timeline QC — {now.astimezone(ICT):%Y-%m-%d %H:%M} ICT\n",
         "_How the house-timeline pages were produced and whether they can "
         "be trusted. parent: [house-timeline](#/house-timeline)_\n",
         "| check | value |", "|---|---|",
         f"| events docs scanned | {stats['docs_scanned']} |",
         f"| event lines seen | {stats['lines']} |",
         f"| parsed (entity) | {stats['parsed']} |",
         f"| parsed (bare) | {stats['bare']} |",
         f"| parse failures | {stats['failed']} |",
         f"| out-of-window dropped | {stats['out_of_window']} |",
         f"| devices in window | {len(by_device)} |",
         f"| leaf pages written | {n_leaves} |",
         f"| external leaves adopted | {len(external)} |",
         f"| window | {WINDOW_H}h |",
         f"| leaf threshold | ≥{LEAF_MIN} events |",
         f"| source | {EVENTS_COLLECTION} @ mddb primary |",
         f"| writer | {GENERATOR} {VERSION} |"]
    return "\n".join(L)


# ---------- publish ----------

def publish(key, body, now, role, title, domain, summary,
            extra_meta=None, dry=False):
    meta = {
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "lang": ["en"], "kind": ["report"], "attribute": ["report"],
        "report_role": [role], "generated_by": [GENERATOR],
        "domain": [domain], "fresh_for": ["1h"],
        "status": ["active"], "slug": [key],
        "sources": [f"{EVENTS_COLLECTION} collection (mddb :11023)"],
        "title": [title], "summary": [summary],
        "parent": [PAGE if role == "leaf" else "reports-index"],
        "written_by": ["house-timeline"],
    }
    if extra_meta:
        meta.update(extra_meta)
    if dry:
        print(f"--- {key} ({role}) ---\n{body[:600]}\n…[{len(body)}B]\n")
        return
    _post(MDDB_CMS, "add", {"collection": COLLECTION, "key": key,
                            "lang": "en", "contentMd": body,
                            "meta": meta}, timeout=120)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)

    events, stats = collect_events(now)
    by_device: dict[str, list] = {}
    for e in events:
        by_device.setdefault(device_of(e), []).append(e)
    # activity-ranked devices; leaves only for the busy ones
    leaf_devices = [k for k, _ in sorted(
        by_device.items(), key=lambda kv: -len(kv[1]))
        if len(by_device[k]) >= LEAF_MIN][:MAX_LEAVES]

    # adopt external leaves: meta.parent=house-timeline, not ours
    ours = {leaf_key(k) for k in leaf_devices} | {PAGE, f"{PAGE}-qc"}
    external = [d for d in search_all(MDDB_CMS, COLLECTION)
                if PAGE in ((d.get("meta") or {}).get("parent") or [])
                and d.get("key") not in ours]

    n_leaves = 0
    for entity in leaf_devices:
        evs = by_device[entity]
        name = evs[0]["name"] or entity
        publish(leaf_key(entity),
                render_leaf(leaf_key(entity), entity, name, evs, now),
                now, "leaf", f"{name} — activity {WINDOW_H}h",
                "home", f"{len(evs)} events in {WINDOW_H}h — device leaf "
                        f"of house-timeline", dry=args.dry_run)
        n_leaves += 1
    publish(PAGE, render_rollup(by_device, external, now), now, "rollup",
            f"House timeline — {now.astimezone(ICT):%Y-%m-%d %H:%M} ICT",
            "home", f"Household device activity rollup, {WINDOW_H}h — "
                    "one row per device + merged feed",
            dry=args.dry_run)
    publish(f"{PAGE}-qc",
            render_qc(stats, by_device, external, n_leaves, now),
            now, "qc", f"house-timeline QC — "
                       f"{now.astimezone(ICT):%Y-%m-%d %H:%M} ICT",
            "meta", "Provenance + self-checks for the house-timeline "
                    "family", dry=args.dry_run)
    print(f"house-timeline: {n_leaves} leaves + rollup + qc "
          f"({'dry-run' if args.dry_run else 'published'}; "
          f"{len(events)} events from {stats['docs_scanned']} docs)")


if __name__ == "__main__":
    main()
