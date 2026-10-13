#!/usr/bin/env python3
"""card-column-guard — kill the autostash-pop column-resurrection class.

git pull --rebase --autostash pops a stash holding OLD card-file
versions onto the rebased tree. The 3-way merge applies cleanly even
when it shouldn't: upstream's new comms land at the bottom of the file
while the stash's stale `column:` field at the top merges "cleanly" —
closed cards silently come back as review/doing (6+ observed waves,
card git-autostash-column-guard).

Fix: after every pull, for every TRACKED card file, decide the column
from the card's own comm trail first — a legit board-api move appends
`moved <old> -> <new>` / `closed by <frm>` / `(column -> <new>)`, and
that intent beats BOTH the stash residue and the committed HEAD (a
fresh uncommitted move must survive a pull; reverting it silently
eats user actions — observed 2026-10-13, four doing->done moves
reverted mid-flight). When no move/close comm exists, the committed
HEAD column wins over whatever the pop merged in, as before.

Exit always 0 — a failed guard must never block a pull.
Usage: card-column-guard.py [repo-dir]
"""
import re
import subprocess
import sys
from pathlib import Path

CARDS_GLOB = "docs/ssot/kanban/cards/*.yml"
COL_RE = re.compile(r"^(column:\s*)(\S+)", re.M)
# comm texts that assert a column, in evaluation order. The LAST match
# in the file wins — comms are append-only, so it reflects latest intent.
COMM_COL = [
    (re.compile(r"put on hold"), "backlog"),
    (re.compile(r"queued for processing|re-queued|requeued"), "backlog"),
    (re.compile(r"moved \S+ -> (\w+)"), None),   # group 1
    (re.compile(r"\(column -> (\w+)\)"), None),  # merge-sweep marker
    (re.compile(r"closed by \w+"), "done"),
    (re.compile(r"claimed"), "doing"),
]
VALID = {"backlog", "doing", "review", "done"}


def comm_target_column(text: str) -> str | None:
    """Column asserted by the last column-asserting comm, else None."""
    target = None
    for m in re.finditer(r"text:\s*(.*)", text):
        t = m.group(1)
        for pat, fixed in COMM_COL:
            mm = pat.search(t)
            if mm:
                col = mm.group(1) if fixed is None else fixed
                if col in VALID:
                    target = col
                break
    return target


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
        if not m:
            continue
        was = m.group(2)
        if was == want:
            continue
        # A worktree column asserted by the card's own comm trail is a
        # fresh uncommitted move — keep it. Anything else is stash residue.
        if comm_target_column(text) == was:
            continue
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
