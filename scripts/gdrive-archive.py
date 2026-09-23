#!/usr/bin/env python3
"""Archive a document set to gdrive:ada-documents/<YYYY>/<slug>/ via REST, RAM-only.

Reads files from a local dir, computes sha256 + dhash per image, uploads each
page + manifest.json via resumable uploads, prints the folder ID.

Usage: gdrive-archive.py <dir> <set-slug> [--type condo-sale]
"""
import argparse, configparser, datetime, hashlib, json, os, sys, time, urllib.request, urllib.error, urllib.parse

CONF = os.path.expanduser("~/.config/rclone/rclone.conf")
API = "https://www.googleapis.com/drive/v3/files"
UP = "https://www.googleapis.com/upload/drive/v3/files"


def token(cp):
    g = cp["gdrive"]
    body = urllib.parse.urlencode({
        "client_id": g["client_id"], "client_secret": g["client_secret"],
        "refresh_token": json.loads(g["token"])["refresh_token"],
        "grant_type": "refresh_token"}).encode()
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=body), timeout=30).read())["access_token"]


class Drive:
    def __init__(self, at):
        self.h = {"Authorization": f"Bearer {at}"}

    def req(self, m, url, body=None, ct=None):
        h = dict(self.h)
        if ct:
            h["Content-Type"] = ct
        for i in range(4):
            try:
                r = urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h, method=m), timeout=120)
                return r.read(), dict(r.headers)
            except urllib.error.HTTPError as e:
                if e.code in (403, 429, 500, 502, 503) and i < 3:
                    time.sleep(2 ** (i + 1)); continue
                raise

    def find(self, name, parent=None):
        q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent:
            q += f" and '{parent}' in parents"
        d, _ = self.req("GET", f"{API}?q={urllib.parse.quote(q)}&fields=files(id,name)")
        f = json.loads(d)["files"]
        return f[0]["id"] if f else None

    def mkdir(self, name, parent=None):
        meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent:
            meta["parents"] = [parent]
        d, _ = self.req("POST", API, json.dumps(meta).encode(), "application/json")
        return json.loads(d)["id"]

    def upload(self, name, blob, parent, mime="application/octet-stream"):
        meta = {"name": name, "parents": [parent]}
        _, hdr = self.req("POST", f"{UP}?uploadType=resumable", json.dumps(meta).encode(), "application/json")
        d, _ = self.req("PUT", hdr["Location"], blob, mime)
        return json.loads(d)["id"]


def dhash(path_or_im):
    from PIL import Image
    im = Image.open(path_or_im) if isinstance(path_or_im, str) else path_or_im
    im = im.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(im.getdata())
    bits = "".join("1" if px[r * 9 + c] > px[r * 9 + c + 1] else "0" for r in range(8) for c in range(8))
    return f"{int(bits, 2):016x}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("slug")
    ap.add_argument("--type", default="document-set")
    a = ap.parse_args()

    cp = configparser.ConfigParser(); cp.read(CONF)
    d = Drive(token(cp))

    root = d.find("ada-documents") or d.mkdir("ada-documents")
    year = d.find(str(datetime.date.today().year), root) or d.mkdir(str(datetime.date.today().year), root)
    existing = d.find(a.slug, year)
    if existing:
        print(f"set {a.slug} already exists (folder {existing}) — aborting")
        sys.exit(2)
    folder = d.mkdir(a.slug, year)

    pages, manifest_files = [], []
    for fn in sorted(os.listdir(a.dir)):
        path = os.path.join(a.dir, fn)
        blob = open(path, "rb").read()
        rec = {"name": fn, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(blob)) if False else Image.open(path)
            rec["dims"] = list(im.size)
            rec["phash"] = dhash(im)
        except Exception:
            pass
        fid = d.upload(fn, blob, folder)
        rec["drive_id"] = fid
        pages.append(rec)
        print(f"  {fn} -> {fid} ({len(blob)//1024}KB)", flush=True)

    manifest = {"slug": a.slug, "type": a.type, "archived_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "archived_from": os.uname().nodename, "pages": pages}
    mid = d.upload("manifest.json", json.dumps(manifest, indent=1).encode(), folder, "application/json")
    print(f"\nfolder: https://drive.google.com/drive/folders/{folder}")
    print(f"manifest: {mid} | {len(pages)} files")


if __name__ == "__main__":
    main()
