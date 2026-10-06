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

Scan coverage (2026-10-06): /v1/search returns docs in KEY order —
hostlog/<host>/<rt-µs-suffix> — not insertion order, so no chronological
paging shortcut exists. The old forward scan (offset 0 .. 5000) silently
pinned the digest to the oldest docs once the collection outgrew the
page budget — at ~97k docs the "24h" digest was reporting Oct-3 data.
The server honors large pages, so this now scans the WHOLE collection
(PAGE=5000, bounded by --max-docs) and windows client-side — every run
sees the true window and the true baseline.

New-today flag: a line's RX_VOLATILE-normalized signature that appears
inside the report window but has no occurrence in the prior
--baseline-days days gets a 🆕 marker — that's where first-seen
incidents hide. Exact semantics, no state file: the baseline is just
the older slice of the same full scan.

Repeat-cap counts: the shipper caps duplicate (unit,line) signatures at
REPEAT_CAP copies per run and marks the last copy with meta.suppressed;
offender xN counts weigh those docs by 1+suppressed so crash-loop
magnitude stays truthful.

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

# ops collections live on the no-embed ops DB (idc03 :11026) per
# ssot.log-digest-standard.yml — reads AND writes; the leader stays for
# CMS/banks. MDDB_OPS_URL env overrides for local dev.
OPS_URL = os.environ.get(
    "MDDB_OPS_URL",
    os.environ.get("MDDB_BASE_URL",
                   "http://100.102.134.91:11026/v1")).rstrip("/")
MDDB_URL = OPS_URL  # host-logs + ops-digests are both ops collections
LOG_COLLECTION = os.environ.get("LOG_COLLECTION", "host-logs")
STATE_COLLECTION = os.environ.get("LOG_STATE_COLLECTION",
                                  "host-logs-state")
STATE_URL = OPS_URL
DIGEST_COLLECTION = os.environ.get("DIGEST_COLLECTION", "ops-digests")
DEFAULT_OUT = Path.home() / ".local/share/ada-review"
PAGE = 5000
SEVERE = {"oom", "panic", "failed"}
BASELINE_DAYS = 7        # 'new today' = absent from the prior N days
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


def _parse_ts(ts: str):
    try:
        dt = datetime.datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        return None


def _sig(line: str) -> str:
    return RX_VOLATILE.sub("#", line)[:110]


