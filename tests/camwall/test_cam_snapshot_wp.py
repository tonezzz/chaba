"""Unit tests for scripts/cam-wall/cam-snapshot-wp.py — the go2rtc -> WP
cam CPT snapshot writer (card cam-snapshot-writer-wp).

Loads the dash-named script via importlib against a fully fake transport:
go2rtc (frame.jpeg + streams API) and WP REST (/wp/v2/cam + /wp/v2/media)
both ride mocked urllib.request.urlopen — no network, no writes leave the
test process.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/cam-wall/cam-snapshot-wp.py"

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 5000  # > MIN_FRAME_BYTES, jpeg magic
DAY = 86400


class Resp:
    def __init__(self, payload, status=200, raw=None):
        self._b = raw if raw is not None else json.dumps(payload).encode()
        self.status = status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeWP:
    """Minimal /wp/v2 cam + media store."""

    def __init__(self):
        self.posts = {}   # id -> record
        self.media = {}   # id -> {filename, bytes}
        self.next_id = 1000

    def seed_snapshot(self, cam, age_days):
        """A snapshot post + attachment already aged past `age_days`."""
        ts = _dt.datetime.now() - _dt.timedelta(days=age_days)
        mid = self.next_id
        self.next_id += 1
        self.media[mid] = {"filename": f"cam-{cam}-old.jpg",
                           "bytes": JPEG}
        pid = self.next_id
        self.next_id += 1
        rec = {"id": pid, "slug": f"cam-{cam}-{ts.strftime('%Y%m%d-%H%M%S')}",
               "status": "private", "date": ts.strftime("%Y-%m-%dT%H:%M:%S"),
               "featured_media": mid, "meta": {"camera_id": cam,
                                             "kind": "live"},
               "title": {"rendered": f"Cam — {cam} old"}}
        self.posts[pid] = rec
        return pid, mid

    # -- rest routing -------------------------------------------------------
    def handle(self, req):
        url = req.full_url
        method = req.get_method()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        route = qs["rest_route"][0].lstrip("/")  # wp/v2/<...>
        parts = route.split("/")
        assert parts[:2] == ["wp", "v2"], url
        coll = parts[2]
        item = int(parts[3]) if len(parts) > 3 else None
        body = json.loads(req.data) if req.data and \
            req.headers.get("Content-type") == "application/json" else None

        if coll == "media" and method == "POST":
            fn = re.search(r'filename="([^"]+)"',
                           req.headers.get("Content-disposition", ""))
            mid = self.next_id
            self.next_id += 1
            self.media[mid] = {"filename": fn.group(1) if fn else "x.jpg",
                               "bytes": req.data}
            return Resp({"id": mid,
                         "source_url": f"https://wp/media/{mid}.jpg"}, 201)
        if coll == "media" and method == "DELETE":
            if qs.get("force", [""])[0] != "true":
                return Resp({"code": "rest_trash_not_supported"}, 501)
            self.media.pop(item, None)
            return Resp({"deleted": True})
        if coll == "cam" and method == "GET" and item is None:
            out = [p for p in self.posts.values()
                   if (not qs.get("slug") or p["slug"] == qs["slug"][0])
                   and (not qs.get("before") or p["date"] < qs["before"][0])]
            return Resp(out)
        if coll == "cam" and method == "POST" and item is None:
            pid = self.next_id
            self.next_id += 1
            rec = dict(body)
            rec["id"] = pid
            rec["date"] = body.get("date",
                                   _dt.datetime.now().strftime(
                                       "%Y-%m-%dT%H:%M:%S"))
            self.posts[pid] = rec
            return Resp(dict(rec), 201)
        if coll == "cam" and method == "POST" and item is not None:
            self.posts[item].update(body)
            return Resp(dict(self.posts[item]))
        if coll == "cam" and method == "DELETE":
            if qs.get("force", [""])[0] != "true":
                return Resp({"code": "rest_trash_not_supported"}, 501)
            self.posts.pop(item, None)
            return Resp({"deleted": True})
        raise AssertionError(f"unexpected {method} {url}")


class FakeNet:
    """Route urlopen to the fake go2rtc or fake WP by host."""

    def __init__(self):
        self.wp = FakeWP()
        # cam-a base stream dead -> falls back to cam-a_hd; dead-cam is a
        # dead stream; every *_low/_sd variant 404s in the fake.
        self.frames = {"cam-a": b"ok", "cam-a_hd": JPEG,
                       "cam-b": JPEG, "dead-cam": b"ok"}

    def handle(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if url.startswith("http://fake-go2rtc"):
            p = urllib.parse.urlparse(url)
            q = urllib.parse.parse_qs(p.query)
            if p.path == "/api/streams":
                return Resp({k: {} for k in self.frames})
            if p.path == "/api/frame.jpeg":
                src = q["src"][0]
                if src not in self.frames:
                    raise urllib.error.HTTPError(url, 404, "nf", {}, None)
                return Resp({}, raw=self.frames[src])
            raise AssertionError(f"go2rtc {url}")
        return self.wp.handle(req)


GO2RTC_YAML = """\
api:
  listen: 127.0.0.1:1984

