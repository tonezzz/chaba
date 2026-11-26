#!/usr/bin/env python3
"""kanban-stats — board statistics as a layered-reporting node.

L2-domain node `kanban` (docs/ssot/infrastructure/ssot.reports.yml).
Reads docs/ssot/kanban/cards/*.yml and emits:

  reports/kanban/kanban-stats.yml   rolling machine artifact (overwritten)
  reports/kanban/meta.yml           node meta via scripts/lib/report.py
  ~/var/chaba/reports/timeline.jsonl  one appended event
  stacks/web/public/apps/system-report/data/kanban.md  small md rollup

Runs under kanban-sync.timer (15 min) inside the chaba-kanban-sync
worktree; every output is mirrored into the served chaba-tony-dell
checkout when it exists — the same dual-root pattern report-system.py
uses, since that is the tree the web container bind-mounts.

Card timestamps (`updated`, `comms[].at`, `claim.since`) are written by
board-api/kanban-dispatch as naive "%Y-%m-%d %H:%M" in Asia/Bangkok —
naive values are interpreted as UTC+7.

Usage:
  python3 scripts/board/kanban-stats.py              # compute + write
  python3 scripts/board/kanban-stats.py --check      # print stats + md only
  python3 scripts/board/kanban-stats.py --cards-dir <dir>  # other card source
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import card_io  # noqa: E402
from lib.report import append_timeline, now_iso, write_meta  # noqa: E402

def _act(card: dict) -> dict:
    """card['action'] read accessor — schema says dict, but marker cards
    carry scalars ('spec-review'). Returns {} for non-dict WITHOUT
    writing, so read-only passes don't stamp action:{} onto cards."""
    a = card.get("action")
    return a if isinstance(a, dict) else {}

NODE = "kanban"
LAYER = "L2-domain"
PURPOSE = ("Board health — column counts, dispatch throughput, open "
           "requests, stale review lane")
GENERATED_BY = "scripts/board/kanban-stats.py via kanban-sync.timer"

CARDS_DIR = REPO / "docs" / "ssot" / "kanban" / "cards"
OUT_DIR = "reports/kanban"
WEB_DATA = ("stacks", "web", "public", "apps", "system-report", "data")
# The web container bind-mounts this checkout's stacks/web — mirror
# outputs there so the served system-report page sees them regardless
# of which worktree the timer ran in.
SERVED_ROOT = Path("/home/tony/CascadeProjects/chaba-tony-dell")

BANGKOK = datetime.timezone(datetime.timedelta(hours=7))
STALE_REVIEW_H = 48
TOUCHED_H = 24
DISPATCH_DAYS = 7
DEAD_LETTER_DAYS = 7

_ANSWER_SWEEP_MOD = None


def _answer_sweep_pending(card: dict) -> int | None:
    """Count of answered-but-unexecuted requests on a card, via
    answer-sweep.pending() so the dead-letter definition can never
    drift from the sweep's own. None when the module can't load —
    the stat degrades, it never breaks the report."""
    global _ANSWER_SWEEP_MOD
    if _ANSWER_SWEEP_MOD is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "answer_sweep",
            Path(__file__).resolve().parent / "answer-sweep.py")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            _ANSWER_SWEEP_MOD = mod
        except Exception:
            _ANSWER_SWEEP_MOD = False
    if not _ANSWER_SWEEP_MOD:
        return None
    try:
        return len(_ANSWER_SWEEP_MOD.pending(card))
    except Exception:
        return None

_RE_DISPATCHED = re.compile(r"^dispatched \S+")
_RE_FINISHED = re.compile(r"^run finished")
_RE_FAILED = re.compile(r"^dispatch failed")

