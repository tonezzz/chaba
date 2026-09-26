#!/usr/bin/env python3
"""Devin session digest (L1.5d): per-session facts from CLI history files.

Mechanical pass over ~/.local/share/devin/cli/summaries/history_*.md —
session id, end time, size, task excerpt (first substantive user text, or
the quoted objective when the session is a summary-continuation).

Personal-tier data: stays in the local review dir, rendered into
personal-digest.md by personal-rollup.py — never synced to Ada banks.

Usage:
  devin-report.py [--days 7] [--dir DIR]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

DEFAULT_DIR = Path.home() / ".local/share/devin/cli/summaries"
DEFAULT_OUT = Path.home() / ".local/share/ada-review"

RX_MSG = re.compile(r"^=== MESSAGE (\d+) - (\w+) ===")
# injected context blocks — not real user intent
RX_XML = re.compile(r"<(system_info|project_context|rules|rule|"
                    r"additional_metadata|available_skills|last_todo_list|"
                    r"subagent_completion_notification)[^>]*>.*?</\1>",
                    re.S)
RX_CONT = re.compile(r"continuing work from a previous|"
                     r"summary of the previous conversation", re.I)
# CLI-internal compaction calls — summarizer sessions, not operator sessions
RX_SUMMARIZER = re.compile(
    r"^\s*Output a (new )?summary", re.I)
# user's own words quoted inside a continuation summary
RX_QUOTE = re.compile(r"^>\s*[“\"]?(.{15,200}?)[”\"]?\s*$", re.M)
RX_PREVFILE = re.compile(r"history_([0-9a-f]{16})\.md")


def _plain_text(msg: str) -> str:
    t = RX_XML.sub(" ", msg)
    t = re.sub(r"<[^>]+>", " ", t)  # any remaining tags
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _title(msgs: list[tuple[int, str, str]]) -> tuple[str, str]:
    """Return (kind, title). kind is 'cont' for continuation sessions."""
    users = [(i, body) for i, role, body in msgs if role == "User"]
    if not users:
        return "empty", "(no user messages)"
    if RX_SUMMARIZER.match(_plain_text(users[0][1])[:80]):
        return "summarizer", ""
    cont = any(RX_CONT.search(b[:4000]) for _, b in users[:3])
    # continuation: pull the operator's own words from the embedded summary
    if cont:
        for _, b in users[:3]:
            qs = RX_QUOTE.findall(b)
            if qs:
                return "cont", qs[0][:160]
    for _, b in users:
        t = _plain_text(b)
        if len(t) >= 40 and not t.startswith("==="):
            return ("cont" if cont else "task"), t[:160]
    return ("cont" if cont else "terse"), _plain_text(
        users[0][1])[:80] or "(short reply session)"


def scan_file(p: Path) -> dict:
    txt = p.read_text(encoding="utf-8", errors="replace")
    msgs: list[tuple[int, str, str]] = []
    cur_i, cur_role, buf = -1, "", []
    for ln in txt.splitlines():
        if (m := RX_MSG.match(ln)):
            if cur_i >= 0:
                msgs.append((cur_i, cur_role, "\n".join(buf)))
            cur_i, cur_role, buf = int(m.group(1)), m.group(2), []
        else:
            buf.append(ln)
    msgs.append((cur_i, cur_role, "\n".join(buf)))

    kind, title = _title(msgs)
    st = p.stat()
    prev = RX_PREVFILE.search(txt[:8000])
    return {
        "session": p.stem.removeprefix("history_"),
        "file": p.name,
        "date": time.strftime("%Y-%m-%dT%H:%M", time.localtime(st.st_mtime)),
        "msgs": cur_i + 1,
        "user_msgs": sum(1 for _, r, _ in msgs if r == "User"),
        "kb": round(st.st_size / 1024),
        "kind": kind,
        "title": title,
        "prev": prev.group(1) if prev else None,
    }


def devin_block(rows: list[dict], since: str,
                detail_days: int = 3, per_day: int = 8) -> str:
    real = [r for r in rows if r["kind"] != "summarizer"]
    summ = len(rows) - len(real)
    lines = [f"## devin ({since} — {len(real)} sessions"
             + (f", {summ} summarizer calls" if summ else "") + ")"]
    by_day: dict[str, list[dict]] = {}
    for r in real:
        by_day.setdefault(r["date"][:10], []).append(r)
    days = sorted(by_day, reverse=True)
    for day in days[:detail_days]:
        rs = sorted(by_day[day], key=lambda r: r["date"])
        lines.append(f"### {day} ({len(rs)})")
        for r in rs[-per_day:]:
            mark = "↩ " if r["kind"] == "cont" else ""
            lines.append(
                f"- {r['date'][11:]} {mark}{r['title']} "
                f"({r['user_msgs']} msgs, {r['kb']}K) `{r['session'][:8]}`")
        if len(rs) > per_day:
            lines.append(f"- …({len(rs) - per_day} earlier sessions)")
    older = [(d, len(by_day[d])) for d in days[detail_days:]]
    if older:
        lines.append("older: " + ", ".join(f"{d} x{n}" for d, n in older))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    cutoff = time.time() - args.days * 86400
    rows = []
    for p in sorted(args.dir.expanduser().glob("history_*.md")):
        if p.stat().st_mtime < cutoff:
            continue
        try:
            rows.append(scan_file(p))
        except Exception as e:
            print(f"warn: {p.name}: {e}", file=sys.stderr)

    args.out.mkdir(parents=True, exist_ok=True)
    ops = args.out / "devin-ops.jsonl"
    with ops.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} sessions -> {ops}")
    if rows:
        print(devin_block(rows, f"{args.days}d"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
