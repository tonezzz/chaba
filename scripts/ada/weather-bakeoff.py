#!/usr/bin/env python3
"""weather-bakeoff — side-by-side forecast comparison for a lane's house.

Card kraut-weather-bakeoff (Tony+Michael decision 2026-10-20): Kraut's
weather report currently covers current conditions (RK600) only; forecast
asks fall through to web_search. This demo report keeps measured station
data on top and lines every candidate forecast source up below it in
numbers so the winner is picked by comparing, not guessing.

Sources (all verified live 2026-10-20):
  RK600   sensor.rk600* via the lane's HA upstream (measured ground truth)
  HA-FC   weather.get_forecasts on the lane's weather.* entity
  ECMWF/GFS/ICON  Open-Meteo models= param (free, no key)
  METNO   api.met.no locationforecast compact (free, UA header only)
  TMD     data.tmd.go.th WeatherForecast7Days (provincial, demo key)
  GEMINI  REST generateContent + google_search grounding on the lane
          REST key — same mechanism web_search uses (graceful n/a)

Output: a PNG table (engineer numbers view) dropped into the relay-img
arch dir -> durable public URL, plus a compact text caption. --send posts
both to the lane's TG send API (ada-ai-kraut.env ADA_TG_SEND_URL).

Usage (on idc03, ada-voice venv for PIL):
  ~/CascadeProjects/ada-voice/.venv/bin/python \
      scripts/ada/weather-bakeoff.py --send [--chat 8960073266]
  --no-send prints the text + PNG path only.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

ICT = timezone(timedelta(hours=7))
UA = "chaba-weather-bakeoff/0.1 tony@surf-thailand.com"
TMD_URL = ("https://data.tmd.go.th/api/WeatherForecast7Days/v2/"
           "?uid=api&ukey=api12345&type=xml")
OM_URL = ("https://api.open-meteo.com/v1/forecast"
          "?latitude={lat}&longitude={lon}"
          "&daily=temperature_2m_max,temperature_2m_min,"
          "precipitation_probability_max"
          "&hourly=temperature_2m,precipitation_probability"
          "&forecast_days=5&timezone=Asia%2FBangkok"
          "&models=ecmwf_ifs025,gfs_seamless,icon_seamless")
METNO_URL = ("https://api.met.no/weatherapi/locationforecast/2.0/compact"
             "?lat={lat}&lon={lon}")
ARCH_DIR = Path.home() / ".local/share/ada/line-media/bakeoff"
PUBLIC_BASE = "https://157.85.102.125.sslip.io/relay-img/arch/bakeoff"


def load_env(path: str) -> dict[str, str]:
    env = {}
    for line in Path(path).expanduser().read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def http_json(url: str, headers: dict | None = None,
              data: bytes | None = None, timeout: int = 20):
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": UA, **(headers or {})},
        method="POST" if data else "GET")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read())


def http_bytes(url: str, headers: dict | None = None,
               timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout,
                                context=ssl.create_default_context()) as r:
        return r.read()


# ---------------------------------------------------------------- fetchers

def rk600_now(ha_url: str, token: str) -> dict:
    states = http_json(f"{ha_url}/api/states",
                       {"Authorization": f"Bearer {token}"})
    out = {}
    for e in states:
        eid = e.get("entity_id", "")
        if not eid.startswith("sensor.rk600"):
            continue
        out[eid] = {"state": e.get("state"),
                    "name": e.get("attributes", {}).get("friendly_name", eid),
                    "unit": e.get("attributes", {}).get("unit_of_measurement", "")}
    return out


def ha_daily(ha_url: str, token: str) -> list[dict]:
    body = json.dumps({"entity_id": "weather.forecast_home",
                       "type": "daily"}).encode()
    req = urllib.request.Request(
        f"{ha_url}/api/services/weather/get_forecasts?return_response",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20,
                                context=ssl.create_default_context()) as r:
        d = json.loads(r.read())
    fc = d["service_response"]["weather.forecast_home"]["forecast"]
    return [{"date": x["datetime"][:10], "hi": x.get("temperature"),
             "lo": x.get("templow"), "rain_mm": x.get("precipitation"),
             "cond": x.get("condition")} for x in fc]


def openmeteo(lat: float, lon: float) -> dict[str, list[dict]]:
    d = http_json(OM_URL.format(lat=lat, lon=lon))
    daily = d["daily"]
    out = {}
    for model, tag in (("ecmwf_ifs025", "ECMWF"), ("gfs_seamless", "GFS"),
                       ("icon_seamless", "ICON")):
        rows = []
        for i, day in enumerate(daily["time"]):
            hi = daily.get(f"temperature_2m_max_{model}", [None] * 9)[i]
            lo = daily.get(f"temperature_2m_min_{model}", [None] * 9)[i]
            rp = daily.get(f"precipitation_probability_max_{model}",
                           [None] * 9)[i]
            rows.append({"date": day, "hi": hi, "lo": lo, "rain": rp})
        out[tag] = rows
    hourly = {}
    htime = d["hourly"]["time"]
    for model, tag in (("ecmwf_ifs025", "ECMWF"), ("gfs_seamless", "GFS"),
                       ("icon_seamless", "ICON")):
        hourly[tag] = [
            {"time": t, "temp": d["hourly"].get(
                f"temperature_2m_{model}", [None] * len(htime))[i],
             "rain": d["hourly"].get(
                 f"precipitation_probability_{model}",
                 [None] * len(htime))[i]}
            for i, t in enumerate(htime)]
    return {"daily": out, "hourly": hourly}


def metno(lat: float, lon: float) -> list[dict]:
    d = http_json(METNO_URL.format(lat=lat, lon=lon))
    by_day: dict[str, dict] = {}
    for ts in d["properties"]["timeseries"]:
        day = ts["time"][:10]
        det = ts["data"]["instant"]["details"]
        t = det.get("air_temperature")
        p6 = ts["data"].get("next_6_hours", {}).get("details", {}) \
            .get("precipitation_amount")
        cur = by_day.setdefault(day, {"hi": None, "lo": None, "rain_mm": 0.0})
        if t is not None:
            cur["hi"] = t if cur["hi"] is None else max(cur["hi"], t)
            cur["lo"] = t if cur["lo"] is None else min(cur["lo"], t)
        if p6:
            cur["rain_mm"] += p6
    return [{"date": k, **v} for k, v in sorted(by_day.items())]


def tmd(province: str = "Rayong") -> list[dict]:
    raw = http_bytes(TMD_URL)
    root = ET.fromstring(raw)
    for prov in root.iter("Province"):
        name = prov.findtext("ProvinceNameEnglish") or ""
        if name.strip().lower() != province.lower():
            continue
        days = []
        node = prov.find("SevenDaysForecast")
        # TMD flattens day fields as sequential children of
        # SevenDaysForecast — a ForecastDate opens each day block.
        cur = None
        for el in node:
            if el.tag == "ForecastDate":
                cur = {"date_raw": el.text}
                days.append(cur)
            elif cur is not None:
                cur[el.tag] = el.text
        out = []
        for day in days:
            try:
                dt = datetime.strptime(day["date_raw"], "%d/%m/%Y")
                out.append({"date": dt.strftime("%Y-%m-%d"),
                            "hi": float(day["MaximumTemperature"]),
                            "lo": float(day["MinimumTemperature"]),
                            "rain": float(day["PercentRainCover"]),
                            "wind_kn": float(day.get("WindSpeed", 0)),
                            "cond": day.get("DescriptionEnglish", "")})
            except (KeyError, ValueError):
                continue
        return sorted(out, key=lambda x: x["date"])
    return []


def gemini_baseline(env: dict, lat: float, lon: float) -> str:
    base = (env.get("ADA_GEMINI_REST_BASE_URL") or
            "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    key = env.get("ADA_GEMINI_REST_API_KEY") or env.get("GEMINI_API_KEY", "")
    model = env.get("ADA_TEXT_MODEL") or "gemini-2.5-flash"
    q = (f"Weather forecast for the next 3 days at {lat:.3f}N {lon:.3f}E "
         "(Ban Chang, Rayong, Thailand) — highs, lows, rain chance. "
         "Two lines max.")
    body = json.dumps({
        "contents": [{"parts": [{"text": q}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"maxOutputTokens": 200},
    }).encode()
    for url in (f"{base}/models/{model}:generateContent?key={key}",
                f"{base}/chat/completions"):
        try:
            if "generateContent" in url:
                d = http_json(url, data=body)
                return d["candidates"][0]["content"]["parts"][0][
                    "text"].strip().replace("\n", " ")
            # LiteLLM shape — no grounding, still a baseline sentence
            d = http_json(
                url, data=json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": q}],
                    "max_tokens": 200}).encode(),
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})
            return d["choices"][0]["message"]["content"].strip() \
                .replace("\n", " ")
        except Exception:
            continue
    raise RuntimeError("gemini baseline: all endpoints failed")


# ---------------------------------------------------------------- render

def f(v, spec="{:.0f}") -> str:
    return "-" if v is None else spec.format(v)


def build_rows(sources: dict[str, list[dict]], days: list[str]) -> list[list]:
    """One row per source: [label, cell per day] cell='hi/lo·rNN'."""
    rows = []
    for name, fc in sources.items():
        by = {d["date"]: d for d in fc}
        cells = []
        for day in days:
            e = by.get(day)
            if not e:
                cells.append("-")
                continue
            rain = e.get("rain")
            if rain is None and e.get("rain_mm") is not None:
                rain_txt = f"{e['rain_mm']:.0f}mm"
            else:
                rain_txt = f"{f(rain)}%"
            cells.append(f"{f(e.get('hi'))}/{f(e.get('lo'))}·{rain_txt}")
        rows.append([name] + cells)
    return rows


def render_png(now_txt: str, place: str, fetched: str,
               daily_rows: list[list], day_labels: list[str],
               hourly_rows: list[list], hour_labels: list[str],
               notes: list[str], out_png: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    def font(sz: int, bold: bool = False):
        cand = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
            if bold else
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/"
            "LiberationMono-Regular.ttf",
        ]
        for c in cand:
            if Path(c).exists():
                return ImageFont.truetype(c, sz)
        return ImageFont.load_default()

    F_T, F_H, F_B, F_S = font(30, True), font(24, True), font(21), font(18)
    W = 940
    pad = 24
    lab = 140
    colw = [lab] + [int((W - 2 * pad - lab) / len(day_labels))] * len(day_labels)
    hcolw = [lab] + [int((W - 2 * pad - lab) / len(hour_labels))] * len(hour_labels)

    def measure():
        h = pad + 44 + 30 + 34  # title + now + daily header
        h += len(daily_rows) * 32 + 16 + 30 + 34
        h += len(hourly_rows) * 32 + 20 + len(notes) * 24 + pad
        return h

    img = Image.new("RGB", (W, measure()), "#0d1117")
    dr = ImageDraw.Draw(img)
    y = pad
    dr.text((pad, y), f"WEATHER BAKE-OFF - {place}", font=F_T,
            fill="#e6edf3")
    y += 40
    dr.text((pad, y), f"fetched {fetched}", font=F_S, fill="#8b949e")
    y += 30
    dr.text((pad, y), now_txt, font=F_B, fill="#58d6a0")
    y += 34

    def table(rows, labels, colws):
        nonlocal y
        x = pad
        dr.rectangle([pad, y, W - pad, y + 30], fill="#161b22")
        for i, lab in enumerate(labels):
            dr.text((x + 6, y + 4), lab, font=F_H, fill="#79b8ff")
            x += colws[i]
        y += 32
        for r_i, row in enumerate(rows):
            bg = "#11151b" if r_i % 2 else "#0d1117"
            dr.rectangle([pad, y, W - pad, y + 30], fill=bg)
            x = pad
            for i, cell in enumerate(row):
                dr.text((x + 6, y + 3), str(cell), font=F_B,
                        fill="#e6edf3" if i else "#ffa657")
                x += colws[i]
            y += 32

    table(daily_rows, ["DAILY"] + day_labels, colw)
    y += 16
    table(hourly_rows, ["NEXT12H"] + hour_labels, hcolw)
    y += 20
    for n in notes:
        dr.text((pad, y), n, font=F_S, fill="#8b949e")
        y += 24
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file",
                    default="~/.config/secrets/ada-ai-kraut.env")
    ap.add_argument("--chat", default=None,
                    help="TG chat_id (default: first allowed via relay)")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--out", default=None, help="PNG path override")
    ap.add_argument("--province", default="Rayong")
    ap.add_argument("--ha-url", default=None,
                    help="override HOME_ASSISTANT_URL (e.g. ssh tunnel)")
    ap.add_argument("--ha-token", default=None)
    args = ap.parse_args()

    env = {**load_env(args.env_file), **os.environ}
    ha_url = (args.ha_url or env["HOME_ASSISTANT_URL"]).rstrip("/")
    token = args.ha_token or env["HOME_ASSISTANT_TOKEN"]

    cfg = http_json(f"{ha_url}/api/config",
                    {"Authorization": f"Bearer {token}"})
    lat, lon = cfg["latitude"], cfg["longitude"]
    place = f"{lat:.2f}N {lon:.2f}E"

    # --- fetch all sources, never let one kill the report
    errs: dict[str, str] = {}
    try:
        rk = rk600_now(ha_url, token)
    except Exception as e:
        rk, errs["RK600"] = {}, str(e)
    try:
        ha = ha_daily(ha_url, token)
    except Exception as e:
        ha, errs["HA-FC"] = [], str(e)
    try:
        om = openmeteo(lat, lon)
    except Exception as e:
        om, errs["OM"] = {"daily": {}, "hourly": {}}, str(e)
    try:
        mn = metno(lat, lon)
    except Exception as e:
        mn, errs["METNO"] = [], str(e)
    try:
        td = tmd(args.province)
    except Exception as e:
        td, errs["TMD"] = [], str(e)
    try:
        gm = gemini_baseline(env, lat, lon)
    except Exception as e:
        gm, errs["GEMINI"] = "", str(e)

    fetched = datetime.now(ICT).strftime("%H:%M ICT %d %b")

    # --- now line (RK600 measured)
    def pick(sub):
        for eid, s in rk.items():
            if sub in eid and s["state"] not in ("unknown", "unavailable"):
                try:
                    return f"{float(s['state']):.1f}{s['unit']}"
                except ValueError:
                    return s["state"]
        return "-"
    now_txt = (f"NOW (RK600 station, measured): "
               f"{pick('temperature')} · {pick('humidity')} RH · "
               f"wind {pick('wind_speed')}")

    # --- daily matrix
    sources_daily: dict[str, list[dict]] = {}
    for tag in ("ECMWF", "GFS", "ICON"):
        if om["daily"].get(tag):
            sources_daily[tag] = om["daily"][tag]
    if mn:
        sources_daily["METNO"] = [
            {"date": d["date"], "hi": d["hi"], "lo": d["lo"],
             "rain_mm": d["rain_mm"]} for d in mn]
    if ha:
        sources_daily["HA-FC"] = [
            {"date": d["date"], "hi": d["hi"], "lo": d["lo"],
             "rain_mm": d["rain_mm"], "cond": d["cond"]} for d in ha]
    if td:
        sources_daily["TMD"] = td
    days = sorted({d["date"] for fc in sources_daily.values()
                   for d in fc})[:5]
    day_labels = [datetime.strptime(x, "%Y-%m-%d").strftime("%a %d")
                  for x in days]
    daily_rows = build_rows(sources_daily, days)
    if td:
        conds = {d["date"]: d.get("cond", "") for d in td}
        first = next((conds[d] for d in days if conds.get(d)), "")
        if first:
            daily_rows.append(["TMD says", first[:28]])
    if gm:
        daily_rows.append(["GEMINI", gm[:48]])
    elif "GEMINI" in errs:
        daily_rows.append(["GEMINI", f"n/a ({errs['GEMINI'][:36]})"])

    # --- hourly next-12h, 3-hourly slots
    now = datetime.now(ICT).replace(minute=0, second=0, microsecond=0)
    slots = [now + timedelta(hours=3 * i) for i in range(1, 5)]
    slot_keys = [s.strftime("%Y-%m-%dT%H:00") for s in slots]
    hour_labels = [s.strftime("%Hh") for s in slots]
    hourly_rows = []
    for tag, series in om["hourly"].items():
        idx = {p["time"]: p for p in series}
        cells = []
        for k in slot_keys:
            p = idx.get(k)
            cells.append("-" if not p else
                         f"{f(p['temp'])}·{f(p['rain'])}")
        hourly_rows.append([tag] + cells)

    notes = [
        "rain = daily % chance (TMD cover) | hourly = precip %",
        "sources: RK600 measured · HA-FC weather.forecast_home ·",
        "  ECMWF/GFS/ICON via Open-Meteo · METNO api.met.no ·",
        "  TMD data.tmd.go.th (Rayong) · GEMINI lane REST+grounding",
    ] + [f"! {k}: {v[:52]}" for k, v in errs.items()]

    ts = datetime.now(ICT).strftime("%Y%m%d-%H%M")
    out_png = Path(args.out) if args.out else ARCH_DIR / f"wx-{ts}.png"
    try:
        render_png(now_txt, place, fetched, daily_rows, day_labels,
                   hourly_rows, hour_labels, notes, out_png)
    except ImportError:
        out_png = None
        print("PIL missing - text only")

    # --- text caption
    lines = ["WEATHER BAKE-OFF " + place + " · " + fetched, "",
             now_txt, "", "DAILY hi/lo · rain%:"]
    for r in daily_rows:
        lines.append("  " + " | ".join(str(c) for c in r))
    lines.append("")
    lines.append("NEXT 12H (3-hourly, temp·rain%):")
    for r in hourly_rows:
        lines.append("  " + " | ".join(str(c) for c in r))
    text = "\n".join(lines)
    print(text)
    if out_png:
        print(f"\npng: {out_png}")

    if not args.send:
        return 0

    send_url = env.get("ADA_TG_SEND_URL", "http://127.0.0.1:8917/send")
    payload = {"text": text[:3800]}
    if args.chat:
        payload["chat_id"] = int(args.chat)
    if out_png:
        payload["photo_url"] = f"{PUBLIC_BASE}/{out_png.name}"
        payload["caption"] = f"Weather bake-off {place} {fetched}"
    d = http_json(send_url, data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json"}, timeout=30)
    print("send:", d)
    return 0 if d.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
