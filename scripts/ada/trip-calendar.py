#!/usr/bin/env python3
"""trip-calendar.py — trip calendar -> CMS page family (card
ada-trip-calendar-pages).

Renders the "show my trip calendar" ask as a cms-page-standard
(docs/kb/cms-page-standard.md) parent/leaf/QC family:

  trip-<slug>               rollup — lede, mermaid gantt of the span,
                            day table (day|date|headline|events|leaf)
  trip-<slug>-<YYYY-MM-DD>  leaf   — that day's schedule table
                            (time|event|detail) + journal notes
  trip-<slug>-qc            qc     — leaf coverage / meta / staleness

Inputs (merged):
  * CalendarService (ada-pi backend.calendar_providers) events, loaded
    from the lane's rendered registry file — same read path as
    calendar-smoke.py.
  * LINE relay conv_journal archive (journal-<day>.jsonl per room under
    LINE_MEDIA_ARCHIVE_DIR) for per-day trip context.

Lanes (--lane):
  tony    -> ada-cms-pages        + ~/.config/ada/calendar.json
  kk      -> ada-cms-pages-kk     + ~/.config/ada/calendar-kk.json
  kk-dev  -> ada-cms-pages-kk-dev + ~/.config/ada/calendar-kk-dev.json
             (dev twin reads the real kk calendar for parity; no public
             tenant — --public is a no-op there)

Env:
  MDDB_BASE_URL           default http://100.102.134.91:11027/v1
  REPO                    default = this checkout root
  ADA_PI_DIR              default ~/CascadeProjects/ada-pi
  LINE_MEDIA_ARCHIVE_DIR  default ~/.local/share/ada/line-media
  ADA_CMS_BASE            viewer base for view_url in --json output
  ADA_CMS_PUBLIC_BASE     public base override (else tenant-derived)

Usage:
  trip-calendar.py --slug southafrica --lane kk-dev --dry-run
  trip-calendar.py --slug southafrica --from 2026-12-20 --to 2026-12-28 --lane kk --public
  trip-calendar.py --slug southafrica --lane kk --json   # machine summary
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11027/v1").rstrip("/")
ADA_PI_DIR = Path(os.environ.get(
    "ADA_PI_DIR", os.path.expanduser("~/CascadeProjects/ada-pi")))
ARCHIVE_DIR = Path(os.environ.get(
    "LINE_MEDIA_ARCHIVE_DIR",
    os.path.expanduser("~/.local/share/ada/line-media")))
sys.path.insert(0, str(REPO / "scripts" / "lib"))

GENERATOR = "trip-calendar.py"
VERSION = "1.0.0 2026-10-13"
FRESH_FOR = "1d"          # on-demand snapshot — re-run to refresh
MAX_DAYS = 45             # hard cap on generated leaves
SCAN_STEP = 31            # svc.list_events days cap
SCAN_PAST = 90            # default inference window (days back)
SCAN_FUTURE = 300         # default inference window (days ahead)
GANT_CAP = 60
JOURNAL_CAP = 15          # excerpt lines per leaf
ICT = timezone(timedelta(hours=7))

LANES = {
    "tony": {
        "collection": "ada-cms-pages",
        "calendar": "~/.config/ada/calendar.json",
        "instance": "tony",
        "tenant": "tony-ha",
    },
    "kk": {
        "collection": "ada-cms-pages-kk",
        "calendar": "~/.config/ada/calendar-kk.json",
        "instance": "kk",
        "tenant": "kk-ha",
    },
    "kk-dev": {
        "collection": "ada-cms-pages-kk-dev",
        "calendar": "~/.config/ada/calendar-kk-dev.json",
        # dev twin reads the lane's real calendar for parity — the -dev
        # registry declares instances:[kk]; data never promotes.
        "instance": "kk",
        "tenant": "",       # no public lane for dev pages
    },
}


def _post(path: str, payload: dict, timeout: int = 60):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def kebab(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower())
    return re.sub(r"-{2,}", "-", s).strip("-")


def norm_slug(slug: str) -> str:
    s = kebab(slug)
    return s[5:] if s.startswith("trip-") else s


def words(slug: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", slug.lower()) if len(w) > 1]


# ---------- calendar service ----------

def ensure_runtime():
    """Re-exec under ada-pi's venv when the ambient python lacks the
    provider deps (httpx). The CalendarService path is optional — when
    ada-pi isn't installed the script still renders journal-only pages,
    but when it IS installed it should actually work."""
    try:
        import httpx  # noqa: F401
        return
    except ImportError:
        pass
    venv_dir = ADA_PI_DIR / ".venv"
    venv = venv_dir / "bin" / "python"
    # .venv/bin/python symlinks to the SAME base binary (/usr/bin/python*)
    # — compare sys.prefix (venv-ness), not resolved executable paths.
    if (venv.is_file() and not os.environ.get("TRIP_CALENDAR_REEXEC")
            and Path(sys.prefix).resolve() != venv_dir.resolve()):
        os.environ["TRIP_CALENDAR_REEXEC"] = "1"
        os.execv(str(venv), [str(venv), str(Path(__file__).resolve()),
                             *sys.argv[1:]])


def load_service(lane: dict):
    """CalendarService from ada-pi; None when ada-pi/registry absent."""
    if not (ADA_PI_DIR / "backend" / "calendar_providers.py").is_file():
        return None, f"ada-pi checkout not found at {ADA_PI_DIR}"
    if str(ADA_PI_DIR) not in sys.path:
        sys.path.insert(0, str(ADA_PI_DIR))
    try:
        from backend.calendar_providers import CalendarService
        svc = CalendarService.load(
            path=lane["calendar"], instance=lane["instance"])
        if svc is None:
            return None, (f"no active providers in {lane['calendar']} "
                          f"for instance={lane['instance']}")
        return svc, None
    except Exception as exc:  # token/auth surfaces on the calls, not load
        return None, f"calendar service load failed: {exc}"


async def list_events_window(svc, d0: date, d1: date,
                             query: str | None = None):
    """All events overlapping [d0, d1] in <=31d chunks."""
    events, errors = [], []
    cur = d0
    while cur <= d1:
        n = min(SCAN_STEP, (d1 - cur).days + 1)
        try:
            res = await svc.list_events(day=cur.isoformat(), days=n,
                                        query=query)
            events += res.get("events") or []
            errors += res.get("errors") or []
        except Exception as exc:
            errors.append(f"{cur}: {exc}")
            break
        cur += timedelta(days=n)
    return events, errors


def ev_span(ev: dict):
    """(first_day, last_day, all_day, start_dt|None, end_dt|None).
    Google all-day end is exclusive — last_day = end-1."""
    s, e = str(ev.get("start") or ""), str(ev.get("end") or "")
    if ev.get("all_day") or (len(s) <= 10 and len(e) <= 10):
        try:
            d0 = date.fromisoformat(s[:10])
            d1 = date.fromisoformat(e[:10]) - timedelta(days=1)
        except ValueError:
            return None
        return d0, max(d0, d1), True, None, None
    try:
        sd = datetime.fromisoformat(s.replace("Z", "+00:00"))
        ed = datetime.fromisoformat(e.replace("Z", "+00:00"))
    except ValueError:
        return None
    last = (ed - timedelta(seconds=1)).date() if ed > sd else sd.date()
    return sd.date(), max(sd.date(), last), False, sd, ed


def dedupe_events(events: list[dict]) -> list[dict]:
    seen, out = set(), []
    for ev in events:
        k = (ev.get("title"), str(ev.get("start"))[:16],
             str(ev.get("end"))[:16])
        if k in seen:
            continue
        seen.add(k)
        out.append(ev)
    return out


# ---------- journal context ----------

def journal_days(chat: str | None = None) -> list[Path]:
    if not ARCHIVE_DIR.is_dir():
        return []
    dirs = ([ARCHIVE_DIR / chat] if chat
            else sorted(d for d in ARCHIVE_DIR.iterdir() if d.is_dir()))
    files = []
    for d in dirs:
        files += sorted(d.glob("journal-*.jsonl"))
    return files


def journal_context(days: list[date], kws: list[str],
                    chat: str | None = None):
    """->{day: [excerpt lines], stats} — text entries matching keywords."""
    by_day = {d.isoformat(): [] for d in days}
    stats = {"dirs": 0, "days_found": 0, "entries": 0, "matched": 0}
    if not ARCHIVE_DIR.is_dir():
        return by_day, stats
    dirs = ([ARCHIVE_DIR / chat] if chat
            else sorted(d for d in ARCHIVE_DIR.iterdir() if d.is_dir()))
    dirs = [d for d in dirs if d.is_dir()]
    stats["dirs"] = len(dirs)
    dayset = {d.isoformat() for d in days}
    for d in dirs:
        for jf in d.glob("journal-*.jsonl"):
            day = jf.name[len("journal-"):-len(".jsonl")]
            if day not in dayset:
                continue
            stats["days_found"] += 1
            try:
                lines = jf.read_text().splitlines()
            except Exception:
                continue
            for ln in lines:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get("kind") != "text":
                    continue
                text = str(e.get("text") or "").strip()
                if not text or text.startswith("{"):
                    # serialized tool-call dumps journaled as text are
                    # not conversation context
                    continue
                stats["entries"] += 1
                tl = text.lower()
                if kws and not any(k in tl for k in kws):
                    continue
                who = e.get("from") or e.get("sender") or "?"
                arrow = "→" if e.get("dir") == "out" else "•"
                ts = str(e.get("ts") or "")[-8:-3] or "??:??"
                if len(by_day[day]) < JOURNAL_CAP:
                    by_day[day].append(f"{ts} {arrow} **{who}**: {text}")
                stats["matched"] += 1
    return by_day, stats


# ---------- render ----------

def _md_escape(t: str) -> str:
    return str(t).replace("|", "\\|").replace("\n", " ").strip()


def _gantt_label(t: str) -> str:
    return re.sub(r"[:,;#]", " ", str(t)).strip()[:60] or "event"


def link_for(key: str, public_base: str, use_public: bool) -> str:
    if use_public and public_base:
        return f"{public_base}{key}.html"
    return f"#/{key}"


def render_gantt(title: str, span: tuple[date, date],
                 day_events: dict[date, list[dict]]) -> list[str]:
    d0, d1 = span
    L = ["```mermaid", "gantt",
         f"    dateFormat YYYY-MM-DD",
         f"    axisFormat %d %b",
         f"    title {_gantt_label(title)}",
         "    section Trip",
         f"    {_gantt_label(title)} :crit, {d0.isoformat()}, "
         f"{(d1 - d0).days + 1}d"]
    allday, timed = [], []
    seen = set()
    for d in sorted(day_events):
        for ev in day_events[d]:
            sp = ev_span(ev)
            if not sp or ev.get("id") in seen:
                continue
            seen.add(ev.get("id"))
            (allday if sp[2] else timed).append((ev, sp))
    if allday:
        L.append("    section All-day")
        for ev, sp in allday[:GANT_CAP]:
            n = (sp[1] - sp[0]).days + 1
            L.append(f"    {_gantt_label(ev.get('title'))} "
                     f":{sp[0].isoformat()}, {n}d")
    if timed:
        L.append("    section Timed")
        left = GANT_CAP - len(allday)
        for i, (ev, sp) in enumerate(timed[:max(0, left)], 1):
            t = sp[3].strftime("%H:%M") if sp[3] else ""
            L.append(f"    {_gantt_label(ev.get('title'))} {t} "
                     f":milestone, m{i}, {sp[0].isoformat()}, 0d")
    L.append("```")
    return L


def unique_events(day_events: dict[date, list[dict]]) -> list[dict]:
    seen, out = set(), []
    for d in sorted(day_events):
        for ev in day_events[d]:
            k = ev.get("id") or (ev.get("title"), ev.get("start"))
            if k in seen:
                continue
            seen.add(k)
            out.append(ev)
    return out


def day_headline(evs: list[dict]) -> str:
    """Most informative event for the day — prefer timed events and
    single-day all-day events over the trip's spanning marker."""
    if not evs:
        return "—"
    for ev in evs:
        sp = ev_span(ev)
        if sp and (not sp[2] or sp[0] == sp[1]):
            return _md_escape(ev.get("title") or "—")
    return _md_escape(evs[0].get("title") or "—")


