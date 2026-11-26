"""kk_places — Google Places (New) lookup for member-lane place asks.

Card kk-places-tool (OPS-0506; Tony 2026-10-26 "use my google api key"):
the kk lane answers "ร้านนี้ยังอยู่มั้ย / is X open / มีอะไรดีแถวนี้"
with structured facts — name, address, coords, phone, hours, open-now,
rating — instead of a bare web_search snippet, then saves the
place-<slug> dossier from docs/kb/lane-place-reports.md so the next
ask reads CMS first. place_report owns the maps-link -> public page
flow; this tool owns the Places-API enrichment + the private dossier.

Calls Places API (New) — POST /v1/places:searchText for a name/address
query (optional lat/lon location bias for "แถวนี้" asks), or
GET /v1/places/{place_id} to re-verify a dossier's stored place_id —
and publishes the dossier via runner.cms_publish_page. Private by
default; public='yes' needs confirmed='yes' (same gate as
trip_calendar / cms_publish_page). The lookup answer is returned even
when the dossier write fails — the page is the durable artifact, the
reply is the facts.

Env:
    ADA_PLACES_API_KEY   dedicated Places key (optional)
    GOOGLE_MAPS_API_KEY  fallback — the minted Maps Platform key works
                         when its project has the Places API enabled
    ADA_PLACES_UA        User-Agent for outbound calls
"""

from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import httpx

SEARCH = "https://places.googleapis.com/v1/places:searchText"
DETAIL = "https://places.googleapis.com/v1/places/"
GMAPS_SEARCH = "https://www.google.com/maps/search/"

_FIELDS = ("id", "displayName", "formattedAddress", "location",
           "internationalPhoneNumber", "nationalPhoneNumber",
           "websiteUri", "rating", "userRatingCount", "priceLevel",
           "types", "googleMapsUri", "regularOpeningHours",
           "currentOpeningHours", "businessStatus")
FIELD_MASK_SEARCH = "places." + ",places.".join(_FIELDS)
FIELD_MASK_DETAIL = ",".join(_FIELDS)

UA = os.environ.get(
    "ADA_PLACES_UA", "chaba-ada-kk-places/1.0 (member-lane lookup)")

_TRUE = {"yes", "true", "1", "on", "y"}
_PRICE = {"PRICE_LEVEL_FREE": "free",
          "PRICE_LEVEL_INEXPENSIVE": "$",
          "PRICE_LEVEL_MODERATE": "$$",
          "PRICE_LEVEL_EXPENSIVE": "$$$",
          "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$"}

DECLARATION = {
    "name": "kk_places",
    "description": (
        "Google Places lookup for place asks — name/address in, "
        "structured facts out (address, coords, phone, hours, "
        "open-now, rating) plus a saved place dossier page. Use for "
        "'is X open', 'ร้านนี้ยังอยู่มั้ย', 'ร้านแถวนี้'."),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Place name or address to look up — "
                               "verbatim what the member said. Omit "
                               "when refreshing by place_id.",
            },
            "place_id": {
                "type": "string",
                "description": "Google place_id to re-fetch details "
                               "for — use the place_id from a previous "
                               "kk_places result or a place-* dossier "
                               "to re-verify stale facts.",
            },
            "lat": {
                "type": "number",
                "description": "Latitude bias for 'near me' asks — "
                               "pass with lon when the member means a "
                               "spot near a known location.",
            },
            "lon": {
                "type": "number",
                "description": "Longitude bias — pass with lat.",
            },
            "limit": {
                "type": "number",
                "description": "Max candidates to return, 1-10 "
                               "(default 3) — the dossier is written "
                               "for the top match only.",
            },
            "lang": {
                "type": "string",
                "description": "Result language: 'th' or 'en' "
                               "(default th for kk lane chats).",
            },
            "public": {
                "type": "string",
                "description": "'yes' publishes the dossier to the "
                               "lane's public site — only when the "
                               "member explicitly asked for a "
                               "shareable link, and then pass "
                               "confirmed='yes'.",
            },
            "confirmed": {
                "type": "string",
                "description": "'yes' only after the member confirmed "
                               "public publishing out loud.",
            },
        },
        "additionalProperties": False,
    },
}


