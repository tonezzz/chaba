#!/usr/bin/env python3
"""Record a render_job on WP boards — upload output to /wp/v2/media, then
write the post with output_url = the returned source_url.

Card render-job-writer-must-upload-output-to-78229c (OPS-0701): render
records used to land with filesystem paths (/local/local-gen/...) that
404 in the browser and die with the host's disk. This is the canonical
writer — lanes and scripts call it (or lib.wp_boards directly) so every
render_job carries a durable WP attachment URL.

Usage:
  render-job-record.py --kind image --prompt "a cat" \
      --output /path/to/render.png [--status ok|error] [meta flags...]
  render-job-record.py --kind video --prompt "..." --output-url https://...
  render-job-record.py --kind image --prompt "..." --output https://host/x.png
  render-job-record.py ... --dry-run     # print payload, no WP writes

--output accepts a local path, bytes-source file, or http(s) URL (fetched
then uploaded — Veo-style backends return URLs, not files). --output-url
is for outputs already hosted on WP (skips the upload). --member-gated
stores chaba/v1/media/<id> instead of the public source_url.

Env: WP_BOARDS_ENV (default ~/.config/secrets/wp-boards.env).
Exit 0 + JSON {ok,id,slug,output_url} on stdout; exit 2 on failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from lib.wp_boards import WpBoards, WpBoardsError, load_env  # noqa: E402

META_FLAGS = {
    "negative_prompt": "--negative-prompt",
    "model": "--model",
    "model_file": "--model-file",
    "size_px": "--size-px",
    "steps": "--steps",
    "sampler": "--sampler",
    "cfg_scale": "--cfg-scale",
    "seed": "--seed",
    "duration_s": "--duration-s",
    "secs": "--secs",
    "vae_s": "--vae-s",
    "aspect": "--aspect",
    "res": "--res",
    "ref_url": "--ref-url",
    "operation": "--operation",
    "est_cost_usd": "--est-cost-usd",
    "parent_job": "--parent-job",
    "chain_index": "--chain-index",
    "host": "--host",
    "backend": "--backend",
    "requested_by": "--requested-by",
    "source": "--source",
    "rating": "--rating",
    "error": "--error",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kind", required=True, choices=["image", "video"])
    ap.add_argument("--prompt", default="")
    ap.add_argument("--status", default="ok",
                    help="ok|error|done — error records may omit output")
    ap.add_argument("--output",
                    help="local path or http(s) URL to upload to /wp/v2/media")
    ap.add_argument("--output-url",
                    help="existing WP media URL — skips the upload")
    ap.add_argument("--member-gated", action="store_true",
                    help="store chaba/v1/media/<id> (members-only stream)")
    ap.add_argument("--slug", help="dedup key — upserts an existing post")
    ap.add_argument("--title")
    ap.add_argument("--post-status", default="private")
    ap.add_argument("--dry-run", action="store_true")
    for key, flag in META_FLAGS.items():
        ap.add_argument(flag, dest=key)
    args = ap.parse_args(argv)

    meta = {k: getattr(args, k) for k in META_FLAGS
            if getattr(args, k) not in (None, "")}
    # numeric-ish meta stays strings — WP meta is stringly-typed anyway
    if args.error and args.status == "ok":
        args.status = "error"

    try:
        wp = WpBoards()
        res = wp.write_render_job(
            kind=args.kind, prompt=args.prompt, status=args.status,
            output=args.output, output_url=args.output_url,
            member_gated=args.member_gated, meta=meta, slug=args.slug,
            title=args.title, post_status=args.post_status,
            dry_run=args.dry_run)
    except WpBoardsError as e:
        print(f"render-job-record: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0
    out = {
        "ok": True,
        "id": res.get("id"),
        "slug": res.get("slug"),
        "output_url": (res.get("meta") or {}).get("output_url", ""),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
