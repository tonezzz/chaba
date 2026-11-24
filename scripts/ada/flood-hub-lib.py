#!/usr/bin/env python3
"""flood-hub-lib.py — shared Google Flood Hub API client (stdlib only).

Docs: docs/assessments/flood-hub-assessment.md
API:  https://floodforecasting.googleapis.com/v1 (API key, waitlist-gated)

Consumed by flood-news-update.py (flood-hub:auto CMS block),
flood-hub-alert.py (severity push), flood-status.py (Ada tool backend)
and flood-hub-check.py-style verification flows.

Key comes from $FLOODS_API_KEY or ~/.config/secrets/flood-forecasting.env
(same convention as flood-hub-check.py). Import via importlib — the
filename has dashes, so `import flood_hub_lib` does not work:

    spec = importlib.util.spec_from_file_location(
        "flood_hub_lib", os.path.join(_HERE, "flood-hub-lib.py"))
    fh = importlib.util.module_from_spec(spec); spec.loader.exec_module(fh)

Severity note (card flood-hub-integration says ">= WARNING"): the API
enum has no WARNING — the Flood Hub UI's warning/danger/extreme colours
map to ABOVE_NORMAL / SEVERE / EXTREME. ALERT_MIN default is therefore
ABOVE_NORMAL; NO_FLOODING and UNKNOWN never alert.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://floodforecasting.googleapis.com/v1"
SECRETS_FILE = Path.home() / ".config" / "secrets" / "flood-forecasting.env"

SEVERITY_RANK = {
    "NO_FLOODING": 0,
    "UNKNOWN": 1,
    "ABOVE_NORMAL": 2,
    "SEVERE": 3,
    "EXTREME": 4,
    "SEVERITY_UNSPECIFIED": -1,
}
ALERT_MIN = "ABOVE_NORMAL"  # card's ">= WARNING" — see module docstring

SEVERITY_TH = {
    "NO_FLOODING": "ปกติ",
    "UNKNOWN": "ไม่ทราบ",
    "ABOVE_NORMAL": "สูงกว่าปกติ",
    "SEVERE": "รุนแรง",
    "EXTREME": "วิกฤต",
    "SEVERITY_UNSPECIFIED": "ไม่ระบุ",
}
TREND_TH = {"RISE": "เพิ่มขึ้น", "FALL": "ลดลง", "NO_CHANGE": "คงที่"}


class FloodHubError(RuntimeError):
    pass


def api_key() -> str:
    key = os.environ.get("FLOODS_API_KEY", "").strip()
    if not key and SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text().splitlines():
            if line.startswith("FLOODS_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise FloodHubError(
            "FLOODS_API_KEY not set and no "
            f"{SECRETS_FILE} — see docs/assessments/flood-hub-assessment.md")
    return key


def available() -> bool:
    """True when a key is configured — callers use this to degrade quietly."""
    try:
        api_key()
        return True
    except FloodHubError:
        return False


def _req(method: str, path: str, params: list | None = None,
         body: dict | None = None, raw: bool = False):
    key = api_key()
    q = list(params or []) + [("key", key)]
    url = f"{BASE}{path}"
    if q:
        url += ("&" if "?" in path else "?") + urllib.parse.urlencode(q)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as e:
        raise FloodHubError(
            f"HTTP {e.code} on {path}: {e.read().decode()[:400]}") from e
    except OSError as e:
        raise FloodHubError(f"request failed on {path}: {e}") from e
    return payload if raw else json.loads(payload or b"{}")


def _get(path: str, params: list | None = None) -> dict:
    return _req("GET", path, params=params)


def _post(path: str, body: dict) -> dict:
    return _req("POST", path, body=body)


# --- gauges ---------------------------------------------------------------

def search_gauges(region_code: str | None = None,
                  loop: dict | None = None,
                  include_unverified: bool = False,
                  include_without_model: bool = False) -> list:
    """gauges:searchGaugesByArea — region_code ('TH') or loop polygon."""
    gauges, token = [], None
    while True:
        body = {"pageSize": 1000,
                "includeNonQualityVerified": include_unverified,
                "includeGaugesWithoutHydroModel": include_without_model}
        if region_code:
            body["regionCode"] = region_code
        if loop:
            body["loop"] = loop
        if token:
            body["pageToken"] = token
        out = _post("/gauges:searchGaugesByArea", body)
        gauges += out.get("gauges", [])
        token = out.get("nextPageToken")
        if not token:
            return gauges


def get_gauges(gauge_ids: list) -> dict:
    """gauges:batchGet — {gaugeId: gauge} for siteName/river enrichment."""
    ids = list(dict.fromkeys(gauge_ids))
    if not ids:
        return {}
    params = [("names", f"gauges/{g}") for g in ids]
    out = _get("/gauges:batchGet", params=params)
    return {g.get("gaugeId"): g for g in out.get("gauges", [])}


# --- flood status ---------------------------------------------------------

def latest_statuses_by_gauge_ids(gauge_ids: list,
                                 cutoff_time: str | None = None) -> list:
    """floodStatus:queryLatestFloodStatusByGaugeIds (<=20k ids)."""
    params = [("gaugeIds", g) for g in gauge_ids]
    if cutoff_time:
        params.append(("cutoffTime", cutoff_time))
    out = _get("/floodStatus:queryLatestFloodStatusByGaugeIds", params=params)
    return out.get("floodStatuses", [])


def search_latest_statuses_by_area(region_code: str | None = None,
                                   loop: dict | None = None,
                                   include_unverified: bool = False,
                                   page_size: int = 5000) -> list:
    """floodStatus:searchLatestFloodStatusByArea — paginated."""
    statuses, token = [], None
    while True:
        body = {"pageSize": page_size,
                "includeNonQualityVerified": include_unverified}
        if region_code:
            body["regionCode"] = region_code
        if loop:
            body["loop"] = loop
        if token:
            body["pageToken"] = token
        out = _post("/floodStatus:searchLatestFloodStatusByArea", body)
        statuses += out.get("floodStatuses", [])
        token = out.get("nextPageToken")
        if not token:
            return statuses


def statuses_for_config(fhub_cfg: dict) -> dict:
    """Resolve a page's `flood_hub` config block to {area_label: [status]}.

    Config shapes (flood-news-feeds.json `flood_hub` key, registry can
    override the same way it overrides feeds):

      {"gauges": ["id1", ...]}                     # explicit watch list
      {"areas": [{"name": "...", "loop": {...}} or
                 {"name": "...", "regionCode": "TH"}]}
      plus optional "include_unverified": bool

    `gauges` wins when non-empty; otherwise every area is queried and
    merged under its label. Raises FloodHubError on API failure — callers
    decide whether that is fatal.
    """
    include_unverified = bool(fhub_cfg.get("include_unverified"))
    gauges = [g for g in (fhub_cfg.get("gauges") or []) if g]
    out = {}
    if gauges:
        label = fhub_cfg.get("label") or "watchlist"
        out[label] = latest_statuses_by_gauge_ids(gauges)
        return out
    for area in fhub_cfg.get("areas") or []:
        name = area.get("name") or area.get("label") or "area"
        loop = area.get("loop")
        region = area.get("regionCode") or area.get("region_code")
        if not loop and not region:
            continue
        out[name] = search_latest_statuses_by_area(
            region_code=region, loop=loop,
            include_unverified=include_unverified)
    return out


# --- forecasts / polygons (optional enrichments) ---------------------------

def query_forecasts(gauge_ids: list,
                    issued_time_start: str | None = None) -> dict:
    """gauges:queryGaugeForecasts — {gaugeId: ForecastSet}. <=500 ids."""
    ids = list(dict.fromkeys(gauge_ids))[:500]
    params = [("gaugeIds", g) for g in ids]
    if issued_time_start:
        params.append(("issuedTimeStart", issued_time_start))
    out = _get("/gauges:queryGaugeForecasts", params=params)
    return out.get("forecasts", {})


def get_serialized_polygon(poly_id: str) -> bytes:
    """serializedPolygons/{id} — raw KML/polygon payload for GEV overlay."""
    return _req("GET", f"/serializedPolygons/{urllib.parse.quote(poly_id)}",
                raw=True)


# --- helpers ---------------------------------------------------------------

def severity_rank(severity: str) -> int:
    return SEVERITY_RANK.get(severity or "", 0)


def meets_min(severity: str, min_severity: str = ALERT_MIN) -> bool:
    return severity_rank(severity) >= severity_rank(min_severity)


def sort_by_severity(statuses: list) -> list:
    return sorted(statuses,
                  key=lambda s: severity_rank(s.get("severity")),
                  reverse=True)


def status_point(s: dict) -> dict:
    """Compact normalized view of one FloodStatus."""
    loc = s.get("gaugeLocation") or {}
    return {
        "gaugeId": s.get("gaugeId"),
        "severity": s.get("severity"),
        "severityRank": severity_rank(s.get("severity")),
        "trend": s.get("forecastTrend"),
        "issuedTime": s.get("issuedTime"),
        "lat": loc.get("latitude"),
        "lon": loc.get("longitude"),
        "verified": s.get("qualityVerified"),
        "source": s.get("source"),
        "polygonId": s.get("serializedNotificationPolygonId"),
    }


def worst(statuses: list) -> str:
    return max((s.get("severity") or "NO_FLOODING" for s in statuses),
               key=severity_rank, default="NO_FLOODING")


if __name__ == "__main__":
    # smoke: python3 flood-hub-lib.py — reports key availability only
    print("key configured:", available())
    sys.exit(0 if available() else 1)