def render_rollup(slug: str, title: str, span: tuple[date, date],
                  day_events: dict[date, list[dict]],
                  jctx: dict[str, list[str]], now: datetime,
                  link) -> str:
    d0, d1 = span
    n_events = len(unique_events(day_events))
    L = [f"# Trip — {title}",
         f"_{d0.isoformat()} → {d1.isoformat()} · "
         f"{(d1 - d0).days + 1} days · {n_events} events · "
         f"generated {now:%Y-%m-%d %H:%M}Z · leaf page per day below_\n",
         "Day-by-day schedule for this trip — read the leaf page for a "
         "day's full detail; regenerate on demand when plans move.\n",
         "## Timeline\n"]
    L += render_gantt(title, span, day_events)
    L.append("\n## Days\n")
    L.append("| day | date | headline | events | leaf |")
    L.append("|---|---|---|---|---|")
    d = d0
    i = 0
    while d <= d1:
        i += 1
        evs = day_events.get(d, [])
        head = day_headline(evs)
        key = f"trip-{slug}-{d.isoformat()}"
        L.append(f"| {i} | {d.isoformat()} ({d:%a}) | {head} | "
                 f"{len(evs)} | [{key}]({link(key)}) |")
        d += timedelta(days=1)
    hits = [(day, ln) for day, lines in sorted(jctx.items())
            for ln in lines][:10]
    if hits:
        L.append("\n## Journal highlights\n")
        L += [f"- `{day}` {ln}" for day, ln in hits]
    L.append(f"\n_QC: [trip-{slug}-qc]({link(f'trip-{slug}-qc')})_\n")
    L.append("\n---\n_Parent: [reports-index](#/reports-index) · "
             f"generated by {GENERATOR} v{VERSION} · sources: "
             "CalendarService.list_events + LINE journal archive · "
             "cadence: on-demand_")
    return "\n".join(L)


