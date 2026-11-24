#!/usr/bin/env python3
"""flood-hub-alert.py — Google Flood Hub severity watchdog + push alerts.

Card flood-hub-integration: polls the same `flood_hub` config blocks that
flood-news-update.py renders into the flood-report* CMS pages
(flood-news-feeds.json + ada-cms-automation registry), and pushes ONE
batched notification via scripts/board/board_notify.py when a watched
gauge's severity reaches the page's min_severity.

Severity mapping (the card says ">= WARNING" — the API has no WARNING
enum): Flood Hub UI warning/danger/extreme map to ABOVE_NORMAL / SEVERE /
EXTREME. Default alert floor is ABOVE_NORMAL; NO_FLOODING and UNKNOWN
never alert. Per-page "min_severity" in the flood_hub config overrides.

Design mirrors flood-alert.py:

- State file dedups by gaugeId: each gauge fires at most once per
  severity level; re-alerts only on escalation. Missing state file =>
  seed silently, push nothing — arming against a live feed never bursts.
- Writes an ada-cms-automation doc keyed 'flood-hub-alert' each run so
  cms-auto-health watches this lane like the page generators.
- Degrades quietly without FLOODS_API_KEY — exits 0 with a note, so the
  timer can be installed before the waitlist key lands.

LINE delivery: the card asks for LINE — set BOARD_NOTIFY_CHANNEL=yomi
(+ BOARD_NOTIFY_YOMI_CHAT) once the Yomi session is valid again; the
default 'ha,yomi' fans out to HA iPhone push always and LINE when
configured (board_notify returns True when any channel accepts).

Usage:
  flood-hub-alert.py                 # scan all flood_hub configs, push
  flood-hub-alert.py --dry-run       # classify + show decisions, no writes
  flood-hub-alert.py --seed          # record current gauges, push nothing
  flood-hub-alert.py --page flood-report --channel file
  flood-hub-alert.py --min-level SEVERE --since-hours 24

Env:
  MDDB_BASE_URL          automation registry (default in flood-news-update)
  FLOODS_API_KEY         or ~/.config/secrets/flood-forecasting.env
  FLOOD_NEWS_FEEDS       feeds config path (same as flood-news-update)
  FLOOD_HUB_ALERT_STATE  state file (default ~/.cache/flood-hub-alert-state.json)
  BOARD_NOTIFY_CHANNEL   ha|yomi|tg|ntfy|file|off, comma list ok
                         (default 'ha,yomi')
"""

import argparse
import importlib.util
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fnu = _load("flood_news_update", "flood-news-update.py")
fh = _load("flood_hub_lib", "flood-hub-lib.py")
sys.path.insert(0, os.path.join(_HERE, "..", "board"))
try:
    import board_notify
except ImportError:
    board_notify = None

ICT = fnu.ICT
STATE_FILE = os.environ.get(
    "FLOOD_HUB_ALERT_STATE",
    os.path.expanduser("~/.cache/flood-hub-alert-state.json"))
STATE_DOC_KEY = "flood-hub-alert"
STATE_KEEP_DAYS = 14
MAX_PUSH_ITEMS = 8
NAME_ENRICH_CAP = 10


def load_state(path):
    try:
        return json.loads(Path(path).read_text()), True
    except FileNotFoundError:
        return None, False
    except (OSError, json.JSONDecodeError) as e:
        print(f"warn: state file {path} unreadable ({e}) — starting empty",
              file=sys.stderr)
        return {"gauges": {}}, True


def save_state(path, state):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def prune_state(state, now):
    from datetime import timedelta
    cutoff = (now - timedelta(days=STATE_KEEP_DAYS)).isoformat()
    state["gauges"] = {k: v for k, v in state.get("gauges", {}).items()
                       if v.get("at", "") >= cutoff}


def collect_pages(config, registry, pages_filter):
    """{page: (cfg, {area: [statuses]})} for pages with flood_hub config."""
    pages = pages_filter or sorted(
        {k for k in config if not k.startswith("_")} | set(registry))
    out = {}
    for page in pages:
        if page in (STATE_DOC_KEY, "flood-alert"):
            continue
        cfg, _ = fnu.effective_config(
            page, fnu.seed_entry(config, page), registry.get(page), None)
        fhub_cfg = cfg.get("flood_hub")
        if not isinstance(fhub_cfg, dict) or not fhub_cfg:
            continue
        try:
            by_area = fh.statuses_for_config(fhub_cfg)
        except Exception as e:
            print(f"warn: {page} flood-hub fetch failed: {e}", file=sys.stderr)
            continue
        if by_area:
            out[page] = (cfg, by_area)
    return out


