#!/usr/bin/env python3
"""Publish landed render candidates as Adobe Stock preview assets (OPS-1131).

For one campaign under ``gdrive:ada-nest-adobe-stock/campaigns/<id>/``:

1. Find landed candidates in ``30-candidates/<asset-id>/`` that have an
   image (png/jpg) plus ``<asset-id>.manifest.json``.
2. Copy each image to the LINE relay media archive on the relay host so it
   gets a durable public ``https://.../relay-img/arch/renders/<name>`` URL.
3. Upsert matching ``assets[]`` entries in the campaign ``RUN.json``
   (created when missing) with ``preview_url`` / ``thumbnail_url`` /
   ``source_ref`` — the fields ``ada_adobe_stock_reuse`` already validates.
4. Rebuild the bounded reuse indexes from every ``RUN.json`` on the remote
   and publish them to ``<remote>/indexes/`` for the read-only Ada mount.

Nothing is uploaded to Adobe, licensed, or mutated beyond the campaign
manifest and index files. Preview URLs are only ever the relay archive
https URLs minted here — never local paths or invented links.

Usage:
  publish-previews.py --campaign AS-2026-11-05-REMOTE-WORK-001
  publish-previews.py --campaign AS-... --dry-run
  publish-previews.py --reindex-only --remote gdrive:ada-nest-adobe-stock
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REMOTE_DEFAULT = "gdrive:ada-nest-adobe-stock"
RELAY_HOST_DEFAULT = "idc03"
ARCHIVE_DIR = "~/.local/share/ada/line-media/renders"
PUBLIC_BASE = "https://157.85.102.125.sslip.io/relay-img"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
HERE = Path(__file__).resolve().parent


def rclone(*args: str, stdin: bytes | None = None, timeout: int = 300) -> bytes:
    r = subprocess.run(
        ["rclone", *args],
        input=stdin,
        capture_output=True,
        timeout=timeout,
    )
    if r.returncode:
        raise RuntimeError(
            f"rclone {' '.join(args[:3])} failed: {r.stderr.decode()[:300]}"
        )
    return r.stdout


def rclone_text(*args: str, **kw) -> str:
    return rclone(*args, **kw).decode("utf-8", errors="replace")


def list_candidates(remote: str, campaign: str) -> list[dict]:
    """-> [{asset_id, image_path, manifest_path}] under 30-candidates/."""
    base = f"{remote}/campaigns/{campaign}/30-candidates"
    listing = rclone_text("lsf", "-R", "--files-only", base).splitlines()
    files = [x.strip() for x in listing if x.strip()]
    images: dict[str, str] = {}
    manifests: dict[str, str] = {}
    for rel in files:
        parts = rel.split("/")
        if len(parts) != 2:
            continue
        asset_id, name = parts
        low = name.lower()
        if low.endswith(tuple(e for e in IMAGE_EXTS)):
            images.setdefault(asset_id, rel)
        elif low.endswith(".manifest.json"):
            manifests.setdefault(asset_id, rel)
    out = []
    for asset_id in sorted(set(images) & set(manifests)):
        out.append({
            "asset_id": asset_id,
            "image_path": f"{base}/{images[asset_id]}",
            "manifest_path": f"{base}/{manifests[asset_id]}",
        })
    return out


def fetch_remote(path: str) -> bytes | None:
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "f"
        r = subprocess.run(
            ["rclone", "copyto", path, str(dst)],
            capture_output=True, timeout=120,
        )
        return dst.read_bytes() if r.returncode == 0 and dst.exists() else None


def archive_publish(host: str, name: str, data: bytes) -> str | None:
    """Write image bytes into the relay media archive; return public URL."""
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", name)
    remote_path = f"{ARCHIVE_DIR}/{safe}"
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
         f"mkdir -p {ARCHIVE_DIR} && cat > {remote_path}"],
        input=data, capture_output=True, timeout=300,
    )
    if r.returncode:
        print(f"warn: archive write failed for {safe}: "
              f"{r.stderr.decode()[:200]}", file=sys.stderr)
        return None
    url = f"{PUBLIC_BASE}/arch/renders/{safe}"
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                print(f"warn: archive URL not reachable: {url}",
                      file=sys.stderr)
                return None
    except Exception as exc:
        print(f"warn: archive verify failed {url}: {exc}",
              file=sys.stderr)
        return None
    return url


def load_run_json(remote: str, campaign: str) -> dict:
    data = fetch_remote(f"{remote}/campaigns/{campaign}/RUN.json")
    if data is None:
        return {"campaign_id": campaign, "status": "active",
                "assets": [], "prompt_patterns": [],
                "rejection_patterns": []}
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("RUN.json must contain a JSON object")
    payload.setdefault("assets", [])
    return payload


def upsert_asset(run: dict, asset: dict, source_ref: str) -> str:
    assets = run["assets"]
    for i, existing in enumerate(assets):
        if existing.get("id") == asset["id"]:
            merged = dict(existing)
            merged.update(asset)
            merged["source_ref"] = source_ref
            assets[i] = merged
            return "updated"
    record = dict(asset)
    record["source_ref"] = source_ref
    assets.append(record)
    return "added"


def write_run_json(remote: str, campaign: str, run: dict) -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "RUN.json"
        p.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n")
        rclone("copyto", str(p),
               f"{remote}/campaigns/{campaign}/RUN.json")


def publish_campaign(args) -> dict:
    candidates = list_candidates(args.remote, args.campaign)
    if args.asset_id:
        candidates = [c for c in candidates if c["asset_id"] == args.asset_id]
    if not candidates:
        return {"ok": True, "campaign": args.campaign,
                "assets_processed": 0, "note": "no landed candidates"}

    run = load_run_json(args.remote, args.campaign)
    results = []
    for cand in candidates:
        asset_id = cand["asset_id"]
        manifest_raw = fetch_remote(cand["manifest_path"])
        manifest = json.loads(manifest_raw) if manifest_raw else {}
        image_name = cand["image_path"].rsplit("/", 1)[-1]
        ext = Path(image_name).suffix.lower().lstrip(".")
        arch_name = (f"adobe-{re.sub(r'[^a-z0-9]+', '-', args.campaign.lower())}"
                     f"-{re.sub(r'[^a-z0-9]+', '-', asset_id.lower())}.{ext}")
        data = fetch_remote(cand["image_path"])
        if data is None:
            results.append({"asset_id": asset_id, "status": "fetch_failed"})
            continue
        url = None if args.dry_run else archive_publish(
            args.relay_host, arch_name, data)
        preview_url = url or (f"{PUBLIC_BASE}/arch/renders/{arch_name}"
                              if args.dry_run else None)
        dims = (manifest.get("dimensions") or "").split("x")
        asset = {
            "id": asset_id,
            "title": manifest.get("title") or asset_id,
            "preview_url": preview_url,
            "thumbnail_url": preview_url,
            "width": int(dims[0]) if dims and dims[0].isdigit() else None,
            "height": int(dims[1]) if len(dims) > 1 and dims[1].isdigit() else None,
            "sha256": manifest.get("sha256"),
            "provider": manifest.get("provider"),
            "job_id": manifest.get("job_id"),
            "landed_at": manifest.get("landed_at"),
            "status": "candidate-qc-pending",
        }
        asset = {k: v for k, v in asset.items() if v is not None}
        source_ref = (f"{args.campaign}/30-candidates/{asset_id}/"
                      f"{image_name}")
        if args.dry_run:
            action = "dry-run"
        else:
            action = upsert_asset(run, asset, source_ref)
        results.append({
            "asset_id": asset_id, "status": action,
            "preview_url": preview_url, "source_ref": source_ref,
        })

    if not args.dry_run:
        run["campaign_id"] = args.campaign
        write_run_json(args.remote, args.campaign, run)
    return {"ok": True, "campaign": args.campaign,
            "assets_processed": len(results), "assets": results,
            "run_json_assets": len(run.get("assets", []))}


def reindex(args) -> dict:
    """Export every RUN.json on the remote, rebuild indexes, publish."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        campaigns_root = root / "campaigns"
        campaigns_root.mkdir()
        remote_base = f"{args.remote}/campaigns"
        listing = rclone_text(
            "lsf", "-R", "--files-only", "--include", "RUN.json",
            remote_base).splitlines()
        copied = 0
        for rel in listing:
            rel = rel.strip()
            if not rel.endswith("RUN.json"):
                continue
            campaign_dir = rel.rsplit("/", 1)[0] or rel
            # rel is <campaign>/.../RUN.json — preserve structure under campaigns/
            local = campaigns_root / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            data = fetch_remote(f"{remote_base}/{rel}")
            if data is not None:
                local.write_bytes(data)
                copied += 1
        if copied == 0:
            return {"ok": False, "error": "no RUN.json found on remote"}
        sys.path.insert(0, str(HERE))
        import build_adobe_stock_indexes as builder
        indexes = builder.build_indexes(campaigns_root)
        out_root = root / "indexes"
        builder.write_indexes(indexes, out_root)
        for path in sorted(out_root.iterdir()):
            rclone("copyto", str(path), f"{args.remote}/indexes/{path.name}")
        return {
            "ok": True, "manifests": copied,
            "campaigns": len(indexes["campaigns"]),
            "assets": len(indexes["assets"]),
            "prompt_patterns": len(indexes["prompt-patterns"]),
            "rejection_patterns": len(indexes["rejection-patterns"]),
            "published": [p.name for p in sorted(out_root.iterdir())],
        }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--campaign", default="")
    p.add_argument("--asset-id", default="")
    p.add_argument("--remote", default=REMOTE_DEFAULT)
    p.add_argument("--relay-host", default=RELAY_HOST_DEFAULT)
    p.add_argument("--reindex-only", action="store_true")
    p.add_argument("--skip-reindex", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    out = {"ok": True}
    if args.campaign:
        out["publish"] = publish_campaign(args)
    if args.reindex_only or (args.campaign and not args.skip_reindex):
        out["reindex"] = reindex(args)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
