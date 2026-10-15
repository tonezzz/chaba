#!/usr/bin/env python3
"""cam snapshot writer: go2rtc frames -> WP cam CPT (boards.surf-thailand.com).

Runs on the go2rtc aggregator host (tony-dell) via wp-cam-snapshot.timer
(job:wp-cam-snapshot, rendered from ssot.jobs.yml). Each run:

  1. enumerate cams from the go2rtc config `streams:` section
     (~/.config/go2rtc/go2rtc.yaml; falls back to GET /api/streams)
  2. collapse *_hd/_low/_sd quality variants onto their base stream
     (same physical camera — cam-wall-pull convention), then GET
     /api/frame.jpeg?src=<cam> with variant fallback per cam
  3. upload the frame as a WP attachment (POST /wp/v2/media)
  4. create a private cam post — title "Cam — <id> <ts>", deterministic
     slug cam-<id>-<yyyymmdd-HHMMSS>, meta camera_id/captured_at/
     kind=live/stream_url, featured_media=<attachment>
  5. upsert the per-camera directory post (slug cam-<id>, kind=live) —
     its featured image + captured_at track the newest frame
  6. purge snapshot posts + their attachments older than RETENTION_DAYS
     (directory posts are kept — their slug carries no timestamp)

Creds: ~/.config/secrets/wp-boards.env (WP_SITE_URL/WP_APP_USER/
WP_APP_PASSWORD) — parsed, never sourced (password has shell-special
chars). Fleet writers hit the WP origin (WP_SITE_URL points at
boards.h3.gizmo-thailand.com): the public edge bot-checks script UAs
(ssot.wp-boards.yml). REST rides index.php?rest_route= — the api()
helper rewrites ? to & like line-chat-timeline.py.

Env overrides: GO2RTC_URL, GO2RTC_CONFIG, WP_BOARDS_ENV, WP_BASE,
CAM_SNAPSHOT_SKIP (comma list), CAM_SNAPSHOT_ALL_STREAMS=1 (disable
variant collapse), CAM_STREAM_BASE, CAM_SNAPSHOT_RETENTION_DAYS.
Flags: --dry-run (no WP writes), --cams=a,b (override roster), --seed-only
(directory upserts only, no snapshots/purge), --purge-only.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

GO2RTC = os.environ.get("GO2RTC_URL", "http://127.0.0.1:1984").rstrip("/")
GO2RTC_CFG = os.environ.get(
    "GO2RTC_CONFIG",
    os.path.expanduser("~/.config/go2rtc/go2rtc.yaml"))
WP_ENV = os.environ.get(
    "WP_BOARDS_ENV", os.path.expanduser("~/.config/secrets/wp-boards.env"))
STREAM_BASE = os.environ.get("CAM_STREAM_BASE", GO2RTC)
RETENTION_DAYS = int(os.environ.get("CAM_SNAPSHOT_RETENTION_DAYS", "7"))
FRAME_TIMEOUT = int(os.environ.get("CAM_SNAPSHOT_FRAME_TIMEOUT", "20"))
MIN_FRAME_BYTES = 500  # dead streams return 200 + tiny/empty body (cam-wall-pull)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SNAP_SLUG = re.compile(r"^cam-.+-\d{8}-\d{6}$")
DRY = "--dry-run" in sys.argv

# --- WP REST (app-password basic auth; index.php?rest_route= style) ----------

def _load_wp_env(path):
    env = {}
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError:
        return env
    for line in lines:
        if "=" in line:
            k, v = line.rstrip("\n").split("=", 1)
            env[k] = v
    return env

_env = _load_wp_env(WP_ENV)
BASE = (os.environ.get("WP_BASE") or _env.get("WP_SITE_URL") or "").strip().rstrip("/")
AUTH = ""
if _env.get("WP_APP_USER") and _env.get("WP_APP_PASSWORD"):
    AUTH = "Basic " + base64.b64encode(
        f"{_env['WP_APP_USER'].strip()}:{_env['WP_APP_PASSWORD'].strip()}"
        .encode()).decode()


def api(method, route, data=None, raw=None, ctype="application/json",
        filename=None):
    """WP REST helper — same conventions as scripts/ada/line-chat-timeline.py.
    route uses ? for the first query arg; it is rewritten to & because the
    query slot is already occupied by rest_route."""
    route = route.replace("?", "&")
    url = f"{BASE}/index.php?rest_route=/wp/v2/{route}"
    body = raw if raw is not None else (
        json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", AUTH)
    req.add_header("User-Agent", UA)
    if body:
        req.add_header("Content-Type", ctype)
        if filename:
            req.add_header("Content-Disposition",
                           f'attachment; filename="{filename}"')
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": e.read()[:200].decode(errors="replace")}


# --- go2rtc ------------------------------------------------------------------

def http_get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def go2rtc_streams(path=GO2RTC_CFG):
    """Stream names = first-level children of the top-level `streams:`
    mapping in go2rtc.yaml. Indent-based — no yaml dep, and robust to the
    mixed str/list/map values go2rtc allows per stream."""
    names, in_streams, child_indent = [], False, None
    try:
        with open(path) as fh:
            lines = fh.readlines()
        for raw in lines:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                in_streams = line.split(":")[0].strip() == "streams"
                child_indent = None
                continue
            if not in_streams:
                continue
            if child_indent is None:
                child_indent = indent
            if indent == child_indent and not line.lstrip().startswith("-"):
                names.append(line.split(":", 1)[0].strip().strip("'\""))
    except FileNotFoundError:
        print(f"go2rtc config missing: {path}", file=sys.stderr)
    if not names:
        try:
            _, data = http_get(f"{GO2RTC}/api/streams", 10)
            names = sorted(json.loads(data))
        except Exception as e:
            print(f"stream discovery failed (yaml + /api/streams): {e}",
                  file=sys.stderr)
    skip = {s.strip() for s in
            os.environ.get("CAM_SNAPSHOT_SKIP", "").split(",") if s.strip()}
    return [n for n in names if n and n not in skip]


def capture_cams(streams):
    """Collapse go2rtc quality variants onto the base stream: ip_cam_65_hd /
    _low / _sd are the same camera as ip_cam_65 (cam-wall-pull convention).
    A variant whose base isn't configured stays its own camera.
    CAM_SNAPSHOT_ALL_STREAMS=1 disables the collapse."""
    if os.environ.get("CAM_SNAPSHOT_ALL_STREAMS"):
        return streams
    have = set(streams)
    return [s for s in streams
            if re.sub(r"_(hd|low|sd)$", "", s) == s
            or re.sub(r"_(hd|low|sd)$", "", s) not in have]


def fetch_frame(cam):
    """Try the stream, then its quality variants — an adaptive/auto stream
    can 200-with-empty-body while the dedicated variant is alive
    (cam-wall-pull does the same)."""
    for src in (cam, f"{cam}_hd", f"{cam}_low", f"{cam}_sd"):
        try:
            _, data = http_get(
                f"{GO2RTC}/api/frame.jpeg?src={urllib.parse.quote(src)}",
                FRAME_TIMEOUT)
            if len(data) >= MIN_FRAME_BYTES and data.startswith(b"\xff\xd8"):
                return src, data
        except Exception:
            continue
    raise ValueError(f"empty frame from {cam} (all variants)")


def stream_url(cam):
    return f"{STREAM_BASE}/stream.html?src={urllib.parse.quote(cam)}"


# --- WP records ---------------------------------------------------------------

def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def upload_media(name, blob):
    s, res = api("POST", "media", raw=blob, ctype="image/jpeg",
                 filename=name)
    if s in (200, 201) and res.get("id"):
        return res["id"], res.get("source_url", "")
    raise RuntimeError(f"media upload failed {s}: {str(res)[:200]}")


def find_cam_post(slug):
    s, res = api("GET", f"cam?slug={urllib.parse.quote(slug)}"
                        "&status=any&_fields=id,slug,featured_media")
    return res[0] if s == 200 and isinstance(res, list) and res else None


def create_snapshot(cam, ts, att_id, media_url):
    captured = ts.strftime("%Y-%m-%dT%H:%M:%S")
    body = {
        "title": f"Cam — {cam} {ts.strftime('%Y-%m-%d %H:%M')}",
        "slug": f"cam-{cam}-{ts.strftime('%Y%m%d-%H%M%S')}",
        "status": "private",
        "date": captured,  # post_date = capture time -> `before` purge is exact
        "featured_media": att_id,
        "meta": {"camera_id": cam, "captured_at": captured,
                 "kind": "live", "stream_url": stream_url(cam)},
    }
    if media_url:
        body["content"] = (
            f'<p><img src="{esc(media_url)}" style="max-width:100%" '
            f'loading="lazy"></p><p>{esc(cam)} — {captured}</p>')
    s, res = api("POST", "cam", body)
    if s not in (200, 201):
        raise RuntimeError(f"cam post failed {s}: {str(res)[:200]}")
    return res.get("id")


def upsert_directory(cam, ts, att_id, media_url):
    """One stable post per camera — the member-visible directory entry.
    featured_media/captured_at track the newest frame each run."""
    captured = ts.strftime("%Y-%m-%dT%H:%M:%S")
    body = {
        "title": f"Cam — {cam}",
        "slug": f"cam-{cam}",
        "status": "private",
        "featured_media": att_id,
        "meta": {"camera_id": cam, "captured_at": captured,
                 "kind": "live", "stream_url": stream_url(cam)},
        "content": (
            f'<p><img src="{esc(media_url)}" style="max-width:100%" '
            f'loading="lazy"></p>'
            f'<p>Live camera. Snapshots: posts slugged '
            f'<code>cam-{esc(cam)}-&lt;ts&gt;</code>. Last frame {captured}.</p>'
            if media_url else
            f'<p>Live camera. Last seen {captured}.</p>'),
    }
    existing = find_cam_post(f"cam-{cam}")
    if existing:
        s, res = api("POST", f"cam/{existing['id']}", body)
        return existing["id"], "updated" if s in (200, 201) else f"fail {s}"
    s, res = api("POST", "cam", body)
    if s not in (200, 201):
        raise RuntimeError(f"directory post failed {s}: {str(res)[:200]}")
    return res.get("id"), "created"


def purge_old(now):
    """Snapshot posts (slug cam-*-<yyyymmdd-HHMMSS>) past retention -> force
    delete post + featured attachment. Directory posts keep slug cam-<id>
    (no timestamp) and are never purged."""
    cutoff = (now - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    purged_posts = purged_media = 0
    page = 1
    while True:
        s, res = api(
            "GET", f"cam?status=any&before={cutoff}&per_page=100&page={page}"
                   "&_fields=id,slug,featured_media,date")
        if s != 200 or not isinstance(res, list) or not res:
            if s not in (200, 400):  # 400 = page past the end
                print(f"  purge list fail {s}: {str(res)[:160]}",
                      file=sys.stderr)
            break
        for p in res:
            if not SNAP_SLUG.match(p.get("slug") or ""):
                continue
            if DRY:
                print(f"  [dry] purge {p['slug']} (id {p['id']}, "
                      f"media {p.get('featured_media') or 0})")
                purged_posts += 1
                continue
            ds, dres = api("DELETE", f"cam/{p['id']}?force=true")
            if ds == 200:
                purged_posts += 1
            else:
                print(f"  purge post {p['id']} fail {ds}", file=sys.stderr)
                continue
            fm = p.get("featured_media") or 0
            if fm:
                ms, _ = api("DELETE", f"media/{fm}?force=true")
                if ms == 200:
                    purged_media += 1
                else:
                    print(f"  purge media {fm} fail {ms}", file=sys.stderr)
        if len(res) < 100:
            break
        page += 1
    return purged_posts, purged_media


# --- run ----------------------------------------------------------------------

def main(argv):
    seed_only = "--seed-only" in argv
    purge_only = "--purge-only" in argv
    cams = None
    for a in argv:
        if a.startswith("--cams="):
            cams = [c.strip() for c in a[7:].split(",") if c.strip()]

    if not BASE or not AUTH:
        print(f"WP creds missing — need WP_SITE_URL/WP_APP_USER/"
              f"WP_APP_PASSWORD in {WP_ENV}", file=sys.stderr)
        return 2

    if purge_only:
        cams = []
    elif cams is None:
        cams = capture_cams(go2rtc_streams())
    if not cams and not purge_only:
        print("no cams discovered (go2rtc.yaml streams: empty)",
              file=sys.stderr)
        return 2

    now = datetime.now()
    ok = fails = 0
    if not purge_only:
        for cam in cams:
            try:
                src, frame = fetch_frame(cam)
                tsf = now.strftime("%Y%m%d-%H%M%S")
                if DRY:
                    print(f"[dry] {cam}: frame {len(frame)}B — would upload "
                          f"cam-{cam}-{tsf}.jpg + post + directory upsert")
                    ok += 1
                    continue
                att_id, media_url = upload_media(f"cam-{cam}-{tsf}.jpg", frame)
                try:
                    snap_id = None if seed_only else create_snapshot(
                        cam, now, att_id, media_url)
                except Exception:
                    api("DELETE", f"media/{att_id}?force=true")  # no orphans
                    raise
                dir_id, dir_st = upsert_directory(cam, now, att_id, media_url)
                print(f"{cam}: snap={snap_id} dir={dir_id}({dir_st}) "
                      f"frame={len(frame)}B src={src}")
                ok += 1
            except Exception as e:
                fails += 1
                print(f"{cam}: FAIL {e}", file=sys.stderr)

    purged = (0, 0) if seed_only else purge_old(now)
    print(f"done: {ok} ok, {fails} fail, "
          f"purged {purged[0]} posts + {purged[1]} media "
          f"(>{RETENTION_DAYS}d)")
    return 2 if ok == 0 and fails > 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