def render_leaf(slug: str, title: str, day: date, daynum: int,
                evs: list[dict], notes: list[str], now: datetime,
                link) -> str:
    key = f"trip-{slug}-{day.isoformat()}"
    L = [f"# Trip — {title} — day {daynum} — {day.isoformat()}",
         f"_{day:%A} · {len(evs)} event(s) · generated "
         f"{now:%Y-%m-%d %H:%M}Z · part of "
         f"[trip-{slug}]({link(f'trip-{slug}')})_\n",
         "## Schedule\n",
         "| time | event | detail |", "|---|---|---|"]
    if evs:
        for ev in evs:
            sp = ev_span(ev)
            if not sp:
                continue
            if sp[2]:
                when = "all day" if sp[0] == sp[1] else \
                    f"{sp[0].isoformat()} → {sp[1].isoformat()}"
            else:
                st = sp[3].strftime("%H:%M") if sp[3] else "??:??"
                en = sp[4].strftime("%H:%M") if sp[4] else ""
                when = f"{st}–{en}" if en else st
                if sp[1] > sp[0]:
                    when = f"{st}→{en}+{(sp[1] - sp[0]).days}d"
                if sp[0] != day:
                    when = f"{sp[0].isoformat()} {st}"
            detail = " · ".join(x for x in (
                _md_escape(ev.get("location") or ""),
                _md_escape((ev.get("notes") or "")[:120]),
                _md_escape(ev.get("provider") or "")) if x)
            L.append(f"| {when} | {_md_escape(ev.get('title'))} | "
                     f"{detail or '—'} |")
    else:
        L.append("| — | _no calendar events this day_ | — |")
    if notes:
        L.append("\n## Journal notes\n")
        L += [f"- {ln}" for ln in notes]
    L.append("\n---\n_Parent: "
             f"[trip-{slug}]({link(f'trip-{slug}')}) · "
             f"generated by {GENERATOR} v{VERSION}_")
    return "\n".join(L)


