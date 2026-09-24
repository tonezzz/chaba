#!/usr/bin/env python3
"""Stage-1 mechanical index of Ada voice transcripts (no LLM).

Parses ~/.local/share/ada-review/transcripts/*.md (the format written by
ada-pi backend/conversation_memory.py: "# Ada voice session <id>" then
"## Ada|## User [HH:MM:SS]" turns) into one JSONL record per session.

Mechanical signals only — cheap, deterministic, safe to run on private
transcripts. The LLM rubric (missed actions, recall failures, ...) is a
separate stage-2 pass that consumes this index.

Usage:
  transcript-index.py                      # index default review dir
  transcript-index.py --dir PATH --out index.jsonl
  transcript-index.py --summary            # aggregate stats to stdout
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

DEFAULT_DIR = Path.home() / ".local/share/ada-review/transcripts"

TURN_RE = re.compile(r"^## (Ada|User)(?: \[(\d{2}):(\d{2}):(\d{2})\])?\s*$")
SESSION_RE = re.compile(r"^# Ada voice session (\S+)")

# Script buckets via unicode range checks — stdlib only, no langdetect dep.
_RANGES = {
    "th": ((0x0E01, 0x0E5B),),
    "ja": ((0x3040, 0x30FF),),                    # hiragana + katakana
    "ko": ((0xAC00, 0xD7AF), (0x1100, 0x11FF)),   # hangul syllables + jamo
    "cjk": ((0x4E00, 0x9FFF),),
    "lat": ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F)),
}


def _script_of(ch: str) -> str | None:
    cp = ord(ch)
    for name, ranges in _RANGES.items():
        if any(lo <= cp <= hi for lo, hi in ranges):
            return name
    return None


def lang_of(text: str) -> str:
    """Dominant script: th/en/ja/ko/cjk/mixed/unknown."""
    counts: dict[str, int] = {}
    for ch in text:
        s = _script_of(ch)
        if s:
            counts[s] = counts.get(s, 0) + 1
    if not counts:
        return "unknown"
    total = sum(counts.values())
    top, n = max(counts.items(), key=lambda kv: kv[1])
    if top == "lat":
        top = "en"
    if n / total < 0.6 and len(counts) > 1:
        return "mixed:" + top
    return top


def parse_file(path: Path) -> dict:
    session_id = path.stem.split("-", 3)[-1]  # YYYY-MM-DD-<id>
    date = path.stem[:10]
    turns: list[dict] = []
    cur: dict | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        m = SESSION_RE.match(line)
        if m:
            session_id = m.group(1)
            continue
        m = TURN_RE.match(line)
        if m:
            if cur is not None:
                turns.append(cur)
            stamp = f"{m.group(2)}:{m.group(3)}:{m.group(4)}" if m.group(2) else None
            cur = {"role": "user" if m.group(1) == "User" else "ada",
                   "stamp": stamp, "text": []}
            continue
        if cur is not None:
            cur["text"].append(line)

    if cur is not None:
        turns.append(cur)

    stamps = []
    flags: list[str] = []
    lang_counts: dict[str, int] = {}
    n_empty_ada = n_foreign = n_tiny_user = 0
    parsed_turns = []

    for t in turns:
        text = "\n".join(t["text"]).strip()
        lang = lang_of(text) if text else "empty"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        if t["stamp"]:
            stamps.append(t["stamp"])
        if t["role"] == "ada" and not text:
            n_empty_ada += 1
        if lang in ("ja", "ko", "cjk"):
            n_foreign += 1
        if t["role"] == "user" and text and len(text) <= 3:
            n_tiny_user += 1
        parsed_turns.append({"role": t["role"], "stamp": t["stamp"],
                             "lang": lang, "chars": len(text)})

    if n_empty_ada:
        flags.append(f"empty_ada_turns={n_empty_ada}")
    if n_foreign:
        flags.append(f"foreign_script_turns={n_foreign}")
    if n_tiny_user:
        flags.append(f"tiny_user_turns={n_tiny_user}")
    if parsed_turns and parsed_turns[-1]["role"] == "user":
        flags.append("ends_on_user_turn")
    if not parsed_turns:
        flags.append("no_turns")
    if stamps and len(stamps) < len(parsed_turns):
        flags.append("partial_stamps")

    duration_s = None
    if len(stamps) >= 2:
        def _sec(s: str) -> int:
            h, m, sec = (int(x) for x in s.split(":"))
            return h * 3600 + m * 60 + sec
        duration_s = _sec(stamps[-1]) - _sec(stamps[0])
        if duration_s < 0:  # crossed UTC midnight
            duration_s += 86400

    return {
        "file": path.name,
        "date": date,
        "session_id": session_id,
        "turns": len(parsed_turns),
        "user_turns": sum(1 for t in parsed_turns if t["role"] == "user"),
        "ada_turns": sum(1 for t in parsed_turns if t["role"] == "ada"),
        "chars": sum(t["chars"] for t in parsed_turns),
        "langs": lang_counts,
        "duration_s": duration_s,
        "stamped": bool(stamps),
        "flags": flags,
        "turn_detail": parsed_turns,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--out", type=Path, default=None,
                    help="JSONL output (default <dir>/transcript-index.jsonl)")
    ap.add_argument("--summary", action="store_true",
                    help="print aggregate stats to stdout")
    args = ap.parse_args()

    d = args.dir.expanduser()
    files = sorted(p for p in d.glob("*.md") if p.is_file())
    if not files:
        print(f"no transcripts in {d}", file=sys.stderr)
        return 1

    records = [parse_file(p) for p in files]
    out = args.out or (d / "transcript-index.jsonl")
    with out.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    if args.summary:
        tot_turns = sum(r["turns"] for r in records)
        langs: dict[str, int] = {}
        flag_counts: dict[str, int] = {}
        for r in records:
            for k, v in r["langs"].items():
                langs[k] = langs.get(k, 0) + v
            for f in r["flags"]:
                key = f.split("=")[0]
                flag_counts[key] = flag_counts.get(key, 0) + 1
        print(f"files={len(records)} turns={tot_turns} "
              f"chars={sum(r['chars'] for r in records)}")
        print(f"langs={dict(sorted(langs.items(), key=lambda kv: -kv[1]))}")
        print(f"flagged_files: {flag_counts}")
        flagged = [r['file'] for r in records if r["flags"]]
        for f in flagged:
            r = next(x for x in records if x["file"] == f)
            print(f"  {f}: {', '.join(r['flags'])}")

    print(f"wrote {len(records)} records -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
