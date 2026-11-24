#!/usr/bin/env python3
"""flood-status.py — Flood Hub status as JSON (Ada `flood_status` backend).

Card flood-hub-integration. One-shot query of Google Flood Hub gauge
statuses, normalized for tool consumption: severity enum + Thai label,
forecast trend, gauge location, quality flag, site/river names.

Sources (pick one; default = every page's flood_hub config merged):
  --page <slug> [...]     flood_hub.areas/gauges from flood-news-feeds.json
                          (+ ada-cms-automation registry overrides)
  --gauges id [id...]     explicit gauge ids
  --region TH             whole-region area search
  --loop-json '<json>'    custom loop {"vertices":[{latitude,longitude}]}
  --loop-file <path>      same, read from file

Output (stdout, always JSON):
  {ok, generated, worst, alertable, areas: {label: {count, worst}},
   statuses: [{gaugeId, severity, severityTh, severityRank, trend,
               trendTh, issuedTime, lat, lon, verified, source,
               siteName, river, areas}]}

Env: FLOODS_API_KEY or ~/.config/secrets/flood-forecasting.env
     FLOOD_NEWS_FEEDS  feeds config path (default: sibling flood-news-feeds.json)
"""

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fnu = _load("flood_news_update", "flood-news-update.py")
fh = _load("flood_hub_lib", "flood-hub-lib.py")

PRETTY = False


def emit(payload, code=0):
    print(json.dumps(payload, ensure_ascii=False,
                     indent=2 if PRETTY else None))
    return code


def collect_by_area(config, registry, pages):
    """Merge flood_hub configs -> (by_gauge_id, by_area_label).

    by_gauge_id: {gaugeId: FloodStatus} deduped across pages/areas.
    by_area_label: {label: [FloodStatus]} for the areas summary.
    """
    by_id, by_area, gauge_areas = {}, {}, {}
    for page in pages:
        cfg, _ = fnu.effective_config(
            page, fnu.seed_entry(config, page), registry.get(page), None)
        fhub_cfg = cfg.get("flood_hub")
        if not isinstance(fhub_cfg, dict) or not fhub_cfg:
            continue
        for label, statuses in fh.statuses_for_config(fhub_cfg).items():
            for s in statuses or []:
                gid = s.get("gaugeId")
                if not gid:
                    continue
                by_id.setdefault(gid, s)
                by_area.setdefault(label, []).append(s)
                if label not in gauge_areas.setdefault(gid, []):
                    gauge_areas[gid].append(label)
    return by_id, by_area, gauge_areas


def normalize(statuses, gauge_areas):
    points = []
    for s in statuses:
        p = fh.status_point(s)
        gid = p["gaugeId"]
        p["severityTh"] = fh.SEVERITY_TH.get(p["severity"], p["severity"])
        p["trendTh"] = fh.TREND_TH.get(p["trend"], p["trend"])
        p["areas"] = sorted(gauge_areas.get(gid, []))
        points.append(p)
    points.sort(key=lambda p: p["severityRank"], reverse=True)
    return points


def main():
    global PRETTY
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--page", action="append", default=[],
                    help="CMS page slug with flood_hub config (repeatable)")
    ap.add_argument("--gauges", nargs="+", default=[],
                    help="explicit gauge ids")
    ap.add_argument("--region", help="region code, e.g. TH")
    ap.add_argument("--loop-json", help='loop polygon JSON {"vertices":[...]}')
    ap.add_argument("--loop-file", help="file containing loop polygon JSON")
    ap.add_argument("--min-severity", default=fh.ALERT_MIN,
                    help="only include gauges at/above this severity "
                         "(NO_FLOODING shows everything)")
    ap.add_argument("--max", type=int, default=50,
                    help="max statuses in output (worst first)")
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("--config", help="feeds JSON path")
    args = ap.parse_args()
    PRETTY = args.pretty

    if not fh.available():
        return emit({"ok": False,
                     "error": "FLOODS_API_KEY not configured "
                              "(waitlist key pending — "
                              "flood-hub-integration)"}, 2)

    now = datetime.now(timezone.utc)
    try:
        gauge_areas = {}
        area_summary = {}
        if args.gauges:
            statuses = fh.latest_statuses_by_gauge_ids(args.gauges)
            by_area = {"watchlist": statuses}
        elif args.region or args.loop_json or args.loop_file:
            loop = None
            if args.loop_file:
                loop = json.loads(Path(args.loop_file).read_text())
            elif args.loop_json:
                loop = json.loads(args.loop_json)
            statuses = fh.search_latest_statuses_by_area(
                region_code=args.region, loop=loop)
            by_area = {args.region or "custom-area": statuses}
        else:
            if args.config:
                fnu.FEEDS_CONFIG = args.config
            config = fnu.load_config()
            registry, _ = fnu.list_registry()
            pages = args.page or sorted(
                {k for k in config if not k.startswith("_")}
                | {k for k, v in registry.items()
                   if isinstance(v, dict) and v.get("flood_hub")})
            pages = [p for p in pages
                     if p not in ("flood-alert", "flood-hub-alert")]
            by_id, by_area, gauge_areas = collect_by_area(
                config, registry, pages)
            statuses = list(by_id.values())

        for label, sts in by_area.items():
            sev = [s.get("severity") for s in sts or []]
            area_summary[label] = {"count": len(sts or []),
                                   "worst": fh.worst(sts or [])}
        if args.gauges or args.region or args.loop_json or args.loop_file:
            label = ("watchlist" if args.gauges
                     else (args.region or "custom-area"))
            for s in statuses or []:
                gid = s.get("gaugeId")
                if gid and label not in gauge_areas.setdefault(gid, []):
                    gauge_areas[gid].append(label)
    except Exception as e:
        return emit({"ok": False, "error": str(e)}, 1)

    all_points = normalize(statuses or [], gauge_areas)
    shown = [p for p in all_points
             if fh.meets_min(p["severity"], args.min_severity)]
    truncated = len(shown) > args.max
    shown = shown[:args.max]

    names = {}
    ids = [p["gaugeId"] for p in shown if p["gaugeId"]]
    if ids:
        try:
            names = fh.get_gauges(ids)
        except Exception:
            pass
    for p in shown:
        g = names.get(p["gaugeId"]) or {}
        p["siteName"] = g.get("siteName")
        p["river"] = g.get("river")
        p["gaugeSource"] = g.get("source")

    return emit({
        "ok": True,
        "generated": now.isoformat(timespec="seconds"),
        "minSeverity": args.min_severity,
        "worst": (max((p["severity"] for p in all_points),
                      key=fh.severity_rank, default="NO_FLOODING")),
        "alertable": sum(1 for p in all_points
                         if fh.meets_min(p["severity"], fh.ALERT_MIN)),
        "returned": len(shown),
        "truncated": truncated,
        "areas": area_summary,
        "statuses": shown,
    })


if __name__ == "__main__":
    sys.exit(main())
