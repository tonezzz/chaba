"""Google Drive REST client for doc-archive — factored from scripts/gdrive-archive.py.

RAM-only: uploads take bytes, downloads return bytes; nothing touches disk.
Auth: OAuth refresh_token taken from the [gdrive] section of rclone.conf
(client_id/client_secret written there per the 2026-09-23 dedicated-client
decision — see docs/kb/document-archive-service.md). The access token is
refreshed lazily and re-fetched once on a 401.

No third-party deps — urllib only.
"""
import configparser
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

CONF = os.path.expanduser("~/.config/rclone/rclone.conf")
API = "https://www.googleapis.com/drive/v3/files"
UP = "https://www.googleapis.com/upload/drive/v3/files"
ABOUT = "https://www.googleapis.com/drive/v3/about"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PICKER = "https://photospicker.googleapis.com/v1"
FOLDER_MIME = "application/vnd.google-apps.folder"

# Transient statuses worth retrying (quota 403s and 500s observed in bench).
RETRY_CODES = (403, 429, 500, 502, 503, 504)


def load_rclone_credentials(conf_path=CONF):
    """Return {client_id, client_secret, refresh_token} from rclone.conf [gdrive]."""
    cp = configparser.ConfigParser()
    if not cp.read(conf_path):
        raise FileNotFoundError(f"rclone conf not readable: {conf_path}")
    g = cp["gdrive"]
    return {
        "client_id": g["client_id"],
        "client_secret": g["client_secret"],
        "refresh_token": json.loads(g["token"])["refresh_token"],
    }


def refresh_access_token(creds, timeout=30):
    """Exchange a refresh_token for an access token. Returns the token string."""
    body = urllib.parse.urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    resp = urllib.request.urlopen(
        urllib.request.Request(TOKEN_URL, data=body), timeout=timeout)
    return json.loads(resp.read())["access_token"]


def token_provider_from_rclone(conf_path=CONF):
    """Callable returning a fresh access token each invocation."""
    def provide():
        return refresh_access_token(load_rclone_credentials(conf_path))
    return provide


def token_provider_for(client_id, client_secret, refresh_token):
    """Callable minting access tokens for a scoped refresh_token that is
    NOT the rclone one — e.g. photospicker.mediaitems.readonly granted by
    gphoto-auth.py and stored in doc-archive.env."""
    creds = {"client_id": client_id, "client_secret": client_secret,
             "refresh_token": refresh_token}
    def provide():
        return refresh_access_token(creds)
    return provide


def _esc(name):
    return name.replace("\\", "\\\\").replace("'", "\\'")


