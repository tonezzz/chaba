#!/usr/bin/env python3
"""Render voice-bench results into reports/voice-fallback/.

Reads scripts/voice-bench/results/*.json, writes:
  reports/voice-fallback/LATEST.md   combo x metric table (newest run per combo)
  reports/voice-fallback/trend.md    appended one summary row per new result

With --card <id>, also posts a summary comment to the kanban card via the
board-api (curl https://tony-dell.taila0626a.ts.net/apps/board-api/comment).
Safe to run with zero results: renders an empty table.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import lib

REPORTS = Path(__file__).resolve().parents[2] / "reports" / "voice-fallback"
LATEST = REPORTS / "LATEST.md"
TREND = REPORTS / "trend.md"
BOARD_API = "https://tony-dell.taila0626a.ts.net/apps/board-api/comment"


def _fmt(v, suffix=""):
    return f"{v}{suffix}" if isinstance(v, (int, float)) else "—"


def _tool_cell(tally):
    return f"{tally.get('exact', 0)}/{tally.get('partial', 0)}/{tally.get('none', 0)}"


def render_table(rows):
    head = ("| combo | stt | llm | tts | orchestrator | host_labels | n | ok | "
            "mean ttfa ms | mean total ms | mean wer | tool exact/partial/none |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    body = "".join(
        f"| {r['combo']} | {r['stt']} | {r['llm']} | {r['tts']} | "
        f"{r['orchestrator']} | {','.join(r['labels']) or '—'} | {r['n']} | "
        f"{r['ok']} | {_fmt(r['ttfa'])} | {_fmt(r['total'])} | "
        f"{_fmt(r['wer'])} | {r['tool']} |\n"
        for r in rows)
    return head + body


def collect_rows():
    """Newest result doc per combo id."""
    newest = {}
    for path, doc in lib.iter_results():
        if not isinstance(doc, dict):
            continue
        cdoc = doc.get("combo")
        cid = cdoc.get("id", "?") if isinstance(cdoc, dict) \
            else (cdoc or "?")  # legacy schema: combo was a bare string
        if cid not in newest or doc.get("meta", {}).get("at", "") > \
                newest[cid][1].get("meta", {}).get("at", ""):
            newest[cid] = (path, doc)
    rows = []
    for cid, (path, doc) in sorted(newest.items()):
        c = doc.get("combo", {})
        if not isinstance(c, dict):
            c = {}
        s = doc.get("summary", {})
        rows.append({
            "combo": cid,
            "stt": c.get("stt", "?"), "llm": c.get("llm", "?"),
            "tts": c.get("tts", "?"), "orchestrator": c.get("orchestrator", "?"),
            "labels": c.get("host_labels", []),
            "n": s.get("n", 0), "ok": s.get("ok", 0),
            "ttfa": s.get("mean_ttfa_ms"), "total": s.get("mean_total_ms"),
            "wer": s.get("mean_wer"), "tool": _tool_cell(s.get("tool_call", {})),
            "at": doc.get("meta", {}).get("at", "?"),
            "dry": doc.get("dry_run"), "path": path.name,
        })
    return rows


def append_trend(rows):
    TREND.parent.mkdir(parents=True, exist_ok=True)
    if not TREND.exists():
        TREND.write_text(
            "# voice-fallback trend\n\n"
            "| at | combo | n | ok | mean ttfa ms | mean total ms | mean wer | tool e/p/n | dry |\n"
            "|---|---|---|---|---|---|---|---|---|\n")
    with TREND.open("a") as f:
        for r in rows:
            f.write(f"| {r['at']} | {r['combo']} | {r['n']} | {r['ok']} | "
                    f"{_fmt(r['ttfa'])} | {_fmt(r['total'])} | {_fmt(r['wer'])} | "
                    f"{r['tool']} | {'yes' if r['dry'] else 'no'} |\n")


def post_card_comment(card_id, text):
    payload = json.dumps({"id": card_id, "from": "voice-bench", "text": text})
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", BOARD_API,
         "-H", "Content-Type: application/json", "-d", payload],
        capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        print(f"warn: board-api comment failed: {r.stderr.strip()}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", help="kanban card id to post the summary to")
    ap.add_argument("--no-trend", action="store_true")
    args = ap.parse_args()

    rows = collect_rows()
    REPORTS.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    LATEST.write_text(
        "# Voice-fallback benchmark — latest results\n\n"
        f"Rendered {now} by `scripts/voice-bench/report.py`.\n\n"
        + render_table(rows)
        + ("\n_No results yet — run `bench.py --combo <id>`._\n" if not rows else "")
        + "\nTool column is exact/partial/none matches; "
          "see `scripts/voice-bench/results/` for raw JSON.\n")
    if rows and not args.no_trend:
        append_trend(rows)
    print(f"wrote {LATEST}" + (" + trend" if rows and not args.no_trend else ""))

    if args.card:
        if rows:
            lines = [f"voice-bench report ({now}): "
                     f"{len(rows)} combo(s) benched"]
            for r in rows:
                lines.append(
                    f"- {r['combo']}: ok {r['ok']}/{r['n']}, "
                    f"ttfa {_fmt(r['ttfa'])}ms, rt {_fmt(r['total'])}ms, "
                    f"wer {_fmt(r['wer'])}, tool {r['tool']}")
            lines.append(f"table: reports/voice-fallback/LATEST.md")
            post_card_comment(args.card, "\n".join(lines))
        else:
            post_card_comment(args.card, f"voice-bench report ({now}): no results yet.")


if __name__ == "__main__":
    try:
        main()
    except lib.HarnessError as e:
        sys.exit(f"report: {e}")
