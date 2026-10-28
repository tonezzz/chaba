#!/usr/bin/env python3
"""Hybrid media store — one write path for archive bytes, backend is config.

Card media-hybrid-object-store (Tony 2026-10-15): hybrid, not migration.
Local hosts keep hot/working data; this helper is the durable archive +
link layer for renders, LINE media, cam captures, WP uploads, backups.
S3-upgrade-ready: backend=local|r2|s3 is a config flag, not code.

Design rules (the card spec):

  1. All writers go through this helper — never hand-roll PUTs.
  2. Records store the canonical `url` field, never a host path.
     `media://<key>` resolves on any host through the configured
     backend, so records survive a local->r2->s3 backend flip.
     `public_url` (when MEDIA_STORE_PUBLIC_BASE is set) is the
     human/edge link; the canonical url stays media://.
  3. Object layout: media/<kind>/<yyyy-mm>/<name> — kind is the media
     family (render, line, cam, wp, backup, ...), month buckets keep
     listings cheap and retention sweeps trivial.

Config — ~/.config/secrets/media-store.env (parsed, never sourced;
MEDIA_STORE_ENV overrides path; env vars win over file):

  MEDIA_STORE_BACKEND        local | r2 | s3        (default: local)
  MEDIA_STORE_LOCAL_ROOT     local backend root
                             (default: ~/.local/share/media-store)
  MEDIA_STORE_ENDPOINT       S3 endpoint, e.g.
                             https://<acct>.r2.cloudflarestorage.com
                             (r2: derived from account id when unset)
  MEDIA_STORE_ACCOUNT_ID     R2 account id (R2_ACCOUNT_ID /
                             CF_API_ACCOUNT_ID also honored)
  MEDIA_STORE_BUCKET         bucket name (required for r2/s3)
  MEDIA_STORE_ACCESS_KEY_ID  S3 access key (AWS_ACCESS_KEY_ID honored)
  MEDIA_STORE_SECRET_ACCESS_KEY  (AWS_SECRET_ACCESS_KEY honored)
  MEDIA_STORE_REGION         default: auto (r2) / us-east-1 (s3)
  MEDIA_STORE_PREFIX         key prefix (default: media)
  MEDIA_STORE_PUBLIC_BASE    base for public_url, e.g.
                             https://media.surf-thailand.com

Stdlib only — SigV4 implemented here; no boto3 dependency. PUT bodies
are held in memory (v1); fine for archive-scale objects (photos, docs,
clips) — chunked/multi-part upload is the v2 lever if renders go
multi-GB.

Import:  sys.path.insert(0, "<repo>/scripts"); from lib.media_store import MediaStore
CLI:     media_store.py put|get|stat|ls|rm|url|doctor  (see --help)
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import json
import mimetypes
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_ENV = os.path.expanduser("~/.config/secrets/media-store.env")
CF_ENV = os.path.expanduser("~/.config/secrets/cloudflare.env")
CANONICAL_SCHEME = "media://"
USER_AGENT = "chaba-media-store/1"
_META_SUFFIX = ".meta.json"


class MediaStoreError(RuntimeError):
    """Backend failure — carries the HTTP status when there is one."""

    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


# --- config ------------------------------------------------------------------

def _load_env_file(path):
    """Parse KEY=VALUE lines — never source (passwords carry shell chars)."""
    env = {}
    try:
        with open(os.path.expanduser(path)) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return env


def _cfg(env_file, *names, default=""):
    """First non-empty value: process env, then env file, then default."""
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    for n in names:
        v = env_file.get(n, "").strip()
        if v:
            return v
    return default


def _clean_part(s):
    """Slug-safe a key segment — [a-z0-9._-], collapse junk to -."""
    s = (s or "").strip().replace("\\", "/").split("/")[-1]
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = re.sub(r"-+\.", ".", s)
    return s.strip(".-_").lower()


def object_key(kind, name, when=None, prefix="media"):
    """media/<kind>/<yyyy-mm>/<name> — the layout from the card spec."""
    month = (when or datetime.datetime.now()).strftime("%Y-%m")
    return f"{prefix}/{_clean_part(kind)}/{month}/{_clean_part(name)}"


def canonical_url(key):
    return f"{CANONICAL_SCHEME}{key}"


def _split_url(value, prefix="media"):
    """media://key, s3://bucket/key, public_base URL, or bare key -> key.

    Returns (key, external_http_url). External http(s) URLs that don't
    match the store resolve as ("", url) — fetchable but not managed."""
    v = (value or "").strip()
    if v.startswith(CANONICAL_SCHEME):
        return v[len(CANONICAL_SCHEME):], ""
    if v.startswith("s3://"):
        rest = v[5:]
        return rest.split("/", 1)[1] if "/" in rest else "", ""
    if v.startswith("http://") or v.startswith("https://"):
        return "", v
    if v.startswith(f"{prefix}/"):
        return v, ""
    return "", v


# --- SigV4 -------------------------------------------------------------------

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _signing_key(secret, date, region, service="s3"):
    k = ("AWS4" + secret).encode()
    for part in (date, region, service, "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    return k


def _quote(s, safe="-_.~/"):
    return urllib.parse.quote(s, safe=safe)


def _canonical_query(params):
    pairs = []
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            pairs += [(k, x) for x in v]
        else:
            pairs.append((k, v))
    pairs.sort(key=lambda p: (_quote(p[0], ""), _quote(str(p[1]), "")))
    return "&".join(f"{_quote(k, '')}={_quote(str(v), '')}" for k, v in pairs)


def _signature(method, uri, params, headers, payload_hash,
               access_key, secret, amz_date, region, service="s3"):
    """Full SigV4 -> (authorization_header, signed_header_names).

    uri is the already-encoded canonical URI; params the raw query dict;
    headers must include host + every x-amz-* header to sign. Kept
    parameter-explicit so tests can drive the AWS doc vector directly."""
    hlist = sorted((k.lower(), " ".join(str(v).split()))
                   for k, v in headers.items())
    canon_headers = "".join(f"{k}:{v}\n" for k, v in hlist)
    signed_names = ";".join(k for k, _ in hlist)
    canon_req = "\n".join([
        method.upper(), uri, _canonical_query(params), canon_headers,
        signed_names, payload_hash])
    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    sts = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                     hashlib.sha256(canon_req.encode()).hexdigest()])
    sig = hmac.new(_signing_key(secret, amz_date[:8], region, service),
                   sts.encode(), hashlib.sha256).hexdigest()
    return (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_names}, Signature={sig}", signed_names)


# --- backends ------------------------------------------------------------------

class _LocalBackend:
    """Hot store on local disk — default backend, zero deps. Byte files
    live under <root>/<key>; a sibling <key>.meta.json carries the record
    fields so stat()/dedup match the S3 backend's behavior."""

    name = "local"

    def __init__(self, root):
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key):
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise MediaStoreError(f"key escapes local root: {key}")
        return p

    def _meta_path(self, key):
        return self._path(key).with_name(
            self._path(key).name + _META_SUFFIX)

    def head(self, key):
        p = self._path(key)
        if not p.is_file():
            return None
        meta = {}
        try:
            meta = json.loads(self._meta_path(key).read_text())
        except OSError:
            pass
        meta.setdefault("size", p.stat().st_size)
        meta.setdefault("sha256",
                        hashlib.sha256(p.read_bytes()).hexdigest())
        return meta

    def put(self, key, body, content_type, sha256):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".ms-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(body)
            os.replace(tmp, p)
        except BaseException:
            os.unlink(tmp)
            raise
        meta = {"size": len(body), "sha256": sha256,
                "content_type": content_type,
                "put_at": datetime.datetime.now().isoformat(
                    timespec="seconds")}
        self._meta_path(key).write_text(json.dumps(meta, indent=1))
        return meta

    def get(self, key):
        p = self._path(key)
        if not p.is_file():
            raise MediaStoreError(f"not found: {key}", status=404)
        return p.read_bytes()

    def delete(self, key):
        gone = False
        for f in (self._path(key), self._meta_path(key)):
            try:
                f.unlink()
                gone = True
            except OSError:
                pass
        return gone

    def list(self, prefix, limit=1000):
        base = self._path(prefix) if prefix else self.root
        start = base if base.is_dir() else self.root
        out = []
        for dirpath, _dirs, files in os.walk(start):
            for fn in files:
                if fn.endswith(_META_SUFFIX) or fn.startswith(".ms-"):
                    continue
                full = Path(dirpath) / fn
                key = str(full.relative_to(self.root))
                if prefix and not key.startswith(prefix):
                    continue
                out.append({"key": key, "size": full.stat().st_size,
                            "modified": datetime.datetime.fromtimestamp(
                                full.stat().st_mtime).isoformat(
                                    timespec="seconds")})
                if len(out) >= limit:
                    return sorted(out, key=lambda r: r["key"])
        return sorted(out, key=lambda r: r["key"])

    def check(self):
        probe = self._path(".probe")
        probe.write_text("ok")
        probe.unlink()
        return True, f"local root writable: {self.root}"