def _api_key() -> str:
    return (os.environ.get("ADA_PLACES_API_KEY", "").strip()
            or os.environ.get("GOOGLE_MAPS_API_KEY", "").strip())


def _slug_for(place: dict[str, Any]) -> str:
    """place-<name>-<seed6> — deterministic per resolved place so a
    re-ask upserts the same dossier instead of duplicating it."""
    name = place.get("name") or place.get("address") or "place"
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    if not base:
        base = "place"
    seed_src = place.get("place_id") or "|".join(
        str(place.get(k) or "") for k in ("name", "coords", "address"))
    seed = hashlib.sha1(seed_src.encode()).hexdigest()[:6]
    return f"place-{base}-{seed}"[:64]


def _norm(p: dict[str, Any], checked_at: str) -> dict[str, Any]:
    """Places API (New) Place -> flat lane-facing dict."""
    loc = p.get("location") or {}
    coords = ""
    try:
        if loc.get("latitude") is not None and loc.get("longitude") is not None:
            coords = (f"{float(loc['latitude']):.6f},"
                      f"{float(loc['longitude']):.6f}")
    except (TypeError, ValueError):
        coords = ""
    dn = p.get("displayName") or {}
    hours = (p.get("currentOpeningHours")
             or p.get("regularOpeningHours") or {})
    open_now = hours.get("openNow")
    return {
        "name": str(dn.get("text") or "").strip(),
        "place_id": str(p.get("id") or ""),
        "address": str(p.get("formattedAddress") or ""),
        "coords": coords,
        "phone": (p.get("internationalPhoneNumber")
                  or p.get("nationalPhoneNumber") or ""),
        "website": str(p.get("websiteUri") or ""),
        "rating": p.get("rating"),
        "ratings_count": p.get("userRatingCount"),
        "price_level": _PRICE.get(str(p.get("priceLevel") or ""), ""),
        "types": [str(t) for t in (p.get("types") or [])][:8],
        "google_maps_uri": str(p.get("googleMapsUri") or ""),
        "business_status": str(p.get("businessStatus") or ""),
        "open_now": open_now,
        "hours": [str(h) for h in (hours.get("weekdayDescriptions") or [])],
        "checked_at": checked_at,
    }


def _verdict(place: dict[str, Any], lang: str) -> str:
    """One-line status for the dossier — honest about unknowns."""
    bs = place.get("business_status")
    if bs == "CLOSED_PERMANENTLY":
        return ("ปิดกิจการแล้ว (permanently closed)"
                if lang == "th" else "Permanently closed")
    if bs == "CLOSED_TEMPORARILY":
        return ("ปิดชั่วคราว (temporarily closed)"
                if lang == "th" else "Temporarily closed")
    if place.get("open_now") is True:
        return ("เปิดอยู่ (open now)" if lang == "th"
                else "Open now")
    if place.get("open_now") is False:
        return ("ปิดอยู่ตอนนี้ (closed now)" if lang == "th"
                else "Closed now")
    return ("ไม่ทราบสถานะเปิด-ปิด (hours on file below)"
            if lang == "th" else "Open status unknown — hours below")