def render_qc(slug: str, title: str, span: tuple[date, date],
              day_events: dict[date, list[dict]], jstats: dict,
              cal_errors: list[str], lane_name: str, lane: dict,
              span_source: str, matched: list[dict], existing: set[str],
              now: datetime, link) -> str:
    d0, d1 = span
    days = (d1 - d0).days + 1
    expected = {f"trip-{slug}-{(d0 + timedelta(days=i)).isoformat()}"
                for i in range(days)}
    expected |= {f"trip-{slug}", f"trip-{slug}-qc"}
    present = expected & existing
    missing = sorted(expected - existing)
    L = [f"# Trip — {title} — QC / coverage",
         f"_Updated {now:%Y-%m-%d %H:%M}Z · self-check for the "
         f"trip-{slug} page family_\n",
         "## Family coverage\n",
         "| check | value |", "|---|---|",
         f"| lane / collection | {lane_name} / {lane['collection']} |",
         f"| span | {d0} → {d1} ({days}d) — {span_source} |",
         f"| expected pages | {len(expected)} (rollup + {days} leaves + qc) |",
         f"| present in collection | {len(present)} |",
         f"| missing | {len(missing)} |",
         f"| events in span | {len(unique_events(day_events))} |",
         f"| days with events | {sum(1 for v in day_events.values() if v)} |",
         f"| journal dirs scanned | {jstats['dirs']} |",
         f"| journal days in span | {jstats['days_found']} |",
         f"| journal entries matched | {jstats['matched']}/{jstats['entries']} |",
         f"| calendar registry | {lane['calendar']} (instance "
         f"{lane['instance']}) |",
         f"| generator | {GENERATOR} v{VERSION} |",
         f"| fresh_for | {FRESH_FOR} (on-demand snapshot) |"]
    if matched:
        L.append("\n## Span inference matches\n")
        L += [f"- `{str(e.get('start'))[:10]}` {_md_escape(e.get('title'))}"
              for e in matched[:10]]
    if cal_errors:
        L.append("\n## ⚠️ Source errors\n")
        L += [f"- `{_md_escape(e)}`" for e in cal_errors]
    if missing:
        L.append("\n## Missing pages\n")
        L += [f"- `{k}`" for k in missing]
    L.append("\n## Staleness\n")
    L.append(f"Pages declare fresh_for={FRESH_FOR}; past that the "
             "reports-index flags them ⚠STALE — re-run the generator to "
             "refresh (trip calendars are generated on demand, no timer).")
    L.append("\n---\n_Parent: "
             f"[trip-{slug}]({link(f'trip-{slug}')}) · "
             f"generated by {GENERATOR} v{VERSION}_")
    return "\n".join(L)