class _S3Backend:
    """S3-compatible object store over stdlib urllib + SigV4. Path-style
    URLs ({endpoint}/{bucket}/{key}) — works on R2, AWS, MinIO. R2 is
    this class with region=auto and the account-id endpoint."""

    name = "s3"

    def __init__(self, endpoint, bucket, access_key, secret, region):
        if not all([endpoint, bucket, access_key, secret]):
            raise MediaStoreError(
                "s3 backend needs endpoint, bucket, access key, secret")
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.access_key = access_key
        self.secret = secret
        self.region = region

    def _request(self, method, key=None, params=None, body=b"",
                 extra_headers=None, expect_meta=False):
        uri = f"/{self.bucket}" + (f"/{_quote(key)}" if key else "")
        params = dict(params or {})
        amz_date = datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        payload_hash = hashlib.sha256(body or b"").hexdigest()
        host = urllib.parse.urlparse(self.endpoint).netloc
        headers = {"host": host, "x-amz-date": amz_date,
                   "x-amz-content-sha256": payload_hash}
        headers.update(extra_headers or {})
        auth, _ = _signature(method, uri, params, headers, payload_hash,
                             self.access_key, self.secret, amz_date,
                             self.region)
        headers["Authorization"] = auth
        headers["User-Agent"] = USER_AGENT
        url = f"{self.endpoint}{uri}"
        qs = _canonical_query(params)
        if qs:
            url += f"?{qs}"
        req = urllib.request.Request(url, data=body if body else None,
                                     method=method)
        for k, v in headers.items():
            if k.lower() != "host":
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode(errors="replace")
            raise MediaStoreError(
                f"{method} {key or self.bucket} -> {e.code}: {detail}",
                status=e.code)

    def head(self, key):
        try:
            s, h, _ = self._request("HEAD", key)
        except MediaStoreError as e:
            if e.status in (404, 403):
                return None
            raise
        return {"size": int(h.get("Content-Length") or 0),
                "sha256": h.get("x-amz-meta-sha256") or "",
                "content_type": h.get("Content-Type") or "",
                "etag": (h.get("ETag") or "").strip('"')}

    def put(self, key, body, content_type, sha256):
        self._request("PUT", key, body=body, extra_headers={
            "Content-Type": content_type or "application/octet-stream",
            "Content-Length": str(len(body)),
            "x-amz-meta-sha256": sha256})
        return {"size": len(body), "sha256": sha256,
                "content_type": content_type}

    def get(self, key):
        s, _h, body = self._request("GET", key)
        return body

    def delete(self, key):
        try:
            self._request("DELETE", key)
            return True
        except MediaStoreError as e:
            if e.status == 404:
                return False
            raise

    def list(self, prefix, limit=1000):
        out, token = [], None
        while len(out) < limit:
            params = {"list-type": "2", "prefix": prefix,
                      "max-keys": str(min(1000, limit - len(out)))}
            if token:
                params["continuation-token"] = token
            _s, _h, body = self._request("GET", None, params=params)
            ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
            root = ET.fromstring(body)
            for c in root.findall("s:Contents", ns):
                out.append({
                    "key": c.findtext("s:Key", "", ns),
                    "size": int(c.findtext("s:Size", "0", ns)),
                    "modified": c.findtext("s:LastModified", "", ns)})
                if len(out) >= limit:
                    return out
            if root.findtext("s:IsTruncated", "false", ns) != "true":
                return out
            token = root.findtext("s:NextContinuationToken", "", ns)
            if not token:
                return out
        return out

    def check(self):
        _s, _h, _b = self._request(
            "GET", None, params={"list-type": "2", "max-keys": "1"})
        return True, f"bucket {self.bucket} reachable via {self.endpoint}"


