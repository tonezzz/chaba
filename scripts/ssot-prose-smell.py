#!/usr/bin/env python3
"""SSOT prose-smell check (Tony direction 2026-11-07, card
assessments-to-education-split-ssot-keep-113ca4).

Rule: github/website/repo assessments and research depth live in
Education (wiki lessons + MDDB chaba-lessons) and docs/kb; SSOT keeps
ONLY the verdict row + pointer link. A string scalar carrying >~40
lines of prose inside a docs/ssot/**/*.yml file is a smell.

This script walks every YAML string value and flags those with more
than --lines (default 40) lines where sentence-like lines dominate
(>50%). Code/config-shaped blocks (systemd units, shell, env files,
JSON) are not prose and are ignored — the check targets narrative.

Output: one line per flagged value: file :: dotted key path :: total
lines :: prose% :: first prose line. Exit 1 when any flagged (--warn
to keep exit 0). Deliberate exceptions live in ALLOW below —
(file, key-path-prefix) pairs with a reason; keep it empty by default.

Usage:
  ssot-prose-smell.py [--lines N] [--warn] [--all] [--include-kanban]
                      [--file PATH ...]
"""
import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required: pip install pyyaml")

REPO = Path(__file__).resolve().parent.parent
SSOT_DIR = REPO / "docs" / "ssot"

# Deliberate exceptions: (relative path, key-path prefix, reason).
ALLOW = []

# A line counts as prose (sentence-like) when it reads like natural
# language: several word characters, a space, and none of the
# structural markers that betray code/config/markup.
_NONPROSE_RE = re.compile(
    r"^\s*(?:[\[{}\]#;]|//|\.\w|\w[\w.-]*\s*[:=]\s*\S|\$|\||\*)"
    r"|[{};]|=\s*$|:=|->\s")
_WORD_RE = re.compile(r"[A-Za-z]")


def _is_prose_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if not _WORD_RE.search(s):
        return False
    if _NONPROSE_RE.search(line):
        return False
    # mostly letters/punctuation = natural language
    letters = sum(1 for c in s if c.isalpha() or c.isspace()
                  or c in ".,;'\"()?!—–-:%/")
    return letters / len(s) > 0.75


def _iter_strings(obj, path):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v, path + [str(k)])
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_strings(v, path + [f"[{i}]"])
    elif isinstance(obj, str):
        yield ".".join(path), obj


def _prose_stats(text: str):
    lines = text.split("\n")
    nonempty = [l for l in lines if l.strip()]
    prose = [l for l in nonempty if _is_prose_line(l)]
    return len(lines), len(nonempty), len(prose), prose


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=40,
                    help="flag string values longer than this (default 40)")
    ap.add_argument("--warn", action="store_true",
                    help="report but exit 0")
    ap.add_argument("--all", action="store_true",
                    help="list every >N-line string, prose or not")
    ap.add_argument("--include-kanban", action="store_true",
                    help="also scan kanban card files (skipped by default)")
    ap.add_argument("--file", action="append", default=[])
    a = ap.parse_args()

    if a.file:
        files = [Path(f) for f in a.file]
    else:
        files = sorted(SSOT_DIR.rglob("*.yml"))
    flagged = 0
    for f in files:
        if not a.include_kanban and "kanban" in f.parts:
            continue
        rel = f.relative_to(REPO).as_posix() if f.is_absolute() else str(f)
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            print(f"YAML_ERROR {rel}: {e}")
            flagged += 1
            continue
        for keypath, text in _iter_strings(data, []):
            total, nonempty, nprose, prose = _prose_stats(text)
            if total <= a.lines:
                continue
            ratio = nprose / nonempty if nonempty else 0
            is_prose = ratio >= 0.5
            if not (a.all or is_prose):
                continue
            if any(rel == r and keypath.startswith(kp)
                   for r, kp, _why in ALLOW):
                continue
            flagged += 1
            first = prose[0].strip() if prose else text.strip()[:60]
            print(f"{total:4d} lines {ratio:0.0%} prose  {rel}"
                  f" :: {keypath} :: {first[:70]}")
    print(f"-- {flagged} flagged value(s) "
          f"({'warn' if a.warn else 'fail'} mode, >{a.lines} lines)")
    return 0 if (a.warn or not flagged) else 1


if __name__ == "__main__":
    sys.exit(main())