def page_candidates(pages_data, default_min):
    """Flatten to [{key, level, areas, status}] deduped by gaugeId —
    same gauge on two pages/areas merges (max level, joined areas)."""
    out = {}
    for page, (cfg, by_area) in pages_data.items():
        fhub_cfg = cfg.get("flood_hub") or {}
        min_sev = fhub_cfg.get("min_severity") or default_min
        alert_on = fhub_cfg.get("alert", True)
        if not alert_on or min_sev == "off":
            continue
        for area, statuses in by_area.items():
            for s in statuses or []:
                sev = s.get("severity") or "UNKNOWN"
                if not fh.meets_min(sev, min_sev):
                    continue
                gid = s.get("gaugeId")
                if not gid:
                    continue
                cur = out.get(gid)
                if cur is None:
                    out[gid] = {"key": gid, "level": sev, "areas": {area},
                                "pages": {page}, "status": s}
                else:
                    cur["areas"].add(area)
                    cur["pages"].add(page)
                    if fh.severity_rank(sev) > fh.severity_rank(cur["level"]):
                        cur["level"], cur["status"] = sev, s
    return sorted(out.values(),
                  key=lambda a: (fh.severity_rank(a["level"]),
                                 a["status"].get("issuedTime") or ""),
                  reverse=True)


def select_alerts(candidates, state):
    """Fire on new gaugeId or severity escalation vs state."""
    seen = state.get("gauges", {})
    return [c for c in candidates
            if fh.severity_rank(c["level"])
            > fh.severity_rank((seen.get(c["key"]) or {}).get("level",
                                                    "NO_FLOODING"))]


def enrich_names(alerts):
    ids = [a["key"] for a in alerts[:NAME_ENRICH_CAP]]
    try:
        return fh.get_gauges(ids)
    except Exception as e:
        print(f"warn: gauge name enrichment failed: {e}", file=sys.stderr)
        return {}


def render_push(alerts, names):
    sev_th = fh.SEVERITY_TH
    trend_th = fh.TREND_TH
    crit = sum(1 for a in alerts if a["level"] in ("SEVERE", "EXTREME"))
    n = len(alerts)
    title = (f"Flood Hub — {crit} severe/extreme" if crit
             else f"Flood Hub — {n} above normal+")
    lines = []
    for a in alerts[:MAX_PUSH_ITEMS]:
        s = a["status"]
        g = names.get(a["key"]) or {}
        label = g.get("siteName") or g.get("river") or a["key"]
        trend = trend_th.get(s.get("forecastTrend"),
                             s.get("forecastTrend") or "-")
        flag = "" if s.get("qualityVerified", True) else " (unverified)"
        lines.append(
            f"[{sev_th.get(a['level'], a['level'])}] {label} — "
            f"{', '.join(sorted(a['areas']))} · {trend} · {a['key']}{flag}")
    if n > MAX_PUSH_ITEMS:
        lines.append(f"… +{n - MAX_PUSH_ITEMS} more gauges")
    lines.append("ref: Google Flood Hub — check flood-report before acting")
    return title, "\n".join(lines)


