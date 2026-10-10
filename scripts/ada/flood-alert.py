#!/usr/bin/env python3
"""flood-alert.py — flood-situation severity watchdog + push alerts.

Scans the same Google News RSS feeds that flood-news-update.py uses to
maintain the flood-report* CMS pages, classifies each fresh item by
severity, and pushes ONE batched notification (HA iPhone via
scripts/board/board_notify.py) when new items reach a page's alert_min
level.

Design (2026-10-10, card flood-situation-alert-system-9f3407):

- Host: tony_dell — the HA push channel is loopback+token there
  (~/.config/secrets/home-assistant-token.env). The CMS writer stays on
  idc02, so alerting survives a CMS-lane outage.
- Severity is vocabulary, not presence: every collected item is already
  flood-related (feeds + 'require' filter), so 'info' is the baseline —
  only escalation language pushes.
- Per-page 'alert_min' in flood-news-feeds.json (registry can override):
  the home-area page alerts at 'warning'; the nongdon/saraburi leaf
  defaults to 'critical' because every dam-discharge cycle produces
  เฝ้าระวัง copy — routine watch language there is noise.
- State file dedups pushes by normalized title: each item fires at most
  once per severity level; a re-classification upward fires once more.
  Missing state file => seed silently, push nothing — arming against a
  live feed never bursts.
- Writes an ada-cms-automation doc keyed 'flood-alert' each run so
  cms-auto-health watches this lane like the page generators (stale ->
  cms-auto-flood-alert card).

Usage:
  flood-alert.py                 # scan all configured pages, push alerts
  flood-alert.py --dry-run       # classify + show decisions, no writes
  flood-alert.py --self-test     # classifier sanity check, no network
  flood-alert.py --seed          # record current items, push nothing
  flood-alert.py --page flood-report --channel file
  flood-alert.py --since-hours 24 --min-level critical

Env:
  MDDB_BASE_URL       automation registry + state doc (default in
                      flood-news-update.py)
  FLOOD_ALERT_STATE   state file (default ~/.cache/flood-alert-state.json)
  BOARD_NOTIFY_CHANNEL  push channel — ha|yomi|ntfy|file|off (ha default)
  FLOOD_ALERT_CLICK   push click-through URL
                      (default https://idc03.taila0626a.ts.net/cms/#/flood-report)
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- import flood-news-update.py machinery (module name has dashes) ----
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "flood_news_update", os.path.join(_HERE, "flood-news-update.py"))
fnu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fnu)

# board_notify lives in scripts/board — sibling dir, valid module name.
sys.path.insert(0, os.path.join(_HERE, "..", "board"))
try:
    import board_notify
except ImportError:  # channel 'off' still works without it
    board_notify = None

ICT = fnu.ICT
LEVELS = ("info", "warning", "critical")

STATE_FILE = os.environ.get(
    "FLOOD_ALERT_STATE",
    os.path.expanduser("~/.cache/flood-alert-state.json"))
STATE_KEEP_DAYS = 14
MAX_PUSH_ITEMS = 6
ALERT_LOG_KEEP = 10
STATE_DOC_KEY = "flood-alert"
CMS_CLICK = os.environ.get(
    "FLOOD_ALERT_CLICK",
    "https://idc03.taila0626a.ts.net/cms/#/flood-report")

# --- severity classifier ------------------------------------------------
# Paired barrier+breach match catches "เขื่อนแตก"/"dike breach" phrasing in
# either order; single-term list catches the rest. Thai substring matches
# are unaccented — the vocabulary is specific enough that false positives
# are rare inside flood-scoped feeds.

_BARRIER = (r"คันกั้น|คันดิน|แนวคัน|เขื่อน|ประตู(?:ระบาย)?น้ำ|"
            r"ตลิ่ง|dike|levee|embankment|dam\b|sea ?wall")
_BREACH = (r"แตก|ทะลัก|พัง|รั่ว|ถล่ม|ล้น|"
           r"breach|burst|collaps|fail|overflow|top(?:s|ped|ping)?\b")

_CRITICAL_SINGLE = re.compile(
    r"อพยพ|ภัยพิบัติ|เสียชีวิต|จมน้ำ|มวลน้ำ|วิกฤต|ล้นตลิ่ง|ท่วมสูง"
    r"|ประกาศ.{0,15}(ฉุกเฉิน|สูงสุด)"
    r"|evacuat|drown|death toll|fatalit|\bkilled\b|\bdead\b"
    r"|disaster (?:zone|declar|area)|state of emergency", re.I)
_BARRIER_BREACH = re.compile(
    rf"(?:{_BARRIER}).{{0,40}}(?:{_BREACH})"
    rf"|(?:{_BREACH}).{{0,40}}(?:{_BARRIER})", re.I)
_WARNING = re.compile(
    r"เตือนภัย|เฝ้าระวัง|แจ้งเตือน|ประกาศเตือน|เตือนน้ำ|รับมือน้ำ"
    r"|น้ำท่วมฉับพลัน|น้ำป่า|น้ำหลาก|น้ำล้น|น้ำเอ่อ|เอ่อล้น|น้ำเชี่ยว|น้ำขัง|น้ำรอระบาย"
    r"|ระบายน้ำ|เพิ่มการระบาย|ระดับน้ำ.{0,15}(สูง|ขึ้น|เพิ่ม|เกิน)"
    r"|ท่วมขัง|ท่วมถนน|ถนน.{0,10}(ท่วม|ปิด)|ปิดถนน"
    r"|flash ?flood|flood (?:warning|watch|risk|alert)|runoff|inundat"
    r"|water level.{0,25}(?:ris|exceed|above|critical|swell)"
    r"|dam (?:discharge|release)|river (?:overflow|burst|swell)", re.I)


def classify(title, desc=""):
    """info|warning|critical — the highest tier matched in title+desc."""
    text = f"{title}\n{desc}"
    if _CRITICAL_SINGLE.search(text) or _BARRIER_BREACH.search(text):
        return "critical"
    if _WARNING.search(text):
        return "warning"
    return "info"


# --- state --------------------------------------------------------------

def load_state(path):
    """(state, existed). Missing file => None state => caller seeds."""
    try:
        return json.loads(Path(path).read_text()), True
    except FileNotFoundError:
        return None, False
    except (OSError, json.JSONDecodeError) as e:
        print(f"warn: state file {path} unreadable ({e}) — starting empty",
              file=sys.stderr)
        return {"items": {}}, True


def save_state(path, state):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def prune_state(state, now):
    cutoff = (now - timedelta(days=STATE_KEEP_DAYS)).isoformat()
    state["items"] = {k: v for k, v in state.get("items", {}).items()
                      if v.get("at", "") >= cutoff}


# --- alert selection ----------------------------------------------------

def page_min_level(cfg, default):
    lvl = str(cfg.get("alert_min") or default).lower()
    return lvl if lvl in LEVELS or lvl == "off" else default


def select_alerts(pages_items, state, default_min):
    """pages_items: {page: (cfg, [items])} -> [{key,page,area,level,item}]

    A candidate fires when its severity >= the page's alert_min and the
    state file has no record at an equal-or-higher level — re-alerts only
    on escalation. The same item seen on two pages merges (max level,
    joined areas).
    """
    out = {}
    seen = state.get("items", {})
    for page, (cfg, items) in pages_items.items():
        minlvl = page_min_level(cfg, default_min)
        if minlvl == "off" or not cfg.get("alert", True):
            continue
        thresh = LEVELS.index(minlvl)
        area = cfg.get("alert_label") or page
        for it in items:
            sev = classify(it["title"], it.get("desc", ""))
            if LEVELS.index(sev) < thresh:
                continue
            key = fnu.dedup_key(it["title"])
            if not key:
                continue
            prev = seen.get(key)
            if prev and LEVELS.index(prev.get("level", "info")) >= LEVELS.index(sev):
                continue
            cur = out.get(key)
            if cur is None:
                out[key] = {"key": key, "level": sev, "areas": {area},
                            "item": it}
            else:
                cur["areas"].add(area)
                if LEVELS.index(sev) > LEVELS.index(cur["level"]):
                    cur["level"] = sev
    order = {l: i for i, l in enumerate(reversed(LEVELS))}
    return sorted(out.values(),
                  key=lambda a: (order[a["level"]],
                                 -(a["item"]["pub"].timestamp()
                                   if a["item"].get("pub") else 0)))


def render_push(alerts):
    """(title, body) — one batched notification per run."""
    crit = sum(1 for a in alerts if a["level"] == "critical")
    n = len(alerts)
    title = (f"FLOOD ALERT — {crit} critical" if crit
             else f"Flood alert — {n} new")
    lines = []
    for a in alerts[:MAX_PUSH_ITEMS]:
        t = a["item"]["title"]
        t = t if len(t) <= 110 else t[:107].rstrip() + "…"
        tag = "CRIT" if a["level"] == "critical" else "WARN"
        lines.append(f"[{tag}] {t} — {', '.join(sorted(a['areas']))}")
    if n > MAX_PUSH_ITEMS:
        lines.append(f"… +{n - MAX_PUSH_ITEMS} more (see flood-report)")
    return title, "\n".join(lines)


# --- registry state doc --------------------------------------------------

def save_state_doc(state, status, scanned, pushed, now, error=None):
    """ada-cms-automation 'flood-alert' — lets cms-auto-health judge this
    lane's freshness exactly like the page generators."""
    doc = {"interval_min": 15,
           "last_run": now.isoformat(timespec="seconds"),
           "last_status": status,
           "last_count": scanned,
           "alerts_sent": pushed,
           "alert_log": state.get("alert_log", [])[-ALERT_LOG_KEEP:]}
    if error:
        doc["last_error"] = str(error)[:500]
    meta = {"kind": ["automation-config"], "bank": ["cms"], "scope": ["tony"],
            "status": ["active"], "source": ["api"],
            "written_by": ["flood-alert"], "subject": [STATE_DOC_KEY],
            "attribute": ["automation"], "slug": [STATE_DOC_KEY],
            "title": ["CMS automation: flood-alert"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    fnu._post("add", {"collection": fnu.REGISTRY, "key": STATE_DOC_KEY,
                      "lang": "en", "contentMd":
                      json.dumps(doc, ensure_ascii=False, indent=2),
                      "meta": meta}, timeout=120)


# --- self-test ------------------------------------------------------------

SELF_TEST = [
    ("อพยพด่วน! น้ำทะลักคันกั้นเข้าท่วมบางพลี", "", "critical"),
    ("Evacuations ordered as dike bursts in Samut Prakan", "", "critical"),
    ("Dam breach fears force emergency declaration", "", "critical"),
    ("เขื่อนเจ้าพระยาระบายน้ำเพิ่ม เตือน 7 จังหวัดเฝ้าระวัง", "", "warning"),
    ("เฝ้าระวังน้ำท่วมฉับพลัน กทม. คืนนี้", "", "warning"),
    ("Flash flood warning issued for Bangkok suburbs", "", "warning"),
    ("เขื่อนเจ้าพระยาระบายน้ำตามปกติ", "", "warning"),
    ("ปรับปรุงถนนเทพารักษ์หลังน้ำลดแล้ว", "", "info"),
    ("Flood situation in Thailand improves", "", "info"),
]


def self_test():
    bad = [(t, want, classify(t, d)) for t, d, want in SELF_TEST
           if classify(t, d) != want]
    for t, want, got in bad:
        print(f"FAIL: {t!r} want={want} got={got}")
    print(f"self-test: {len(SELF_TEST) - len(bad)}/{len(SELF_TEST)} ok")
    return 1 if bad else 0


# --- main -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Flood-news severity watchdog — batched push alerts")
    ap.add_argument("--page", action="append", default=[],
                    help="limit scan to this page slug (repeatable)")
    ap.add_argument("--since-hours", type=int, default=48)
    ap.add_argument("--max-items", type=int, default=25)
    ap.add_argument("--min-level", default="warning",
                    choices=LEVELS + ("off",),
                    help="default alert threshold; per-page alert_min wins")
    ap.add_argument("--channel",
                    help="board_notify channel override (ha|yomi|ntfy|file|off)")
    ap.add_argument("--state", default=STATE_FILE)
    ap.add_argument("--config", help="feeds JSON path")
    ap.add_argument("--seed", action="store_true",
                    help="record current items as alerted, push nothing")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.config:
        fnu.FEEDS_CONFIG = args.config
    config = fnu.load_config()
    registry, registry_up = fnu.list_registry()

    now = datetime.now(timezone.utc)
    now_ict = now.astimezone(ICT)

    if args.page:
        pages = args.page
    else:
        pages = sorted({k for k in config if not k.startswith("_")}
                       | set(registry))

    # fetch + classify per page
    pages_items, scanned = {}, 0
    for page in pages:
        if page == STATE_DOC_KEY:
            continue
        cfg, ok = fnu.effective_config(
            page, fnu.seed_entry(config, page), registry.get(page), None)
        if not ok:
            continue
        since = int(cfg.get("alert_since_hours") or args.since_hours)
        items = fnu.collect(cfg["feeds"], since, args.max_items,
                            cfg.get("require") or config.get("_require_default"))
        pages_items[page] = (cfg, items)
        scanned += len(items)
        if args.dry_run:
            for it in items:
                pub = (it["pub"].astimezone(ICT).strftime("%m-%d %H:%M")
                       if it["pub"] else "?")
                print(f"  [{page}] [{pub}] "
                      f"{classify(it['title'], it.get('desc', '')):8s} "
                      f"{it['title'][:80]}")

    state, state_existed = load_state(args.state)
    seeding = args.seed or not state_existed
    if state is None:
        state = {"items": {}}
    prune_state(state, now)

    alerts = select_alerts(pages_items, state, args.min_level)

    if seeding and not args.dry_run:
        # arm silently: every qualifying item becomes 'already alerted'
        for page, (cfg, items) in pages_items.items():
            minlvl = page_min_level(cfg, args.min_level)
            if minlvl == "off" or not cfg.get("alert", True):
                continue
            for it in items:
                sev = classify(it["title"], it.get("desc", ""))
                if LEVELS.index(sev) >= LEVELS.index(minlvl):
                    state["items"][fnu.dedup_key(it["title"])] = {
                        "level": sev, "at": now.isoformat(timespec="seconds"),
                        "page": page, "title": it["title"][:140]}
        print(f"seeded {len(state['items'])} items — no push "
              f"({'missing state file' if not state_existed else '--seed'})")
        alerts = []

    pushed = 0
    run_status = "ok"
    if alerts:
        title, body = render_push(alerts)
        if args.dry_run:
            print(f"\n--- would push ({len(alerts)} items) ---\n"
                  f"{title}\n{body}\n")
        else:
            chan = args.channel or os.environ.get("BOARD_NOTIFY_CHANNEL")
            ok = (board_notify.send(title, body, url=CMS_CLICK,
                                    channel=chan)
                  if board_notify is not None else False)
            if not ok:
                # don't mark items — next tick retries the push; the
                # registry 'error' status lets cms-auto-health surface a
                # dead push channel instead of losing the alert.
                run_status = "error"
                print(f"push FAILED ({len(alerts)} alerts held for retry)",
                      file=sys.stderr)
            else:
                print(f"push sent: {len(alerts)} alert(s)")
                log = state.setdefault("alert_log", [])
                for a in alerts:
                    pushed += 1
                    state["items"][a["key"]] = {
                        "level": a["level"],
                        "at": now.isoformat(timespec="seconds"),
                        "page": next(iter(a["areas"])),
                        "title": a["item"]["title"][:140]}
                    log.append({"at": now_ict.isoformat(timespec="seconds"),
                                "level": a["level"],
                                "areas": sorted(a["areas"]),
                                "title": a["item"]["title"][:140]})
    else:
        print(f"{scanned} items scanned, nothing new at/above "
              f"{args.min_level}")

    if not args.dry_run:
        state["last_run"] = now.isoformat(timespec="seconds")
        save_state(args.state, state)
        if registry_up:
            try:
                save_state_doc(state, run_status, scanned, pushed, now,
                               error="push channel failed" if run_status != "ok"
                               else None)
            except Exception as e:
                print(f"warn: state doc write failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