# --- store front ---------------------------------------------------------------

class MediaStore:
    """One write path for archive media. Writers hold a MediaStore and
    never know which backend serves it.

      store = MediaStore()                       # config/env resolution
      rec = store.put("cam", path_or_bytes, name="gate.jpg")
      rec["url"]        -> media://media/cam/2026-10/gate.jpg  (store this)
      rec["public_url"] -> https://media.example.com/... or None
      store.get(rec["url"]) -> bytes
    """

    def __init__(self, backend=None, env_path=None, **over):
        file_env = _load_env_file(env_path or os.environ.get(
            "MEDIA_STORE_ENV", DEFAULT_ENV))
        cf_env = _load_env_file(CF_ENV)

        def c(*names, default=""):
            for n in names:
                v = over.get(n)
                if v:
                    return str(v)
            return _cfg(file_env, *names, default=default)

        self.prefix = c("MEDIA_STORE_PREFIX", default="media")
        self.public_base = c("MEDIA_STORE_PUBLIC_BASE").rstrip("/")
        self.backend_name = (backend or c(
            "MEDIA_STORE_BACKEND", default="local")).lower()

        if self.backend_name == "local":
            root = c("MEDIA_STORE_LOCAL_ROOT",
                     default=os.path.expanduser(
                         "~/.local/share/media-store"))
            self.backend = _LocalBackend(root)
        elif self.backend_name in ("r2", "s3"):
            endpoint = c("MEDIA_STORE_ENDPOINT")
            account = c("MEDIA_STORE_ACCOUNT_ID", "R2_ACCOUNT_ID") or \
                cf_env.get("CF_API_ACCOUNT_ID", "")
            if self.backend_name == "r2" and not endpoint and account:
                endpoint = f"https://{account}.r2.cloudflarestorage.com"
            self.backend = _S3Backend(
                endpoint=endpoint,
                bucket=c("MEDIA_STORE_BUCKET", "R2_BUCKET"),
                access_key=c("MEDIA_STORE_ACCESS_KEY_ID",
                             "AWS_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID"),
                secret=c("MEDIA_STORE_SECRET_ACCESS_KEY",
                         "AWS_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY"),
                region=c("MEDIA_STORE_REGION",
                         default="auto" if self.backend_name == "r2"
                         else "us-east-1"))
            self.backend.name = self.backend_name
        else:
            raise MediaStoreError(
                f"unknown MEDIA_STORE_BACKEND: {self.backend_name} "
                "(local|r2|s3)")

    # -- url helpers --

    def url_for(self, key):
        return canonical_url(key)

    def public_url(self, key):
        return f"{self.public_base}/{key}" if self.public_base else None

    def _key(self, url_or_key):
        key, external = _split_url(url_or_key, self.prefix)
        if external:
            raise MediaStoreError(
                f"external URL is fetch-only, not a store object: "
                f"{external[:80]}")
        if not key:
            raise MediaStoreError(f"not a store URL/key: {url_or_key}")
        return key

    # -- ops --

    def put(self, kind, source, name=None, when=None, unique=True,
            content_type=None, dry_run=False):
        """Archive bytes under media/<kind>/<yyyy-mm>/<name>.

        source: path (str/Path), bytes, or binary file object.
        unique=True (default): on a same-name/different-content
        collision the object gets -<sha8> inserted before the extension
        (archive never silently overwrites). unique=False: overwrite —
        for 'latest'-style records. Same sha256 + size = idempotent
        skip."""
        if isinstance(source, (str, Path)):
            body = Path(source).read_bytes()
            name = name or Path(source).name
        elif isinstance(source, (bytes, bytearray)):
            body = bytes(source)
        else:
            body = source.read()
        if not name or not _clean_part(name):
            raise MediaStoreError(
                f"put() needs a usable name (got {name!r})")
        sha = hashlib.sha256(body).hexdigest()
        ctype = content_type or \
            mimetypes.guess_type(name)[0] or "application/octet-stream"
        key = object_key(kind, name, when, self.prefix)

        prior = self.backend.head(key)
        if prior and prior.get("sha256") == sha:
            return self._record(key, body, sha, ctype, skipped=True)
        if prior and unique:
            stem, dot, ext = name.rpartition(".")
            alt = f"{stem}-{sha[:8]}{dot}{ext}" if dot else \
                f"{name}-{sha[:8]}"
            key = object_key(kind, alt, when, self.prefix)
            prior = self.backend.head(key)
            if prior and prior.get("sha256") == sha:
                return self._record(key, body, sha, ctype, skipped=True)

        if not dry_run:
            self.backend.put(key, body, ctype, sha)
        return self._record(key, body, sha, ctype)

    def _record(self, key, body, sha, ctype, skipped=False):
        rec = {"url": canonical_url(key), "key": key,
               "backend": self.backend_name, "size": len(body),
               "sha256": sha, "content_type": ctype}
        if skipped:
            rec["skipped"] = True
        pub = self.public_url(key)
        if pub:
            rec["public_url"] = pub
        return rec

    def get(self, url_or_key):
        """Fetch object bytes. media:// + bare keys go through the
        configured backend; foreign http(s) URLs pass to urllib."""
        key, external = _split_url(url_or_key, self.prefix)
        if external:
            req = urllib.request.Request(
                external, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        return self.backend.get(key)

    def stat(self, url_or_key):
        return self.backend.head(self._key(url_or_key))

    def list(self, kind=None, month=None, prefix=None, limit=1000):
        if prefix:
            p = prefix
        else:
            p = self.prefix
            if kind:
                p += f"/{_clean_part(kind)}"
                if month:
                    p += f"/{month}"
            p += "/"
        return self.backend.list(p, limit)

    def delete(self, url_or_key):
        return self.backend.delete(self._key(url_or_key))

    def doctor(self):
        """Config + reachability check — never prints secrets."""
        info = {"backend": self.backend_name, "prefix": self.prefix,
                "public_base": self.public_base or "(unset)"}
        ok, detail = self.backend.check()
        info["check"] = detail
        return ok, info


# --- CLI -----------------------------------------------------------------------

def _print_rec(rec, as_json):
    if as_json:
        print(json.dumps(rec, indent=1))
        return
    skip = " (unchanged, skipped)" if rec.get("skipped") else ""
    print(f"{rec['url']}{skip}")
    print(f"  size={rec['size']} sha256={rec['sha256'][:16]} "
          f"type={rec['content_type']} backend={rec['backend']}")
    if rec.get("public_url"):
        print(f"  public={rec['public_url']}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="media_store.py",
        description="Hybrid media store — local|r2|s3 behind one helper.")
    ap.add_argument("--config", help="env file (default "
                    "~/.config/secrets/media-store.env)")
    ap.add_argument("--backend", help="local|r2|s3 override")
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("put", help="archive a file")
    p.add_argument("path")
    p.add_argument("--kind", required=True)
    p.add_argument("--name")
    p.add_argument("--month", help="YYYY-MM override (default: now)")
    p.add_argument("--content-type")
    p.add_argument("--overwrite", action="store_true",
                   help="same-name replaces (default: unique -sha8)")
    p.add_argument("--dry-run", action="store_true")

    g = sub.add_parser("get", help="fetch object to stdout or -o")
    g.add_argument("url")
    g.add_argument("-o", "--out")

    s = sub.add_parser("stat")
    s.add_argument("url")
    l = sub.add_parser("ls")
    l.add_argument("--kind")
    l.add_argument("--month")
    l.add_argument("--limit", type=int, default=1000)
    r = sub.add_parser("rm")
    r.add_argument("url")
    r.add_argument("--dry-run", action="store_true")
    u = sub.add_parser("url", help="canonical + public URL for a key")
    u.add_argument("key")
    sub.add_parser("doctor", help="config + reachability check")

    a = ap.parse_args(argv)
    store = MediaStore(backend=a.backend, env_path=a.config)

    if a.cmd == "put":
        when = None
        if a.month:
            when = datetime.datetime.strptime(a.month, "%Y-%m")
        rec = store.put(a.kind, a.path, name=a.name, when=when,
                        unique=not a.overwrite,
                        content_type=a.content_type, dry_run=a.dry_run)
        _print_rec(rec, a.json)
    elif a.cmd == "get":
        body = store.get(a.url)
        if a.out:
            Path(a.out).write_bytes(body)
            print(f"{a.out} ({len(body)}B)")
        else:
            sys.stdout.buffer.write(body)
    elif a.cmd == "stat":
        meta = store.stat(a.url)
        print(json.dumps(meta, indent=1) if a.json else
              "\n".join(f"{k}: {v}" for k, v in (meta or {}).items()))
        return 0 if meta else 2
    elif a.cmd == "ls":
        for o in store.list(kind=a.kind, month=a.month, limit=a.limit):
            print(f"{o['key']}\t{o['size']}\t{o.get('modified', '')}")
    elif a.cmd == "rm":
        if a.dry_run:
            print(f"[dry] would delete {store._key(a.url)}")
        else:
            return 0 if store.delete(a.url) else 2
    elif a.cmd == "url":
        print(store.url_for(a.key))
        pub = store.public_url(a.key)
        if pub:
            print(f"  public={pub}")
    elif a.cmd == "doctor":
        ok, info = store.doctor()
        for k, v in info.items():
            print(f"{k}: {v}")
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