def _page(place: dict[str, Any], query: str, lang: str,
          lane: str) -> tuple[str, str]:
    """place-<slug> dossier body — docs/kb/lane-place-reports.md shape:
    status verdict -> hours -> contact -> notes -> provenance."""
    name = place["name"] or place["address"].split(",")[0] or "Place"
    title = name if lang == "en" else f"{name} — place dossier"
    lines = [f"# {name}", ""]
    if place["address"]:
        lines += [place["address"], ""]
    facts = []
    if place["coords"]:
        facts.append(f"Coordinates: {place['coords']}")
    if place.get("rating") is not None:
        n = place.get("ratings_count")
        facts.append(f"Rating: {place['rating']}"
                     + (f" ({n} reviews)" if n else ""))
    if place.get("price_level"):
        facts.append(f"Price: {place['price_level']}")
    if place.get("business_status"):
        facts.append(f"Status: {place['business_status']}")
    if facts:
        lines += [" · ".join(facts), ""]
    links = []
    if place["google_maps_uri"]:
        links.append(f"[Google Maps]({place['google_maps_uri']})")
    if place["coords"]:
        lat, lon = place["coords"].split(",", 1)
        links.append(
            f"[OpenStreetMap](https://www.openstreetmap.org/"
            f"?mlat={lat}&mlon={lon}#map=16/{lat}/{lon})")
    if place["website"]:
        links.append(f"[Website]({place['website']})")
    if links:
        lines += [" · ".join(links), ""]
    label_status = "สถานะ" if lang == "th" else "Status"
    lines += [f"## {label_status}", "", _verdict(place, lang), ""]
    if place["hours"]:
        label_hours = "เวลาเปิด-ปิด" if lang == "th" else "Hours"
        lines += [f"## {label_hours}", ""]
        lines += [f"- {h}" for h in place["hours"]]
        lines.append("")
    contact = []
    if place["phone"]:
        contact.append(f"Phone: {place['phone']}")
    if place["website"]:
        contact.append(f"Web: {place['website']}")
    label_contact = "ติดต่อ" if lang == "th" else "Contact"
    lines += [f"## {label_contact}", ""]
    lines += contact or ["no phone/website on file"]
    lines.append("")
    label_notes = "บันทึก" if lang == "th" else "Notes"
    bits = []
    if place.get("types"):
        bits.append("types: " + ", ".join(place["types"]))
    if place.get("place_id"):
        bits.append(f"place_id: {place['place_id']}")
    if query:
        bits.append(f"asked as: {query}")
    lines += [f"## {label_notes}", ""]
    lines += [" · ".join(bits), ""]
    lane_tag = f"{lane} " if lane else ""
    lines += ["---", "",
              f"*Checked by {lane_tag}via google-places · "
              f"{place['checked_at']}Z*"]
    return title, "\n".join(lines)


def _lane() -> str:
    """Lane tag for the provenance footer — same env binding the
    runner uses (ada-cms-pages[-<x>] -> tony|<x>); read directly so the
    module stays loadable outside the ada-voice package."""
    coll = os.environ.get("ADA_CMS_COLLECTION", "")
    if coll == "ada-cms-pages":
        return "tony"
    if coll.startswith("ada-cms-pages-"):
        return coll[len("ada-cms-pages-"):]
    return coll or ""


async def _places_call(client: httpx.AsyncClient, key: str,
                       place_id: str, body: dict[str, Any],
                       lang: str) -> dict[str, Any]:
    """One Places API (New) call — details GET or searchText POST."""
    headers = {"X-Goog-Api-Key": key,
               "X-Goog-FieldMask": (FIELD_MASK_DETAIL if place_id
                                    else FIELD_MASK_SEARCH)}
    if place_id:
        r = await client.get(
            DETAIL + urllib.parse.quote(place_id, safe=""),
            params={"languageCode": lang}, headers=headers)
    else:
        r = await client.post(SEARCH, json=body, headers=headers)
    r.raise_for_status()
    return r.json() or {}


def _api_error(exc: Exception) -> dict[str, Any]:
    """Surface Google's error object when present; REQUEST_DENIED on a
    Places call almost always means the key's project lacks the API."""
    msg = getattr(exc, "message", "") or str(exc)
    resp = getattr(exc, "response", None)
    detail = ""
    if resp is not None:
        try:
            err = (resp.json() or {}).get("error") or {}
            detail = str(err.get("message") or "")
            status = str(err.get("status") or "")
        except Exception:
            status, detail = "", ""
        code = getattr(resp, "status_code", "")
        if status == "PERMISSION_DENIED" or code in (401, 403):
            return {"ok": False,
                    "error": f"Places API rejected the key ({code} "
                             f"{status}) — the key's GCP project needs "
                             "the Places API (New) enabled, or set "
                             "ADA_PLACES_API_KEY to a key that has it. "
                             + (detail or msg)[:200]}
        return {"ok": False,
                "error": f"Places API error {code}: "
                         f"{(detail or msg)[:200]}"}
    return {"ok": False, "error": f"Places lookup failed: "
                                  f"{type(exc).__name__} — "
                                  f"{msg[:160]}"}