def save_state_doc(state, status, scanned, pushed, now, error=None):
    doc = {"interval_min": 60,
           "last_run": now.isoformat(timespec="seconds"),
           "last_status": status,
           "last_count": scanned,
           "alerts_sent": pushed,
           "alert_log": state.get("alert_log", [])[-10:]}
    if error:
        doc["last_error"] = str(error)[:500]
    meta = {"kind": ["automation-config"], "bank": ["cms"], "scope": ["tony"],
            "status": ["active"], "source": ["api"],
            "written_by": ["flood-hub-alert"], "subject": [STATE_DOC_KEY],
            "attribute": ["automation"], "slug": [STATE_DOC_KEY],
            "title": ["CMS automation: flood-hub-alert"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    fnu._post("add", {"collection": fnu.REGISTRY, "key": STATE_DOC_KEY,
                      "lang": "en",
                      "contentMd": json.dumps(doc, ensure_ascii=False,
                                              indent=2),
                      "meta": meta}, timeout=120)


SELF_TEST = [
    ("NO_FLOODING", "ABOVE_NORMAL", False),
    ("UNKNOWN", "ABOVE_NORMAL", False),
    ("ABOVE_NORMAL", "ABOVE_NORMAL", True),
    ("SEVERE", "ABOVE_NORMAL", True),
    ("EXTREME", "SEVERE", True),
    ("SEVERE", "EXTREME", False),
]


def self_test():
    bad = [(s, m) for s, m, want in SELF_TEST
           if fh.meets_min(s, m) != want]
    for s, m in bad:
        print(f"FAIL: meets_min({s}, {m})")
    print(f"self-test: {len(SELF_TEST) - len(bad)}/{len(SELF_TEST)} ok")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(
        description="Flood Hub severity watchdog — batched push alerts")
    ap.add_argument("--page", action="append", default=[],
                    help="limit scan to this page slug (repeatable)")
    ap.add_argument("--min-level", default=fh.ALERT_MIN,
                    help="default alert floor (per-page min_severity wins)")
    ap.add_argument("--channel",
                    help="board_notify channel override (ha|yomi|tg|ntfy|file|off)")
    ap.add_argument("--state", default=STATE_FILE)
    ap.add_argument("--config", help="feeds JSON path")
    ap.add_argument("--seed", action="store_true",
                    help="record current gauges as alerted, push nothing")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.config:
        fnu.FEEDS_CONFIG = args.config
    if not fh.available():
        print("FLOODS_API_KEY not configured — nothing to poll "
              "(flood-hub-integration still waiting on waitlist key)")
        return 0

    config = fnu.load_config()
    registry, registry_up = fnu.list_registry()
    now = datetime.now(timezone.utc)

    pages_data = collect_pages(config, registry, args.page or None)
    candidates = page_candidates(pages_data, args.min_level)
    scanned = sum(len(v) for _, by_area in pages_data.values()
                  for v in by_area.values())

    state, state_existed = load_state(args.state)
    if state is None:
        state = {"gauges": {}}
    seeding = args.seed or not state_existed
    prune_state(state, now)

    alerts = [] if seeding else select_alerts(candidates, state)

    if seeding and not args.dry_run:
        for c in candidates:
            state["gauges"][c["key"]] = {
                "level": c["level"],
                "at": now.isoformat(timespec="seconds"),
                "areas": sorted(c["areas"]),
                "gaugeId": c["key"]}
        print(f"seeded {len(candidates)} gauges — no push "
              f"({'missing state file' if not state_existed else '--seed'})")

    pushed = 0
    run_status = "ok"
    if alerts:
        names = enrich_names(alerts)
        title, body = render_push(alerts, names)
        if args.dry_run:
            print(f"\n--- would push ({len(alerts)} gauges) ---\n"
                  f"{title}\n{body}\n")
        else:
            chan = args.channel or os.environ.get(
                "BOARD_NOTIFY_CHANNEL", "ha,yomi")
            click = os.environ.get(
                "FLOOD_HUB_ALERT_CLICK",
                "https://idc03.taila0626a.ts.net/cms/#/flood-report")
            ok = (board_notify.send(title, body, url=click, channel=chan)
                  if board_notify is not None else False)
            if not ok:
                run_status = "error"
                print(f"push FAILED ({len(alerts)} alerts held for retry)",
                      file=sys.stderr)
            else:
                print(f"push sent: {len(alerts)} gauge alert(s)")
                log = state.setdefault("alert_log", [])
                for a in alerts:
                    pushed += 1
                    state["gauges"][a["key"]] = {
                        "level": a["level"],
                        "at": now.isoformat(timespec="seconds"),
                        "areas": sorted(a["areas"]),
                        "gaugeId": a["key"]}
                    log.append({"at": now.astimezone(ICT)
                                .isoformat(timespec="seconds"),
                                "level": a["level"],
                                "areas": sorted(a["areas"]),
                                "gaugeId": a["key"]})
    else:
        print(f"{scanned} statuses scanned across "
              f"{len(pages_data)} pages — nothing at/above {args.min_level}")

    if not args.dry_run:
        state["last_run"] = now.isoformat(timespec="seconds")
        save_state(args.state, state)
        if registry_up:
            try:
                save_state_doc(state, run_status, scanned, pushed, now,
                               error="push channel failed"
                               if run_status != "ok" else None)
            except Exception as e:
                print(f"warn: state doc write failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