streams:
  # house cams
  cam-a: rtsp://admin:x@192.168.2.71:10554/udp/av0_0
  cam-a_hd: ffmpeg:cam-a#video=h264
  cam-b:
    - rtsp://10.0.0.2/one
    - ffmpeg:cam-b#video=h264
  dead-cam: exec:/home/tony/.config/go2rtc/dead.sh

webrtc:
  listen: 127.0.0.1:8555
"""


class CamSnapWpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = Path(self.tmp.name) / "go2rtc.yaml"
        cfg.write_text(GO2RTC_YAML)
        env = Path(self.tmp.name) / "wp-boards.env"
        env.write_text("WP_SITE_URL=https://fake-wp\n"
                       "WP_APP_USER=agent\nWP_APP_PASSWORD=pw\n")
        for k, v in {"GO2RTC_URL": "http://fake-go2rtc",
                     "GO2RTC_CONFIG": str(cfg),
                     "WP_BOARDS_ENV": str(env),
                     "CAM_SNAPSHOT_SKIP": ""}.items():
            os.environ[k] = v
        spec = importlib.util.spec_from_file_location("cam_snapshot_wp", SCRIPT)
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["cam_snapshot_wp"] = self.mod
        spec.loader.exec_module(self.mod)
        self.net = FakeNet()
        self._patch = mock.patch.object(
            urllib.request, "urlopen", side_effect=self.net.handle)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()
        sys.modules.pop("cam_snapshot_wp", None)

    def test_streams_parsing(self):
        self.assertEqual(self.mod.go2rtc_streams(),
                         ["cam-a", "cam-a_hd", "cam-b", "dead-cam"])
        # _hd collapses onto cam-a (same physical camera)
        self.assertEqual(
            self.mod.capture_cams(self.mod.go2rtc_streams()),
            ["cam-a", "cam-b", "dead-cam"])

    def test_streams_api_fallback(self):
        self.mod.GO2RTC_CFG = str(Path(self.tmp.name) / "missing.yaml")
        self.assertEqual(sorted(self.mod.go2rtc_streams()),
                         ["cam-a", "cam-a_hd", "cam-b", "dead-cam"])

    def test_full_run(self):
        rc = self.mod.main([])
        self.assertEqual(rc, 0)  # dead-cam fails, run still succeeds
        wp = self.net.wp
        snaps = [p for p in wp.posts.values()
                 if self.mod.SNAP_SLUG.match(p["slug"])]
        dirs = [p for p in wp.posts.values() if p["slug"].startswith("cam-")
                and not self.mod.SNAP_SLUG.match(p["slug"])]
        self.assertEqual(len(snaps), 2)
        self.assertEqual(len(dirs), 2)
        for p in snaps + dirs:
            self.assertEqual(p["status"], "private")
            self.assertEqual(p["meta"]["kind"], "live")
            self.assertTrue(p["meta"]["camera_id"])
            self.assertIn("stream.html?src=", p["meta"]["stream_url"])
            self.assertTrue(p["featured_media"] in wp.media)
        self.assertTrue(all(p["meta"]["captured_at"] for p in snaps))

    def test_retention(self):
        wp = self.net.wp
        old_pid, old_mid = wp.seed_snapshot("cam-a", age_days=8)
        fresh_pid, fresh_mid = wp.seed_snapshot("cam-a", age_days=1)
        rc = self.mod.main([])
        self.assertEqual(rc, 0)
        self.assertNotIn(old_pid, wp.posts)      # >7d snapshot purged
        self.assertNotIn(old_mid, wp.media)    # its attachment too
        self.assertIn(fresh_pid, wp.posts)     # <7d kept
        self.assertIn(fresh_mid, wp.media)
        self.assertTrue(any(p["slug"] == "cam-cam-a"
                            for p in wp.posts.values()))  # directory kept

    def test_dry_run_writes_nothing(self):
        self.mod.DRY = True
        rc = self.mod.main(["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.net.wp.posts, {})
        self.assertEqual(self.net.wp.media, {})

    def test_seed_only(self):
        rc = self.mod.main(["--seed-only", "--cams=cam-a"])
        self.assertEqual(rc, 0)
        self.assertEqual([p["slug"] for p in self.net.wp.posts.values()],
                         ["cam-cam-a"])


if __name__ == "__main__":
    unittest.main()