# ---------- publish ----------

def publish(collection: str, key: str, body: str, now_utc: datetime,
            meta: dict):
    _post("add", {"collection": collection, "key": key, "lang": "en",
                  "contentMd": body, "meta": meta}, timeout=120)


def page_meta(key: str, title: str, summary: str, role: str,
              parent: str, lane_name: str, sources: list[str],
              now_utc: datetime, public: bool, confidence: str) -> dict:
    meta = {
        "kind": ["report"], "domain": ["personal"], "slug": [key],
        "title": [title], "summary": [summary[:240]],
        "status": ["active"], "format": ["markdown"], "lang": ["en"],
        "updated": [now_utc.isoformat(timespec="seconds")],
        "fresh_for": [FRESH_FOR], "confidence": [confidence],
        "report_role": [role], "parent": [parent],
        "generated_by": [GENERATOR], "written_by": ["trip-calendar"],
        "instance": [lane_name], "sources": sources,
        "last_verified": [now_utc.date().isoformat()],
        "timeline": [f"{now_utc.isoformat(timespec='seconds')[:16]} "
                     f"generated trip family member ({role})"],
    }
    if public:
        meta["public"] = ["true"]
    return meta


# ---------- main ----------

async def async_main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True,
                    help="trip slug — rollup key is trip-<slug>")
    ap.add_argument("--from", dest="date_from",
                    help="trip start YYYY-MM-DD (else inferred)")
    ap.add_argument("--to", dest="date_to",
                    help="trip end YYYY-MM-DD (else inferred)")
    ap.add_argument("--title", default="",
                    help="trip title override (default: matched event "
                         "title or 'Trip <slug>')")
    ap.add_argument("--lane", default="kk-dev", choices=sorted(LANES),
                    help="CMS/calendar lane (default kk-dev)")
    ap.add_argument("--public", action="store_true",
                    help="flag rollup+leaves meta.public (kk/tony only; "
                         "explicit-ask gate — same rule as cms_publish_page)")
    ap.add_argument("--chat", default="",
                    help="limit journal context to one archive room dir")
    ap.add_argument("--keywords", default="",
                    help="comma-sep extra journal match terms")
    ap.add_argument("--no-journal", action="store_true")
    ap.add_argument("--scan-past", type=int, default=SCAN_PAST)
    ap.add_argument("--scan-future", type=int, default=SCAN_FUTURE)
    ap.add_argument("--dry-run", action="store_true",
                    help="render to stdout, write nothing")
    ap.add_argument("--json", action="store_true",
                    help="print machine-readable result summary")
    args = ap.parse_args()

    slug = norm_slug(args.slug)
    if not slug:
        print("error: empty slug after normalization", file=sys.stderr)
        return 2
    lane_name = args.lane
    lane = LANES[lane_name]
    collection = lane["collection"]
    public_base = (os.environ.get("ADA_CMS_PUBLIC_BASE", "").strip()
                   or (f"https://surf-thailand.com/{lane['tenant']}/"
                       if lane["tenant"] else ""))
    use_public_links = args.public and bool(public_base)
    # --public on a lane with no tenant (kk-dev) must not flag the pages
    # — a flag without a publish lane is a lie waiting for a TENANTS
    # entry to appear.
    want_public = args.public and bool(public_base)
    if args.public and not want_public:
        print(f"warn: --public ignored — lane {lane_name} has no public "
              "tenant", file=sys.stderr)

    kws = words(slug) + [k.strip().lower()
                         for k in args.keywords.split(",") if k.strip()]

    now_utc = datetime.now(timezone.utc)
    today = now_utc.astimezone(ICT).date()

    svc, svc_err = load_service(lane)
    cal_errors: list[str] = [svc_err] if svc_err else []

    # ---- span ----
    d0 = date.fromisoformat(args.date_from) if args.date_from else None
    d1 = date.fromisoformat(args.date_to) if args.date_to else None
    matched: list[dict] = []
    span_source = "explicit --from/--to"
    if (d0 is None or d1 is None) and svc is not None:
        q = " ".join(words(slug)) or slug
        lo = d0 or (today - timedelta(days=args.scan_past))
        hi = d1 or (today + timedelta(days=args.scan_future))
        found, errs = await list_events_window(svc, lo, hi, query=q)
        cal_errors += errs
        matched = [e for e in dedupe_events(found) if ev_span(e)]
        if matched:
            lo_d = min(ev_span(e)[0] for e in matched)
            hi_d = max(ev_span(e)[1] for e in matched)
            d0 = d0 or lo_d
            d1 = d1 or hi_d
            span_source = (f"inferred from {len(matched)} calendar "
                           f"event(s) matching '{q}'")
        else:
            span_source = (f"no calendar events matched '{q}' in "
                           f"{lo}..{hi}")
    if d0 is None and d1 is None:
        print(f"error: cannot infer trip span — {span_source}; "
              "pass --from/--to", file=sys.stderr)
        return 2
    d0 = d0 or d1
    d1 = d1 or d0
    if d1 < d0:
        d0, d1 = d1, d0
    if (d1 - d0).days + 1 > MAX_DAYS:
        print(f"error: span {(d1 - d0).days + 1}d exceeds MAX_DAYS "
              f"{MAX_DAYS} — narrow --from/--to", file=sys.stderr)
        return 2

    title = args.title.strip()
    if not title:
        title = (matched[0].get("title") if len(matched) == 1
                 else None) or " ".join(
                     w.capitalize() for w in words(slug)) or slug

    # ---- events across span ----
    span_events: list[dict] = []
    if svc is not None:
        span_events, errs = await list_events_window(svc, d0, d1)
        cal_errors += errs
    day_events: dict[date, list[dict]] = {}
    for ev in dedupe_events(span_events):
        sp = ev_span(ev)
        if not sp:
            continue
        d = max(sp[0], d0)
        while d <= min(sp[1], d1):
            day_events.setdefault(d, []).append(ev)
            d += timedelta(days=1)
    for evs in day_events.values():
        evs.sort(key=lambda e: (0 if e.get("all_day") else 1,
                                str(e.get("start"))))

    # ---- journal context ----
    days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
    if args.no_journal:
        jctx, jstats = {d.isoformat(): [] for d in days}, \
            {"dirs": 0, "days_found": 0, "entries": 0, "matched": 0}
    else:
        jctx, jstats = journal_context(
            days, kws, chat=args.chat or None)

    # ---- existing docs for qc coverage ----
    existing: set[str] = set()
    if not args.dry_run:
        try:
            from cms_index import list_docs
            existing = {d.get("key") for d in list_docs(MDDB, collection)}
        except Exception as exc:
            cal_errors.append(f"coverage scan failed: {exc}")
    # pages this run intends to write count as covered
    intended = {f"trip-{slug}-{d.isoformat()}" for d in days}
    intended |= {f"trip-{slug}", f"trip-{slug}-qc"}
    existing |= intended

    confidence = "high" if svc is not None and not cal_errors else \
        "medium"
    if svc is None:
        confidence = "low"

    sources = [
        f"CalendarService.list_events registry={lane['calendar']} "
        f"instance={lane['instance']}",
    ]
    if not args.no_journal:
        sources.append(f"LINE journal archive {ARCHIVE_DIR}"
                       + (f" chat={args.chat}" if args.chat else ""))

    link = lambda key: link_for(key, public_base, use_public_links)  # noqa: E731

    rollup_body = render_rollup(slug, title, (d0, d1), day_events,
                                jctx, now_utc, link)
    qc_body = render_qc(slug, title, (d0, d1), day_events, jstats,
                        cal_errors, lane_name, lane, span_source,
                        matched, existing, now_utc, link)
    leaves = []
    for i, d in enumerate(days, 1):
        leaves.append((
            f"trip-{slug}-{d.isoformat()}",
            f"{title} — day {i} {d.isoformat()}",
            render_leaf(slug, title, d, i, day_events.get(d, []),
                        jctx.get(d.isoformat(), []), now_utc, link),
            i, d))

    if args.dry_run:
        print(rollup_body)
        print("\n" + "=" * 70 + " LEAF SAMPLE " + "=" * 70)
        for key, t, body, _i, _d in leaves[:2]:
            print(f"\n----- {key} -----")
            print(body)
        if len(leaves) > 2:
            print(f"\n... {len(leaves) - 2} more leaves ...")
        print("\n" + "=" * 70 + " QC " + "=" * 70)
        print(qc_body)
        return 0

    publish(collection, f"trip-{slug}", rollup_body, now_utc,
            page_meta(f"trip-{slug}", f"Trip — {title}",
                      f"Trip {title} {d0}→{d1} — {len(days)}d, "
                      f"{len(unique_events(day_events))} events",
                      "rollup", "reports-index", lane_name, sources,
                      now_utc, want_public, confidence))
    for key, t, body, i, d in leaves:
        publish(collection, key, body, now_utc,
                page_meta(key, t, f"Day {i} {d.isoformat()} — "
                          f"{len(day_events.get(d, []))} events",
                          "leaf", f"trip-{slug}", lane_name, sources,
                          now_utc, want_public, confidence))
    publish(collection, f"trip-{slug}-qc", qc_body, now_utc,
            page_meta(f"trip-{slug}-qc", f"Trip — {title} — QC",
                      f"QC/coverage for trip-{slug} family "
                      f"({len(days)} leaves)",
                      "qc", f"trip-{slug}", lane_name, sources,
                      now_utc, False, confidence))

    idx_ok = True
    try:
        from cms_index import regen_reports_index
        regen_reports_index(MDDB, written_by=GENERATOR,
                            collection=collection, instance=lane_name)
    except Exception as exc:
        idx_ok = False
        print(f"warn: reports-index regen failed ({exc})",
              file=sys.stderr)

    view_base = os.environ.get(
        "ADA_CMS_BASE", "https://idc03.taila0626a.ts.net/cms/")
    result = {
        "ok": True, "rollup": f"trip-{slug}",
        "leaves": len(leaves), "days": len(days),
        "events": len(unique_events(day_events)),
        "collection": collection, "lane": lane_name,
        "span": [d0.isoformat(), d1.isoformat()], "title": title,
        "span_source": span_source,
        "view_url": f"{view_base}#/trip-{slug}",
        "public_url": (f"{public_base}trip-{slug}.html"
                       if want_public and public_base else ""),
        "public_flagged": bool(want_public),
        "index_regen": idx_ok, "errors": cal_errors,
    }
    if args.json:
        print(json.dumps(result))
    else:
        pub = f" · public {result['public_url']}" if result["public_url"] else ""
        print(f"trip-{slug} published — {len(leaves)} leaves, "
              f"{result['events']} events, {d0}→{d1}, "
              f"{collection}{pub}")
    return 0


def main() -> int:
    ensure_runtime()
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
