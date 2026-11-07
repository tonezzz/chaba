#!/usr/bin/env python3
"""model-cache.py — content-addressed GGUF/Ollama blob cache (OPS-0969).

One file, stdlib only: runs the same on con01/idc03 (cache origin) and on
macOS/Linux consumers (KK-Mac, other fleet workers). No credentials are
moved — fetches hit the public Ollama registry; transfers ride SSH or a
tailnet-bound read-only HTTP export.

Store layout under ROOT (default ~/var/cache/devnest/models):

    ollama-models/
      blobs/sha256-<hex>                  content-addressed model/layer blobs
      manifests/<registry>/<ns>/<name>/<tag>   OCI manifest JSON
    index.json                          per-model metadata (name, quant,
                                        source, sha256, bytes, license,
                                        created_at, compatibility)
    quarantine/                         in-flight + failed downloads; nothing
                                        is promoted to blobs/ until sha256
                                        matches the manifest digest
    metrics.jsonl                     download/transfer/verify/serve timings
    serve.log                         http export log

The ollama-models/ dir is itself a valid OLLAMA_MODELS store, so an
isolated `ollama serve` can point straight at the cache for smoke tests.

Subcommands:
  fetch MODEL[:TAG]     registry manifest -> quarantine -> sha256 -> blobs/
  verify [MODEL[:TAG]]  re-check sha256 of cached blobs (verifier quality)
  index                 rebuild index.json from on-disk manifests
  list                  print index
  export-gguf MODEL     hardlink/copy the GGUF layer to exports/<name>.gguf
                        (llama.cpp / mlx_lm direct-load path)
  serve                 read-only HTTP export of ollama-models/ (tailnet only)
  pull MODEL            consumer import: HTTP or ssh source -> local OLLAMA_MODELS
  metrics               tail metrics.jsonl

Never prints signed URLs or tokens; logs only registry host + repo refs.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

REGISTRY = "registry.ollama.ai"
DEFAULT_ROOT = Path(
    os.environ.get("MODEL_CACHE_ROOT", "~/var/cache/devnest/models")
).expanduser()

MANIFEST_ACCEPT = "application/vnd.docker.distribution.manifest.v2+json"
CHUNK = 1 << 20


# ---------------------------------------------------------------- helpers

def log(msg):
    print(f"[model-cache {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_model(ref):
    """'qwen3:0.6b' -> ('library', 'qwen3', '0.6b'); allows ns/name:tag."""
    name, _, tag = ref.partition(":")
    tag = tag or "latest"
    ns, _, name = name.rpartition("/")
    return ns or "library", name, tag


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def metrics_path(root):
    return root / "metrics.jsonl"


def record_metric(root, op, **fields):
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "op": op}
    rec.update(fields)
    with open(metrics_path(root), "a") as f:
        f.write(json.dumps(rec) + "\n")


def index_path(root):
    return root / "index.json"


def load_index(root):
    p = index_path(root)
    return json.loads(p.read_text()) if p.exists() else {"models": {}}


def save_index(root, idx):
    idx["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = index_path(root).with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, indent=2, sort_keys=True) + "\n")
    tmp.replace(index_path(root))


def blobs_dir(root):
    return root / "ollama-models" / "blobs"


def manifests_dir(root):
    return root / "ollama-models" / "manifests"


def manifest_path(root, registry, ns, name, tag):
    return manifests_dir(root) / registry / ns / name / tag


def http_get_json(url):
    req = urllib.request.Request(url, headers={"Accept": MANIFEST_ACCEPT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def download_resumable(url, dest_part, expected_size=None):
    """Download url -> dest_part with Range resume. Returns (bytes, secs)."""
    got = dest_part.stat().st_size if dest_part.exists() else 0
    if expected_size and got == expected_size:
        return got, 0.0
    t0 = time.time()
    while True:
        headers = {"Range": f"bytes={got}-"} if got else {}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(
                dest_part, "ab"
            ) as f:
                shutil.copyfileobj(r, f, CHUNK)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            got = dest_part.stat().st_size if dest_part.exists() else 0
            if expected_size and got >= expected_size:
                break
            log(f"  retry after {type(e).__name__}: {got} bytes so far")
            time.sleep(3)
    size = dest_part.stat().st_size
    return size, time.time() - t0


def compat_from_config(cfg_blob_bytes):
    try:
        cfg = json.loads(cfg_blob_bytes)
    except Exception:
        return {}
    # ollama config blob keys: model_family (llm arch), model_type (params),
    # file_type (quant), model_format, architecture (host arch), os, rootfs
    return {
        "architecture": cfg.get("model_family") or cfg.get("architecture"),
        "parameters": cfg.get("model_type") or cfg.get("parameters"),
        "quantization": cfg.get("file_type") or cfg.get("quantization"),
        "file_format": cfg.get("model_format") or cfg.get("file_format"),
        "host_arch": cfg.get("architecture"),
        "os": cfg.get("os"),
        "capabilities": cfg.get("capabilities", []),
        "runtime": ["ollama", "llama.cpp", "mlx-lm(gguf)"],
    }


def license_from_blob(path):
    try:
        head = open(path, "rb").read(4096).decode("utf-8", "replace")
    except OSError:
        return None
    for line in head.splitlines():
        s = line.strip(" #*\t")
        if s:
            return s[:120]
    return None


# ---------------------------------------------------------------- commands

def cmd_fetch(args):
    root = args.root
    ns, name, tag = parse_model(args.model)
    reg = args.registry
    quarantine = root / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    blobs_dir(root).mkdir(parents=True, exist_ok=True)
    log(f"fetch {ns}/{name}:{tag} from {reg}")

    man_url = f"https://{reg}/v2/{ns}/{name}/manifests/{tag}"
    man = http_get_json(man_url)
    layers = list(man.get("layers", []))
    if man.get("config"):
        layers = [man["config"]] + layers

    total_bytes = sum(l["size"] for l in layers)
    t0 = time.time()
    fetched = 0
    for layer in layers:
        digest = layer["digest"]
        algo, _, hexv = digest.partition(":")
        if algo != "sha256":
            log(f"  SKIP {algo} digest (unsupported)")
            continue
        blob = blobs_dir(root) / f"sha256-{hexv}"
        if blob.exists() and blob.stat().st_size == layer["size"]:
            log(f"  have sha256-{hexv[:12]} ({layer['size']} B)")
            continue
        part = quarantine / f"sha256-{hexv}.part"
        url = f"https://{reg}/v2/{ns}/{name}/blobs/{digest}"
        size, secs = download_resumable(url, part, layer["size"])
        if size != layer["size"]:
            log(f"  QUARANTINE sha256-{hexv[:12]}: size {size} != {layer['size']}")
            continue
        got = sha256_file(part)
        if got != hexv:
            log(f"  QUARANTINE sha256-{hexv[:12]}: sha mismatch (kept in quarantine)")
            continue
        part.replace(blob)  # atomic promote
        fetched += size
        log(f"  ok sha256-{hexv[:12]} ({size} B)")
    dl_secs = time.time() - t0

    # write manifest only when every layer landed
    missing = [
        l["digest"].split(":")[1]
        for l in layers
        if l["digest"].startswith("sha256:")
        and not (blobs_dir(root) / f"sha256-{l['digest'].split(':')[1]}").exists()
    ]
    if missing:
        log(f"INCOMPLETE — {len(missing)} blob(s) still quarantined")
        record_metric(root, "fetch", model=f"{ns}/{name}:{tag}",
                      ok=False, missing=len(missing))
        return 2

    mpath = manifest_path(root, reg, ns, name, tag)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(man))

    cfg_blob = blobs_dir(root) / f"sha256-{man['config']['digest'].split(':')[1]}"
    compat = compat_from_config(cfg_blob.read_bytes()) if cfg_blob.exists() else {}
    lic = None
    model_blob = None
    for l in man.get("layers", []):
        if l["mediaType"].endswith("license"):
            lic = license_from_blob(
                blobs_dir(root) / f"sha256-{l['digest'].split(':')[1]}")
        if l["mediaType"].endswith("image.model"):
            model_blob = l["digest"].split(":")[1]

    idx = load_index(root)
    entry = idx["models"].get(f"{name}:{tag}", {})
    entry.update({
        "name": name, "namespace": ns, "tag": tag, "registry": reg,
        "source": f"ollama://{reg}/{ns}/{name}:{tag}",
        "source_url": f"https://{reg}/v2/{ns}/{name}/manifests/{tag}",
        "model_sha256": model_blob,
        "bytes": total_bytes,
        "license": lic or entry.get("license"),
        "compatibility": compat,
        "manifest": str(mpath.relative_to(root)),
        "created_at": entry.get("created_at")
        or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    idx["models"][f"{name}:{tag}"] = entry
    save_index(root, idx)
    mbps = fetched / dl_secs / 1e6 if dl_secs and fetched else 0
    record_metric(root, "fetch", model=f"{name}:{tag}", ok=True,
                  bytes=fetched, secs=round(dl_secs, 2), mbps=round(mbps, 1))
    log(f"cached {name}:{tag} — {total_bytes} B total, "
        f"{fetched} B fetched in {dl_secs:.1f}s ({mbps:.1f} MB/s)")
    return 0


def cmd_verify(args):
    root = args.root
    idx = load_index(root)
    models = ({args.model} if args.model else set(idx["models"]))
    bad = 0
    t0 = time.time()
    checked = 0
    for key in sorted(models):
        e = idx["models"].get(key)
        if not e:
            ns, name, tag = parse_model(key)
            mp = manifest_path(root, REGISTRY, ns, name, tag)
            if not mp.exists():
                log(f"{key}: not in index, no manifest — skip")
                continue
            man = json.loads(mp.read_text())
        else:
            mp = root / e["manifest"]
            man = json.loads(mp.read_text())
        layers = list(man.get("layers", []))
        if man.get("config"):
            layers.append(man["config"])
        ok = True
        for l in layers:
            hexv = l["digest"].split(":")[1]
            p = blobs_dir(root) / f"sha256-{hexv}"
            if not p.exists() or p.stat().st_size != l["size"]:
                log(f"  {key} sha256-{hexv[:12]}: MISSING/size")
                ok = bad = True
                continue
            if sha256_file(p) != hexv:
                log(f"  {key} sha256-{hexv[:12]}: SHA MISMATCH")
                ok = bad = True
            else:
                checked += l["size"]
        log(f"{key}: {'OK' if ok else 'FAIL'} ({len(layers)} blobs)")
    secs = time.time() - t0
    mbps = checked / secs / 1e6 if secs else 0
    record_metric(root, "verify", ok=not bad, bytes=checked,
                  secs=round(secs, 2), mbps=round(mbps, 1))
    log(f"verify done: {checked/1e6:.0f} MB in {secs:.1f}s ({mbps:.0f} MB/s)")
    return 1 if bad else 0


def cmd_index(args):
    root = args.root
    idx = load_index(root)
    mroot = manifests_dir(root)
    n = 0
    for mp in sorted(mroot.rglob("*")):
        if not mp.is_file():
            continue
        rel = mp.relative_to(mroot).parts
        if len(rel) != 4:
            continue
        reg, ns, name, tag = rel
        try:
            man = json.loads(mp.read_text())
        except Exception:
            continue
        cfgp = blobs_dir(root) / f"sha256-{man.get('config', {}).get('digest', ':').split(':')[1]}"
        compat = compat_from_config(cfgp.read_bytes()) if cfgp.exists() else {}
        lic, model_blob = None, None
        total = man.get("config", {}).get("size", 0)
        for l in man.get("layers", []):
            total += l["size"]
            if l["mediaType"].endswith("license"):
                lic = license_from_blob(
                    blobs_dir(root) / f"sha256-{l['digest'].split(':')[1]}")
            if l["mediaType"].endswith("image.model"):
                model_blob = l["digest"].split(":")[1]
        key = f"{name}:{tag}"
        e = idx["models"].get(key, {})
        e.update({
            "name": name, "namespace": ns, "tag": tag, "registry": reg,
            "source": f"ollama://{reg}/{ns}/{name}:{tag}",
            "source_url": f"https://{reg}/v2/{ns}/{name}/manifests/{tag}",
            "model_sha256": model_blob, "bytes": total,
            "license": lic or e.get("license"),
            "compatibility": compat or e.get("compatibility", {}),
            "manifest": str(mp.relative_to(root)),
            "created_at": e.get("created_at")
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        idx["models"][key] = e
        n += 1
    save_index(root, idx)
    log(f"index rebuilt: {n} manifest(s) -> {index_path(root)}")
    return 0


def cmd_list(args):
    idx = load_index(args.root)
    for key, e in sorted(idx["models"].items()):
        c = e.get("compatibility", {})
        log(f"{key:24} {e.get('bytes', 0)/1e6:8.0f} MB  "
            f"{c.get('quantization') or '?':8} lic={str(e.get('license'))[:40]}")
    return 0


def cmd_export_gguf(args):
    root = args.root
    idx = load_index(root)
    e = idx["models"].get(args.model)
    if not e or not e.get("model_sha256"):
        log(f"{args.model}: no model blob in index — run fetch/index first")
        return 2
    src = blobs_dir(root) / f"sha256-{e['model_sha256']}"
    dest_dir = root / "exports"
    dest_dir.mkdir(exist_ok=True)
    quant = (e.get("compatibility") or {}).get("quantization") or "gguf"
    dest = dest_dir / f"{e['name']}-{e['tag']}-{quant}.gguf"
    if dest.exists():
        log(f"exists: {dest}")
        return 0
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)
    log(f"exported {dest} ({dest.stat().st_size} B) — sha256 {e['model_sha256'][:16]}…")
    return 0


def cmd_serve(args):
    root = args.root
    os.chdir(root / "ollama-models")
    log_fh = open(root / "serve.log", "a")

    class H(SimpleHTTPRequestHandler):
        def log_message(self, fmt, *a):
            log_fh.write("%s %s\n" % (time.strftime("%FT%TZ", time.gmtime()),
                                      fmt % a))
            log_fh.flush()

        def do_POST(self):
            self.send_error(405)

        do_PUT = do_DELETE = do_POST

    srv = ThreadingHTTPServer((args.bind, args.port), H)
    log(f"serving {root}/ollama-models on {args.bind}:{args.port} (GET-only)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_pull(args):
    """Consumer side: import model into a local ollama-models dir."""
    root = args.root
    ns, name, tag = parse_model(args.model)
    quarantine = root / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    blobs_dir(root).mkdir(parents=True, exist_ok=True)

    if args.base_url:
        mrel = f"manifests/{args.registry or REGISTRY}/{ns}/{name}/{tag}"
        man = http_get_json(f"{args.base_url.rstrip('/')}/{mrel}")
        blob_url = lambda d: f"{args.base_url.rstrip('/')}/blobs/sha256-{d.split(':')[1]}"  # noqa: E731
        fetcher = "http"
    elif args.ssh:
        mrel = f"manifests/{args.registry or REGISTRY}/{ns}/{name}/{tag}"
        remote_root = args.remote_root or str(DEFAULT_ROOT / "ollama-models")
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", args.ssh,
             f"cat {remote_root}/{mrel}"],
            capture_output=True, check=True)
        man = json.loads(out.stdout)
        blob_url = None
        fetcher = "ssh"
    else:
        sys.exit("pull needs --base-url or --ssh")

    layers = list(man.get("layers", []))
    if man.get("config"):
        layers.append(man["config"])
    t0 = time.time()
    moved = 0
    for l in layers:
        hexv = l["digest"].split(":")[1]
        blob = blobs_dir(root) / f"sha256-{hexv}"
        if blob.exists() and blob.stat().st_size == l["size"]:
            continue
        part = quarantine / f"sha256-{hexv}.part"
        if fetcher == "http":
            download_resumable(blob_url(l["digest"]), part, l["size"])
        else:
            remote_root = args.remote_root or str(DEFAULT_ROOT / "ollama-models")
            with open(part, "wb") as f:
                subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", args.ssh,
                     f"cat {remote_root}/blobs/sha256-{hexv}"],
                    stdout=f, check=True)
        if part.stat().st_size != l["size"] or sha256_file(part) != hexv:
            log(f"  QUARANTINE sha256-{hexv[:12]} (kept; not imported)")
            continue
        part.replace(blob)
        moved += l["size"]
        log(f"  ok sha256-{hexv[:12]} ({l['size']} B)")

    reg = args.registry or REGISTRY
    mp = manifest_path(root, reg, ns, name, tag)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(man))
    secs = time.time() - t0
    record_metric(root, "pull", model=f"{name}:{tag}", via=fetcher,
                  bytes=moved, secs=round(secs, 2),
                  mbps=round(moved / secs / 1e6, 1) if secs else 0)
    log(f"imported {name}:{tag} -> {root}/ollama-models "
        f"({moved/1e6:.0f} MB in {secs:.1f}s)")
    return 0


def cmd_metrics(args):
    p = metrics_path(args.root)
    if not p.exists():
        log("no metrics yet")
        return 0
    for line in p.read_text().splitlines()[-args.n:]:
        print(line)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                    help=f"cache root (default {DEFAULT_ROOT})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch")
    p.add_argument("model")
    p.add_argument("--registry", default=REGISTRY)
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("verify")
    p.add_argument("model", nargs="?")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("index")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("list")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("export-gguf")
    p.add_argument("model")
    p.set_defaults(fn=cmd_export_gguf)

    p = sub.add_parser("serve")
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8377)
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("pull")
    p.add_argument("model")
    p.add_argument("--base-url", help="http://host:port of a `serve` instance")
    p.add_argument("--ssh", help="ssh host alias holding the cache")
    p.add_argument("--remote-root", help="remote ollama-models dir")
    p.add_argument("--registry")
    p.set_defaults(fn=cmd_pull)

    p = sub.add_parser("metrics")
    p.add_argument("-n", type=int, default=20)
    p.set_defaults(fn=cmd_metrics)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