_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def parse_ts(value) -> datetime.datetime | None:
    """Card timestamps -> aware datetime. Naive = Asia/Bangkok."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    elif isinstance(value, datetime.date):
        dt = datetime.datetime(value.year, value.month, value.day)
    else:
        s = str(value).strip().strip("'\"")
        dt = None
        try:
            dt = datetime.datetime.fromisoformat(s)
        except ValueError:
            for fmt in _TS_FORMATS:
                try:
                    dt = datetime.datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=BANGKOK)


def load_cards(cards_dir: Path) -> list[dict]:
    cards = []
    for p in sorted(cards_dir.glob("*.yml")):
        try:
            c = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if not isinstance(c, dict):
            continue
        c.setdefault("id", p.stem)
        cards.append(c)
    return cards


def last_touched(card: dict) -> datetime.datetime | None:
    stamps = [parse_ts(card.get("updated")),
              parse_ts((card.get("claim") or {}).get("since"))]
    stamps += [parse_ts(e.get("at"))
               for e in card.get("comms") or [] if isinstance(e, dict)]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


def collect(cards: list[dict], now: datetime.datetime) -> dict:
    columns: dict[str, int] = {}
    action_status: dict[str, int] = {}
    open_requests: list[dict] = []
    touched_24h = 0
    stale_review: list[dict] = []
    dispatched_n = finished_n = failed_n = 0
    cycle_h: list[float] = []

    touched_cut = now - datetime.timedelta(hours=TOUCHED_H)
    stale_cut = now - datetime.timedelta(hours=STALE_REVIEW_H)
    disp_cut = now - datetime.timedelta(days=DISPATCH_DAYS)
    dead_cut = now - datetime.timedelta(days=DEAD_LETTER_DAYS)
    awaiting_n = 0
    dead_letters: list[dict] = []
    # DEV-0045 lane-routing watch: bucket stamped action.lane on open
    # cards by lane_source provenance. 'pin' (lane with no
    # lane_source) is an author-set route that wins forever; every
    # other source is a classifier/claim stamp that re-evaluates on
    # re-queue — the matrix makes misroute cohorts (e.g. free_lane
    # kw hits, fallback->devin) visible on the 15m report.
    lane_routing = {"stamped": 0, "unstamped_dispatch": 0,
                    "cells": {}}

    for c in cards:
        col = str(c.get("column") or "backlog")
        columns[col] = columns.get(col, 0) + 1

        a = _act(c)
        st = str(a.get("status")) if a.get("status") else "none"
        action_status[st] = action_status.get(st, 0) + 1

        if col != "done":
            if a.get("lane"):
                lane_routing["stamped"] += 1
                cell = lane_routing["cells"].setdefault(
                    str(a["lane"]), {})
                src = str(a.get("lane_source") or "pin")
                cell[src] = cell.get(src, 0) + 1
            elif str(a.get("type") or "") == "dispatch":
                lane_routing["unstamped_dispatch"] += 1

        for r in c.get("requests") or []:
            if isinstance(r, dict) and r.get("status") == "open":
                open_requests.append({
                    "card": c["id"],
                    "request": r.get("id"),
                    "ask": str(r.get("ask") or "")[:120],
                })
        # card-level ask counts as one open item (board-structured-responses)
        ask = c.get("ask")
        if isinstance(ask, dict) and ask.get("question") \
                and ask.get("status") != "answered":
            open_requests.append({
                "card": c["id"],
                "request": "ask",
                "ask": str(ask.get("question") or "")[:120],
            })

        touched = last_touched(c)
        if touched and touched >= touched_cut:
            touched_24h += 1
        # dead-letter aging (KNB-0180): awaiting_action cards nobody
        # has touched in DEAD_LETTER_DAYS are the answered-but-
        # unexecuted pile — count them so they cannot grow silently
        if c.get("awaiting_action"):
            awaiting_n += 1
            if touched is None or touched < dead_cut:
                dead_letters.append({
                    "id": c["id"],
                    "age_d": (round((now - touched).total_seconds() / 86400, 1)
                              if touched else None),
                    "unanswered": _answer_sweep_pending(c),
                })
        if col == "review" and (touched is None or touched < stale_cut):
            age_h = (round((now - touched).total_seconds() / 3600, 1)
                     if touched else None)
            stale_review.append({"id": c["id"], "age_h": age_h})

        dispatched = None
        for e in c.get("comms") or []:
            if not isinstance(e, dict):
                continue
            at = parse_ts(e.get("at"))
            if not at:
                continue
            text = str(e.get("text") or "")
            if _RE_DISPATCHED.match(text):
                dispatched = at
                if at >= disp_cut:
                    dispatched_n += 1
            elif _RE_FINISHED.match(text):
                if at >= disp_cut:
                    finished_n += 1
                if dispatched and at >= dispatched:
                    cycle_h.append(
                        (at - dispatched).total_seconds() / 3600)
                    dispatched = None
            elif _RE_FAILED.match(text):
                dispatched = None
                if at >= disp_cut:
                    failed_n += 1

    cycle_h.sort()
    stats = {
        "generated_at": now_iso(),
        "cards_total": len(cards),
        "columns": dict(sorted(columns.items())),
        "action_status": dict(sorted(action_status.items())),
        "open_requests": {
            "count": len(open_requests),
            "items": open_requests,
        },
        "touched_24h": touched_24h,
        "dispatch_7d": {
            "window_days": DISPATCH_DAYS,
            "dispatched": dispatched_n,
            "finished": finished_n,
            "failed": failed_n,
            "per_day": round(finished_n / DISPATCH_DAYS, 2),
            "median_cycle_h": (round(cycle_h[len(cycle_h) // 2], 1)
                               if cycle_h else None),
        },
        "stale_review": {
            "threshold_h": STALE_REVIEW_H,
            "count": len(stale_review),
            "cards": sorted(stale_review,
                            key=lambda r: -(r["age_h"] or 1e9)),
        },
        "dead_letters": {
            "threshold_d": DEAD_LETTER_DAYS,
            "awaiting_action": awaiting_n,
            "count": len(dead_letters),
            "cards": sorted(dead_letters,
                            key=lambda r: -(r["age_d"] or 1e9)),
        },
        "lane_routing": lane_routing,
    }
    return stats


def render_md(stats: dict) -> str:
    cols = stats["columns"]
    disp = stats["dispatch_7d"]
    stale = stats["stale_review"]
    reqs = stats["open_requests"]

    lines = [
        "# Kanban stats",
        "",
        (f"- Generated: {stats['generated_at']} by "
         f"`{GENERATED_BY.split()[0]}` (node `kanban`, 15m cadence)"),
        f"- Cards: **{stats['cards_total']}** — " + " · ".join(
            f"{k} {v}" for k, v in cols.items()),
        f"- Touched last 24h: **{stats['touched_24h']}**",
        "",
        "| lane | cards |",
        "|------|-------|",
        *[f"| {k} | {v} |" for k, v in cols.items()],
        "",
        "## Dispatch — last 7d",
        "",
        (f"- queued→done: **{disp['finished']}** runs finished "
         f"({disp['per_day']}/day); dispatched {disp['dispatched']}, "
         f"failed {disp['failed']}"),
    ]
    if disp["median_cycle_h"] is not None:
        lines.append(f"- median dispatch→finish cycle: "
                     f"{disp['median_cycle_h']}h")
    lr = stats.get("lane_routing") or {}
    lines += ["", "## Lane routing — open cards", ""]
    if lr.get("stamped"):
        cells = lr["cells"]
        srcs = sorted({s for m in cells.values() for s in m})
        lines.append("| lane | " + " | ".join(srcs) + " | total |")
        lines.append("|" + "---|" * (len(srcs) + 2))
        for ln in sorted(cells):
            m = cells[ln]
            tot = sum(m.values())
            lines.append(
                f"| {ln} | " + " | ".join(
                    str(m[s]) if m.get(s) else "·" for s in srcs)
                + f" | {tot} |")
        lines.append("")
        lines.append("`pin` = author-set lane (wins over the "
                     "classifier); kw/claim/fallback/jevos/"
                     "timer-alert are classifier stamps that "
                     "re-evaluate on re-queue (DEV-0045).")
    else:
        lines.append("- no stamped `action.lane` on open cards")
    if lr.get("unstamped_dispatch"):
        lines.append(f"- unstamped `type:dispatch` cards "
                     f"(classify at queue/claim): "
                     f"**{lr['unstamped_dispatch']}**")
    lines += ["", "## Needs attention", ""]
    if stale["cards"]:
        items = ", ".join(
            f"`{c['id']}` ({c['age_h']}h)" if c["age_h"] is not None
            else f"`{c['id']}` (age unknown)"
            for c in stale["cards"][:10])
        lines.append(f"- stale in review >{stale['threshold_h']}h: "
                     f"**{stale['count']}** — {items}")
    else:
        lines.append(f"- stale in review >{stale['threshold_h']}h: none")
    if reqs["items"]:
        items = "; ".join(
            f"`{r['card']}`/{r['request']}" for r in reqs["items"][:10])
        lines.append(f"- open requests: **{reqs['count']}** — {items}")
    else:
        lines.append("- open requests: none")
    dl = stats["dead_letters"]
    if dl["cards"]:
        items = ", ".join(
            f"`{c['id']}` ({c['age_d']}d)" if c["age_d"] is not None
            else f"`{c['id']}` (age unknown)"
            for c in dl["cards"][:10])
        lines.append(
            f"- answered-but-unexecuted >{dl['threshold_d']}d: "
            f"**{dl['count']}** of {dl['awaiting_action']} awaiting_action"
            f" — {items}")
    else:
        lines.append(
            f"- answered-but-unexecuted >{dl['threshold_d']}d: none "
            f"({dl['awaiting_action']} awaiting_action)")
    lines += [
        "",
        ("_Generated file — do not hand-edit. Source: "
         "`docs/ssot/kanban/cards/*.yml`; full metrics in "
         "`reports/kanban/kanban-stats.yml`._"),
        "",
    ]
    return "\n".join(lines)


def main(cards=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cards-dir", type=Path,
                   default=Path(os.environ.get(
                       "KANBAN_CARDS_DIR", str(CARDS_DIR))),
                   help="card YAML dir (default: this checkout's "
                        "docs/ssot/kanban/cards)")
    p.add_argument("--check", action="store_true",
                   help="print stats + markdown; write nothing")
    args = p.parse_args()

    now = datetime.datetime.now(BANGKOK)
    if cards is None:
        cards = load_cards(args.cards_dir)
    stats = collect(cards, now)
    md = render_md(stats)

    if args.check:
        print(yaml.safe_dump(stats, sort_keys=False, allow_unicode=True))
        print(md)
        return 0

    stale_n = stats["stale_review"]["count"]
    failed_n = stats["dispatch_7d"]["failed"]
    status = "delta" if (stale_n or failed_n) else "ok"
    cols = stats["columns"]
    summary = (f"{stats['cards_total']} cards "
               f"(doing {cols.get('doing', 0)}, review "
               f"{cols.get('review', 0)}); "
               f"{stats['open_requests']['count']} open req; "
               f"{stale_n} stale-review; "
               f"{stats['dispatch_7d']['finished']} done/7d")
    extra = {k: stats[k] for k in
             ("cards_total", "columns", "action_status",
              "touched_24h", "dispatch_7d")}
    extra["open_requests"] = stats["open_requests"]["count"]
    extra["stale_review"] = stats["stale_review"]

    roots = [REPO]
    if SERVED_ROOT != REPO and SERVED_ROOT.is_dir():
        roots.append(SERVED_ROOT)

    meta_path = None
    for root in roots:
        out_dir = root / OUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact = out_dir / "kanban-stats.yml"
        card_io.atomic_write_text(artifact, yaml.safe_dump(
            stats, sort_keys=False, allow_unicode=True))
        meta_path = write_meta(
            out_dir / "meta.yml",
            node=NODE, layer=LAYER, generated_by=GENERATED_BY,
            status=status, purpose=PURPOSE, summary=summary,
            sources=[f"docs/ssot/kanban/cards ({len(cards)} cards)"],
            children=[], extra=extra)
        data_dir = root.joinpath(*WEB_DATA)
        if data_dir.parent.is_dir():
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "kanban.md").write_text(md)

    append_timeline(NODE, LAYER, status, summary, ref=meta_path)
    print(f"kanban-stats: {status} — {summary}")
    for root in roots:
        print(f"  -> {root / OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
