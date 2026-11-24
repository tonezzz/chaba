#!/usr/bin/env python3
"""flood-hub-check.py — verify Flood Forecasting API access and list gauges.

Docs: docs/assessments/flood-hub-assessment.md
API:  https://floodforecasting.googleapis.com/v1 (API key, waitlist-gated)

Usage:
    flood-hub-check.py gauges [--region TH] [--include-unverified]
    flood-hub-check.py status <gaugeId> [<gaugeId>...]
    flood-hub-check.py forecast <gaugeId> [<gaugeId>...]
    flood-hub-check.py area [--region TH] [--min-severity ABOVE_NORMAL]

Key comes from $FLOODS_API_KEY or ~/.config/secrets/flood-forecasting.env.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://floodforecasting.googleapis.com/v1"
SECRETS_FILE = Path.home() / ".config" / "secrets" / "flood-forecasting.env"


def api_key() -> str:
    key = os.environ.get("FLOODS_API_KEY", "").strip()
    if not key and SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text().splitlines():
            if line.startswith("FLOODS_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit(
            "FLOODS_API_KEY not set and no "
            f"{SECRETS_FILE} — get one via the waitlist "
            "(docs/assessments/flood-hub-assessment.md)."
        )
    return key


def req(key: str, method: str, path: str, body: dict | None = None) -> dict:
    sep = "&" if "?" in path else "?"
    url = f"{BASE}{path}{sep}key={urllib.parse.quote(key)}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} on {path}\n{e.read().decode()[:500]}")


def cmd_gauges(key: str, region: str, include_unverified: bool) -> None:
    gauges, token = [], None
    while True:
        body = {
            "regionCode": region,
            "pageSize": 1000,
            "includeNonQualityVerified": include_unverified,
            "includeGaugesWithoutHydroModel": False,
        }
        if token:
            body["pageToken"] = token
        out = req(key, "POST", "/gauges:searchGaugesByArea", body)
        gauges += out.get("gauges", [])
        token = out.get("nextPageToken")
        if not token:
            break
    print(f"{len(gauges)} gauges in {region}")
    for g in gauges:
        loc = g.get("location", {})
        print(
            f"  {g['gaugeId']:24} {g.get('river','?'):30} "
            f"{g.get('siteName','-'):30} "
            f"({loc.get('latitude',0):.3f},{loc.get('longitude',0):.3f}) "
            f"verified={g.get('qualityVerified')} model={g.get('hasModel')}"
        )


def cmd_status(key: str, ids: list[str]) -> None:
    q = urllib.parse.urlencode([("gaugeIds", i) for i in ids])
    out = req(key, "GET", f"/floodStatus:queryLatestFloodStatusByGaugeIds?{q}")
    statuses = out.get("floodStatuses", [])
    for s in statuses:
        print(
            f"{s['gaugeId']:24} severity={s.get('severity','?'):14} "
            f"trend={s.get('forecastTrend','?'):12} "
            f"issued={s.get('issuedTime','?')} verified={s.get('qualityVerified')}"
        )
    if not statuses:
        print(json.dumps(out, indent=2)[:2000])


SEVERITY_RANK = {"NO_FLOODING": 0, "UNKNOWN": 1, "ABOVE_NORMAL": 2,
                 "SEVERE": 3, "EXTREME": 4}


def cmd_area(key: str, region: str, min_severity: str) -> None:
    """floodStatus:searchLatestFloodStatusByArea — worst-first summary.
    Useful before gauge enumeration: shows which Thai gauges (or a
    --loop polygon) currently report actionable severity."""
    statuses, token = [], None
    while True:
        body = {"regionCode": region, "pageSize": 5000,
                "includeNonQualityVerified": False}
        if token:
            body["pageToken"] = token
        out = req(key, "POST", "/floodStatus:searchLatestFloodStatusByArea",
                  body)
        statuses += out.get("floodStatuses", [])
        token = out.get("nextPageToken")
        if not token:
            break
    floor = SEVERITY_RANK.get(min_severity, 2)
    hits = [s for s in statuses
            if SEVERITY_RANK.get(s.get("severity"), 0) >= floor]
    hits.sort(key=lambda s: SEVERITY_RANK.get(s.get("severity"), 0),
              reverse=True)
    print(f"{len(statuses)} statuses in {region}; "
          f"{len(hits)} at/above {min_severity}")
    for s in hits[:100]:
        loc = s.get("gaugeLocation", {})
        print(f"  {s.get('gaugeId', '?'):24} "
              f"sev={s.get('severity', '?'):14} "
              f"trend={s.get('forecastTrend', '?'):10} "
              f"({loc.get('latitude', 0):.3f},{loc.get('longitude', 0):.3f}) "
              f"verified={s.get('qualityVerified')}")


def cmd_forecast(key: str, ids: list[str]) -> None:
    # Forecasts issue ~daily; 25h back catches the latest run (DELFT-FEWS trick).
    start = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    q = urllib.parse.urlencode(
        [("gaugeIds", i) for i in ids] + [("issueTimeStart", start)]
    )
    out = req(key, "GET", f"/gauges:queryGaugeForecasts?{q}")
    print(json.dumps(out, indent=2)[:4000])


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    key = api_key()
    cmd, rest = args[0], args[1:]
    if cmd == "gauges":
        region = rest[rest.index("--region") + 1] if "--region" in rest else "TH"
        cmd_gauges(key, region, "--include-unverified" in rest)
    elif cmd == "status" and rest:
        cmd_status(key, rest)
    elif cmd == "forecast" and rest:
        cmd_forecast(key, rest)
    elif cmd == "area":
        region = rest[rest.index("--region") + 1] if "--region" in rest else "TH"
        min_sev = (rest[rest.index("--min-severity") + 1]
                   if "--min-severity" in rest else "ABOVE_NORMAL")
        cmd_area(key, region, min_sev)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
