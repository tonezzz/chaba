"""doc-archive — document archiving API on idc01.

POST /v1/archive: base64 page images -> sha256 + dhash -> dedup check against
the MDDB `documents` collection -> resumable upload to
gdrive:ada-documents/<YYYY>/<slug>/ + manifest.json -> one metadata doc in
MDDB (metadata only — page bytes never go to MDDB).

Design: docs/kb/document-archive-service.md (RAM-only, direct Drive REST,
dedup tiers). Auth: X-API-Key, same pattern as notebooklm-rest. Bind is
tailnet/loopback only (DOC_ARCHIVE_BIND, default idc01 tailnet IP).
"""
import base64
import binascii
import datetime
import hashlib
import io
import json
import mimetypes
import os
import re
import socket
import urllib.error
import urllib.request
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from drive_client import Drive, token_provider_from_rclone

# ----------------------------
# Config / Security
# ----------------------------
_API_KEYS = {k.strip() for k in
             os.environ.get("DOC_ARCHIVE_API_KEYS",
                            os.environ.get("DOC_ARCHIVE_API_KEY", "")).split(",")
             if k.strip()}

RCLONE_CONF = os.environ.get("RCLONE_CONF",
                             os.path.expanduser("~/.config/rclone/rclone.conf"))
MDDB_BASE = os.environ.get("MDDB_BASE", "http://100.74.146.0:11023").rstrip("/")
MDDB_COLLECTION = os.environ.get("MDDB_COLLECTION", "documents")
DRIVE_ROOT = os.environ.get("DRIVE_ROOT", "ada-documents")
DHASH_MAX_HAMMING = int(os.environ.get("DHASH_MAX_HAMMING", "6"))
MAX_FILES = int(os.environ.get("DOC_ARCHIVE_MAX_FILES", "50"))

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def require_api_key(request: Request,
                    x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    # GET /health* is unauthenticated so monitors can probe liveness; it
    # exposes only ok/drive status, no data.
    if request.method == "GET" and request.url.path.startswith("/health"):
        return
    if _API_KEYS and x_api_key not in _API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ----------------------------
# Hashing (in-RAM, PIL only)
# ----------------------------
def sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def dhash(blob: bytes):
    """64-bit difference hash -> 16 hex chars, or None if not decodable."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(blob)).convert("L").resize((9, 8), Image.LANCZOS)
        px = im.tobytes()  # mode "L": one byte per pixel, row-major
        bits = "".join("1" if px[r * 9 + c] > px[r * 9 + c + 1] else "0"
                       for r in range(8) for c in range(8))
        return f"{int(bits, 2):016x}"
    except Exception:
        return None


def image_dims(blob: bytes):
    try:
        from PIL import Image
        return list(Image.open(io.BytesIO(blob)).size)
    except Exception:
        return None


def hamming(a: str, b: str) -> int:
    """Hamming distance between two hex dhash strings."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


# ----------------------------
# MDDB client (stdlib — no requests dep)
# ----------------------------
class Mddb:
    def __init__(self, base=MDDB_BASE, timeout=30):
        self.base = base
        self.timeout = timeout

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"{self.base}{path}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        return json.loads(urllib.request.urlopen(req, timeout=self.timeout).read())

    def search(self, collection, query="", limit=100, offset=0):
        return self._post("/v1/search", {"collection": collection, "query": query,
                                         "limit": limit, "offset": offset})

    def list_docs(self, collection):
        """Page through /v1/search to list every doc {key, lang, meta, ...}."""
        docs, skip = [], 0
        while True:
            page = self.search(collection, query="", limit=100, offset=skip)
            if not page:
                break
            docs.extend(page)
            if len(page) < 100:
                break
            skip += 100
        return docs

    def find_key(self, collection, key):
        for d in self.list_docs(collection):
            if d.get("key") == key:
                return d
        return None

    def add(self, collection, key, content_md, meta):
        return self._post("/v1/add", {"collection": collection, "key": key,
                                      "lang": "en", "contentMd": content_md,
                                      "meta": meta})


def _meta_list(doc, name):
    """meta values are lists of strings; return [] when absent."""
    v = (doc.get("meta") or {}).get(name)
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)] if v else []


def _meta_first(doc, name):
    vals = _meta_list(doc, name)
    return vals[0] if vals else ""


