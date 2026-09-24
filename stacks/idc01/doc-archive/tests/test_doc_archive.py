"""Unit tests for doc-archive — Drive REST and MDDB are mocked, nothing
leaves the process. Run: pytest tests/ (see README)."""
import base64
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("DOC_ARCHIVE_API_KEY", "test-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import doc_archive
import drive_client


# ----------------------------
# Fakes
# ----------------------------
class FakeDrive:
    """In-memory Drive: folders/files keyed by id, records uploads."""

    def __init__(self):
        self.folders = {}   # id -> {name, parent}
        self.files = {}     # id -> {name, parent, blob, mime}
        self.uploads = []   # (name, parent, len(blob))
        self._seq = 0
        self.about_calls = 0

    def _nid(self, prefix):
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def about(self):
        self.about_calls += 1
        return {"user": {"kind": "drive#user"}}

    def find(self, name, parent=None, mime=drive_client.FOLDER_MIME):
        for fid, f in self.folders.items():
            if f["name"] == name and f["parent"] == parent:
                return fid
        if mime is None:  # file lookup (e.g. manifest.json)
            for fid, f in self.files.items():
                if f["name"] == name and f["parent"] == parent:
                    return fid
        return None

    def mkdir(self, name, parent=None):
        fid = self._nid("folder")
        self.folders[fid] = {"name": name, "parent": parent}
        return fid

    def upload(self, name, blob, parent, mime="application/octet-stream"):
        fid = self._nid("file")
        self.files[fid] = {"name": name, "parent": parent, "blob": blob,
                           "mime": mime}
        self.uploads.append((name, parent, len(blob)))
        return fid

    def download(self, file_id):
        return self.files[file_id]["blob"]


class FakeMddb:
    """In-memory MDDB 'documents' collection."""

    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.adds = []

    def list_docs(self, collection):
        return [d for d in self.docs]

    def find_key(self, collection, key):
        for d in self.docs:
            if d.get("key") == key:
                return d
        return None

    def add(self, collection, key, content_md, meta):
        self.adds.append({"collection": collection, "key": key,
                          "content_md": content_md, "meta": meta})
        self.docs.append({"key": key, "lang": "en", "meta": meta,
                          "contentMd": content_md})


# ----------------------------
# Helpers / fixtures
# ----------------------------
def png_bytes(size=(64, 48), color=(200, 200, 200), quality=95):
    im = Image.new("RGB", size, color)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def b64(blob):
    return base64.b64encode(blob).decode()


@pytest.fixture()
def env(monkeypatch):
    drive, mddb = FakeDrive(), FakeMddb()
    app = doc_archive.app
    app.dependency_overrides[doc_archive.get_drive] = lambda: drive
    app.dependency_overrides[doc_archive.get_mddb] = lambda: mddb
    with TestClient(app) as client:
        yield client, drive, mddb
    app.dependency_overrides.clear()


AUTH = {"X-API-Key": "test-key"}


# ----------------------------
# Tests
# ----------------------------
def test_happy_path(env):
    client, drive, mddb = env
    p1, p2 = png_bytes(color=(220, 30, 30)), png_bytes(color=(30, 30, 220))
    r = client.post("/v1/archive", headers=AUTH, json={
        "slug": "a-68-sale", "doc_type": "condo-sale",
        "files": [{"name": "p1.jpg", "data_b64": b64(p1)},
                  {"name": "p2.jpg", "data_b64": b64(p2)}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["archive_id"] == "a-68-sale"
    assert body["dedup"] == "none"
    assert len(body["page_ids"]) == 2
    assert body["folder_id"] in drive.folders

    # 2 pages + manifest.json uploaded under ada-documents/<YYYY>/<slug>/
    assert any(f["name"] == "ada-documents" for f in drive.folders.values())
    assert drive.folders[body["folder_id"]]["name"] == "a-68-sale"
    uploaded = sorted(n for n, _, _ in drive.uploads)
    assert uploaded == ["manifest.json", "p1.jpg", "p2.jpg"]

    # MDDB doc: metadata only, hashes + drive ids present
    assert len(mddb.adds) == 1
    add = mddb.adds[0]
    assert add["collection"] == "documents" and add["key"] == "a-68-sale"
    meta = add["meta"]
    assert meta["page_sha256"] == [hashlib.sha256(p1).hexdigest(),
                                   hashlib.sha256(p2).hexdigest()]
    assert meta["folder_id"] == [body["folder_id"]]
    assert meta["status"] == ["active"]
    assert len(meta["page_dhash"]) == 2
    # metadata only — raw page bytes must not appear in the MDDB payload
    assert b64(p1) not in add["content_md"]

    # GET /v1/archive/{slug} returns manifest + mddb doc
    r = client.get("/v1/archive/a-68-sale", headers=AUTH)
    assert r.status_code == 200
    got = r.json()
    assert got["manifest"]["slug"] == "a-68-sale"
    assert len(got["manifest"]["pages"]) == 2
    assert got["mddb"]["key"] == "a-68-sale"

    # GET page streams the bytes back
    r = client.get("/v1/archive/a-68-sale/page/2", headers=AUTH)
    assert r.status_code == 200
    assert r.content == p2
    assert r.headers["x-page-sha256"] == hashlib.sha256(p2).hexdigest()


def test_exact_dup_short_circuits(env):
    client, drive, mddb = env
    p1 = png_bytes()
    sha = hashlib.sha256(p1).hexdigest()
    mddb.docs.append({"key": "a-68-sale", "lang": "en", "meta": {
        "page_sha256": [sha], "folder_id": ["folder-99"],
        "page_ids": ["file-9"], "doc_type": ["condo-sale"]}})

    r = client.post("/v1/archive", headers=AUTH, json={
        "slug": "a-68-sale-v2",
        "files": [{"name": "p1.jpg", "data_b64": b64(p1)}]})
    assert r.status_code == 200
    body = r.json()
    assert body["dedup"] == "exact"
    assert body["archive_id"] == "a-68-sale"      # existing archive returned
    assert body["folder_id"] == "folder-99"
    assert drive.uploads == []                    # nothing re-uploaded
    assert mddb.adds == []                        # no new metadata doc


def test_near_dup_still_archives_with_candidates(env):
    client, drive, mddb = env
    # Same image, different bytes -> same dhash, different sha256.
    original = png_bytes(color=(10, 180, 90), quality=95)
    recapture = png_bytes(color=(10, 180, 90), quality=40)
    assert hashlib.sha256(original).digest() != hashlib.sha256(recapture).digest()
    mddb.docs.append({"key": "old-scan", "lang": "en", "meta": {
        "page_sha256": [hashlib.sha256(original).hexdigest()],
        "page_dhash": [doc_archive.dhash(original)],
        "doc_type": ["id-card"], "folder_id": ["folder-1"]}})

    r = client.post("/v1/archive", headers=AUTH, json={
        "slug": "new-scan",
        "files": [{"name": "p1.jpg", "data_b64": b64(recapture)}]})
    assert r.status_code == 200
    body = r.json()
    assert body["dedup"] == "near"
    assert body["archive_id"] == "new-scan"
    assert len(body["dedup_candidates"]) == 1
    assert body["dedup_candidates"][0]["archive_id"] == "old-scan"
    assert body["dedup_candidates"][0]["distance"] <= 6
    assert len(drive.uploads) == 2  # page + manifest still uploaded


def test_auth_failure(env):
    client, drive, mddb = env
    payload = {"slug": "x", "files": [{"name": "p.jpg", "data_b64": b64(png_bytes())}]}
    assert client.post("/v1/archive", json=payload).status_code == 401
    assert client.post("/v1/archive", headers={"X-API-Key": "wrong"},
                       json=payload).status_code == 401
    assert client.get("/v1/archive/x").status_code == 401
    assert drive.uploads == [] and mddb.adds == []
    # /health stays open for monitors
    assert client.get("/health").status_code == 200


def test_bad_base64_rejected(env):
    client, drive, mddb = env
    r = client.post("/v1/archive", headers=AUTH, json={
        "slug": "x", "files": [{"name": "p.jpg", "data_b64": "!!!"}]})
    assert r.status_code == 400
    assert drive.uploads == []


def test_drive_req_retries_on_500(monkeypatch):
    calls = {"n": 0}

    class FakeResp:
        headers = {"Content-Type": "application/json"}

        def read(self):
            return b'{"ok": true}'

    def flaky_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)
        return FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", flaky_urlopen)
    d = drive_client.Drive(lambda: "tok", sleep=lambda s: None)
    body, _ = d.req("GET", "https://example.test/x")
    assert json.loads(body)["ok"] is True
    assert calls["n"] == 2  # one 500, one success

    # Persistent 500 exhausts retries and raises.
    calls["n"] = 0

    def always_500(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", always_500)
    d = drive_client.Drive(lambda: "tok", retries=3, sleep=lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        d.req("GET", "https://example.test/x")
    assert calls["n"] == 3


def test_health(env):
    client, drive, _ = env
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "drive": "reachable"}
    assert drive.about_calls == 1
