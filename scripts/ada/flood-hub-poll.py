#!/usr/bin/env python3
"""flood-hub-poll.py — poll Google Flood Hub gauge severities, publish to MDDB.

Runs on idc01 (the API key in ~/.config/secrets/flood-forecasting.env is
IP-restricted to idc01's egress, so no other host can call
floodforecasting.googleapis.com). Consumers — the flood-hub:auto CMS
block in flood-news-update.py, the severity alerts in flood-alert.py,
and the mn-ha-dev flood_hub_* sensors — all read the published doc
and never need the key.

Each run:
  1. Query floodStatus:searchLatestFloodStatusByArea for each watched
     basin (loop polygons below), paginated.
  2. Resolve site/river names via gauges:batchGet for gauges at
     ABOVE_NORMAL or worse only (keeps the call small).
  3. Write one ada-cms-automation doc keyed 'flood-hub-status' — same
     state-doc pattern as flood-alert.py, so cms-auto-health watches
     this lane's freshness too.

Card: flood-hub-integration (OPS-0007). Plan: docs/assessments/
flood-hub-assessment.md.

Usage:
    flood-hub-poll.py                 # poll + publish
    flood-hub-poll.py --dry-run       # fetch + print, no MDDB write
    flood-hub-poll.py --areas nakhon-nayok,saraburi-lopburi

Env:
    FLOODS_API_KEY       or ~/.config/secrets/flood-forecasting.env
    MDDB_BASE_URL        default http://100.102.134.91:11027/v1
"""

import argparse
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# flood-hub-check.py holds api_key()/req(); flood-news-update.py holds
# the MDDB post + registry-doc write pattern. Module names have dashes —
# import by path like flood-alert.py does.
_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fhc = _load("flood_hub_check", "flood-hub-check.py")
fnu = _load("flood_news_update", "flood-news-update.py")

MDDB = os.environ.get("MDDB_BASE_URL", fnu.MDDB).rstrip("/")
STATUS_KEY = "flood-hub-status"
STATE_DOC_COLLECTION = fnu.REGISTRY  # ada-cms-automation

# Google severity ladder (FloodStatus.Severity). There is no literal
# WARNING — ABOVE_NORMAL is the watch tier; the card's ">= WARNING"
# alert threshold maps to ABOVE_NORMAL and up.
SEV_RANK = {
    "SEVERITY_UNSPECIFIED": 0,
    "UNKNOWN": 0,
    "NO_FLOODING": 0,
    "ABOVE_NORMAL": 1,
    "SEVERE": 2,
    "EXTREME": 3,
}
ALERTABLE = {s for s, r in SEV_RANK.items() if r >= SEV_RANK["ABOVE_NORMAL"]}

# Watched basins — bbox loops (closed rings) matching the flood-report
# coverage areas in the assessment: Chao Phraya delta/Bangkok, the
# Nakhon Nayok event basin, and the Saraburi/Lopburi nongdon leaf.
AREAS = {
    "chao-phraya": {
        "label": "Chao Phraya / Bangkok",
        "loop": [
            [13.2, 100.2], [13.2, 101.2], [14.9, 101.2],
            [14.9, 100.2], [13.2, 100.2],
        ],
    },
    "nakhon-nayok": {
        "label": "Nakhon Nayok",
        "loop": [
            [13.9, 100.6], [13.9, 101.4], [14.8, 101.4],
            [14.8, 100.6], [13.9, 100.6],
        ],
    },
    "saraburi-lopburi": {
        "label": "Saraburi / Lopburi",
        "loop": [
            [14.3, 100.4], [14.3, 101.3], [15.2, 101.3],
            [15.2, 100.4], [14.3, 100.4],
        ],
    },
}

INTERVAL_MIN = 60  # matches the rendered timer cadence


def _loop_vertices(loop):
    return [{"latitude": la, "longitude": lo} for la, lo in loop]


def search_statuses(key, area_key, page_size=20000):
    """All flood statuses whose gauge sits inside the area loop."""
    out = []
    token = None
    while True:
        body = {
            "loop": {"vertices": _loop_vertices(AREAS[area_key]["loop"])},
            "pageSize": page_size,
            "includeNonQualityVerified": False,
        }
        if token:
            body["pageToken"] = token
        resp = fhc.req(key, "POST",
                       "/floodStatus:searchLatestFloodStatusByArea", body)
        out += resp.get("floodStatuses", [])
        token = resp.get("nextPageToken")
        if not token:
            return out