# ----------------------------
# Dedup index over the MDDB `documents` collection
# ----------------------------
def build_dedup_index(docs):
    """sha256 -> doc, plus [(doc, page_idx, dhash)] for near-dup scans."""
    by_sha, dhashes = {}, []
    for d in docs:
        key = d.get("key", "")
        for h in _meta_list(d, "page_sha256"):
            by_sha.setdefault(h, d)
        for i, h in enumerate(_meta_list(d, "page_dhash")):
            dhashes.append((d, i, h))
    return by_sha, dhashes


def find_near_dups(page_hashes, dhash_index, max_hamming=DHASH_MAX_HAMMING):
    """page_hashes: [dhash|None]. Returns [{archive_id, slug, their_page,
    our_page, distance}] for dhash hits <= max_hamming."""
    candidates = []
    for our_i, dh in enumerate(page_hashes):
        if not dh:
            continue
        for doc, their_i, other in dhash_index:
            dist = hamming(dh, other)
            if dist <= max_hamming:
                candidates.append({
                    "archive_id": doc.get("key", ""),
                    "doc_type": _meta_first(doc, "doc_type"),
                    "their_page": their_i + 1,
                    "our_page": our_i + 1,
                    "distance": dist,
                })
    return candidates


# ----------------------------
# Request models
# ----------------------------
class ArchiveFile(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    data_b64: str


class ArchiveRequest(BaseModel):
    slug: str
    doc_type: str = "document-set"
    files: list[ArchiveFile] = Field(min_length=1)


# ----------------------------
# App + providers (dependency-overridable in tests)
# ----------------------------
app = FastAPI(title="doc-archive", dependencies=[Depends(require_api_key)])

_drive = None
_mddb = None


def get_drive():
    global _drive
    if _drive is None:
        _drive = Drive(token_provider_from_rclone(RCLONE_CONF))
    return _drive


def get_mddb():
    global _mddb
    if _mddb is None:
        _mddb = Mddb(MDDB_BASE)
    return _mddb


def _guess_mime(name):
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _page_doc(p, n):
    return {"n": n, "name": p["name"], "sha256": p["sha256"],
            "dhash": p["dhash"], "bytes": p["bytes"], "dims": p["dims"]}


# ----------------------------
# Endpoints
# ----------------------------
@app.get("/health")
def health(drive: Drive = Depends(get_drive)):
    try:
        drive.about()
        return {"ok": True, "drive": "reachable"}
    except Exception:
        return {"ok": True, "drive": "unreachable"}


@app.post("/v1/archive")
def archive(req: ArchiveRequest,
            drive: Drive = Depends(get_drive),
            mddb: Mddb = Depends(get_mddb)):
    if not _SLUG_RE.match(req.slug):
        raise HTTPException(400, "slug must be [A-Za-z0-9._-], <=128 chars")
    if len(req.files) > MAX_FILES:
        raise HTTPException(400, f"too many files (max {MAX_FILES})")

    # 1. Decode + hash every page in RAM.
    pages = []
    seen_names = set()
    for f in req.files:
        if f.name in seen_names:
            raise HTTPException(400, f"duplicate file name: {f.name}")
        seen_names.add(f.name)
        try:
            blob = base64.b64decode(f.data_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, f"bad base64 in file: {f.name}")
        if not blob:
            raise HTTPException(400, f"empty file: {f.name}")
        pages.append({"name": f.name, "blob": blob, "bytes": len(blob),
                      "sha256": sha256_hex(blob), "dhash": dhash(blob),
                      "dims": image_dims(blob)})

    # 2. Dedup check against the MDDB documents collection.
    docs = mddb.list_docs(MDDB_COLLECTION)
    by_sha, dhash_index = build_dedup_index(docs)
    for p in pages:
        hit = by_sha.get(p["sha256"])
        if hit:
            return {"archive_id": hit.get("key"),
                    "folder_id": _meta_first(hit, "folder_id"),
                    "page_ids": _meta_list(hit, "page_ids"),
                    "dedup": "exact",
                    "dedup_candidates": [],
                    "note": "page sha256 already archived — no re-upload"}
    candidates = find_near_dups([p["dhash"] for p in pages], dhash_index)

    # 3. Upload pages + manifest.json to ada-documents/<YYYY>/<slug>/.
    year = str(datetime.date.today().year)
    root = drive.find(DRIVE_ROOT) or drive.mkdir(DRIVE_ROOT)
    year_id = drive.find(year, root) or drive.mkdir(year, root)
    if drive.find(req.slug, year_id):
        raise HTTPException(409, f"folder '{req.slug}' already exists in "
                            f"{DRIVE_ROOT}/{year} — pick a new slug")
    folder = drive.mkdir(req.slug, year_id)

    page_ids = []
    manifest_pages = []
    for p in pages:
        fid = drive.upload(p["name"], p["blob"], folder, _guess_mime(p["name"]))
        page_ids.append(fid)
        manifest_pages.append({**{k: p[k] for k in ("name", "sha256", "dhash",
                                                    "bytes", "dims")},
                               "drive_id": fid})
    manifest = {"slug": req.slug, "type": req.doc_type,
                "archived_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "archived_from": socket.gethostname(),
                "folder_id": folder, "pages": manifest_pages}
    manifest_id = drive.upload("manifest.json",
                               json.dumps(manifest, indent=1).encode(),
                               folder, "application/json")

    # 4. Metadata doc in MDDB — metadata only, never page bytes.
    content_md = "\n".join([
        f"# Archived document set: {req.slug}",
        f"- type: {req.doc_type}",
        f"- folder: {DRIVE_ROOT}/{year}/{req.slug} (drive id {folder})",
        f"- pages: {len(pages)}",
        f"- archived_at: {manifest['archived_at']}",
        f"- page sha256: {', '.join(p['sha256'] for p in pages)}",
    ])
    mddb.add(MDDB_COLLECTION, req.slug, content_md, {
        "slug": [req.slug],
        "doc_type": [req.doc_type],
        "status": ["active"],
        "source": ["doc-archive"],
        "folder_id": [folder],
        "manifest_id": [manifest_id],
        "drive_path": [f"{DRIVE_ROOT}/{year}/{req.slug}"],
        "page_sha256": [p["sha256"] for p in pages],
        "page_dhash": [p["dhash"] for p in pages if p["dhash"]],
        "page_ids": page_ids,
        "page_names": [p["name"] for p in pages],
        "archived_at": [manifest["archived_at"]],
    })

    return {"archive_id": req.slug, "folder_id": folder,
            "manifest_id": manifest_id, "page_ids": page_ids,
            "dedup": "near" if candidates else "none",
            "dedup_candidates": candidates}


def _manifest_for(slug, drive, mddb):
    """Resolve slug -> (mddb doc, manifest dict). 404s if either is missing."""
    doc = mddb.find_key(MDDB_COLLECTION, slug)
    if not doc:
        raise HTTPException(404, f"no MDDB doc for archive '{slug}'")
    folder_id = _meta_first(doc, "folder_id")
    manifest_id = _meta_first(doc, "manifest_id")
    if not manifest_id and folder_id:
        manifest_id = drive.find("manifest.json", folder_id, mime=None)
    if not manifest_id:
        raise HTTPException(404, f"no manifest.json for archive '{slug}'")
    try:
        manifest = json.loads(drive.download(manifest_id))
    except urllib.error.HTTPError as e:
        raise HTTPException(502, f"manifest download failed: HTTP {e.code}")
    return doc, manifest


@app.get("/v1/archive/{slug}")
def get_archive(slug: str,
                drive: Drive = Depends(get_drive),
                mddb: Mddb = Depends(get_mddb)):
    doc, manifest = _manifest_for(slug, drive, mddb)
    return {"archive_id": slug, "mddb": doc, "manifest": manifest}


@app.get("/v1/archive/{slug}/page/{n}")
def get_page(slug: str, n: int,
             drive: Drive = Depends(get_drive),
             mddb: Mddb = Depends(get_mddb)):
    _, manifest = _manifest_for(slug, drive, mddb)
    pages = manifest.get("pages", [])
    if not 1 <= n <= len(pages):
        raise HTTPException(404, f"page {n} out of range (1..{len(pages)})")
    page = pages[n - 1]
    try:
        blob = drive.download(page["drive_id"])
    except urllib.error.HTTPError as e:
        raise HTTPException(502, f"page download failed: HTTP {e.code}")
    return StreamingResponse(io.BytesIO(blob),
                             media_type=_guess_mime(page["name"]),
                             headers={"X-Page-Sha256": page.get("sha256", "")})
