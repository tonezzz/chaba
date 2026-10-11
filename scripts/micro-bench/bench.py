#!/usr/bin/env python3
"""Run the micro-AI input-polish benchmark for one variant.

Usage:
  bench.py --variant <id> [--dry-run] [--fixtures a,b,c] [--timeout N]

For every fixture in fixtures/manifest.yml:
  1. polish step (skipped for polish: null variants — the direct baseline):
     raw -> polish model (normalize prompt) -> polished text
  2. downstream step: sent text -> receiving AI (fixed HA-tool JSON
     protocol in lib.DOWNSTREAM_SYSTEM) -> tool_call | answer

Measures per fixture: tool_call_match (exact/partial/none/fabricated),
entity preservation, polish similarity to gold, latency per stage, and
NET tokens (polish + downstream — the efficiency claim must count both).

Writes results/<variant>-<UTCts>.json (schema: micro-bench-result, v1).
--dry-run exercises the full schema with no model calls.
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import lib
import providers


def _extract_json(text):
    """Pull the first JSON object out of a model reply."""
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _clean_polished(text, raw):
    """Normalize a polish reply: strip quotes/labels; if the model wrapped
    or refused, fall back to raw so the pipeline still measures downstream."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("{") or t.startswith("["):
        return None  # model emitted JSON — treat as polish failure
    t = re.sub(r"^(rewritten|output|result)\s*[:—-]\s*", "", t,
               flags=re.I).strip()
    if len(t) > 2 and t[0] == t[-1] and t[0] in "\"'`":
        t = t[1:-1].strip()
    return t or None


def run_fixture(variant, fx, timeout):
    polished = polish_ms = polish_tokens = None
    gated = False
    gate_reason = None
    pre_gate_skip = False
    pre_gate_reason = None
    sent = fx["raw"]

    pol = variant.get("polish")
    if pol and pol.get("pre_gate"):
        should, pre_gate_reason = lib.pre_gate_check(
            pol["pre_gate"], fx["raw"])
        if not should:
            pre_gate_skip = True
            pol = None  # pass raw through untouched
    if pol:
        start = time.monotonic()
        try:
            r = providers.chat(
                pol,
                [{"role": "system",
                  "content": lib.POLISH_PROMPTS[pol.get("prompt",
                                                      "normalize_v1")]},
                 {"role": "user", "content": fx["raw"]}],
                timeout)
            polish_ms = r["ms"]
            polish_tokens = ((r.get("prompt_tokens") or 0)
                             + (r.get("completion_tokens") or 0)) or None
            polished = _clean_polished(r.get("text"), fx["raw"])
        except Exception as e:
            return lib.fixture_result(
                fx, status="error", error=f"polish: {e}",
                polish_ms=round((time.monotonic() - start) * 1000))
        if polished:
            ok, reason = lib.gate_ok(pol.get("gate"), fx["raw"], polished)
            gated = not ok
            gate_reason = reason
            sent = fx["raw"] if gated else polished

    try:
        r = providers.chat(
            variant["downstream"],
            [{"role": "system", "content": lib.DOWNSTREAM_SYSTEM},
             {"role": "user", "content": sent}],
            timeout)
    except Exception as e:
        return lib.fixture_result(
            fx, polished=polished, polish_ms=polish_ms,
            polish_tokens=polish_tokens, gated=gated,
            gate_reason=gate_reason, pre_gate_skip=pre_gate_skip,
            pre_gate_reason=pre_gate_reason, status="error",
            error=f"downstream: {e}")

    parsed = _extract_json(r.get("text"))
    tool_call = parsed.get("tool_call") if isinstance(
        parsed.get("tool_call"), dict) else None
    return lib.fixture_result(
        fx,
        polished=polished, polish_ms=polish_ms, polish_tokens=polish_tokens,
        gated=gated, gate_reason=gate_reason,
        pre_gate_skip=pre_gate_skip, pre_gate_reason=pre_gate_reason,
        reply=r.get("text"),
        tool_call=tool_call,
        answer=parsed.get("answer"),
        downstream_ms=r["ms"],
        downstream_tokens=((r.get("prompt_tokens") or 0)
                           + (r.get("completion_tokens") or 0)) or None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="emit the full result schema with no model calls")
    ap.add_argument("--fixtures", help="comma-separated fixture ids to run")
    ap.add_argument("--timeout", type=int, default=60,
                    help="per-call secs (each stage gets this)")
    ap.add_argument("--out", help="override results output path")
    args = ap.parse_args()

    variant = lib.get_variant(args.variant)
    fixtures = lib.load_fixtures()
    if args.fixtures:
        keep = set(args.fixtures.split(","))
        fixtures = [f for f in fixtures if f["id"] in keep]
    if not fixtures:
        sys.exit("no fixtures selected")

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta = {"at": ts, "host": subprocess.run(
        ["hostname"], capture_output=True, text=True).stdout.strip()}

    if args.dry_run:
        results = [lib.fixture_result(f, status="dry_run") for f in fixtures]
    else:
        results = []
        for fx in fixtures:
            print(f"[{fx['id']}] ...", flush=True)
            r = run_fixture(variant, fx, args.timeout)
            results.append(r)
            print(f"  status={r['status']} match={r['tool_call_match']} "
                  f"ent={r['entities']} sim={r['polish_sim']} "
                  f"net_tok={r['net_tokens']} ms={r['total_ms']}")

    doc = lib.result_doc(variant, results, dry_run=args.dry_run, meta=meta)
    out = Path(args.out) if args.out else lib.results_path(args.variant, ts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {out}")
    print(json.dumps(doc["summary"], indent=2))


if __name__ == "__main__":
    try:
        main()
    except lib.HarnessError as e:
        sys.exit(f"bench: {e}")
