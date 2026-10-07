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

from lib.report import append_timeline, now_iso, write_meta  # noqa: E402

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

    for c in cards:
        col = str(c.get("column") or "backlog")
        columns[col] = columns.get(col, 0) + 1

        a = c.get("action") or {}
        st = str(a.get("status")) if a.get("status") else "none"
        action_status[st] = action_status.get(st, 0) + 1

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
    lines += [
        "",
        ("_Generated file — do not hand-edit. Source: "
         "`docs/ssot/kanban/cards/*.yml`; full metrics in "
         "`reports/kanban/kanban-stats.yml`._"),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
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
        artifact.write_text(yaml.safe_dump(
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