class Drive:
    """Minimal Drive v3 client: find/mkdir/upload/download with retry+backoff.

    token_provider: callable returning an access token (e.g.
        token_provider_from_rclone()). Called lazily on first request and
        again after a 401.
    """

    def __init__(self, token_provider, retries=4, timeout=120, sleep=time.sleep):
        self._token_provider = token_provider
        self._token = None
        self.retries = retries
        self.timeout = timeout
        self.sleep = sleep  # injectable so tests don't wait

    def _headers(self):
        if self._token is None:
            self._token = self._token_provider()
        return {"Authorization": f"Bearer {self._token}"}

    def req(self, method, url, body=None, content_type=None):
        """Run one Drive request. Retries RETRY_CODES with exponential
        backoff; on 401 drops the cached token and retries once."""
        refreshed = False
        last_exc = None
        for i in range(self.retries):
            h = dict(self._headers())
            if content_type:
                h["Content-Type"] = content_type
            try:
                r = urllib.request.urlopen(
                    urllib.request.Request(url, data=body, headers=h, method=method),
                    timeout=self.timeout)
                return r.read(), dict(r.headers)
            except urllib.error.HTTPError as e:
                last_exc = e
                if e.code == 401 and not refreshed:
                    refreshed = True
                    self._token = None
                    continue
                if e.code in RETRY_CODES and i < self.retries - 1:
                    self.sleep(2 ** (i + 1))
                    continue
                raise
            except urllib.error.URLError as e:
                last_exc = e
                if i < self.retries - 1:
                    self.sleep(2 ** (i + 1))
                    continue
                raise
        raise last_exc

    def find(self, name, parent=None, mime=FOLDER_MIME):
        """First file/folder id matching name (+optional parent), or None."""
        q = f"name='{_esc(name)}' and trashed=false"
        if mime:
            q += f" and mimeType='{mime}'"
        if parent:
            q += f" and '{parent}' in parents"
        d, _ = self.req("GET",
                        f"{API}?q={urllib.parse.quote(q)}&fields=files(id,name)")
        files = json.loads(d).get("files", [])
        return files[0]["id"] if files else None

    def mkdir(self, name, parent=None):
        meta = {"name": name, "mimeType": FOLDER_MIME}
        if parent:
            meta["parents"] = [parent]
        d, _ = self.req("POST", API, json.dumps(meta).encode(), "application/json")
        return json.loads(d)["id"]

    def ensure_path(self, *names):
        """mkdir -p: walk/create a folder path, return the leaf folder id."""
        parent = None
        for name in names:
            parent = self.find(name, parent) or self.mkdir(name, parent)
        return parent

    def upload(self, name, blob, parent, mime="application/octet-stream"):
        """Resumable upload of bytes -> new file id."""
        meta = {"name": name, "parents": [parent]}
        _, hdr = self.req("POST", f"{UP}?uploadType=resumable",
                          json.dumps(meta).encode(), "application/json")
        d, _ = self.req("PUT", hdr["Location"], blob, mime)
        return json.loads(d)["id"]

    def download(self, file_id):
        """alt=media download -> bytes."""
        d, _ = self.req("GET", f"{API}/{file_id}?alt=media")
        return d

    def about(self):
        """Cheap reachability probe."""
        d, _ = self.req("GET", f"{ABOUT}?fields=user")
        return json.loads(d)

    # -- browse / read / edit --------------------------------------------

    _LIST_FIELDS = ("files(id,name,mimeType,size,modifiedTime,"
                    "webViewLink,parents,thumbnailLink)")

    def search(self, query, mime=None, limit=20):
        """files.list — fullText+name match, optional mimeType filter.
        Returns [{id,name,mimeType,size,modifiedTime,webViewLink,
        thumbnailLink,parents}]."""
        q = f"(name contains '{_esc(query)}' or fullText contains '{_esc(query)}') and trashed=false"
        if mime:
            q += f" and mimeType contains '{_esc(mime)}'"
        url = (f"{API}?q={urllib.parse.quote(q)}"
               f"&fields={urllib.parse.quote(self._LIST_FIELDS)}"
               f"&pageSize={max(1, min(int(limit), 100))}"
               "&orderBy=" + urllib.parse.quote("modifiedTime desc"))
        d, _ = self.req("GET", url)
        return json.loads(d).get("files", [])

    def get_meta(self, file_id, fields=None):
        f = fields or ("id,name,mimeType,size,modifiedTime,"
                       "webViewLink,parents,thumbnailLink")
        d, _ = self.req("GET", f"{API}/{file_id}?fields={urllib.parse.quote(f)}")
        return json.loads(d)

    def export(self, file_id, mime="text/plain"):
        """Export a Google-native doc (Docs/Sheets/Slides) to a flat mime."""
        d, _ = self.req("GET",
                        f"{API}/{file_id}/export?mimeType={urllib.parse.quote(mime)}")
        return d

    def update_media(self, file_id, blob, mime="text/plain"):
        """PATCH upload — replaces a regular file's content in place.
        Google-native types can't be media-updated; use export+re-upload."""
        d, _ = self.req(
            "PATCH", f"{UP}/{file_id}?uploadType=media", blob, mime)
        return json.loads(d)

    # -- Google Photos Picker --------------------------------------------

    def picker_session_create(self):
        """POST /v1/sessions — returns {id, pickerUri, expireTime, ...}.
        Needs a token minted with photospicker.mediaitems.readonly scope."""
        d, _ = self.req("POST", f"{PICKER}/sessions", b"{}",
                        "application/json")
        return json.loads(d)

    def picker_session_get(self, session_id):
        d, _ = self.req("GET", f"{PICKER}/sessions/{session_id}")
        return json.loads(d)

    def picker_media_items(self, session_id, limit=50):
        d, _ = self.req(
            "GET", f"{PICKER}/mediaItems?sessionId={session_id}"
                   f"&pageSize={max(1, min(int(limit), 100))}")
        return json.loads(d).get("mediaItems", [])
