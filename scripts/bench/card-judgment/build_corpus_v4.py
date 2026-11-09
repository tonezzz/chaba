#!/usr/bin/env python3
"""build_corpus_v4.py — card-judgment corpus v4: distilled brief + raw
gate fields (card-distill-free-lane / ADA-1133).

v3 snapshots carry the prose verbatim (brief + comms_tail ~2KB/case).
v4 replaces the prose with the fixed-slot distilled brief and keeps the
decisive gate fields raw — the compression target for live lane turns.

  raw gate fields kept : title priority review_kind tags spec_present
                         open_requests claim action_status
  prose dropped        : brief comms_tail
  added                : distilled {7 slots} + distilled_lane

The distiller runs on the FROZEN case snapshot (pseudo-card), never the
live card — post-decision comms would leak proven_right. Cached by
snapshot content hash, so rebuilds are free unless the input changed.

Usage:
  build_corpus_v4.py [--corpus corpus.jsonl] [--out corpus-v4.jsonl]
                     [--limit N] [--refresh] [--cache-dir DIR]
Env: same lane-chain vars as distill.py (CF_*/LITELLM_*/GEMINI_API_KEY).
"""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import distill

GATE_FIELDS = ("title", "priority", "review_kind", "tags", "spec_present",
               "open_requests", "claim", "action_status")


def v4_snapshot(case):
    s = case.get("snapshot") or {}
    pseudo = distill.pseudo_card(s, case.get("card_id"))
    key = distill.snapshot_key(s)
    return pseudo, key, {f: s.get(f) for f in GATE_FIELDS}


def main():
    ap = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    ap.add_argument("--corpus", default=str(here / "corpus.jsonl"))
    ap.add_argument("--out", default=str(here / "corpus-v4.jsonl"))
    ap.add_argument("--cache-dir", default=distill.CACHE_DIR)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--retries", type=int, default=3,
                    help="re-walk the lane chain after --retry-wait on "
                    "total failure (RPM windows on free tiers)")
    ap.add_argument("--retry-wait", type=int, default=30)
    args = ap.parse_args()

    lanes = distill.default_lanes()
    if not lanes:
        print("no lanes configured — need CF_*/ollama/LITELLM_*/GEMINI_API_KEY",
              file=sys.stderr)
        sys.exit(2)
    print("lanes: " + " -> ".join(n for n, *_ in lanes), file=sys.stderr)

    cases = [json.loads(l) for l in Path(args.corpus).read_text().splitlines()
             if l.strip()]
    if args.limit:
        cases = cases[:args.limit]

    out, lane_hist, failed = [], {}, 0
    for i, case in enumerate(cases, 1):
        pseudo, key, gate = v4_snapshot(case)
        brief = distill.distill_card(pseudo, lanes, key=key,
                                     cache_dir=args.cache_dir,
                                     refresh=args.refresh)
        tries = 0
        while brief.get("_lane") == "none" and tries < args.retries:
            tries += 1
            print(f"  all lanes failed on {case['case_id']} — "
                  f"retry {tries}/{args.retries} in {args.retry_wait}s",
                  file=sys.stderr)
            __import__("time").sleep(args.retry_wait)
            brief = distill.distill_card(pseudo, lanes, key=key,
                                         cache_dir=args.cache_dir,
                                         refresh=True)
        lane = brief.get("_lane", "none")
        lane_hist[lane] = lane_hist.get(lane, 0) + 1
        if lane == "none":
            failed += 1
        snap = dict(gate)
        snap["distilled"] = {s: brief.get(s, "") for s in distill.SLOTS}
        snap["distilled_lane"] = lane
        new = dict(case, snapshot=snap, corpus_version="v4")
        out.append(new)
        if i % 10 == 0 or i == len(cases):
            print(f"[{i}/{len(cases)}] {case['case_id']} lane={lane}",
                  file=sys.stderr)

    Path(args.out).write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in out))
    print(f"wrote {len(out)} v4 cases -> {args.out}", file=sys.stderr)
    print(f"lane usage: {lane_hist}  failed: {failed}", file=sys.stderr)


if __name__ == "__main__":
    main()
