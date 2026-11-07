"""Unit tests for scripts/lib/media_store.py — the hybrid media store.

Everything is offline: the local backend runs in a temp dir, the S3
backend runs against an in-process mock that just checks the SigV4
Authorization header is present and shaped right. The signer itself is
pinned to the AWS documentation vector.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

spec = importlib.util.spec_from_file_location(
    "media_store", REPO / "scripts" / "lib" / "media_store.py")
ms = importlib.util.module_from_spec(spec)
sys.modules["media_store"] = ms
spec.loader.exec_module(ms)

# hermetic config — no host env file, no inherited MEDIA_STORE_* vars
_TMP_ENV = tempfile.NamedTemporaryFile(
    "w", suffix=".env", delete=False, prefix="media-store-test-")
_TMP_ENV.write("")
_TMP_ENV.close()
for _k in list(os.environ):
    if _k.startswith(("MEDIA_STORE_", "AWS_", "R2_")):
        os.environ.pop(_k, None)
os.environ["MEDIA_STORE_ENV"] = _TMP_ENV.name


def local_store(**over):
    root = tempfile.mkdtemp(prefix="media-store-test-")
    return ms.MediaStore(backend="local", MEDIA_STORE_LOCAL_ROOT=root)


def cfg_store(env_text, **over):
    f = tempfile.NamedTemporaryFile(
        "w", suffix=".env", delete=False, prefix="media-store-cfg-")
    f.write(env_text)
    f.close()
    return ms.MediaStore(env_path=f.name, **over)


# --- key layout + canonical URLs ----------------------------------------------

class TestLayout(unittest.TestCase):
    def test_object_key_month_bucket(self):
        import datetime
        k = ms.object_key("cam", "gate.jpg",
                          datetime.datetime(2026, 3, 15))
        self.assertEqual(k, "media/cam/2026-03/gate.jpg")

    def test_sanitization(self):
        k = ms.object_key("LINE Media!", "My Photo (1).JPG")
        self.assertTrue(k.startswith("media/line-media/"))
        self.assertTrue(k.endswith("/my-photo-1.jpg"), k)

    def test_traversal_neutralized(self):
        k = ms.object_key("cam", "../../etc/passwd")
        self.assertNotIn("..", k.split("/")[-1])
        self.assertTrue(k.startswith("media/cam/"))


# --- local backend round trip ---------------------------------------------------

class TestLocalBackend(unittest.TestCase):
    def test_put_get_stat(self):
        st = local_store()
        rec = st.put("cam", b"JPEG-DATA", name="gate.jpg")
        self.assertEqual(rec["backend"], "local")
        self.assertTrue(rec["url"].startswith("media://media/cam/"))
        self.assertEqual(rec["sha256"],
                         hashlib.sha256(b"JPEG-DATA").hexdigest())
        self.assertEqual(st.get(rec["url"]), b"JPEG-DATA")
        meta = st.stat(rec["url"])
        self.assertEqual(meta["size"], 9)
        self.assertEqual(meta["sha256"], rec["sha256"])

    def test_put_from_path(self):
        st = local_store()
        f = tempfile.NamedTemporaryFile(
            suffix=".png", delete=False, prefix="ms-")
        f.write(b"PNG!")
        f.close()
        rec = st.put("render", f.name)
        self.assertTrue(rec["key"].endswith(f.name.split("/")[-1].lower()))

    def test_idempotent_skip(self):
        st = local_store()
        r1 = st.put("cam", b"AAA", name="a.bin")
        r2 = st.put("cam", b"AAA", name="a.bin")
        self.assertEqual(r1["key"], r2["key"])
        self.assertTrue(r2.get("skipped"))

    def test_unique_collision_gets_hash_suffix(self):
        st = local_store()
        r1 = st.put("cam", b"AAA", name="a.bin")
        r2 = st.put("cam", b"DIFFERENT", name="a.bin")
        self.assertNotEqual(r1["key"], r2["key"])
        sha8 = hashlib.sha256(b"DIFFERENT").hexdigest()[:8]
        self.assertIn(sha8, r2["key"])
        self.assertEqual(st.get(r1["url"]), b"AAA")  # original intact

    def test_overwrite_mode(self):
        st = local_store()
        st.put("backup", b"v1", name="latest.tar")
        r2 = st.put("backup", b"v2-bigger", name="latest.tar",
                    unique=False)
        self.assertEqual(st.get(r2["url"]), b"v2-bigger")

    def test_list_kind_month(self):
        st = local_store()
        import datetime
        st.put("cam", b"1", name="a.jpg",
               when=datetime.datetime(2026, 10, 1))
        st.put("cam", b"2", name="b.jpg",
               when=datetime.datetime(2026, 9, 1))
        st.put("line", b"3", name="c.jpg",
               when=datetime.datetime(2026, 10, 1))
        keys = [o["key"] for o in st.list(kind="cam", month="2026-10")]
        self.assertEqual(len(keys), 1)
        self.assertTrue(keys[0].endswith("a.jpg"))
        self.assertEqual(len(st.list(kind="cam")), 2)

    def test_delete(self):
        st = local_store()
        rec = st.put("wp", b"x", name="u.bin")
        self.assertTrue(st.delete(rec["url"]))
        self.assertIsNone(st.stat(rec["url"]))

    def test_media_url_resolves(self):
        st = local_store()
        rec = st.put("cam", b"B", name="z.jpg")
        key = rec["url"][len("media://"):]
        self.assertEqual(st.get(key), b"B")  # bare key also works

    def test_public_base(self):
        st = local_store()
        st2 = ms.MediaStore(
            backend="local",
            MEDIA_STORE_LOCAL_ROOT=st.backend.root,
            MEDIA_STORE_PUBLIC_BASE="https://media.example.com")
        rec = st2.put("cam", b"p", name="pub.jpg")
        self.assertEqual(
            rec["public_url"],
            f"https://media.example.com/{rec['key']}")
        self.assertTrue(rec["url"].startswith("media://"))


# --- config resolution -------------------------------------------------------------

class TestConfig(unittest.TestCase):
    def test_env_file_backend_and_root(self):
        st = cfg_store("MEDIA_STORE_BACKEND=local\n"
                       "MEDIA_STORE_LOCAL_ROOT=/tmp/ms-cfg-test\n")
        self.assertEqual(st.backend_name, "local")
        self.assertEqual(str(st.backend.root), "/tmp/ms-cfg-test")

    def test_env_var_wins_over_file(self):
        os.environ["MEDIA_STORE_BACKEND"] = "local"
        try:
            st = cfg_store("MEDIA_STORE_BACKEND=s3\n")
            self.assertEqual(st.backend_name, "local")
        finally:
            os.environ.pop("MEDIA_STORE_BACKEND")

    def test_r2_endpoint_from_account(self):
        st = cfg_store(
            "MEDIA_STORE_BACKEND=r2\n"
            "MEDIA_STORE_ACCOUNT_ID=abc123\n"
            "MEDIA_STORE_BUCKET=media\n"
            "MEDIA_STORE_ACCESS_KEY_ID=AK\n"
            "MEDIA_STORE_SECRET_ACCESS_KEY=SK\n")
        self.assertEqual(st.backend_name, "r2")
        self.assertEqual(st.backend.endpoint,
                         "https://abc123.r2.cloudflarestorage.com")
        self.assertEqual(st.backend.region, "auto")

    def test_missing_s3_config_raises(self):
        with self.assertRaises(ms.MediaStoreError):
            cfg_store("MEDIA_STORE_BACKEND=s3\n")

    def test_bad_backend_raises(self):
        with self.assertRaises(ms.MediaStoreError):
            cfg_store("MEDIA_STORE_BACKEND=ftp\n")


# --- SigV4 (AWS documentation vectors) ---------------------------------------------

class TestSigV4(unittest.TestCase):
    SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"

    def test_derived_signing_key(self):
        # AWS docs: https://docs.aws.amazon.com/.../sig-v4-examples
        k = ms._signing_key(self.SECRET, "20150830", "us-east-1", "iam")
        self.assertEqual(
            k.hex(),
            "c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3"
            "c154a4b9")

    def test_get_listusers_signature(self):
        # AWS docs worked example: GET iam.amazonaws.com
        # ?Action=ListUsers&Version=2010-05-08 at 20150830T123600Z
        auth, signed = ms._signature(
            "GET", "/",
            {"Action": "ListUsers", "Version": "2010-05-08"},
            {"content-type":
             "application/x-www-form-urlencoded; charset=utf-8",
             "host": "iam.amazonaws.com",
             "x-amz-date": "20150830T123600Z"},
            hashlib.sha256(b"").hexdigest(),
            "AKIDEXAMPLE", self.SECRET,
            "20150830T123600Z", "us-east-1", "iam")
        self.assertEqual(signed, "content-type;host;x-amz-date")
        self.assertIn(
            "Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400"
            "e06b5924a6f2b5d7", auth)
        self.assertIn(
            "Credential=AKIDEXAMPLE/20150830/us-east-1/iam/aws4_request",
            auth)


# --- S3 backend against an in-process mock -------------------------------------------

class _MockS3(BaseHTTPRequestHandler):
    """Path-style S3 shim: stores objects in a dict, serves
    ListObjectsV2 XML. Validates only that requests carry a SigV4
    Authorization header — crypto correctness is pinned by TestSigV4."""

    objects = {}

    def log_message(self, *_a):
        pass

    def _auth_ok(self):
        auth = self.headers.get("Authorization", "")
        return auth.startswith("AWS4-HMAC-SHA256 Credential=AK/")

    def _key(self):
        """Object key without the bucket segment; '' = bucket-only."""
        path = urllib.parse.unquote(
            self.path.split("?", 1)[0]).lstrip("/")
        return path.split("/", 1)[1] if "/" in path else ""

    def _deny(self):
        self.send_response(403)
        self.end_headers()

    def do_PUT(self):
        if not self._auth_ok():
            return self._deny()
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _MockS3.objects[self._key()] = body
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if not self._auth_ok():
            return self._deny()
        path = self._key()
        if path == "":
            q = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            prefix = q.get("prefix", [""])[0]
            items = "".join(
                f"<Contents><Key>{k}</Key><Size>{len(v)}</Size>"
                f"<LastModified>2026-10-28T00:00:00Z</LastModified>"
                f"</Contents>"
                for k, v in sorted(_MockS3.objects.items())
                if k.startswith(prefix))
            body = (b"<ListBucketResult xmlns="
                    b'"http://s3.amazonaws.com/doc/2006-03-01/">'
                    + items.encode()
                    + b"<IsTruncated>false</IsTruncated>"
                    b"</ListBucketResult>")
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.end_headers()
            self.wfile.write(body)
        elif path in _MockS3.objects:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(_MockS3.objects[path])
        else:
            self._deny()

    def do_HEAD(self):
        if not self._auth_ok():
            return self._deny()
        path = self._key()
        if path in _MockS3.objects:
            body = _MockS3.objects[path]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("x-amz-meta-sha256",
                             hashlib.sha256(body).hexdigest())
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        if not self._auth_ok():
            return self._deny()
        _MockS3.objects.pop(self._key(), None)
        self.send_response(204)
        self.end_headers()


class TestS3Backend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _MockS3.objects = {}
        cls.httpd = HTTPServer(("127.0.0.1", 0), _MockS3)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def store(self):
        return ms.MediaStore(
            backend="s3",
            MEDIA_STORE_ENDPOINT=f"http://127.0.0.1:{self.port}",
            MEDIA_STORE_BUCKET="bkt",
            MEDIA_STORE_ACCESS_KEY_ID="AK",
            MEDIA_STORE_SECRET_ACCESS_KEY="SK",
            MEDIA_STORE_REGION="us-east-1")

    def test_put_get_roundtrip(self):
        st = self.store()
        rec = st.put("line", b"LINE-BYTES", name="m123.jpg")
        self.assertEqual(rec["backend"], "s3")
        self.assertEqual(_MockS3.objects[rec["key"]], b"LINE-BYTES")
        self.assertEqual(st.get(rec["url"]), b"LINE-BYTES")

    def test_head_dedup_skip(self):
        st = self.store()
        r1 = st.put("cam", b"SAME", name="d.jpg")
        r2 = st.put("cam", b"SAME", name="d.jpg")
        self.assertTrue(r2.get("skipped"))

    def test_list_prefix(self):
        st = self.store()
        st.put("cam", b"1", name="l1.jpg")
        st.put("wp", b"2", name="l2.jpg")
        keys = [o["key"] for o in st.list(kind="cam")]
        self.assertTrue(any(k.endswith("l1.jpg") for k in keys))
        self.assertFalse(any(k.endswith("l2.jpg") for k in keys))

    def test_delete(self):
        st = self.store()
        rec = st.put("backup", b"r", name="rm.bin")
        self.assertTrue(st.delete(rec["url"]))
        self.assertIsNone(st.stat(rec["url"]))

    def test_doctor(self):
        ok, info = self.store().doctor()
        self.assertTrue(ok)
        self.assertIn("bkt", info["check"])


# --- CLI smoke ---------------------------------------------------------------------

class TestCli(unittest.TestCase):
    def test_put_ls_get_via_cli(self):
        root = tempfile.mkdtemp(prefix="ms-cli-")
        env = tempfile.NamedTemporaryFile(
            "w", suffix=".env", delete=False)
        env.write(f"MEDIA_STORE_BACKEND=local\n"
                  f"MEDIA_STORE_LOCAL_ROOT={root}\n")
        env.close()
        argv = ["--config", env.name]
        src = tempfile.NamedTemporaryFile(
            suffix=".jpg", delete=False, prefix="ms-cli-src-")
        src.write(b"CLI-BYTES")
        src.close()
        self.assertEqual(ms.main(
            argv + ["put", src.name, "--kind", "cam"]), 0)
        self.assertEqual(ms.main(argv + ["ls", "--kind", "cam"]), 0)
        self.assertEqual(ms.main(argv + ["doctor"]), 0)


if __name__ == "__main__":
    unittest.main()
