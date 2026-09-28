#!/usr/bin/env python3
"""Host-logs distillation (L1.5g): MDDB host-logs -> distilled report.

Read-side of the log pipeline. log-shipper.py writes filtered journald
lines into the MDDB "host-logs" collection (one doc per interesting line,
meta {host, journal, unit, ts, kind}); this reads them back, aggregates
per host (kind counts, top units, repeated offenders, first/last seen),
renders the infra-digest block, and optionally re-posts the digest as a
doc in "ops-digests" so trend queries work ("has X been failing all
week?").

MDDB-down tolerant: network reads with a hard timeout; returns an empty
digest block so the rollup still renders. Works while the vector index
is rebuilding — /v1/search is keyword/meta, not vector.

Usage:
  logs-report.py [--hours 24] [--out DIR]
  logs-report.py --no-publish            # skip the ops-digests write
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

MDDB_URL = os.environ.get("MDDB_BASE_URL",
                          "http://100.74.146.0:11023/v1").rstrip("/")
LOG_COLLECTION = os.environ.get("LOG_COLLECTION", "host-logs")
DIGEST_COLLECTION = os.environ.get("DIGEST_COLLECTION", "ops-digests")
DEFAULT_OUT = Path.home() / ".local/share/ada-review"
PAGE = 200
SEVERE = {"oom", "panic", "failed"}
# normalize a line for repeat-counting: strip volatile parts (timestamps,
# PIDs, hex ids) so the same recurring error collapses into one entry
RX_VOLATILE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^ ]*|"
    r"\bpid[ =:]\d+|\b0x[0-9a-f]+\b|\b[0-9a-f]{8}\b|\b\d+\b", re.I)


def _post(path: str, payload: dict, timeout: int = 15):
    try:
        req = urllib.request.Request(
            f"{MDDB_URL}{path}", data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def fetch_logs(hours: int, max_docs: int = 5000) -> list[dict]:
    """Page /v1/search over host-logs; filter client-side to the window."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=hours))
    docs, offset = [], 0
    while len(docs) < max_docs:
        page = _post("/search", {"collection": LOG_COLLECTION,
                                 "query": "", "limit": PAGE,
                                 "offset": offset})
        if not isinstance(page, list):
            if page is None:
                print("warn: mddb unreachable — empty digest",
                      file=sys.stderr)
            break
        docs.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    rows = []
    for d in docs:
        meta = d.get("meta") or {}
        ts = (meta.get("ts") or [""])[0]
        try:
            dt = datetime.datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            if dt < cutoff:
                continue
        except Exception:
            pass  # unparseable ts still counts — shipper always sets it
        rows.append({
            "host": (meta.get("host") or ["?"])[0],
            "journal": (meta.get("journal") or ["?"])[0],
            "unit": (meta.get("unit") or ["?"])[0],
            "ts": ts,
            "kind": (meta.get("kind") or ["?"])[0],
            "line": re.sub(r"^`[^`]*`\s*\[[^\]]*\]\s*", "",
                           (d.get("contentMd") or "").strip()),
        })
    return rows


def distill(rows: list[dict]) -> list[dict]:
    """One summary row per host."""
    by_host: dict[str, list[dict]] = {}
    for r in rows:
        by_host.setdefault(r["host"], []).append(r)
    out = []
    for host, hs in sorted(by_host.items()):
        kinds = Counter(r["kind"] for r in hs)
        units = Counter(r["unit"] for r in hs)
        offenders = Counter(RX_VOLATILE.sub("#", r["line"])[:110]
                            for r in hs)
        tss = sorted(r["ts"] for r in hs if r["ts"])
        out.append({
            "host": host,
            "total": len(hs),
            "kinds": dict(kinds),
            "severe": sum(kinds[k] for k in SEVERE),
            "top_units": dict(units.most_common(6)),
            "top_lines": [{"n": n, "line": ln}
                          for ln, n in offenders.most_common(5) if n > 1],
            "first": tss[0] if tss else "",
            "last": tss[-1] if tss else "",
        })
    return out


def logs_block(rows: list[dict], since: str) -> str:
    if not rows:
        return f"## host-logs ({since})\nno shipped log lines"
    total = sum(r["total"] for r in rows)
    severe = sum(r["severe"] for r in rows)
    lines = [f"## host-logs ({since} — {total} lines"
             + (f", {severe} severe ⚠" if severe else "") + ")"]
    for r in rows:
        lines.append(
            f"{r['host']}: {r['total']} lines — "
            + ", ".join(f"{k} x{c}" for k, c in
                        sorted(r["kinds"].items(), key=lambda kv: -kv[1]))
            + (f" ⚠ [{r['first'][:16]}..{r['last'][11:16]}]"
               if r["severe"] else ""))
        for u, c in sorted(r["top_units"].items(),
                           key=lambda kv: -kv[1])[:4]:
            lines.append(f"  {u} x{c}")
        for t in r["top_lines"][:3]:
            lines.append(f"  x{t['n']} {t['line'][:95]}")
    return "\n".join(lines)


def publish_digest(block: str, hours: int) -> bool:
    """Store the rendered block in ops-digests for trend queries.
    Key is unique per run — same-key re-adds feed the unfixed HNSW
    tombstone bug (delete+add drops the chunk)."""
    stamp = datetime.datetime.now(datetime.timezone.utc)\
        .strftime("%Y-%m-%dT%H%M")
    return bool(_post("/add", {
        "collection": DIGEST_COLLECTION,
        "key": f"digest/host-logs/{stamp}",
        "lang": "en",
        "contentMd": block,
        "meta": {"kind": ["digest"], "source": ["host-logs"],
                 "window_h": [str(hours)], "ts": [
                     datetime.datetime.now(datetime.timezone.utc)
                     .isoformat(timespec="seconds")]}}, timeout=20))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--max-docs", type=int, default=5000)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--no-publish", action="store_true")
    args = ap.parse_args()

    rows = fetch_logs(args.hours, args.max_docs)
    summary = distill(rows)

    args.out.mkdir(parents=True, exist_ok=True)
    ops = args.out / "hostlogs-ops.jsonl"
    with ops.open("w") as fh:
        for r in summary:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    block = logs_block(summary, f"{args.hours}h")
    print(f"{len(rows)} lines from {len(summary)} hosts -> {ops}")
    print(block)

    if not args.no_publish and summary:
        ok = publish_digest(block, args.hours)
        print("digest -> ops-digests" if ok else
              "warn: ops-digests publish skipped (mddb unreachable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