def fetch_logs(hours: int, baseline_days: int, max_docs: int):
    """Full collection scan, client-side windowing. -> (rows,
    baseline_sigs, truncated).

    rows          — docs with meta.ts inside the last `hours`
                    (unparseable ts counts as in-window — the shipper
                    always sets it)
    baseline_sigs — {(host, normalized_sig)} for every doc with ts in
                    [now-baseline_days, window_start): the 'prior 7d'
                    membership set behind the 🆕 new-today flag
    truncated     — the page budget ran out mid-collection; both the
                    window and the baseline may be incomplete
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    win_start = now - datetime.timedelta(hours=hours)
    base_start = now - datetime.timedelta(days=baseline_days)
    rows, base_sigs = [], set()
    offset = scanned = 0
    while scanned < max_docs:
        page = _post("/search", {"collection": LOG_COLLECTION,
                                 "query": "", "limit": PAGE,
                                 "offset": offset})
        if not isinstance(page, list):
            if page is None:
                print("warn: mddb unreachable — empty digest"
                      if scanned == 0 else
                      "warn: mddb read failed mid-scan — partial digest",
                      file=sys.stderr)
            break
        if not page:
            break
        scanned += len(page)
        offset += PAGE
        for d in page:
            meta = d.get("meta") or {}
            ts = (meta.get("ts") or [""])[0]
            dt = _parse_ts(ts)
            host = (meta.get("host") or ["?"])[0]
            line = re.sub(r"^`[^`]*`\s*\[[^\]]*\]\s*", "",
                          (d.get("contentMd") or "").strip())
            if dt is not None:
                if dt < base_start:
                    continue        # older than the baseline horizon
                if dt < win_start:
                    base_sigs.add((host, _sig(line)))
                    continue
            try:
                sup = int((meta.get("suppressed") or ["0"])[0] or 0)
            except Exception:
                sup = 0
            rows.append({
                "host": host,
                "journal": (meta.get("journal") or ["?"])[0],
                "unit": (meta.get("unit") or ["?"])[0],
                "ts": ts,
                "kind": (meta.get("kind") or ["?"])[0],
                "line": line,
                "suppressed": sup,
            })
        if len(page) < PAGE:
            break
    if scanned >= max_docs:
        print(f"warn: scan hit {max_docs}-doc budget — window/baseline "
              "coverage partial, 🆕 flags may over-report",
              file=sys.stderr)
    return rows, base_sigs, scanned >= max_docs


def distill(rows: list[dict], base_sigs: set | None = None) -> list[dict]:
    """One summary row per host. base_sigs is the {(host, sig)} set from
    the prior baseline-days window — a window row whose sig is absent
    gets the 🆕 new-today flag."""
    by_host: dict[str, list[dict]] = {}
    for r in rows:
        by_host.setdefault(r["host"], []).append(r)
    out = []
    for host, hs in sorted(by_host.items()):
        kinds = Counter(r["kind"] for r in hs)
        units = Counter(r["unit"] for r in hs)
        offenders: Counter = Counter()
        new_sigs = set()
        for r in hs:
            sig = _sig(r["line"])
            offenders[sig] += 1 + r.get("suppressed", 0)
            if base_sigs is not None and (host, sig) not in base_sigs:
                new_sigs.add(sig)
        tss = sorted(r["ts"] for r in hs if r["ts"])
        out.append({
            "host": host,
            "total": len(hs),
            "kinds": dict(kinds),
            "severe": sum(kinds[k] for k in SEVERE),
            "top_units": dict(units.most_common(6)),
            "new": len(new_sigs),
            "new_lines": [{"n": offenders[s], "line": s}
                          for s in sorted(new_sigs,
                                          key=lambda s: -offenders[s])
                          [:5]],
            "top_lines": [{"n": n, "line": ln, "new": ln in new_sigs}
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
               if r["severe"] else "")
            + (f", {r['new']} new 🆕" if r["new"] else ""))
        for u, c in sorted(r["top_units"].items(),
                           key=lambda kv: -kv[1])[:4]:
            lines.append(f"  {u} x{c}")
        shown = set()
        for t in r["new_lines"][:4]:
            shown.add(t["line"])
            lines.append(f"  🆕 x{t['n']} {t['line'][:95]}")
        for t in r["top_lines"][:3]:
            if t["line"] in shown:
                continue
            lines.append(("  🆕" if t.get("new") else "  ")
                         + f" x{t['n']} {t['line'][:95]}")
    return "\n".join(lines)


def post_report_state(summary: list[dict], hours: int) -> None:
    """Sidecar state doc so logs-kanban can judge severe counts without
    re-reading the collection — one doc, same-key upsert, ~1 rev/day.
    Posted even with --no-publish (that flag is about the ops-digests
    trend doc; this is the pipeline's health heartbeat)."""
    try:
        req = urllib.request.Request(
            f"{STATE_URL}/add",
            data=json.dumps({
        "collection": STATE_COLLECTION, "key": "report/24h",
        "lang": "en",
        "contentMd": json.dumps(
            {"kind": "log-report", "hours": hours,
             "ts": datetime.datetime.now(datetime.timezone.utc)
             .isoformat(timespec="seconds"),
             "hosts": {r["host"]: {"total": r["total"],
                                   "severe": r["severe"]}
                       for r in summary}}),
        "meta": {"kind": ["log-report"],
                 "ts": [datetime.datetime.now(datetime.timezone.utc)
                        .isoformat(timespec="seconds")]}}).encode(),
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception:
        pass  # heartbeat is best-effort — never break the digest


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
    ap.add_argument("--max-docs", type=int, default=250000,
                    help="page budget for the whole-collection scan "
                         "(bounded by the 14d prune retention)")
    ap.add_argument("--baseline-days", type=int, default=BASELINE_DAYS,
                    help="'new today' = absent from the prior N days")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--no-publish", action="store_true")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    rows, base_sigs, _truncated = fetch_logs(
        args.hours, args.baseline_days, args.max_docs)
    summary = distill(rows, base_sigs)
    ops = args.out / "hostlogs-ops.jsonl"
    with ops.open("w") as fh:
        for r in summary:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    block = logs_block(summary, f"{args.hours}h")
    print(f"{len(rows)} lines from {len(summary)} hosts -> {ops}")
    print(block)
    post_report_state(summary, args.hours)

    if not args.no_publish and summary:
        ok = publish_digest(block, args.hours)
        print("digest -> ops-digests" if ok else
              "warn: ops-digests publish skipped (mddb unreachable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
