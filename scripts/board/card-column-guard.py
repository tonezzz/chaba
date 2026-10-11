#!/usr/bin/env python3
"""card-column-guard — kill the autostash-pop column-resurrection class.

git pull --rebase --autostash pops a stash holding OLD card-file
versions onto the rebased tree. The 3-way merge applies cleanly even
when it shouldn't: upstream's new comms land at the bottom of the file
while the stash's stale `column:` field at the top merges "cleanly" —
closed cards silently come back as review/doing (6+ observed waves,
card git-autostash-column-guard).

Fix: after every pull, for every TRACKED card file, the committed HEAD
column wins over whatever the pop merged in. Surgical — the stash's
other content (a session's uncommitted comms edits) still lands; only
the column field is forced to the record's truth. Uncommitted column
changes are exactly the bug class; the column belongs to the committed
card, so there is no legitimate casualty.

Exit always 0 — a failed guard must never block a pull.
Usage: card-column-guard.py [repo-dir]
"""
import re
import subprocess
import sys
from pathlib import Path

CARDS_GLOB = "docs/ssot/kanban/cards/*.yml"
COL_RE = re.compile(r"^(column:\s*)(\S+)", re.M)


def head_column(repo: Path, path: str) -> str | None:
    try:
        s = subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{path}"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if s.returncode != 0:
        return None
    m = COL_RE.search(s.stdout)
    return m.group(2) if m else None


def main() -> int:
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    tracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files", CARDS_GLOB],
        capture_output=True, text=True, timeout=15)
    fixed = 0
    for rel in tracked.stdout.splitlines():
        p = repo / rel
        if not p.is_file():
            continue
        want = head_column(repo, rel)
        if not want:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = COL_RE.search(text)
        if not m or m.group(2) == want:
            continue
        was = m.group(2)
        text = text[:m.start(2)] + want + text[m.end(2):]
        try:
            p.write_text(text, encoding="utf-8")
            fixed += 1
            print(f"card-column-guard: {rel} column {was} -> {want} "
                  f"(HEAD wins — stale pop merge reverted)",
                  file=sys.stderr)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
