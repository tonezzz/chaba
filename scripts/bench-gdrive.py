#!/usr/bin/env python3
"""Benchmark Google Drive access: rclone vs direct Drive REST (RAM-only).

Compares upload (rcat vs resumable-upload), download (cat vs alt=media),
and list latency — all in-memory, no disk staging. Run on any host that
has an rclone `gdrive:` remote configured.

Token note: when rclone.conf has empty client_id/secret (rclone's
built-in OAuth client) we cannot refresh via REST — instead a throwaway
`rclone lsf` makes rclone refresh+rewrite the token, which we then reuse.

Usage: python3 bench-gdrive.py [--sizes ...] [--iters 3]
"""
import argparse, configparser, json, os, statistics, subprocess, time, urllib.request, urllib.error, urllib.parse

RCLONE_CONF = os.path.expanduser("~/.config/rclone/rclone.conf")
REMOTE = "gdrive"
API = "https://www.googleapis.com"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def rclone(args, stdin=None, timeout=300):
    t0 = time.perf_counter()
    for attempt in range(4):
        r = subprocess.run(["rclone"] + args, input=stdin, capture_output=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout, time.perf_counter() - t0
        err = r.stderr.decode()[:300]
        if (any(s in err for s in ("403", "429", "500", "502", "503")) or "rate" in err.lower() or "quota" in err.lower()) and attempt < 3:
            time.sleep(2 ** (attempt + 2))
            continue
        raise RuntimeError(f"rclone {' '.join(args)} rc={r.returncode}: {err}")


def load_token():
    cp = configparser.ConfigParser()
    cp.read(RCLONE_CONF)
    g = cp[REMOTE]
    tok = json.loads(g["token"])
    if not g.get("client_id", "").strip():
        # built-in rclone client: make rclone refresh and rewrite the conf
        rclone(["lsf", f"{REMOTE}:", "--max-depth", "1"], timeout=120)
        cp.read(RCLONE_CONF)
        return json.loads(cp[REMOTE]["token"])["access_token"]
    exp = tok.get("expiry", "")
    try:
        from datetime import datetime
        e = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        fresh = (e - datetime.now(e.tzinfo)).total_seconds() > 60
    except Exception:
        fresh = False
    if not fresh:
        body = urllib.parse.urlencode({
            "client_id": g["client_id"], "client_secret": g["client_secret"],
            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
        }).encode()
        r = urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30)
        tok["access_token"] = json.loads(r.read())["access_token"]
    return tok["access_token"]


def http(req, timeout=300):
    t0 = time.perf_counter()
    for attempt in range(4):
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
            data = r.read()
            return data, time.perf_counter() - t0, dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            raise


class Rest:
    def __init__(self, token):
        self.h = {"Authorization": f"Bearer {token}"}

    def req(self, method, url, body=None, ctype=None):
        h = dict(self.h)
        if ctype:
            h["Content-Type"] = ctype
        return urllib.request.Request(url, data=body, headers=h, method=method)

    def mkdir(self, name):
        meta = json.dumps({"name": name, "mimeType": "application/vnd.google-apps.folder"}).encode()
        data, _, _ = http(self.req("POST", f"{API}/drive/v3/files", meta, "application/json"))
        return json.loads(data)["id"]

    def upload(self, folder_id, name, blob):
        meta = json.dumps({"name": name, "parents": [folder_id]}).encode()
        _, dt0, hdrs = http(self.req("POST", f"{UPLOAD}?uploadType=resumable", meta, "application/json"))
        data, dt1, _ = http(self.req("PUT", hdrs["Location"], blob))
        return json.loads(data)["id"], dt0 + dt1

    def download(self, fid):
        data, dt, _ = http(self.req("GET", f"{API}/drive/v3/files/{fid}?alt=media"))
        return data, dt

    def listdir(self, folder_id):
        q = urllib.parse.quote(f"'{folder_id}' in parents and trashed=false")
        data, dt, _ = http(self.req("GET", f"{API}/drive/v3/files?q={q}&fields=files(id,name)&pageSize=1000"))
        return json.loads(data)["files"], dt

    def delete(self, fid):
        http(self.req("DELETE", f"{API}/drive/v3/files/{fid}"), timeout=30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="262144,1048576,8388608,33554432")
    ap.add_argument("--iters", type=int, default=3)
    a = ap.parse_args()
    sizes = [int(s) for s in a.sizes.split(",")]
    host = os.uname().nodename
    folder_name = f"bench-gdrive-{host}-{int(time.time())}"

    token = load_token()
    rest = Rest(token)
    fid = rest.mkdir(folder_name)
    rflags = ["--drive-root-folder-id", fid]
    print(f"# {host} folder={folder_name} id={fid}", flush=True)

    results = {}
    for it in range(a.iters):
        for sz in sizes:
            blob = os.urandom(sz)
            name = f"s{sz}-i{it}.bin"
            order = ["rest", "rclone"] if it % 2 == 0 else ["rclone", "rest"]
            fids = {}
            for meth in order:
                if meth == "rest":
                    fids["rest"], dt = rest.upload(fid, f"rest-{name}", blob)
                else:
                    _, dt = rclone(rflags + ["rcat", f"{REMOTE}:rclone-{name}"], stdin=blob)
                results.setdefault((meth, "up", sz), []).append(dt)
            # rclone's uploaded file id — find via list inside its root
            for meth in order:
                if meth == "rest":
                    _, dt = rest.download(fids["rest"])
                else:
                    _, dt = rclone(rflags + ["cat", f"{REMOTE}:rclone-{name}"])
                results.setdefault((meth, "down", sz), []).append(dt)
            rest.delete(fids["rest"])
            rclone(rflags + ["deletefile", f"{REMOTE}:rclone-{name}"])
            print(f"  iter {it} size {sz} done", flush=True)

    for meth in ("rest", "rclone"):
        for _ in range(5):
            if meth == "rest":
                _, dt = rest.listdir(fid)
            else:
                _, dt = rclone(rflags + ["lsf", f"{REMOTE}:"])
            results.setdefault((meth, "list", 0), []).append(dt)

    print(f"\n## RESULTS {host} (median; MB/s = size/median)\n")
    print(f"{'op':6} {'size':>9} {'rclone_s':>9} {'rclone_MB/s':>12} {'rest_s':>8} {'rest_MB/s':>10} {'speedup':>8}")
    for sz in sizes:
        row = {}
        for meth in ("rclone", "rest"):
            for op in ("up", "down"):
                row[(meth, op)] = statistics.median(results[(meth, op, sz)])
        for op in ("up", "down"):
            rc, rs = row[("rclone", op)], row[("rest", op)]
            mb = sz / 1e6
            print(f"{op:6} {sz:>9} {rc:>9.2f} {mb/rc:>12.1f} {rs:>8.2f} {mb/rs:>10.1f} {rc/rs:>8.2f}x")
    lr, ls = statistics.median(results[("rclone", "list", 0)]), statistics.median(results[("rest", "list", 0)])
    print(f"{'list':6} {'-':>9} {lr:>9.2f} {'-':>12} {ls:>8.2f} {'-':>10} {lr/ls:>8.2f}x")

    rest.delete(fid)


if __name__ == "__main__":
    main()