def gauge_names(key, gauge_ids):
    """gaugeId -> {siteName, river} via gauges:batchGet. Best-effort —
    a failure leaves names empty rather than failing the poll."""
    names = {}
    ids = list(gauge_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        try:
            resp = fhc.req(key, "POST", "/gauges:batchGet",
                           {"names": [f"gauges/{g}" for g in chunk]})
        except SystemExit:
            continue
        for g in resp.get("gauges", []):
            gid = g.get("gaugeId") or g.get("name", "").rsplit("/", 1)[-1]
            names[gid] = {"siteName": g.get("siteName", ""),
                          "river": g.get("river", "")}
    return names


def collect(key, area_keys):
    """-> (gauges, area_summaries). gauges: gaugeId -> record."""
    gauges = {}
    summaries = {}
    for ak in area_keys:
        try:
            statuses = search_statuses(key, ak)
        except SystemExit as e:
            print(f"warn: {ak} query failed: {e}", file=sys.stderr)
            continue
        counts = {}
        for s in statuses:
            sev = s.get("severity") or "SEVERITY_UNSPECIFIED"
            counts[sev] = counts.get(sev, 0) + 1
            gid = s.get("gaugeId")
            if not gid:
                continue
            rec = gauges.setdefault(gid, {
                "gaugeId": gid,
                "severity": sev,
                "trend": s.get("forecastTrend", ""),
                "issuedTime": s.get("issuedTime", ""),
                "lat": (s.get("gaugeLocation") or {}).get("latitude"),
                "lon": (s.get("gaugeLocation") or {}).get("longitude"),
                "verified": bool(s.get("qualityVerified")),
                "source": s.get("source", ""),
                "areas": [],
            })
            if ak not in rec["areas"]:
                rec["areas"].append(ak)
            if SEV_RANK.get(sev, 0) > SEV_RANK.get(rec["severity"], 0):
                rec["severity"] = sev
                rec["trend"] = s.get("forecastTrend", rec["trend"])
                rec["issuedTime"] = s.get("issuedTime", rec["issuedTime"])
        worst = max(counts, key=lambda s: SEV_RANK.get(s, 0), default=None)
        summaries[ak] = {"label": AREAS[ak]["label"], "gauges": len(statuses),
                         "counts": counts,
                         "max_severity": worst if worst else "NO_FLOODING"}
        print(f"{ak}: {len(statuses)} gauges, max={summaries[ak]['max_severity']}")
    return gauges, summaries


def publish(doc):
    now = datetime.now(timezone.utc)
    meta = {"kind": ["automation-config"], "bank": ["cms"], "scope": ["tony"],
            "status": ["active"], "source": ["api"],
            "written_by": ["flood-hub-poll"], "subject": [STATUS_KEY],
            "attribute": ["automation"], "slug": [STATUS_KEY],
            "title": ["CMS automation: flood-hub-status"], "format": ["json"],
            "lang": ["en"],
            "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    fnu._post("add", {"collection": STATE_DOC_COLLECTION, "key": STATUS_KEY,
                      "lang": "en",
                      "contentMd": json.dumps(doc, ensure_ascii=False),
                      "meta": meta}, timeout=120)


def main():
    ap = argparse.ArgumentParser(
        description="Poll Flood Hub gauge severities -> MDDB status doc")
    ap.add_argument("--areas", default=",".join(AREAS),
                    help="comma list of area keys (default: all)")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch + print summary, no MDDB write")
    args = ap.parse_args()

    area_keys = [a.strip() for a in args.areas.split(",") if a.strip()]
    bad = [a for a in area_keys if a not in AREAS]
    if bad:
        sys.exit(f"unknown areas {bad} — choose from {sorted(AREAS)}")

    try:
        key = fhc.api_key()
    except SystemExit as e:
        # Pre-approval this is the expected state — quiet skip, exit 0 so
        # the timer doesn't flag a failed unit every tick.
        print(f"flood-hub-poll: {e} — skipped")
        return 0

    gauges, summaries = collect(key, area_keys)

    alertable = {g: r for g, r in gauges.items()
                 if r["severity"] in ALERTABLE}
    if alertable:
        names = gauge_names(key, alertable.keys())
        for gid, rec in alertable.items():
            rec.update(names.get(gid) or {})

    now = datetime.now(timezone.utc)
    doc = {
        "generated_at": now.isoformat(timespec="seconds"),
        "source": "flood-hub-poll.py",
        "interval_min": INTERVAL_MIN,
        "areas": summaries,
        "counts": {},
        "alertable": sorted(alertable.values(),
                            key=lambda r: -SEV_RANK.get(r["severity"], 0)),
    }
    for rec in gauges.values():
        doc["counts"][rec["severity"]] = doc["counts"].get(rec["severity"], 0) + 1

    n_alert = len(alertable)
    print(f"{len(gauges)} gauges total, {n_alert} alertable "
          f"(>= ABOVE_NORMAL)")
    for rec in doc["alertable"][:10]:
        label = rec.get("siteName") or rec.get("river") or rec["gaugeId"]
        print(f"  {rec['severity']:13s} {label} [{','.join(rec['areas'])}]")

    if args.dry_run:
        print("\n" + json.dumps(doc, ensure_ascii=False, indent=2)[:4000])
        return 0
    try:
        publish(doc)
    except Exception as e:
        print(f"error: MDDB publish failed: {e}", file=sys.stderr)
        return 2
    print(f"published {STATUS_KEY} -> {STATE_DOC_COLLECTION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
