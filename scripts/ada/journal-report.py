#!/usr/bin/env python3
"""Session-ops layer (L1.5): per-session operational facts from journald.

The L1 session reports are transcript-derived — they see what Ada SAID.
This layer sees what the RUNTIME did: tool calls and errors, response
latency, token usage, stream aborts/reconnects, interruptions, speaker
events, and prefetch failures. Mechanical pass, no LLM.

Usage:
  journal-report.py --host idc01 --since "24 hours ago"
  journal-report.py --units ada-ha-tony,ada-ha-michael --since 2026-09-20
  journal-report.py --merge-reports reports/   # add ops{} into report JSONs
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_OUT = Path.home() / ".local/share/ada-review"
UNITS = ["ada-ha-tony", "ada-ha-michael", "ada-pi-pwa"]

RX_SESSION = re.compile(r"session=([0-9a-f]{8,16})")
RX_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})")
RX_USAGE = re.compile(r"usage turn in=(\d+) out=(\d+) \| total in=(\d+) out=(\d+)")
RX_DONE = re.compile(
    r"assistant response completed duration_ms=(\d+) audio_chunks=\d+ audio_bytes=(\d+)")
RX_CALL = re.compile(r"function_call received.*name=([A-Za-z_0-9]+)")
RX_RESULT = re.compile(r"function_call result.*name=([A-Za-z_0-9]+) result=")


def fetch(host: str, unit: str, since: str) -> list[str]:
    out = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host,
         f"journalctl --user -u {unit} --since '{since}' --no-pager -o cat"],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        print(f"warn: journal {unit} failed: {out.stderr.strip()[:100]}",
              file=sys.stderr)
        return []
    return out.stdout.splitlines()


def parse(lines: list[str]) -> dict[str, dict]:
    sess: dict[str, dict] = defaultdict(lambda: {
        "first": None, "last": None,
        "tool_calls": 0, "tool_errors": 0, "tools": defaultdict(int),
        "responses": 0, "durations": [], "audio_bytes": 0,
        "tokens_in": 0, "tokens_out": 0,
        "interrupted": 0, "reconnects": 0,
        "agenda_failures": 0, "proposal_failures": 0,
        "local_speech": 0, "speaker_events": 0, "warnings": 0,
    })
    for ln in lines:
        m = RX_SESSION.search(ln)
        if not m:
            continue
        sid = m.group(1)
        s = sess[sid]
        ts = RX_TS.match(ln)
        if ts:
            t = ts.group(1)
            if s["first"] is None or t < s["first"]:
                s["first"] = t
            if s["last"] is None or t > s["last"]:
                s["last"] = t
        if " WARNING" in ln:
            s["warnings"] += 1
        if (m := RX_CALL.search(ln)):
            s["tool_calls"] += 1
            s["tools"][m.group(1)] += 1
        elif RX_RESULT.search(ln):
            if "'error'" in ln or '"error"' in ln:
                s["tool_errors"] += 1
        elif (m := RX_DONE.search(ln)):
            s["responses"] += 1
            s["durations"].append(int(m.group(1)))
            s["audio_bytes"] += int(m.group(2))
        elif (m := RX_USAGE.search(ln)):
            s["tokens_in"] = max(s["tokens_in"], int(m.group(3)))
            s["tokens_out"] = max(s["tokens_out"], int(m.group(4)))
        elif "assistant interrupted" in ln:
            s["interrupted"] += 1
        elif "live_reconnecting" in ln:
            s["reconnects"] += 1
        elif "agenda prefetch failed" in ln:
            s["agenda_failures"] += 1
        elif "proposals prefetch failed" in ln:
            s["proposal_failures"] += 1
        elif "local_speech" in ln:
            s["local_speech"] += 1
        elif re.search(r"speaker[_ ]", ln):
            s["speaker_events"] += 1
    return sess


def summary_row(sid: str, s: dict) -> dict:
    ds = s["durations"]
    return {
        "session": sid, "first": s["first"], "last": s["last"],
        "tool_calls": s["tool_calls"], "tool_errors": s["tool_errors"],
        "tools": dict(s["tools"]),
        "responses": s["responses"],
        "mean_resp_ms": int(statistics.mean(ds)) if ds else None,
        "p95_resp_ms": int(sorted(ds)[int(len(ds) * 0.95)]) if ds else None,
        "audio_bytes": s["audio_bytes"],
        "tokens_in": s["tokens_in"], "tokens_out": s["tokens_out"],
        "interrupted": s["interrupted"], "reconnects": s["reconnects"],
        "agenda_failures": s["agenda_failures"],
        "proposal_failures": s["proposal_failures"],
        "local_speech": s["local_speech"],
        "speaker_events": s["speaker_events"],
        "warnings": s["warnings"],
    }


def ops_block(rows: list[dict], since: str) -> str:
    """Compact '## ops' digest for the rolling-log injection path."""
    n = len(rows)
    resp = [r for r in rows if r["responses"]]
    tc = sum(r["tool_calls"] for r in rows)
    te = sum(r["tool_errors"] for r in rows)
    ab = sum(r["reconnects"] for r in rows)
    intr = sum(r["interrupted"] for r in rows)
    af = sum(r["agenda_failures"] for r in rows)
    tok = sum(r["tokens_in"] + r["tokens_out"] for r in rows)
    ds = [r["mean_resp_ms"] for r in resp if r["mean_resp_ms"]]
    hot = sorted(rows, key=lambda r: -r["tool_errors"])[:3]
    lines = [f"## ops ({since} — {n} sessions)"]
    if n:
        lines.append(
            f"tools {tc} calls/{te} err | responses {sum(r['responses'] for r in rows)}"
            f" | aborts {ab} | interruptions {intr} | agenda-fails {af}"
            f" | tokens ~{tok // 1000}k")
        if ds:
            lines.append(f"resp latency mean {int(statistics.mean(ds))}ms")
        for r in hot:
            if r["tool_errors"]:
                lines.append(f"error-heavy: {r['session']} "
                             f"{r['tool_errors']}/{r['tool_calls']} tool err")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--host", default="idc01")
    ap.add_argument("--units", default=",".join(UNITS),
                    help="comma-separated journald units")
    ap.add_argument("--since", default="24 hours ago")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--merge-reports", type=Path, default=None,
                    help="report dir — write ops{} into matching <date>-<sid>.json")
    args = ap.parse_args()

    rows: list[dict] = []
    for unit in args.units.split(","):
        unit = unit.strip()
        if not unit:
            continue
        sess = parse(fetch(args.host, unit, args.since))
        for sid, s in sess.items():
            row = summary_row(sid, s)
            row["unit"] = unit
            rows.append(row)
    rows.sort(key=lambda r: r["first"] or "")

    args.out.mkdir(parents=True, exist_ok=True)
    ops_file = args.out / "session-ops.jsonl"
    with ops_file.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} sessions -> {ops_file}")

    if args.merge_reports:
        rdir = args.merge_reports.expanduser()
        merged = 0
        for r in rows:
            for p in rdir.glob(f"*-{r['session']}.json"):
                try:
                    rep = json.loads(p.read_text(encoding="utf-8"))
                    rep["ops"] = r
                    p.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
                    merged += 1
                except Exception as e:
                    print(f"warn: merge {p.name}: {e}", file=sys.stderr)
        print(f"ops merged into {merged} report(s)")

    print(ops_block(rows, args.since))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
