#!/usr/bin/env python3
"""media-inbox-update.py — LINE/TG received-media manifest -> CMS page family.

Family per docs/kb/media-inbox-standard.md (mirrors house-timeline-update.py,
lane mechanics from trip-calendar.py):

  media-inbox               rollup — day-grouped table, newest first
  media-<messageId>         leaf   — receipt record for one item
  media-<messageId>-extract leaf   — doc_read extraction (doc_read-owned,
                                     this generator NEVER renders it)
  media-inbox-qc            leaf   — coverage/dup/parse self-checks

Dedup tiers (standard §3):
  T1 transport  manifest lines grouped by message_id -> ONE leaf per mid,
                extra redelivery lines noted on the leaf, not new leaves.
  T2 content    same sha256 under a new mid -> resend gets its own leaf
                carrying duplicate_of: media-<first-mid>.
  T3 extraction is doc_read's job (media-<mid>-extract leaf as the cache).

Lane attribution: a manifest line belongs to the lane when its `persona`
field matches the lane's persona set (relay writes persona at ingest).
Legacy lines without persona fall back to MEDIA_INBOX_CHATS (the lane's
chat ids, comma-separated). Runs on idc03 as media-inbox-update-<lane>
timers — one timer per lane, each bound to that lane's CMS collection.

Stdlib only. Env:
  MDDB_BASE_URL           CMS plane (default http://100.102.134.91:11027/v1)
  LINE_MEDIA_ARCHIVE_DIR  default ~/.local/share/ada/line-media
  MEDIA_INBOX_CHATS       comma-sep chat ids attributed to this lane
                          (fallback for manifest lines without persona)
  ADA_CMS_BASE            viewer base for view_url in --json output

Usage:
  media-inbox-update.py --lane tony            # collect + publish
  media-inbox-update.py --lane kk --dry-run    # render, write nothing
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

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(REPO / "scripts" / "lib"))

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11027/v1").rstrip("/")
ARCHIVE_DIR = Path(os.environ.get(
    "LINE_MEDIA_ARCHIVE_DIR",
    os.path.expanduser("~/.local/share/ada/line-media")))
LANE_CHATS = {c.strip() for c in
              os.environ.get("MEDIA_INBOX_CHATS", "").split(",") if c.strip()}

GENERATOR = "media-inbox-update.py"
VERSION = "1.0.0 2026-10-13"
ICT = dt.timezone(dt.timedelta(hours=7))
PAGE = "media-inbox"

WINDOW_DAYS = 30       # rollup covers the last N days
MAX_LEAVES = 200       # receipt leaf cap per run (newest first)
LANES = {
    "tony": {
        "collection": "ada-cms-pages",
        "personas": {"ada", "chaba"},
    },
    "kk": {
        "collection": "ada-cms-pages-kk",
        "personas": {"kaewta"},
    },
    "kk-dev": {
        "collection": "ada-cms-pages-kk-dev",
        "personas": {"kaewta-cms"},
    },
}


def _post(path: str, payload: dict, timeout: float = 60):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _md_escape(t: str) -> str:
    return str(t).replace("|", "\\|").replace("\n", " ").strip()


def _fmt_size(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "-"
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


# ---------- collect ----------

def load_manifest(lane: str):
    """manifest.jsonl -> lane-attributed items grouped by message_id.

    -> (items, stats). item = {mid, ts, sender, chat_id, kind, mime,
    file_name, size, path, url, sha256, persona, redeliveries}
    """
    stats = {"lines": 0, "parsed": 0, "failed": 0,
             "other_lane": 0, "no_mid": 0, "t1_extra": 0}
    mf = ARCHIVE_DIR / "manifest.jsonl"
    personas = LANES[lane]["personas"]
    by_mid: dict[str, dict] = {}
    order: list[str] = []
    if mf.is_file():
        for ln in mf.read_text(errors="replace").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            stats["lines"] += 1
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                stats["failed"] += 1
                continue
            persona = str(e.get("persona") or "").strip()
            if persona:
                if persona not in personas:
                    stats["other_lane"] += 1
                    continue
            elif str(e.get("chat_id") or "") not in LANE_CHATS:
                stats["other_lane"] += 1
                continue
            mid = str(e.get("message_id") or "").strip()
            if not mid:
                stats["no_mid"] += 1
                continue
            stats["parsed"] += 1
            if mid in by_mid:
                # T1 transport dedup — same mid redelivered by LINE: keep
                # the first line, count the redelivery on the item.
                by_mid[mid]["redeliveries"] += 1
                stats["t1_extra"] += 1
                continue
            p = Path(str(e.get("path") or ""))
            size = e.get("size") or e.get("file_size")
            if not size and p.is_file():
                try:
                    size = p.stat().st_size
                except OSError:
                    pass
            try:
                ts = dt.datetime.fromisoformat(
                    str(e.get("ts") or "").replace("Z", "+00:00"))
            except ValueError:
                ts = dt.datetime.now().astimezone()
            by_mid[mid] = {
                "mid": mid, "ts": ts,
                "sender": str(e.get("sender") or "?"),
                "chat_id": str(e.get("chat_id") or ""),
                "kind": str(e.get("kind") or "file"),
                "mime": str(e.get("mime") or ""),
                "file_name": str(e.get("file_name") or ""),
                "size": size,
                "path": str(e.get("path") or ""),
                "url": str(e.get("url") or ""),
                "sha256": str(e.get("sha256") or ""),
                "persona": persona,
                "redeliveries": 0,
            }
            order.append(mid)
    items = [by_mid[m] for m in order]
    return items, stats


def mark_duplicates(items: list[dict]) -> int:
    """T2 content dedup: same sha256 -> duplicate_of first mid.

    Items keep manifest order; the earliest sha256 occurrence is the
    canonical copy. Returns the number of marked duplicates."""
    first: dict[str, str] = {}
    n = 0
    for it in sorted(items, key=lambda x: x["ts"]):
        h = it["sha256"]
        it["duplicate_of"] = None
        if not h:
            continue
        if h in first:
            it["duplicate_of"] = first[h]
            n += 1
        else:
            first[h] = it["mid"]
    return n


# ---------- render ----------

def _when(ts: dt.datetime) -> str:
    return ts.astimezone(ICT).strftime("%Y-%m-%d %H:%M")


def leaf_key(mid: str) -> str:
    return f"media-{mid}"


def extract_key(mid: str) -> str:
    return f"media-{mid}-extract"


def render_leaf(it: dict, now: dt.datetime) -> str:
    name = it["file_name"] or it["mid"]
    L = [f"# Media — {_md_escape(name)} · {_when(it['ts'])}\n",
         f"{_md_escape(it['sender'])} sent {it['kind']} "
         f"`{_md_escape(name)}` on {_when(it['ts'])} "
         f"via chat `{it['chat_id']}`.\n"]
    url = it["url"]
    if it["kind"] == "image":
        # linked image: CMS renders a > img as a thumbnail, click -> full
        L += ["## Preview\n", f"[![{_md_escape(name)}]({url})]({url})\n"]
    elif it["kind"] in ("video", "audio"):
        spec = json.dumps({"url": url, "type": it["kind"],
                           "caption": name})
        L += ["## Preview\n", f"```media\n{spec}\n```\n"]
    L += ["## Receipt\n",
         "| field | value |", "|---|---|",
         f"| sender | {_md_escape(it['sender'])} |",
         f"| chat | `{it['chat_id']}` |",
         f"| kind | {it['kind']} |",
         f"| file | {_md_escape(name)} ({it['mime']}, "
         f"{_fmt_size(it['size'])}) |",
         f"| message_id | `{it['mid']}` |",
         f"| sha256 | `{it['sha256'][:16] or '—'}` |",
         f"| archive | [{Path(it['path']).name}]({it['url']}) |"]
    dup = it.get("duplicate_of")
    if dup:
        L.append(f"| duplicate_of | [{leaf_key(dup)}](#/{leaf_key(dup)}) "
                 f"(same sha256) |")
    else:
        L.append("| duplicate_of | — |")
    if it["redeliveries"]:
        L.append(f"| redeliveries | {it['redeliveries']} extra manifest "
                 f"line(s) — LINE transport retry, one leaf kept |")
    L.append("\n---\n_meta: parent=media-inbox · report_role=leaf · "
             "sources=manifest.jsonl_\n")
    return "\n".join(L)


def render_rollup(items: list[dict], existing: set[str], now: dt.datetime,
                  days: int) -> str:
    cutoff = now.astimezone(ICT).date() - dt.timedelta(days=days)
    shown = [it for it in items if it["ts"].astimezone(ICT).date() > cutoff]
    shown.sort(key=lambda x: x["ts"], reverse=True)
    L = [f"# Media inbox — {now.astimezone(ICT):%Y-%m-%d %H:%M} ICT\n",
         f"Files/photos/clips received over LINE in the last {days} "
         f"days. One receipt leaf per item — the extract column links "
         f"doc_read's cached extraction when it exists.\n"]
    cur_day = None
    for it in shown:
        day = it["ts"].astimezone(ICT).date().isoformat()
        if day != cur_day:
            cur_day = day
            L += [f"\n## {day}\n",
                  "| when | sender | file | kind | preview | dup | leaf | "
                  "extract |",
                  "|---|---|---|---|---|---|---|---|"]
        name = _md_escape(it["file_name"] or it["mid"])
        dup = it.get("duplicate_of")
        dup_s = (f"↳ [`{dup[:12]}`](#/{leaf_key(dup)})" if dup else "—")
        ext = extract_key(it["mid"])
        ext_s = f"[extract](#/{ext})" if ext in existing else "—"
        # linked image -> leaf; CMS renders a > img as a small thumb
        prev = (f"[![{name}]({it['url']})](#/{leaf_key(it['mid'])})"
                if it["kind"] == "image" else "—")
        L.append(f"| {it['ts'].astimezone(ICT):%H:%M} | "
                 f"{_md_escape(it['sender'])} | {name} | {it['kind']} | "
                 f"{prev} | "
                 f"{dup_s} | [{leaf_key(it['mid'])}](#/{leaf_key(it['mid'])})"
                 f" | {ext_s} |")
    if not shown:
        L.append(f"\n_No media received in the last {days} days._")
    L.append(f"\n---\n_generated by {GENERATOR} {VERSION} · source: "
             f"manifest.jsonl ({ARCHIVE_DIR}) · window {days}d · "
             f"QC: [media-inbox-qc](#/media-inbox-qc)_")
    return "\n".join(L)


def render_qc(items, stats, n_dups, existing, lane, collection,
              now, days) -> str:
    receipt_keys = {leaf_key(i["mid"]) for i in items}
    stale = sorted(k for k in existing
                   if k.startswith("media-")
                   and not k.endswith("-extract")
                   and k not in receipt_keys
                   and k != PAGE)
    missing = sorted(receipt_keys - existing)
    extracts = sorted(k for k in existing if k.endswith("-extract"))
    L = [f"# media-inbox QC — {now.astimezone(ICT):%Y-%m-%d %H:%M} ICT\n",
         "_How the media-inbox pages were produced and whether they can "
         "be trusted. parent: [media-inbox](#/media-inbox)_\n",
         "| check | value |", "|---|---|",
         f"| lane / collection | {lane} / {collection} |",
         f"| manifest lines seen | {stats['lines']} |",
         f"| attributed to lane | {stats['parsed']} |",
         f"| other-lane filtered | {stats['other_lane']} |",
         f"| parse failures | {stats['failed']} |",
         f"| lines without message_id | {stats['no_mid']} |",
         f"| T1 redelivery lines folded | {stats['t1_extra']} |",
         f"| unique items (leaves) | {len(items)} |",
         f"| T2 duplicate items | {n_dups} |",
         f"| receipt leaves present | {len(receipt_keys & existing)} |",
         f"| receipt leaves missing | {len(missing)} |",
         f"| stale leaves (no manifest) | {len(stale)} |",
         f"| extract leaves (doc_read) | {len(extracts)} |",
         f"| rollup window | {days}d |",
         f"| source | {ARCHIVE_DIR}/manifest.jsonl |",
         f"| writer | {GENERATOR} {VERSION} |"]
    if n_dups:
        L += ["\n## Duplicate chains (T2 — same bytes, new message)\n",
              "| item | duplicate_of |", "|---|---|"]
        for it in items:
            if it.get("duplicate_of"):
                L.append(f"| {leaf_key(it['mid'])} | "
                         f"{leaf_key(it['duplicate_of'])} |")
    if missing:
        L += ["\n## Missing receipt leaves\n"]
        L += [f"- `{k}`" for k in missing]
    if stale:
        L += ["\n## Stale leaves (manifest line gone)\n"]
        L += [f"- `{k}`" for k in stale[:30]]
    L.append("\n---\n_meta: parent=media-inbox · report_role=qc_")
    return "\n".join(L)


# ---------- publish ----------

def publish(collection, key, body, now, role, title, domain, summary,
            lane, dry=False):
    meta = {
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "lang": ["en"], "kind": ["report"], "attribute": ["report"],
        "report_role": [role], "generated_by": [GENERATOR],
        "domain": [domain], "fresh_for": ["1h"],
        "status": ["active"], "slug": [key],
        "sources": ["LINE media manifest.jsonl"],
        "title": [title], "summary": [summary],
        "parent": [PAGE if role == "leaf" else "reports-index"],
        "instance": [lane],
        "written_by": ["media-inbox"],
    }
    if dry:
        print(f"--- {key} ({role}) ---\n{body[:800]}\n…[{len(body)}B]\n")
        return
    _post("add", {"collection": collection, "key": key, "lang": "en",
                  "contentMd": body, "meta": meta}, timeout=120)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lane", default=os.environ.get("ADA_CMS_LANE", "tony"),
                    choices=sorted(LANES),
                    help="CMS lane (collection + persona attribution)")
    ap.add_argument("--days", type=int, default=WINDOW_DAYS,
                    help=f"rollup window in days (default {WINDOW_DAYS})")
    ap.add_argument("--dry-run", action="store_true",
                    help="render to stdout, write nothing")
    ap.add_argument("--json", action="store_true",
                    help="print machine-readable result summary")
    args = ap.parse_args()
    lane = args.lane
    collection = LANES[lane]["collection"]
    now = dt.datetime.now(dt.timezone.utc)

    items, stats = load_manifest(lane)
    n_dups = mark_duplicates(items)
    items.sort(key=lambda x: x["ts"], reverse=True)

    # coverage scan: receipt/extract/stale detection needs the collection
    existing: set[str] = set()
    if not args.dry_run:
        try:
            from cms_index import list_docs
            existing = {d.get("key") for d in list_docs(MDDB, collection)}
        except Exception as exc:
            print(f"warn: coverage scan failed: {exc}", file=sys.stderr)

    n_leaves = 0
    for it in items[:MAX_LEAVES]:
        name = it["file_name"] or it["mid"]
        publish(collection, leaf_key(it["mid"]), render_leaf(it, now),
                now, "leaf", f"Media — {name} {_when(it['ts'])[:10]}",
                "media", f"Receipt for {it['kind']} '{name}' from "
                         f"{it['sender']} ({_when(it['ts'])})",
                lane, dry=args.dry_run)
        n_leaves += 1
    publish(collection, PAGE,
            render_rollup(items, existing, now, args.days),
            now, "rollup",
            f"Media inbox — {now.astimezone(ICT):%Y-%m-%d %H:%M} ICT",
            "media", f"Received-media rollup, last {args.days}d — "
                     f"{len(items)} items",
            lane, dry=args.dry_run)
    publish(collection, f"{PAGE}-qc",
            render_qc(items, stats, n_dups, existing, lane, collection,
                      now, args.days),
            now, "qc",
            f"media-inbox QC — {now.astimezone(ICT):%Y-%m-%d %H:%M} ICT",
            "meta", "Provenance + self-checks for the media-inbox family",
            lane, dry=args.dry_run)

    idx_ok = True
    if not args.dry_run:
        try:
            from cms_index import regen_reports_index
            regen_reports_index(MDDB, written_by=GENERATOR,
                                collection=collection, instance=lane)
        except Exception as exc:
            idx_ok = False
            print(f"warn: reports-index regen failed ({exc})",
                  file=sys.stderr)

    result = {
        "ok": True, "lane": lane, "collection": collection,
        "items": len(items), "leaves": n_leaves,
        "t1_folded": stats["t1_extra"], "t2_dups": n_dups,
        "index_regen": idx_ok,
        "view_url": os.environ.get(
            "ADA_CMS_BASE", "https://idc03.taila0626a.ts.net/cms/"
        ) + "#/media-inbox",
        "stats": stats,
    }
    if args.json:
        print(json.dumps(result))
    else:
        print(f"media-inbox[{lane}]: {n_leaves} leaves + rollup + qc "
              f"({'dry-run' if args.dry_run else 'published'}; "
              f"{len(items)} items, {n_dups} dups, "
              f"{stats['t1_extra']} redeliveries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