async def run(runner: Any, **args: Any) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    place_id = str(args.get("place_id") or "").strip()
    lang = str(args.get("lang") or "th").strip().lower() or "th"
    if lang not in ("th", "en"):
        lang = "th"
    public = str(args.get("public") or "").strip().lower() in _TRUE
    confirmed = str(args.get("confirmed") or "").strip().lower() in _TRUE
    try:
        limit = int(args.get("limit") or 3)
    except (TypeError, ValueError):
        limit = 3
    limit = max(1, min(limit, 10))
    lat = args.get("lat")
    lon = args.get("lon")

    if not query and not place_id:
        return {"ok": False,
                "error": "need a place name/address as query= or a "
                         "place_id= from a previous result — pass what "
                         "the member said verbatim"}

    key = _api_key()
    maps_fallback = (
        GMAPS_SEARCH + "?api=1&query="
        + urllib.parse.quote_plus(query or place_id))
    if not key:
        return {"ok": False, "needs_key": True,
                "maps_url": maps_fallback,
                "error": "Places lookup needs a Maps Platform key with "
                         "the Places API enabled — set ADA_PLACES_API_KEY "
                         "or GOOGLE_MAPS_API_KEY on the backend env. "
                         "No lookup ran; send maps_url in chat or fall "
                         "back to web_search — never invent place facts"}

    body: dict[str, Any] = {"textQuery": query, "maxResultCount": limit,
                           "languageCode": lang}
    try:
        alat, alon = float(lat), float(lon)
    except (TypeError, ValueError):
        alat = alon = None
    if alat is not None and alon is not None:
        body["locationBias"] = {"circle": {
            "center": {"latitude": alat, "longitude": alon},
            "radius": 2000.0}}

    checked_at = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    try:
        async with httpx.AsyncClient(
                timeout=15.0, follow_redirects=True,
                headers={"User-Agent": UA}) as client:
            data = await _places_call(client, key, place_id, body, lang)
    except Exception as exc:
        return _api_error(exc)

    if place_id:
        raw_places = [data] if data.get("id") else []
    else:
        raw_places = list(data.get("places") or [])
    places = [_norm(p, checked_at) for p in raw_places[:limit]]
    places = [p for p in places if p["name"] or p["address"]]

    out: dict[str, Any] = {
        "ok": True,
        "query": query,
        "place_id": place_id,
        "checked_at": checked_at,
        "places": places,
        "count": len(places),
    }
    if not places:
        out["maps_url"] = maps_fallback
        out["note"] = ("Google Places found no match — say so plainly "
                       "and offer maps_url so the member can pin the "
                       "spot; do not invent name/hours/phone. A "
                       "place-* dossier was NOT written.")
        return out

    best = places[0]
    out["best"] = best
    out["maps_url"] = best["google_maps_uri"] or maps_fallback

    # --- dossier save-back (docs/kb/lane-place-reports.md) -----------
    slug = _slug_for(best)
    title, content = _page(best, query, lang, _lane())
    want_public = public
    pub_blocked = False
    if want_public and not confirmed:
        want_public = False
        pub_blocked = True
    summary = (f"Place dossier: {best['name'] or best['address']} — "
               f"{(best['address'] or '')[:80]}")
    dossier: dict[str, Any] = {"slug": slug, "public": want_public}
    try:
        pub = await runner.cms_publish_page(
            slug=slug, title=title, content=content, format="markdown",
            lang=lang, summary=summary, domain="places",
            public="true" if want_public else "false",
            fresh_for="7d",
            confidence="high" if best.get("place_id") else "medium")
        dossier.update({k: pub.get(k) for k in
                        ("status", "view_url", "public_url")})
        dossier["ok"] = True
    except Exception as exc:
        dossier.update({"ok": False,
                        "error": f"dossier publish failed "
                                 f"({type(exc).__name__}): {exc}"})
    out["dossier"] = dossier

    notes = ["answer with the facts AND the check time — 'open now' "
             "is only true as of checked_at; stale answers need a "
             "re-call, not memory"]
    if pub_blocked:
        notes.append("public='yes' was requested without confirmed='yes' "
                     "— the dossier saved PRIVATE; re-call with "
                     "confirmed='yes' only after the member explicitly "
                     "asks for a shareable link")
    if not dossier.get("ok"):
        notes.append("the place-* dossier did NOT save — still answer "
                     "from places[] but say the page could not be "
                     "written; do not claim it was")
    out["note"] = " · ".join(notes)
    return out
